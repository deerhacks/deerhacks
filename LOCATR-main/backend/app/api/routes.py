"""
PATHFINDER API routes.
"""

import asyncio
import io
import logging
import queue

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

from app.schemas import PlanRequest, PlanResponse
from app.core.ws_log_handler import WebSocketLogHandler

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/plan", response_model=PlanResponse)
async def create_plan(request: PlanRequest):
    """
    Accept a natural-language activity request and return ranked venues.

    Flow: prompt → Commander → Scout → [Vibe, Access, Cost] → Critic → Synthesiser → results
    """
    from app.graph import pathfinder_graph

    initial_state = {
        "raw_prompt": request.prompt,
        "parsed_intent": {},
        "complexity_tier": "tier_2",
        "active_agents": [],
        "agent_weights": {},
        "candidate_venues": [],
        "vibe_scores": {},
        "cost_profiles": {},
        "risk_flags": {},
        "veto": False,
        "veto_reason": None,
        "ranked_results": [],
        "snowflake_context": None,
        # Forward request params for agents to use
        "member_locations": request.member_locations or [],
        "chat_history": request.chat_history or [],
    }

    # Inject explicit fields into parsed_intent if provided
    if request.group_size > 1 or request.budget or request.location or request.vibe:
        initial_state["parsed_intent"] = {
            "group_size": request.group_size,
            "budget": request.budget,
            "location": request.location,
            "vibe": request.vibe,
        }

    # Run the full LangGraph workflow
    result = await pathfinder_graph.ainvoke(initial_state)

    return PlanResponse(
        venues=result.get("ranked_results", []),
        execution_summary="Pipeline complete.",
    )


@router.websocket("/ws/plan")
async def websocket_plan(websocket: WebSocket):
    from app.graph import pathfinder_graph
    await websocket.accept()

    log_queue: queue.Queue = queue.Queue()
    handler = WebSocketLogHandler(log_queue)
    handler.setLevel(logging.DEBUG)

    # Attach handler to all agent / graph loggers
    # Must attach to each child logger directly because parent loggers
    # created on-the-fly may not propagate reliably.
    target_logger_names = [
        "app.agents.commander",
        "app.agents.scout",
        "app.agents.vibe_matcher",
        "app.agents.cost_analyst",
        "app.agents.critic",
        "app.agents.synthesiser",
        "app.graph",
    ]
    target_loggers = [logging.getLogger(name) for name in target_logger_names]
    for lg in target_loggers:
        lg.addHandler(handler)
        if lg.level == logging.NOTSET or lg.level > logging.DEBUG:
            lg.setLevel(logging.DEBUG)

    try:
        data = await websocket.receive_json()
        initial_state = {
            "raw_prompt": data.get("prompt", ""),
            "auth_user_id": data.get("auth_user_id"),
            "parsed_intent": {},
            "complexity_tier": "tier_2",
            "active_agents": [],
            "agent_weights": {},
            "candidate_venues": [],
            "vibe_scores": {},
            "cost_profiles": {},
            "risk_flags": {},
            "veto": False,
            "veto_reason": None,
            "ranked_results": [],
            "member_locations": data.get("member_locations", []),
        }

        done_event = asyncio.Event()
        graph_result = {}
        graph_error = None

        async def run_graph():
            nonlocal graph_result, graph_error
            try:
                graph_result = await pathfinder_graph.ainvoke(initial_state)
            except Exception as exc:
                logger.exception("Graph execution failed: %s", exc)
                graph_error = exc
            finally:
                done_event.set()

        graph_task = asyncio.create_task(run_graph())

        # Drain the log queue and send each entry over the WebSocket
        while not done_event.is_set() or not log_queue.empty():
            try:
                entry = log_queue.get_nowait()
                await websocket.send_json({
                    "type": "log",
                    "node": entry["node"],
                    "message": entry["message"],
                })
            except queue.Empty:
                if done_event.is_set():
                    break
                await asyncio.sleep(0.05)

        await graph_task

        # Flush any remaining log entries queued during final moments
        while not log_queue.empty():
            try:
                entry = log_queue.get_nowait()
                await websocket.send_json({
                    "type": "log",
                    "node": entry["node"],
                    "message": entry["message"],
                })
            except queue.Empty:
                break

        if graph_error:
            await websocket.send_json({
                "type": "error",
                "message": str(graph_error),
            })
        else:
            await websocket.send_json({
                "type": "result",
                "data": PlanResponse(
                    venues=graph_result.get("ranked_results", []),
                    execution_summary="Pipeline complete.",
                    global_consensus=graph_result.get("global_consensus"),
                    user_profile=graph_result.get("user_profile"),
                    agent_weights=graph_result.get("agent_weights"),
                    action_request=graph_result.get("action_request"),
                ).model_dump(),
            })
    except WebSocketDisconnect:
        pass
    finally:
        for lg in target_loggers:
            lg.removeHandler(handler)
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/user/preferences")
async def get_preferences(auth_user_id: str):
    """Return the preferences stored in a user's Auth0 app_metadata."""
    from app.services.auth0 import auth0_service
    profile = await auth0_service.get_user_profile(auth_user_id)
    preferences = profile.get("app_metadata", {}).get("preferences", {})
    return {"preferences": preferences}


