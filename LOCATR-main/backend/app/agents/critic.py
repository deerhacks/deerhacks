"""
Node 6 — The CRITIC (Adversarial)
Actively tries to break the plan with real-world risk checks.
Model: Gemini (Adversarial Reasoning)
Tools: OpenWeather API, PredictHQ
"""

import json
import logging
import asyncio
import time

from app.models.state import PathfinderState
from app.services.openweather import get_weather
from app.services.predicthq import get_events
from app.services.gemini import generate_content
import os
from app.services.snowflake import SnowflakeIntelligence
from app.services.cache import search_cache

logger = logging.getLogger(__name__)


_CRITIC_BATCH_PROMPT = """
You are the PATHFINDER Critic Agent. Your job is to find reasons why this plan is TERRIBLE for each specified venue.
Look for dealbreakers that would ruin the experience (e.g., outdoor activity + heavy rain, traffic jam due to a marathon blocking access).

User Intent: {intent}

Venues to evaluate:
{venues_context}

For each venue, evaluate against Fast-Fail Conditions:
1. Condition A: Are there fewer than 3 viable venues after risk filtering?
2. Condition B: Is there a Top Candidate Veto? (Critical dealbreakers).

OUTPUT FORMAT:
Return ONLY a JSON object where keys are the VENUE_IDs provided and values are objects with this shape:
{{
    "risks": [
        {{"type": "weather/events", "severity": "high/medium/low", "detail": "explanation"}}
    ],
    "fast_fail": true/false,
    "fast_fail_reason": "short reason if fast_fail is true"
}}
"""

async def critic_node(state: PathfinderState) -> PathfinderState:
    """
    Cross-reference top venues with real-world risks.
    BATCHED VERSION: Analyzes Top 3 picks in a single Gemini call.
    """
    start_time = time.perf_counter()
    candidates = state.get("candidate_venues", [])
    if not candidates:
        return {"risk_flags": {}, "veto": False, "veto_reason": None}

    top_candidates = candidates[:3]
    vids_sorted = sorted([v.get("venue_id", v.get("name", "")) for v in top_candidates])
    cache_key = f"critic:" + "|".join(vids_sorted)
    
    cached = search_cache.get(cache_key)
    if cached:
        logger.info("[CRITIC] ⚡️ CACHE HIT for risk checks")
        return cached

    # 1. Fetch external data efficiently (Deduplicate by location)
    logger.info("[CRITIC] Unique Location Risk Check for %d venues...", len(top_candidates))
    api_start = time.perf_counter()
    
    # Map (lat, lng) to weather/events to avoid redundant neighborhood calls
    location_cache = {}
    
    async def _get_loc_context(lat, lng):
        loc_key = (round(lat, 3), round(lng, 3)) # Neighborhood granularity
        if loc_key not in location_cache:
            # First time for this neighborhood
            location_cache[loc_key] = asyncio.gather(get_weather(lat, lng), get_events(lat, lng))
        return await location_cache[loc_key]

    async def _fetch_venue_context(v):
        lat, lng = v.get("lat"), v.get("lng")
        weather, events = await _get_loc_context(lat, lng)
        return {
            "id": v.get("venue_id", v.get("name", "unknown")),
            "name": v.get("name"),
            "category": v.get("category"),
            "weather": weather,
            "events": events
        }

    contexts = await asyncio.gather(*[_fetch_venue_context(v) for v in top_candidates])
    logger.info("[CRITIC] Context Fetch took %.2fs (Unique Neighbors: %d)", 
                time.perf_counter() - api_start, len(location_cache))
    
    # 2. Build Batch Prompt
    venues_context_text = ""
    for ctx in contexts:
        venues_context_text += f"ID: {ctx['id']}\nName: {ctx['name']} ({ctx['category']})\nWeather: {json.dumps(ctx['weather'])}\nEvents: {json.dumps(ctx['events'])}\n---\n"

    prompt = _CRITIC_BATCH_PROMPT.format(
        intent=json.dumps(state.get("parsed_intent", {})),
        venues_context=venues_context_text
    )

    logger.info("[CRITIC] Dispatching Gemini batch call...")
    gemini_start = time.perf_counter()
    try:
        raw = await generate_content(prompt)
        logger.info("[CRITIC] Gemini batch call took %.2fs", time.perf_counter() - gemini_start)
        
        cleaned = raw.strip()
        if cleaned.startswith("```json"): cleaned = cleaned[7:]
        elif cleaned.startswith("```"): cleaned = cleaned[3:]
        if cleaned.endswith("```"): cleaned = cleaned[:-3]
        
        batch_results = json.loads(cleaned.strip())
        
        risk_flags = {}
        fast_fail_reason = None
        
        sf = SnowflakeIntelligence()

        for venue, ctx in zip(top_candidates, contexts):
            vid = ctx["id"]
            analysis = batch_results.get(vid, {"risks": [], "fast_fail": False})
            
            risks = analysis.get("risks", [])
            # Inject Historical Risks
            hist_risks = venue.get("historical_risks", [])
            for hr in hist_risks:
                risks.append({"type": "historical_veto", "severity": "high", "detail": f"[HISTORICAL RISK] {hr}"})
            
            risk_flags[vid] = risks
            
            # If Top 1 fails, log it
            if analysis.get("fast_fail") and vid == top_candidates[0].get("venue_id", top_candidates[0].get("name")):
                fast_fail_reason = analysis.get("fast_fail_reason")
                try:
                    sf.log_risk_event(venue.get("name"), vid, fast_fail_reason, str(ctx["weather"]))
                    logger.info("[CRITIC] Logged veto to Snowflake for %s", venue.get("name"))
                except Exception as e:
                    logger.error("[CRITIC] Snowflake logging failed: %s", e)

        logger.info("[CRITIC] Node Complete in %.2fs", time.perf_counter() - start_time)
        
        result_to_cache = {"risk_flags": risk_flags, "fast_fail": False, "fast_fail_reason": fast_fail_reason, "veto": False, "veto_reason": fast_fail_reason}
        search_cache.set(cache_key, result_to_cache)
        return result_to_cache

    except Exception as exc:
        logger.error("[CRITIC] Batch Gemini call failed: %s", exc)
        return {"risk_flags": {}, "veto": False, "veto_reason": None}

