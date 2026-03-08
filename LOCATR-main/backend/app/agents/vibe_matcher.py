"""
Node 3 — The VIBE MATCHER (Qualitative Analysis)
Aesthetic reasoning engine using Gemini 1.5 Pro multimodal.
Scores each venue's vibe against the user's desired aesthetic.
"""

import asyncio
import json
import logging
import time

from app.models.state import PathfinderState
from app.services.gemini import generate_content
from app.services.cache import search_cache

logger = logging.getLogger(__name__)

VIBE_KEYWORDS = [
    "aesthetic", "cozy", "chill", "trendy", "hipster", "romantic", "classy", 
    "upscale", "fancy", "elegant", "modern", "rustic", "bohemian", "artsy", 
    "quirky", "retro", "vintage", "minimalist", "industrial", "dark academia", 
    "cottagecore", "cyberpunk", "neon", "instagrammable", "photogenic", "cute",
    "charming", "intimate", "lively", "energetic", "fun", "exciting", "relaxing",
    "peaceful", "calm", "serene", "warm", "inviting", "atmosphere", "ambiance",
    "mood", "theme", "decor", "design", "beautiful", "pretty", "gorgeous",
    "stunning", "spacious", "unique"
]

_VIBE_PROMPT = f"""You are a spatial aesthetic analyst. Analyze the following cafe based on its reviews and photos.
Assign a score from 0.0 to 1.0 for each of the following {len(VIBE_KEYWORDS)} dimensions:
{", ".join(VIBE_KEYWORDS)}

Venue: {{name}}
Address: {{address}}
Category: {{category}}

INPUT HANDLING:

You will receive 1-3 image descriptions or metadata.

If an image failed to load (e.g., Redirect Error or 404), do not penalize the venue. Instead, rely on the Review Sentiment provided in the text metadata.

Return ONLY a JSON array of {len(VIBE_KEYWORDS)} floats in the exact order listed above.
Example: [0.9, 0.1, 0.4, ...]
"""

_NEUTRAL_VIBE = "a welcoming, enjoyable atmosphere suitable for groups"


_VIBE_BATCH_PROMPT = f"""You are a spatial aesthetic analyst. Analyze the following list of venues based on their metadata and provided photos.
Assign a score from 0.0 to 1.0 for each of the following {len(VIBE_KEYWORDS)} dimensions for EACH venue:
{", ".join(VIBE_KEYWORDS)}

For each venue, you will be provided with its name, address, and category.
If photos are provided, they will be labeled with the venue name.

OUTPUT FORMAT:
Return ONLY a JSON object where keys are the VENUE_IDs provided and values are JSON arrays of {len(VIBE_KEYWORDS)} floats.
Example: 
{{
  "venue_id_1": [0.9, 0.1, ...],
  "venue_id_2": [0.4, 0.8, ...]
}}

Venues to analyze:
{{venues_text}}
"""

async def vibe_matcher_node(state: PathfinderState) -> PathfinderState:
    """
    Score each candidate venue on subjective vibe / aesthetic match.
    BATCHED VERSION: Sends all venues to Gemini in one call to reduce latency.
    """
    start_time = time.perf_counter()
    intent = state.get("parsed_intent", {})
    vibe_pref = intent.get("vibe") or _NEUTRAL_VIBE
    candidates = state.get("candidate_venues", [])

    logger.info("[VIBE] Matching vibe: %s", vibe_pref)
    logger.info("[VIBE] Scoring %d venues with SINGLE BATCH Gemini call...", len(candidates))

    if not candidates:
        return {"vibe_scores": {}}

    # ── Check Cache ──
    vids_sorted = sorted([v.get("venue_id", v.get("name", "")) for v in candidates])
    cache_key = f"vibe:{vibe_pref}:" + "|".join(vids_sorted)
    cached = search_cache.get(cache_key)
    if cached:
        logger.info("[VIBE] ⚡️ CACHE HIT for candidate set")
        return cached

    # Prepare Batch Prompt
    venues_text = ""
    batch_images = []

    for v in candidates:
        vid = v.get("venue_id", v.get("name", "unknown"))
        venues_text += f"ID: {vid}\nName: {v.get('name')}\nAddress: {v.get('address')}\nCategory: {v.get('category')}\n---\n"
        
        # Add first 2 photos per venue to avoid hitting payload limits while keeping visual context
        v_photos = v.get("photos", [])[:2]
        batch_images.extend(v_photos)

    prompt = _VIBE_BATCH_PROMPT.format(venues_text=venues_text)

    logger.info("[VIBE] Dispatching Gemini batch call (Photos: %d)...", len(batch_images))
    gemini_start = time.perf_counter()
    try:
        raw = await generate_content(
            prompt=prompt,
            model="gemini-2.5-flash",
            image_urls=batch_images if batch_images else None,
        )
        logger.info("[VIBE] Gemini batch call took %.2fs", time.perf_counter() - gemini_start)
        
        # Clean JSON
        cleaned = raw.strip()
        if cleaned.startswith("```json"): cleaned = cleaned[7:]
        elif cleaned.startswith("```"): cleaned = cleaned[3:]
        if cleaned.endswith("```"): cleaned = cleaned[:-3]
        
        batch_results = json.loads(cleaned.strip())
        
        vibe_scores = {}
        passed_candidates = []
        rejected_candidates = []

        for venue in candidates:
            vid = venue.get("venue_id", venue.get("name", "unknown"))
            result_list = batch_results.get(vid)
            
            if result_list and isinstance(result_list, list) and len(result_list) == len(VIBE_KEYWORDS):
                score = result_list[0]
                res_dict = {
                    "vibe_score": score,
                    "vibe_dimensions": result_list,
                    "primary_style": vibe_pref,
                    "confidence": 1.0
                }
                vibe_scores[vid] = res_dict
                
                if vibe_pref != _NEUTRAL_VIBE and score < 0.4:
                    rejected_candidates.append((score, venue))
                else:
                    passed_candidates.append(venue)
            else:
                # Fallback for individual venue failure within batch
                logger.warning("[VIBE] Missing or invalid results for %s in batch", vid)
                vibe_scores[vid] = {
                    "vibe_score": 0.5,
                    "vibe_dimensions": [0.5] * len(VIBE_KEYWORDS),
                    "primary_style": "unknown",
                    "confidence": 0.0
                }
                passed_candidates.append(venue)

        # Ensure at least 3
        rejected_candidates.sort(key=lambda x: x[0], reverse=True)
        while len(passed_candidates) < 3 and rejected_candidates:
            score, venue = rejected_candidates.pop(0)
            passed_candidates.append(venue)

        logger.info("[VIBE] Node Complete in %.2fs (Kept %d of %d)", 
                    time.perf_counter() - start_time, len(passed_candidates), len(candidates))
        
        result_to_cache = {"vibe_scores": vibe_scores, "candidate_venues": passed_candidates}
        search_cache.set(cache_key, result_to_cache)
        return result_to_cache

    except Exception as exc:
        logger.error("[VIBE] Batch Gemini call failed: %s", exc)
        return {"vibe_scores": {}, "candidate_venues": candidates[:3]}
