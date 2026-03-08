
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, AsyncMock
from app.agents.vibe_matcher import vibe_matcher_node

# ── Mock venue data ──────────────────

MOCK_CANDIDATES = [
    {
        "venue_id": "gp_test001",
        "name": "The Cozy Bean Café",
        "lat": 43.6510,
        "lng": -79.3935,
    }
]

@patch("app.agents.vibe_matcher.generate_content", new_callable=AsyncMock)
def test_vibe_matcher_success(mock_generate_content):
    mock_generate_content.return_value = '''
    {
      "score": 0.9,
      "style": "cozy",
      "descriptors": ["warm", "quiet"],
      "confidence": 0.8
    }
    '''
    
    state = {
        "parsed_intent": {"vibe": "cozy"},
        "candidate_venues": MOCK_CANDIDATES,
    }

    result = vibe_matcher_node(state)
    scores = result.get("vibe_scores", {})
    assert "gp_test001" in scores
    assert scores["gp_test001"]["score"] == 0.9

def test_vibe_matcher_empty_candidates():
    state = {"candidate_venues": []}
    result = vibe_matcher_node(state)
    assert result["vibe_scores"] == {}
