"""
Integration test — Scout → Vibe Matcher pipeline.
Run: python tests/run_pipeline.py
"""
import sys, os, logging, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from app.agents.scout import scout_node
from app.agents.vibe_matcher import vibe_matcher_node

print("=" * 60)
print("PATHFINDER — Scout → Vibe Matcher Integration Test")
print("=" * 60)

# Initial state
state = {
    "raw_prompt": "cozy café in downtown Toronto",
    "parsed_intent": {
        "activity": "cozy café",
        "location": "downtown Toronto",
        "vibe": "cozy",
    },
    "candidate_venues": [],
    "vibe_scores": {},
}

# Step 1: Scout
print("\n--- STEP 1: Running Scout ---")
try:
    state = scout_node(state)
    candidates = state.get("candidate_venues", [])
    print(f"Scout found {len(candidates)} candidates:")
    for v in candidates:
        print(f"  [{v['source']}] {v['name']} — rating {v['rating']}")
except Exception as e:
    print(f"SCOUT FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

if not candidates:
    print("NO CANDIDATES — cannot test Vibe Matcher")
    sys.exit(1)

# Step 2: Vibe Matcher
print(f"\n--- STEP 2: Running Vibe Matcher (scoring {len(candidates)} venues) ---")
try:
    state = vibe_matcher_node(state)
    scores = state.get("vibe_scores", {})
    print(f"Vibe Matcher returned {len(scores)} scores:")
    for vid, s in scores.items():
        name = next((v["name"] for v in candidates if v["venue_id"] == vid), vid)
        print(f"  {name}: score={s['score']}, style={s['style']}, confidence={s['confidence']}")
except Exception as e:
    print(f"VIBE MATCHER FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# Verify
print("\n--- VERIFICATION ---")
passed = True
for v in candidates:
    vid = v["venue_id"]
    if vid not in scores:
        print(f"FAIL: {v['name']} ({vid}) has no vibe score")
        passed = False

if passed:
    print(f"PASS: All {len(candidates)} candidates have vibe scores")
    print("Scout → Vibe Matcher connection is working!")
else:
    print("FAIL: Some candidates are missing vibe scores")
    sys.exit(1)
