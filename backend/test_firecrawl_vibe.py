import sys
import os
import time
import json
import logging
import asyncio

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, os.path.dirname(__file__))

from app.graph import pathfinder_graph
from app.models.state import PathfinderState

import asyncio

async def run_test_query(query: str):
    print(f"\n{'='*60}")
    print(f"QUERY: '{query}'")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    initial_state = {
        "raw_prompt": query,
        "payment_authorized": True,  # Simulate Solana payment having gone through to bypass CIBA interrupt
        "auth_user_id": "simulated_test_user_123" 
    }
    
    try:
        final_state = initial_state.copy()
        
        # Stream the graph to observe State updates
        async for event in pathfinder_graph.astream(initial_state):
            for node, state_update in event.items():
                print(f"\n[EVENT] Node completed: {node}")
                if state_update is None:
                    continue
                    
                if "candidate_venues" in state_update:
                    print(f"        -> returned {len(state_update['candidate_venues'])} candidates")
                
                # Merge into final state for our own tracking
                final_state.update(state_update)
                
        runtime = time.time() - start_time
        print(f"\n[RUNTIME] {runtime:.2f} seconds")
        
        candidates = final_state.get("candidate_venues", [])
        cost_profiles = final_state.get("cost_profiles", {})
        vibe_scores = final_state.get("vibe_scores", {})
        
        print("\n[VENUES ANALYSIS]")
        for i, venue in enumerate(candidates, 1):
            vid = venue.get("venue_id")
            name = venue.get("name")
            print(f"\n--- {i}. {name} ---")
            
            # Print Vibe info
            vibe = vibe_scores.get(vid, {})
            v_score = vibe.get("score", "N/A")
            v_reason = vibe.get("style", "N/A")
            v_desc = ", ".join(vibe.get("descriptors", []))
            print(f"  VIBE SCORE: {v_score} | STYLE: {v_reason}")
            print(f"  VIBE DESCRIPTORS: {v_desc}")
            
            # Print Cost info
            cost = cost_profiles.get(vid, {})
            base_cost = cost.get("base_cost", "N/A")
            tca = cost.get("total_cost_of_attendance", "N/A")
            pp = cost.get("per_person", "N/A")
            conf = cost.get("pricing_confidence", "N/A")
            print(f"  COST: Base=${base_cost} | Total=${tca} | Per Person=${pp}")
            print(f"  COST CONFIDENCE: {conf}")
            
        print("\n[FINAL RECOMMENDATIONS (Synthesiser)]")
        ranked = final_state.get("ranked_results", [])
        if not ranked:
            print("  No ranked results returned!")
        for r in ranked:
            print(f"  -> {r.get('name', 'Unknown')} (Score: {r.get('final_score', 'N/A')})")
            print(f"     Match Strategy: {r.get('match_strategy', 'Unknown')}")
            for highlight in r.get('highlights', []):
                print(f"       + {highlight}")
            for warning in r.get('warnings', []):
                print(f"       ! {warning}")
            
    except Exception as e:
        print(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()

async def main():
    test_queries = [
        "A cyberpunk or neon-themed arcade or bar in Toronto for 4 friends to hang out. Must look super cool and instagrammable.",
        "My friends and I (8 people) want to rent a basketball court this Saturday afternoon in downtown Toronto. Under $200.",
        "A cute, aesthetic cafe in downtown Toronto with a quiet, cozy vibe for a date. Under $50."
    ]
    
    for q in test_queries:
        await run_test_query(q)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    
    # Suppress httpx to avoid 100,000 line log files from image redirect tracking
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    asyncio.run(main())

