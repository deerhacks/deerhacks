"""
Node 4 — The ACCESS ANALYST (Logistics)
Spatial reality check: travel-time feasibility + isochrone generation.

For each candidate venue:
  1. Fetch a Mapbox Isochrone polygon (reachable area within N minutes).
  2. If member locations are provided, compute average straight-line distance
     and estimate an accessibility score.
  3. Return accessibility_scores + isochrones keyed by venue_id.

Tools: Mapbox Isochrone API
"""

import asyncio
import logging
from math import radians, cos, sin, asin, sqrt

from app.models.state import PathfinderState
from app.services.mapbox import get_isochrone

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in kilometres between two lat/lng points."""
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 6_371 * 2 * asin(sqrt(a))


def _point_in_polygon(lat: float, lng: float, polygon_coords: list) -> bool:
    """
    Simple ray-casting point-in-polygon test.
    polygon_coords is a list of [lng, lat] pairs (GeoJSON order).
    """
    n = len(polygon_coords)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon_coords[i]  # [lng, lat]
        xj, yj = polygon_coords[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _members_reachable(
    member_locations: list[dict],
    isochrone_geojson: dict | None,
) -> tuple[int, int]:
    """
    Count how many group members fall inside a venue's isochrone polygon.
    Returns (reachable_count, total_count).
    """
    if not isochrone_geojson or not member_locations:
        return 0, len(member_locations) if member_locations else 0

    features = isochrone_geojson.get("features", [])
    if not features:
        return 0, len(member_locations)

    # Use the first (largest) polygon
    geometry = features[0].get("geometry", {})
    coords = geometry.get("coordinates", [])
    if not coords:
        return 0, len(member_locations)

    # For Polygon type, coords[0] is the outer ring
    ring = coords[0] if geometry.get("type") == "Polygon" else (coords[0][0] if coords else [])

    reachable = 0
    for member in member_locations:
        mlat = member.get("lat", 0)
        mlng = member.get("lng", 0)
        if _point_in_polygon(mlat, mlng, ring):
            reachable += 1

    return reachable, len(member_locations)


def _compute_score(
    venue: dict,
    isochrone: dict | None,
    member_locations: list[dict] | None,
    center_lat: float,
    center_lng: float,
) -> dict:
    """
    Compute an accessibility score (0.0–1.0) for a single venue.

    Scoring factors:
      - Distance from group centre (closer = better)
      - Member reachability within the isochrone polygon
      - Whether the isochrone was successfully generated
    """
    vlat = venue.get("lat", 0)
    vlng = venue.get("lng", 0)
    dist_km = _haversine_km(center_lat, center_lng, vlat, vlng)

    # Distance score: within 5 km = 1.0, linearly decays to 0.2 at 30 km+
    if dist_km <= 5:
        dist_score = 1.0
    elif dist_km >= 30:
        dist_score = 0.2
    else:
        dist_score = 1.0 - 0.8 * ((dist_km - 5) / 25)

    # Isochrone bonus: having spatial data is valuable
    iso_score = 0.8 if isochrone else 0.4

    # Member reachability score
    member_score = 0.5  # neutral default
    reachable = 0
    total = 0
    transit_accessible = True  # assume true unless we have data to disprove

    if member_locations and isochrone:
        reachable, total = _members_reachable(member_locations, isochrone)
        if total > 0:
            member_score = reachable / total
            transit_accessible = member_score >= 0.5

    # Weighted composite
    score = round(0.4 * dist_score + 0.3 * iso_score + 0.3 * member_score, 2)

    # Rough travel time estimate from distance (avg 30 km/h city driving)
    avg_travel_min = round(dist_km / 30 * 60)
    max_travel_min = round(avg_travel_min * 1.8)  # account for worst-case

    return {
        "score": score,
        "avg_travel_min": avg_travel_min,
        "max_travel_min": max_travel_min,
        "transit_accessible": transit_accessible,
        "distance_km": round(dist_km, 1),
        "members_reachable": reachable,
        "members_total": total,
    }


# ── Per-venue pipeline ─────────────────────────────────────


async def _analyze_venue_access(
    venue: dict,
    member_locations: list[dict] | None,
    center_lat: float,
    center_lng: float,
) -> tuple[str, dict, dict | None]:
    """
    Full accessibility pipeline for a single venue:
    1. Fetch Mapbox isochrone
    2. Compute accessibility score
    """
    venue_id = venue.get("venue_id", venue.get("name", "unknown"))
    vlat = venue.get("lat", 0)
    vlng = venue.get("lng", 0)

    # Fetch isochrone (gracefully returns None on failure)
    isochrone = await get_isochrone(lat=vlat, lng=vlng, profile="driving", contour_minutes=15)

    # Score
    score_data = _compute_score(venue, isochrone, member_locations, center_lat, center_lng)

    return venue_id, score_data, isochrone


# ── Node entry point ───────────────────────────────────────


def access_analyst_node(state: PathfinderState) -> PathfinderState:
    """
    Evaluate travel-time feasibility for the group.

    Steps
    -----
    1. Determine centre point (from member_locations or default Toronto).
    2. For each candidate venue, fetch Mapbox isochrone + compute score.
    3. Return updated state with accessibility_scores + isochrones.
    """
    candidates = state.get("candidate_venues", [])

    if not candidates:
        logger.info("Access Analyst: no candidates to evaluate")
        return {"accessibility_scores": {}, "isochrones": {}}

    # Determine group centre
    member_locations = state.get("member_locations") or []
    if member_locations:
        center_lat = sum(m.get("lat", 0) for m in member_locations) / len(member_locations)
        center_lng = sum(m.get("lng", 0) for m in member_locations) / len(member_locations)
    else:
        # Fallback: use the centroid of the candidate venues themselves
        center_lat = sum(v.get("lat", 0) for v in candidates) / len(candidates)
        center_lng = sum(v.get("lng", 0) for v in candidates) / len(candidates)

    # Analyze all venues concurrently
    async def _analyze_all():
        return await asyncio.gather(*[
            _analyze_venue_access(v, member_locations or None, center_lat, center_lng)
            for v in candidates
        ])

    try:
        results = asyncio.run(_analyze_all())
    except RuntimeError:
        # If event loop is already running
        import nest_asyncio
        nest_asyncio.apply()
        results = asyncio.run(_analyze_all())
    except Exception as exc:
        logger.error("Access Analyst failed: %s", exc)
        results = []

    accessibility_scores = {}
    isochrones = {}

    for venue_id, score_data, isochrone in results:
        accessibility_scores[venue_id] = score_data
        if isochrone:
            isochrones[venue_id] = isochrone

    scored = sum(1 for v in accessibility_scores.values() if v.get("score", 0) > 0)
    logger.info("Access Analyst scored %d/%d venues (%d with isochrones)",
                scored, len(candidates), len(isochrones))

    return {"accessibility_scores": accessibility_scores, "isochrones": isochrones}
