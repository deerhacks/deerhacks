"""
Node 2 — The SCOUT (Discovery)
Discovers candidate venues via Google Places API & Yelp Fusion,
merges + deduplicates, and enriches with Snowflake intelligence.
"""

import asyncio
import logging
import time
from math import radians, cos, sin, asin, sqrt

from app.models.state import PathfinderState
from app.services.google_places import search_places
from app.services.yelp import search_yelp
import os
from app.services.snowflake import SnowflakeIntelligence
from app.services.cache import search_cache

logger = logging.getLogger(__name__)


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in metres between two lat/lng points."""
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(a))


def _deduplicate(venues: list[dict], threshold_m: float = 100) -> list[dict]:
    """
    Remove near-duplicates by name similarity + geographic proximity.
    If two venues have the same lowercase name and are within `threshold_m`
    metres of each other, keep the one with the higher rating but merge pricing sources.
    """
    kept: list[dict] = []
    for v in venues:
        src = v.get("source")
        if src == "google_places":
            v["google_price"] = v.get("price_range")
        elif src == "yelp":
            v["yelp_price"] = v.get("price_range")

        is_dup = False
        for k in kept:
            same_name = v["name"].lower().strip() == k["name"].lower().strip()
            close = _haversine(v["lat"], v["lng"], k["lat"], k["lng"]) < threshold_m
            if same_name and close:
                # Merge pricing data before keeping
                if "google_price" in v and v["google_price"]:
                    k["google_price"] = v["google_price"]
                if "yelp_price" in v and v["yelp_price"]:
                    k["yelp_price"] = v["yelp_price"]

                # Keep the higher-rated one
                if v.get("rating", 0) > k.get("rating", 0):
                    v["google_price"] = k.get("google_price")
                    v["yelp_price"] = k.get("yelp_price")
                    kept.remove(k)
                    kept.append(v)
                is_dup = True
                break
        if not is_dup:
            kept.append(v)
    return kept


async def scout_node(state: PathfinderState) -> PathfinderState:
    """
    Discover 5-10 candidate venues.

    Steps
    -----
    1. Build a search query from parsed_intent.
    2. Call Google Places + Yelp in parallel.
    3. Merge & deduplicate by name + proximity.
    4. Cap at 10 results.
    5. Return updated state with candidate_venues.
    """
    start_time = time.perf_counter()
    intent = state.get("parsed_intent", {})

    # Build search query from intent fields
    activity = intent.get("activity", "")
    location = intent.get("location") or "Toronto"
    raw_prompt = state.get("raw_prompt", "")
    query = activity if activity else raw_prompt

    logger.info("[SCOUT] Searching for %s in %s...", query, location)

    if not query:
        logger.warning("[SCOUT] No query to search — returning empty")
        logger.info("[SCOUT] Node Complete in %.2fs", time.perf_counter() - start_time)
        return {"candidate_venues": []}

    # ── Check Cache ──
    cache_key = f"scout:{query}:{location}".lower()
    cached = search_cache.get(cache_key)
    if cached:
        logger.info("[SCOUT] ⚡️ CACHE HIT for '%s' in %s", query, location)
        logger.info("[SCOUT] Node Complete in %.2fs", time.perf_counter() - start_time)
        return {"candidate_venues": cached}

    # Run both APIs concurrently - using native await instead of asyncio.run
    logger.info("[SCOUT] Querying Google Places + Yelp simultaneously...")
    api_start = time.perf_counter()
    try:
        google_results, yelp_results = await asyncio.gather(
            search_places(query=query, location=location, max_results=8),
            search_yelp(term=query, location=location, max_results=8),
        )
        logger.info("[SCOUT] API Fetch took %.2fs (Google: %d, Yelp: %d)",
                    time.perf_counter() - api_start, len(google_results), len(yelp_results))
    except Exception as exc:
        logger.error("[SCOUT] API calls failed: %s", exc)
        google_results, yelp_results = [], []

    logger.info("[SCOUT] Google returned %d, Yelp returned %d", len(google_results), len(yelp_results))

    # Merge all results
    merge_dedup_start = time.perf_counter()
    all_venues = google_results + yelp_results

    # After deduplication
    unique_venues = _deduplicate(all_venues)
    removed = len(all_venues) - len(unique_venues)
    if removed:
        logger.info("[SCOUT] Merged to %d unique venues (%d duplicate(s) removed)", len(unique_venues), removed)

    # Cap at 10
    candidates = unique_venues[:10]
    logger.info("[SCOUT] Merge & Deduplication took %.2fs", time.perf_counter() - merge_dedup_start)

    # ── Inject Historical Risks (OPTIMIZED BATCH CALL) ──
    sf_start = time.perf_counter()
    try:
        sf = SnowflakeIntelligence()
        # Fetch all risks in one single query
        all_risks = sf.get_batch_historical_risks(candidates)
        
        for cand in candidates:
            # Check by both ID and Name
            vid = cand.get("venue_id", "").lower()
            vname = cand.get("name", "").lower()
            
            cand_risks = all_risks.get(vid, [])
            if not cand_risks and vname:
                cand_risks = all_risks.get(vname, [])
                
            cand["historical_risks"] = cand_risks
            if cand_risks:
                logger.info("[SCOUT] Found %d historical risks for %s", len(cand_risks), cand.get("name"))
    except Exception as exc:
        logger.error("[SCOUT] Failed to enrich historical risks: %s", exc)
        for cand in candidates:
            if "historical_risks" not in cand:
                cand["historical_risks"] = []

    logger.info("[SCOUT] ── DONE — %d candidates (%d Google, %d Yelp, %d after dedup)",
                len(candidates), len(google_results), len(yelp_results), len(unique_venues))
    logger.info("[SCOUT] candidate_venues:\n%s",
                "\n".join(f"  [{i+1}] {v.get('name')} | rating={v.get('rating')} | price={v.get('price_range')} | hist_risks={len(v.get('historical_risks',[]))} | {v.get('address', '')}"
                          for i, v in enumerate(candidates)))

    # ── Save to Cache ──
    search_cache.set(cache_key, candidates)

    return {"candidate_venues": candidates}