@router.patch("/user/preferences")
async def update_preferences(body: dict):
    """Merge new preference values into the user's Auth0 app_metadata."""
    auth_user_id = body.get("auth_user_id")
    preferences = body.get("preferences", {})
    if not auth_user_id:
        return {"ok": False, "error": "auth_user_id required"}
    from app.services.auth0 import auth0_service
    ok = await auth0_service.update_app_metadata(auth_user_id, {"preferences": preferences})
    return {"ok": ok}


@router.get("/health")
async def api_health():
    return {"status": "ok"}


# ── Vibe Heatmap ─────────────────────────────────────────

# 48 vibe dimensions in vector order (indices 0-47).
# Matches the ordered list used when CAFE_VIBE_VECTORS was populated.
VIBE_LABELS = [
    "aesthetic", "cozy", "chill", "trendy", "hipster",
    "romantic", "classy", "upscale", "fancy", "elegant", "modern",
    "rustic", "bohemian", "artsy", "quirky", "retro", "vintage",
    "minimalist", "industrial", "dark academia", "cottagecore",
    "cyberpunk", "neon", "instagrammable", "photogenic", "cute",
    "charming", "intimate", "lively", "energetic", "fun", "exciting",
    "relaxing", "peaceful", "calm", "serene", "warm", "inviting",
    "atmosphere", "ambiance", "mood", "theme", "decor", "design",
    "beautiful", "pretty", "gorgeous", "stunning",
]


@router.get("/vibe-heatmap")
async def vibe_heatmap(vibe_index: int):
    """
    Return all cafe venues with their score for the given vibe dimension.
    vibe_index: integer 0-47 corresponding to VIBE_LABELS.
    Response: { vibes: [str], points: [{ lat, lng, score, name }] }
    """
    if vibe_index < 0 or vibe_index >= len(VIBE_LABELS):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"vibe_index must be 0-{len(VIBE_LABELS)-1}")

    from app.services.snowflake import get_snowflake_connection
    import json as _json

    conn = get_snowflake_connection()
    if not conn:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Snowflake unavailable")

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT NAME, LATITUDE, LONGITUDE, VIBE_VECTOR FROM CAFE_VIBE_VECTORS "
            "WHERE LATITUDE IS NOT NULL AND LONGITUDE IS NOT NULL"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    points = []
    for name, lat, lng, vec in rows:
        try:
            if isinstance(vec, str):
                vec = _json.loads(vec)
            score = float(vec[vibe_index])
        except (TypeError, IndexError, ValueError):
            continue
        points.append({"lat": lat, "lng": lng, "score": score, "name": name})

    return {"vibes": VIBE_LABELS, "points": points}


# ── Voice TTS ────────────────────────────────────────────


class VoiceSynthRequest(BaseModel):
    """Request body for text-to-speech synthesis."""
    text: str = Field(..., description="Text to synthesize")
    voice_id: Optional[str] = Field(None, description="ElevenLabs voice ID")


@router.post("/voice/synthesize")
async def synthesize_voice(request: VoiceSynthRequest):
    """
    Convert text to speech using ElevenLabs.
    Returns an audio/mpeg stream.
    """
    from app.services.elevenlabs import synthesize_speech

    audio_bytes = await synthesize_speech(
        text=request.text,
        voice_id=request.voice_id,
    )

    if audio_bytes is None:
        return {"error": "Voice synthesis unavailable. Check ELEVENLABS_API_KEY."}

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=speech.mp3"},
    )
