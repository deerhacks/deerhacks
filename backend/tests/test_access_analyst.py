"""
Test Node 4 — The ACCESS ANALYST

Run:  python -m pytest tests/test_access_analyst.py -v -s
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, AsyncMock
from app.agents.access_analyst import (
    access_analyst_node,
    _haversine_km,
    _point_in_polygon,
    _members_reachable,
    _compute_score,
)


# ── Unit Tests (no API calls) ────────────────────────────────


class TestHaversine:
    """Test the distance calculation helper."""

    def test_same_point_is_zero(self):
        assert _haversine_km(43.65, -79.38, 43.65, -79.38) == 0.0

    def test_known_distance(self):
        # Toronto CN Tower → Union Station ≈ 0.5 km
        dist = _haversine_km(43.6426, -79.3871, 43.6453, -79.3806)
        assert 0.3 < dist < 1.0, f"Expected ~0.5km, got {dist:.2f}km"


class TestPointInPolygon:
    """Test the ray-casting point-in-polygon helper."""

    def test_inside_square(self):
        # Square from [0,0] to [1,1] — coords in [lng, lat] order
        square = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        assert _point_in_polygon(0.5, 0.5, square) is True

    def test_outside_square(self):
        square = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        assert _point_in_polygon(2.0, 2.0, square) is False


class TestMembersReachable:
    """Test the member reachability counter."""

    def test_no_isochrone(self):
        members = [{"lat": 43.65, "lng": -79.38}]
        reachable, total = _members_reachable(members, None)
        assert reachable == 0
        assert total == 1

    def test_no_members(self):
        reachable, total = _members_reachable([], {"type": "FeatureCollection", "features": []})
        assert reachable == 0
        assert total == 0


class TestComputeScore:
    """Test the scoring function."""

    def test_nearby_venue_scores_high(self):
        venue = {"lat": 43.65, "lng": -79.38}
        iso = {"type": "FeatureCollection", "features": []}
        result = _compute_score(venue, iso, None, 43.65, -79.38)
        assert result["score"] >= 0.6, f"Close venue should score well, got {result['score']}"
        assert result["distance_km"] < 1

    def test_far_venue_scores_lower(self):
        venue = {"lat": 44.0, "lng": -80.0}
        result = _compute_score(venue, None, None, 43.65, -79.38)
        assert result["score"] < 0.6, f"Far venue should score lower, got {result['score']}"


# ── Integration Tests (mocked Mapbox) ─────────────────────────


_MOCK_ISOCHRONE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-79.40, 43.63], [-79.36, 43.63], [-79.36, 43.67], [-79.40, 43.67], [-79.40, 43.63]]
                ],
            },
        }
    ],
}


@patch("app.agents.access_analyst.get_isochrone", new_callable=AsyncMock)
def test_access_analyst_with_candidates(mock_isochrone):
    """Access Analyst should return scores and isochrones for each venue."""
    mock_isochrone.return_value = _MOCK_ISOCHRONE

    state = {
        "candidate_venues": [
            {"venue_id": "v1", "name": "Venue A", "lat": 43.65, "lng": -79.38},
            {"venue_id": "v2", "name": "Venue B", "lat": 43.66, "lng": -79.39},
        ],
        "parsed_intent": {},
    }

    result = access_analyst_node(state)

    assert "accessibility_scores" in result
    assert "isochrones" in result
    assert "v1" in result["accessibility_scores"]
    assert "v2" in result["accessibility_scores"]
    assert result["accessibility_scores"]["v1"]["score"] > 0
    assert "v1" in result["isochrones"]
    assert result["isochrones"]["v1"]["type"] == "FeatureCollection"

    print(f"\n✅ Access Analyst scored {len(result['accessibility_scores'])} venues")
    for vid, data in result["accessibility_scores"].items():
        print(f"   {vid}: score={data['score']}, dist={data['distance_km']}km, "
              f"travel={data['avg_travel_min']}min")


def test_access_analyst_no_candidates():
    """Access Analyst with no candidates should return empty dicts."""
    state = {"candidate_venues": []}
    result = access_analyst_node(state)
    assert result["accessibility_scores"] == {}
    assert result["isochrones"] == {}


@patch("app.agents.access_analyst.get_isochrone", new_callable=AsyncMock)
def test_access_analyst_mapbox_failure(mock_isochrone):
    """Access Analyst should gracefully handle Mapbox API failures."""
    mock_isochrone.return_value = None  # Simulate failure

    state = {
        "candidate_venues": [
            {"venue_id": "v1", "name": "Venue A", "lat": 43.65, "lng": -79.38},
        ],
    }

    result = access_analyst_node(state)

    assert "v1" in result["accessibility_scores"]
    assert result["accessibility_scores"]["v1"]["score"] > 0  # Should still score
    assert "v1" not in result["isochrones"]  # No isochrone data


@patch("app.agents.access_analyst.get_isochrone", new_callable=AsyncMock)
def test_access_analyst_with_member_locations(mock_isochrone):
    """Access Analyst should factor in member reachability when locations are provided."""
    mock_isochrone.return_value = _MOCK_ISOCHRONE

    state = {
        "candidate_venues": [
            {"venue_id": "v1", "name": "Venue A", "lat": 43.65, "lng": -79.38},
        ],
        "member_locations": [
            {"lat": 43.65, "lng": -79.38},  # Inside the isochrone
            {"lat": 43.65, "lng": -79.39},  # Inside the isochrone
            {"lat": 44.00, "lng": -80.00},  # Outside the isochrone
        ],
    }

    result = access_analyst_node(state)

    score_data = result["accessibility_scores"]["v1"]
    assert score_data["members_reachable"] == 2
    assert score_data["members_total"] == 3
