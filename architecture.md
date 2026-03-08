# LOCATR — System Architecture

**Goal:** Group activity and venue planning with vibe scoring, real-time risk detection, and spatial visualization.

---

## Overview

LOCATR is a multi-agent pipeline built on LangGraph. A user types a natural language query; six specialized agents process it in sequence (with three running in parallel), and the system returns ranked venues with plain-English explanations of why each one works — or doesn't.

The core loop:

```
COMMANDER → SCOUT → [VIBE MATCHER | COST ANALYST | CRITIC] → SYNTHESISER
```

The three middle agents (vibe, cost, critic) run concurrently via `asyncio.gather()`. The Commander and Synthesiser always run. Everything else is conditional.

---

## Tech Stack

**Backend:** FastAPI + LangGraph, Python 3.11+
**Frontend:** Next.js 14, Mapbox GL JS, Tailwind CSS
**Auth:** Auth0 (Universal Login, Management API, CIBA, Token Vault)
**AI:** Google Gemini 2.5 Flash (multimodal) + Gemini 1.5 Flash (text)
**Discovery:** Google Places Text Search API, Yelp Fusion
**Actions:** Native Gmail API via `httpx`
**Risk Data:** OpenWeather API, PredictHQ
**Persistence:** Snowflake (`VENUE_RISK_EVENTS`, `CAFE_VIBE_VECTORS`)
**Voice:** ElevenLabs TTS

---

## Agents

### 1. Commander

**Model:** Gemini 1.5 Flash
**File:** `backend/app/agents/commander.py`

The Commander is the first node in every request. It does two things: pull the user's stored preferences from Auth0, then send the raw prompt to Gemini to parse structured intent.

Gemini returns a JSON object with:
- `parsed_intent` — activity, group size, budget (low/medium/high), location, vibe keyword
- `complexity_tier` — tier_1 (simple lookup), tier_2 (multi-factor), tier_3 (strategic/business)
- `active_agents` — which downstream agents to run
- `agent_weights` — importance scores per agent (0.0–1.0), adjusted by user profile
- `requires_oauth` + `oauth_scopes` — if the query implies an action (send email, check calendar)

If Gemini is unavailable, a keyword-based fallback extracts intent from the raw prompt using three hardcoded dictionaries (budget keywords, vibe keywords, activity keywords).

User profile preferences from Auth0 (`budget_sensitivity`, `vibe_first`, `risk_averse`) directly influence the weights passed downstream. A student profile bumps cost weight; an explicit vibe request bumps vibe weight.

The Commander never touches OAuth tokens — it only declares that a scope is required. Execution authority sits with Auth0 + the Synthesiser, not here.

---

### 2. Scout

**Tools:** Google Places API, Yelp Fusion
**File:** `backend/app/agents/scout.py`

The Scout queries both Google Places and Yelp concurrently (up to 8 results each), then deduplicates by:
1. Case-insensitive name match
2. Haversine distance < 100m (catches same venue with slightly different names)

When both sources have pricing data for a venue, both values are passed through — the Cost Analyst resolves the conflict later.

After dedup, the Scout calls Snowflake to pull historical risk events for each venue (past floods, marathon route closures, etc.). This gets injected directly into the Critic's context, bypassing LLM hallucination.

Results are capped at 10 candidates.

**Output per venue:**
```json
{
  "venue_id": "gp_abc123",
  "name": "Example Cafe",
  "address": "123 Main St, Toronto",
  "lat": 43.65,
  "lng": -79.38,
  "rating": 4.4,
  "price_range": "$$",
  "price_source": "google",
  "photos": ["url1", "url2"],
  "category": "cafe",
  "historical_risks": []
}
```

---

### 3. Vibe Matcher

**Model:** Gemini 2.5 Flash (multimodal)
**File:** `backend/app/agents/vibe_matcher.py`

For each candidate venue, the Vibe Matcher sends venue photos + text metadata to Gemini and gets back a 52-dimension vibe vector. The dimensions cover things like: cozy, minimalist, cyberpunk, dark academia, romantic, lively, rustic, industrial, cottagecore, instagrammable, and 42 others.

All venues are scored in parallel. If a specific vibe was requested (e.g., "dark academia") and a venue scores below 0.4 on that dimension, it's filtered out. The fallback logic ensures at least 3 venues always survive — it re-promotes the highest-scoring rejected venues if the list would otherwise be too small.

Failed API calls for individual venues return `{score: null, confidence: 0.0}` and the pipeline continues.

**Output:**
```json
{
  "vibe_scores": {
    "gp_abc123": {
      "score": 0.72,
      "vibe_dimensions": [0.8, 0.3, 0.6, ...],
      "style": "cozy",
      "confidence": 0.85
    }
  }
}
```

---

### 4. Cost Analyst

**Model:** None (pure heuristic)
**File:** `backend/app/agents/cost_analyst.py`

No LLM calls here. The Cost Analyst normalizes price signals from Scout and resolves conflicts:

| Scenario | Outcome |
|----------|---------|
| Google + Yelp agree | Use value, `confidence: "high"` |
| Only one source | Use value, `confidence: "medium"` |
| Conflict (e.g., $ vs $$$) | Median, `confidence: "low"` |
| No data at all | `price_range: null`, `confidence: "none"` |

