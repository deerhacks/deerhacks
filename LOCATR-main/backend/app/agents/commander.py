"""
Node 1 — The COMMANDER (Orchestrator)
Central brain: intent parsing, complexity tiering, dynamic agent weighting.
Model: Gemini 1.5 Flash
Fallback: Keyword-based heuristic when Gemini is unavailable.
"""

import json
import logging
import re
import asyncio
import time

from app.models.state import PathfinderState
from app.services.gemini import generate_content

logger = logging.getLogger(__name__)


# ── Keyword dictionaries for fallback agent activation ────────────────

_COST_KEYWORDS = {
    "budget", "cheap", "affordable", "cost", "price", "pricing", "money",
    "expensive", "inexpensive", "free", "deal", "discount", "value",
    "economical", "low-cost", "under", "frugal", "save", "saving",
    "per person", "per head", "rates", "fees", "rental", "rent",
    "spend", "spending", "splurge", "worth", "overpriced",
    "$", "dollar", "bucks",
}

_VIBE_KEYWORDS = {
    "vibe", "vibes", "aesthetic", "cozy", "chill", "trendy", "hipster",
    "romantic", "classy", "upscale", "fancy", "elegant", "modern",
    "rustic", "bohemian", "artsy", "quirky", "retro", "vintage",
    "minimalist", "industrial", "dark academia", "cottagecore",
    "cyberpunk", "neon", "instagrammable", "photogenic", "cute",
    "charming", "intimate", "lively", "energetic", "fun", "exciting",
    "relaxing", "peaceful", "calm", "serene", "warm", "inviting",
    "atmosphere", "ambiance", "mood", "theme", "decor", "design",
    "beautiful", "pretty", "gorgeous", "stunning", "loves", "hates",
    "likes", "dislikes", "prefers", "preference",
}

_CRITIC_KEYWORDS = {
    "weather", "rain", "snow", "cold", "hot", "outdoor", "outside",
    "patio", "rooftop", "garden", "park", "beach", "pool",
    "risk", "risky", "safe", "safety", "reliable", "dependable",
    "crowded", "busy", "packed", "noisy", "quiet", "event",
    "festival", "concert", "marathon", "parade", "construction",
    "closure", "closed", "cancelled", "available", "availability",
    "weekend", "saturday", "sunday", "tonight", "today", "tomorrow",
    "evening", "afternoon", "morning", "night",
}

_BUDGET_VALUES = {
    "free": "free", "cheap": "low", "budget": "low", "affordable": "low",
    "inexpensive": "low", "economical": "low", "frugal": "low",
    "low-cost": "low", "moderate": "medium", "mid-range": "medium",
    "reasonable": "medium", "expensive": "high", "upscale": "high",
    "luxury": "high", "premium": "high", "splurge": "high",
    "fancy": "high", "high-end": "high",
}


def _keyword_fallback(raw_prompt: str) -> dict:
    """
    Heuristic fallback when Gemini is unavailable.
    Parses intent and activates agents using keyword matching.
    """
    prompt_lower = raw_prompt.lower()
    words = set(re.findall(r"[a-z$]+(?:'[a-z]+)?", prompt_lower))

    # ── Extract intent fields ──
    # Activity: take the core noun phrase (best-effort)
    activity = raw_prompt.split(" in ")[0].strip() if " in " in raw_prompt else raw_prompt

    # Location: look for "in <location>" pattern
    loc_match = re.search(r"\bin\s+([\w\s]+?)(?:\.|,|$)", raw_prompt, re.IGNORECASE)
    location = loc_match.group(1).strip() if loc_match else "Toronto"

    # Group size: look for numbers near "people", "kids", "guests", "friends", "group"
    size_match = re.search(
        r"(\d+)\s*(?:people|person|kids|children|guests|friends|of us|group)",
        raw_prompt, re.IGNORECASE,
    )
    group_size = int(size_match.group(1)) if size_match else 1

    # Budget: keyword match
    budget = "medium"
    for kw, val in _BUDGET_VALUES.items():
        if kw in prompt_lower:
            budget = val
            break

    # Budget from dollar amounts: "$400-600", "under $200"
    dollar_match = re.search(r"\$\s*(\d+)", raw_prompt)
    if dollar_match:
        amount = int(dollar_match.group(1))
        if amount < 100:
            budget = "low"
        elif amount < 500:
            budget = "medium"
        else:
            budget = "high"

    # Vibe: pick first matching vibe keyword
    vibe = None
    for kw in _VIBE_KEYWORDS:
        if kw in prompt_lower:
            vibe = kw
            break

    parsed_intent = {
        "activity": activity,
        "group_size": group_size,
        "budget": budget,
        "location": location,
        "vibe": vibe,
    }

    # ── Determine which agents to activate ──
    active_agents = ["scout"]  # always on
    agent_weights = {"scout": 1.0}

    # Check each agent's keywords against the prompt
    cost_hits = sum(1 for kw in _COST_KEYWORDS if kw in prompt_lower)
    vibe_hits = sum(1 for kw in _VIBE_KEYWORDS if kw in prompt_lower)
    critic_hits = sum(1 for kw in _CRITIC_KEYWORDS if kw in prompt_lower)

    if cost_hits > 0:
        active_agents.append("cost_analyst")
        agent_weights["cost_analyst"] = min(0.5 + cost_hits * 0.1, 1.0)

    if vibe_hits > 0:
        active_agents.append("vibe_matcher")
        agent_weights["vibe_matcher"] = min(0.4 + vibe_hits * 0.1, 1.0)

    if critic_hits > 0:
        active_agents.append("critic")
        agent_weights["critic"] = min(0.4 + critic_hits * 0.1, 1.0)

    # If group activity with multiple people, default-activate cost + critic
    if group_size > 1:
        for agent in ["cost_analyst", "critic"]:
            if agent not in active_agents:
                active_agents.append(agent)
                agent_weights[agent] = 0.5

    # If nothing beyond scout matched, activate all with moderate weight
    if len(active_agents) == 1:
        active_agents = ["scout", "vibe_matcher", "cost_analyst", "critic"]
        agent_weights = {a: 0.6 for a in active_agents}
        agent_weights["scout"] = 1.0

    # ── Determine complexity tier ──
    n_agents = len(active_agents)
    if n_agents <= 2:
        tier = "tier_1"
    elif n_agents <= 4:
        tier = "tier_2"
    else:
        tier = "tier_3"

    logger.info(
        "Commander FALLBACK: tier=%s, agents=%s, budget=%s, group=%d",
        tier, active_agents, budget, group_size,
    )

    return {
        "parsed_intent": parsed_intent,
        "complexity_tier": tier,
        "active_agents": active_agents,
        "agent_weights": agent_weights,
    }


