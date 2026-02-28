"""Quick test to run the pipeline and see what errors come up."""
import sys, os, logging, traceback
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.DEBUG, format="%(name)s | %(levelname)s | %(message)s")

from app.graph import pathfinder_graph

state = {
    "raw_prompt": "Coffee shop in Toronto",
    "parsed_intent": {},
    "complexity_tier": "tier_2",
    "active_agents": [],
    "agent_weights": {},
    "candidate_venues": [],
    "vibe_scores": {},
    "accessibility_scores": {},
    "isochrones": {},
    "cost_profiles": {},
    "risk_flags": {},
    "veto": False,
    "veto_reason": None,
    "ranked_results": [],
    "snowflake_context": None,
    "member_locations": [],
}

try:
    import asyncio
    result = asyncio.run(pathfinder_graph.ainvoke(state))
    print("\n=== SUCCESS ===")
    print(f"Ranked results: {len(result.get('ranked_results', []))}")
    for v in result.get("ranked_results", []):
        print(f"  #{v['rank']} {v['name']} — score={v.get('vibe_score')}")
except Exception as exc:
    print(f"\n=== ERROR ===")
    traceback.print_exc()
