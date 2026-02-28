
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from app.agents.commander import commander_node

@patch('app.agents.commander.generate_content', new_callable=AsyncMock)
def test_commander_node_success(mock_generate_content):
    # Mock Gemini response
    mock_generate_content.return_value = '''
    {
      "parsed_intent": {"activity": "basketball", "budget": "low"},
      "complexity_tier": "tier_2",
      "active_agents": ["scout", "cost_analyst"],
      "agent_weights": {"scout": 1.0, "cost_analyst": 0.8}
    }
    '''
    
    state = {"raw_prompt": "basketball court cheap"}
    new_state = commander_node(state)
    
    assert new_state["parsed_intent"]["activity"] == "basketball"
    assert new_state["complexity_tier"] == "tier_2"
    assert "scout" in new_state["active_agents"]

@patch('app.agents.commander.generate_content', new_callable=AsyncMock)
def test_commander_node_fallback_on_error(mock_generate_content):
    # Mock Gemini throwing an error
    mock_generate_content.side_effect = Exception("API Error")
    
    state = {"raw_prompt": "basketball court"}
    new_state = commander_node(state)
    
    # Assert fallback values (Now tier_3 because of heuristic fallback in code)
    assert new_state["complexity_tier"] == "tier_3"
    assert "scout" in new_state["active_agents"]
