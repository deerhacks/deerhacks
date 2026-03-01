"""
PATHFINDER API routes.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.schemas import PlanRequest, PlanResponse

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
    try:
        data = await websocket.receive_json()
        initial_state = {
            "raw_prompt": data.get("prompt", ""),
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
            "retry_count": 0,
        }
        NODE_LABELS = {
            "commander": "Parsing your request...",
            "scout": "Discovering venues...",
            "vibe_matcher": "Analyzing vibes...",
            "cost_analyst": "Calculating costs...",
            "critic": "Running risk assessment...",
            "synthesiser": "Ranking results...",
        }
        accumulated = {**initial_state}
        async for event in pathfinder_graph.astream(initial_state):
            node_name = list(event.keys())[0]
            accumulated.update(event[node_name])
            await websocket.send_json({
                "type": "progress",
                "node": node_name,
                "label": NODE_LABELS.get(node_name, node_name),
            })
        await websocket.send_json({
            "type": "result",
            "data": PlanResponse(
                venues=accumulated.get("ranked_results", []),
                execution_summary="Pipeline complete.",
            ).model_dump(),
        })
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/health")
async def api_health():
    return {"status": "ok"}