def _apply_user_profile_weights(
    agent_weights: dict, user_profile: dict
) -> dict:
    """
    Adjust agent weights based on the authenticated user's profile metadata.
    Reads app_metadata set by Auth0 rules/actions.
    """
    meta = user_profile.get("app_metadata", {})
    preferences = meta.get("preferences", {})

    # Budget sensitivity
    if preferences.get("budget_sensitive"):
        agent_weights["cost_analyst"] = min(
            agent_weights.get("cost_analyst", 0.5) + 0.2, 1.0
        )

    # Vibe-first user
    if preferences.get("vibe_first"):
        agent_weights["vibe_matcher"] = min(
            agent_weights.get("vibe_matcher", 0.4) + 0.2, 1.0
        )

    # Risk-averse user
    if preferences.get("risk_averse"):
        agent_weights["critic"] = min(
            agent_weights.get("critic", 0.4) + 0.2, 1.0
        )

    return agent_weights


# ── Main node entry point ─────────────────────────────────────────────

async def commander_node(state: PathfinderState) -> PathfinderState:
    """
    Parse the raw user prompt into a structured execution plan.
    """
    start_time = time.perf_counter()
    raw_prompt = state.get("raw_prompt", "")
    auth_user_id = state.get("auth_user_id")

    logger.info("[COMMANDER] Analyzing request...")

    # ── Fetch Auth0 Profile ──
    user_profile = state.get("user_profile")
    if auth_user_id and not user_profile:
        if auth_user_id == "auth0|local_test":
            user_profile = {}
        else:
            from app.services.auth0 import auth0_service
            try:
                user_profile = await auth0_service.get_user_profile(auth_user_id)
            except Exception as e:
                logger.warning("[COMMANDER] Profile fetch failed: %s", e)
                user_profile = {}

    profile_context = ""
    if user_profile:
        prefs = user_profile.get("app_metadata", {}).get("preferences", {})
        if prefs:
            profile_context = f"\nUser Prefs: {json.dumps(prefs)}"

    prompt = f"""You are the PATHFINDER Commander. Parse this request into a JSON execution plan.
Query: "{raw_prompt}"{profile_context}

Tiers: tier_1 (simple), tier_2 (multi-factor), tier_3 (research/business).
Agents: ["scout", "vibe_matcher", "cost_analyst", "critic"]. Scout is mandatory.
Rules: 
- vibe_matcher: Only if aesthetic/vibe/atmosphere is mentioned.
- cost_analyst: Skip if purely aesthetic and no booking requested.

Output JSON:
{{
  "parsed_intent": {{"activity": "...", "group_size": 1, "budget": "medium", "location": "Toronto", "vibe": "..."}},
  "complexity_tier": "tier_2",
  "active_agents": ["scout", ...],
  "agent_weights": {{"scout": 1.0, ...}},
  "requires_oauth": false,
  "oauth_scopes": [],
  "allowed_actions": [],
  "identity_context": "standard_profile"
}}"""

    logger.info("[COMMANDER] Dispatching Gemini parsing...")
    gemini_start = time.perf_counter()
    try:
        response_text = await generate_content(prompt, model="gemini-2.5-flash")
        logger.info("[COMMANDER] Gemini parsing took %.2fs", time.perf_counter() - gemini_start)

        # Clean up markdown
        cleaned = response_text.strip()
        if cleaned.startswith("```json"): cleaned = cleaned[7:]
        elif cleaned.startswith("```"): cleaned = cleaned[3:]
        if cleaned.endswith("```"): cleaned = cleaned[:-3]

        plan = json.loads(cleaned.strip())
    except Exception as e:
        logger.warning("[COMMANDER] Gemini failed, using fallback: %s", e)
        plan = _keyword_fallback(raw_prompt)

    agent_weights = plan.get("agent_weights", {"scout": 1.0})
    if user_profile:
        agent_weights = _apply_user_profile_weights(agent_weights, user_profile)

    output = {
        "parsed_intent": plan.get("parsed_intent", {}),
        "complexity_tier": plan.get("complexity_tier", "tier_2"),
        "active_agents": plan.get("active_agents", ["scout"]),
        "agent_weights": agent_weights,
        "requires_oauth": plan.get("requires_oauth", False),
        "oauth_scopes": plan.get("oauth_scopes", []),
        "allowed_actions": plan.get("allowed_actions", []),
        "user_profile": user_profile,
    }

    logger.info("[COMMANDER] Node Complete in %.2fs", time.perf_counter() - start_time)
    return output