Pricing is display-only. No scraping, no numeric cost computation, no OAuth.

Value scores: `$` → 0.8, `$$` → 0.6, `$$$` → 0.4, `$$$$` → 0.2, adjusted slightly downward for low/estimated confidence.

---

### 5. Critic

**Model:** Gemini (adversarial reasoning)
**Tools:** OpenWeather API, PredictHQ
**File:** `backend/app/agents/critic.py`

The Critic runs against the top 3 candidates. For each, it:
1. Fetches current weather from OpenWeather (temp, condition, description)
2. Fetches upcoming events within a 1-mile radius from PredictHQ
3. Injects Snowflake historical risks (from Scout)
4. Sends everything to Gemini with an adversarial prompt: "find dealbreakers"

Gemini returns risk flags per venue (with severity: high/medium/low). The veto flag is set but the pipeline doesn't halt on veto — the Synthesiser surfaces the risk in `watch_out` text and the frontend shows it as a warning.

Risk events are logged back to Snowflake (`VENUE_RISK_EVENTS`) for future Scout queries to pick up, with deduplication to avoid repeated entries.

**Output:**
```json
{
  "risk_flags": {
    "gp_abc123": [
      {"description": "Outdoor court, heavy rain forecast Saturday", "severity": "high"}
    ]
  },
  "veto": false,
  "veto_reason": null
}
```

---

### 6. Synthesiser

**Model:** Gemini 2.5 Flash
**File:** `backend/app/agents/synthesiser.py`

The Synthesiser collects all agent outputs and produces the final ranked list.

**Composite scoring:**
```
composite = (w_vibe × vibe_score) + (w_cost × value_score) + (w_risk × risk_score)
```

Default weights: vibe=0.33, cost=0.40, risk=0.27. These are overridden by whatever the Commander set in `agent_weights`.

After ranking, Gemini generates `why` and `watch_out` text for each top-3 venue, plus a `global_consensus` — a single comparative sentence highlighting the best pick across price, rating, weather, and vibe.

If the Commander flagged an OAuth requirement (e.g., sending an email), the Synthesiser attempts an Auth0 CIBA (Client Initiated Backchannel Authentication) push notification to the user's mobile device.
- If approved, it retrieves the user's Google OAuth2 token from the Auth0 Token Vault.
- It then executes the action directly on the backend (e.g., dispatching an email via the native Gmail API using `httpx`).
- It returns an `oauth_success` payload to the frontend, which renders an auto-dismissing confirmation UI.
If CIBA fails or is unsupported, it falls back to requesting standard frontend browser consent.

**Output (per venue):**
```json
{
  "rank": 1,
  "name": "Example Cafe",
  "address": "123 Main St, Toronto",
  "lat": 43.65,
  "lng": -79.38,
  "rating": 4.4,
  "vibe_score": 0.72,
  "price_range": "$$",
  "price_confidence": "medium",
  "why": "Best vibe match for cozy + affordable. 4.4 stars from 200+ reviews.",
  "watch_out": "Gets busy weekend afternoons."
}
```

---

## LangGraph State

**File:** `backend/app/models/state.py`

```python
class PathfinderState(TypedDict):
    raw_prompt: str
    parsed_intent: dict
    auth_user_id: Optional[str]
    user_profile: Optional[dict]

    complexity_tier: str          # "tier_1" | "tier_2" | "tier_3"
    active_agents: List[str]
    agent_weights: dict

    requires_oauth: bool
    oauth_scopes: List[str]
    allowed_actions: List[str]

    candidate_venues: List[dict]
    vibe_scores: dict
    cost_profiles: dict
    risk_flags: dict
    veto: bool
    veto_reason: Optional[str]
    fast_fail: bool
    fast_fail_reason: Optional[str]

    ranked_results: List[dict]
    global_consensus: Optional[str]
    action_request: Optional[dict]

    member_locations: List[dict]
    chat_history: Optional[List[dict]]
    snowflake_context: Optional[dict]
```

---

## API Reference

### `GET /health`
```json
{ "status": "ok", "service": "pathfinder" }
```

---

### `POST /api/plan`

Runs the full pipeline synchronously. Use this for testing; the frontend uses the WebSocket.

**Request:**
```json
{
  "prompt": "Basketball court for 10 people under $200",
  "group_size": 1,
  "budget": null,
  "location": null,
  "vibe": null,
  "member_locations": [],
  "chat_history": []
}
```

**Response:**
```json
{
  "venues": [ /* VenueResult[] */ ],
  "global_consensus": "Example Cafe offers the best value...",
  "execution_summary": "Pipeline complete.",
  "user_profile": { ... },
  "agent_weights": { "scout": 1.0, "vibe_matcher": 0.6, "cost_analyst": 0.9 },
  "action_request": null
}
```

---

### `WS /api/ws/plan`

The primary frontend endpoint. Streams agent progress as logs, then emits the final result.

**Client sends on connect:**
```json
{ "prompt": "...", "member_locations": [] }
```

**Server streams (one per log line, per agent):**
```json
{
  "type": "log",
  "node": "scout",
  "message": "[SCOUT] Found 6 candidates after dedup"
}
```

**Server sends once, at the end:**
```json
{
  "type": "result",
  "data": { /* PlanResponse */ }
}
```

---

### `GET /api/user/preferences`
```
?auth_user_id=auth0|abc123
```
Returns the user's stored preferences from Auth0 `app_metadata`.

---

### `PATCH /api/user/preferences`

Merges new preference values into Auth0 `app_metadata`.

---

### `GET /api/vibe-heatmap`
```
?vibe_index=4
```
Returns all venues from Snowflake's `CAFE_VIBE_VECTORS` table with their score for the requested vibe dimension (0–51). The frontend uses this to render a heatmap layer on the map.

---

### `POST /api/voice/synthesize`

Calls ElevenLabs to convert text (e.g., a `why` explanation) to speech.

```json
{ "text": "This venue has great lighting and a cozy atmosphere.", "voice_id": "..." }
```

Returns `audio/mpeg`.

---

## Snowflake Schema

Two tables:

**`VENUE_RISK_EVENTS`** — Critic writes to this. Scout reads from it.
- `VENUE_ID`, `VENUE_NAME`, `RISK_DESCRIPTION`, `WEATHER_CONTEXT`, `VETO_TIMESTAMP`

**`CAFE_VIBE_VECTORS`** — Used for heatmap queries and vibe similarity search.
- `VENUE_ID`, `NAME`, `LATITUDE`, `LONGITUDE`, `H3_INDEX`, `VIBE_VECTOR VECTOR(FLOAT, 50)`, `PRIMARY_VIBE`

The `VIBE_VECTOR` field stores the 52-dimension vibe embedding per venue. The heatmap endpoint queries this to return `{lat, lng, score}` points for a given vibe dimension.

---

## Frontend

**Pages:**
- `/` — Landing page with Auth0 login. Animated SVG trail effect.
- `/map` — Main interface. Mapbox map + search bar + sidebar.

**Map features:**
- 3D buildings layer (fill-extrusion at pitch 45°)
- User geolocation tracking
- Ranked pins: gold (#1), silver (#2), bronze (#3), grey (rest)
- Click pin or sidebar card → map flies to venue
- Optional heatmap layer via vibe filter

**Sidebar:**
- During search: Live agent logs, grouped by node
- After results: Ranked venue cards with vibe score, price, rating, why/watch_out
- Tab toggle between logs and results
- Drag-resizable

**Agent Row:**
- Bottom bar showing completed agent badges
- Dismisses when results arrive

**Preferences Panel:**
- Shows active Auth0 preference weights (budget_sensitivity, vibe_first, risk_averse)

**Vibe Filter:**
- Modal to pick one of 52 vibe dimensions
- Triggers `/api/vibe-heatmap` and renders heatmap layer on map

---

## Environment Variables

**Backend (`backend/.env`):**
```
GOOGLE_CLOUD_API_KEY=       # Google Places + Gemini
YELP_API_KEY=
OPENWEATHER_API_KEY=
PREDICTHQ_API_KEY=
ELEVENLABS_API_KEY=
AUTH0_DOMAIN=
AUTH0_CLIENT_ID=
AUTH0_CLIENT_SECRET=
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_DATABASE=PATHFINDER
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
CORS_ORIGINS=["http://localhost:3000"]
```

**Frontend (`.env`):**
```
NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=
NEXT_PUBLIC_WS_URL=ws://localhost:8000
AUTH0_SECRET=
AUTH0_BASE_URL=http://localhost:3000
AUTH0_DOMAIN=
AUTH0_CLIENT_ID=
AUTH0_CLIENT_SECRET=
```

---

## Logging

Every agent logs structured messages at `INFO` level, prefixed by agent name. Logs are visible in the CLI runner and streamed to the frontend via WebSocket.

| Prefix | Agent |
|--------|-------|
| `[COMMANDER]` | `app.agents.commander` |
| `[SCOUT]` | `app.agents.scout` |
| `[VIBE]` | `app.agents.vibe_matcher` |
| `[COST]` | `app.agents.cost_analyst` |
| `[CRITIC]` | `app.agents.critic` |
| `[SYNTH]` | `app.agents.synthesiser` |
| `[GRAPH]` | `app.graph` |

Root logger and `httpx`/`httpcore` are set to `WARNING` to suppress noise.

---

## Notes

- The system executes real-world actions on behalf of the user. OAuth scope detection is live; transactional actions (like automated email dispatch for bookings) are fully wired up via Auth0 CIBA push notifications and Auth0 Token Vault extraction.
- Local dev supports a mock auth user (`auth0|local_test`) that bypasses the Auth0 Management API lookup.
- The vibe heatmap only returns data if `CAFE_VIBE_VECTORS` has been populated (there's a `verify_population` utility for this).
- Parallel execution (vibe/cost/critic) cuts typical pipeline latency from ~9s to ~2–3s depending on API response times.
- All agent outputs fall back gracefully: keyword heuristics for Commander, `score: null` for failed Vibe calls, `price_range: null` for missing cost data.
