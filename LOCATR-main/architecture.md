# LOCATR — System Architecture

**Goal:** Group activity and venue planning with vibe scoring, real-time risk detection, spatial visualization, and automated memory.

---

## Overview

LOCATR is a high-speed, multi-agent pipeline built on **LangGraph** using a native **async** architecture. It processes natural language queries through specialized agents to return ranked venues with multimodal "Aesthetic DNA" and safety guarantees.

The core pipeline:
```
COMMANDER → SCOUT → [VIBE MATCHER | COST ANALYST | CRITIC] → SYNTHESISER
```

The three middle agents run concurrently via `asyncio.gather()`, ensuring that total latency is dominated only by the slowest external API call (usually Gemini or Yelp).

---

## Tech Stack

**Backend:** FastAPI + LangGraph, Python 3.11+
**Frontend:** Next.js 14, Mapbox GL JS, CSS (Premium Aesthetics)
**Auth:** Auth0 (CIBA, IDP Token Vault, Management API)
**AI:** Google Gemini 2.5 Flash (Multimodal & Batch Processing)
**Discovery:** Google Places API, Yelp Fusion
**Actions:** Native Gmail API via `httpx` and Auth0 IDP tokens
**Risk Data:** OpenWeather API, PredictHQ (Events)
**Persistence:** Snowflake (Historical Risks & Vibe Vectors)

---

## Agents

### 1. Commander
- **Model:** Gemini 2.5 Flash
- **Goal:** Intent parsing and agent orchestration.
- **Features:** 
  - Fetches Auth0 user profiles to apply weight overrides (e.g., `budget_sensitive` → +20% Cost weight).
  - Categorizes queries into Complexity Tiers (Tier 1/2/3).
  - Detects needed OAuth scopes for actions (Gmail, etc.).
  - **Fallback**: Keyword-based logic ensures reliability if the LLM is unreachable.

### 2. Scout
- **Tools:** Google Places, Yelp, Snowflake
- **Goal:** Venue discovery and deduplication.
- **Features:** 
  - Dual-stream search with Haversine deduplication.
  - **Snowflake Batch Query**: Fetches historical risks for all candidates in **one** query (<1s).
  - Capped at 10 candidate venues for downstream evaluation.

### 3. Vibe Matcher
- **Model:** Gemini 2.5 Flash (Multimodal)
- **Goal:** Aesthetic alignment via "Aesthetic DNA".
- **Features:** 
  - Analyzes venue photos and descriptions in a **single batch prompt**.
  - Maps venues to 50 vibe dimensions (e.g., Cyberpunk, Minimalist, Dark Academia).
  - Generates 50-dimension vibe vectors for spatial similarity.

### 4. Cost Analyst
- **Type:** Heuristic Engine
- **Goal:** Price normalization and conflict resolution.
- **Features:** 
  - Merges Google ($) and Yelp ($$$) price signals using a median-based resolution.
  - Assigns `confidence` levels (High/Medium/Low) based on data source agreement.
  - No LLM needed — purely deterministic for speed.

### 5. Critic
- **Model:** Gemini 2.5 Flash (Adversarial)
- **Goal:** Safety Veto and Risk Detection.
- **Features:** 
  - Fetches Weather (OpenWeather) and Local Events (PredictHQ).
  - **Snowflake Logging**: Automatically persists new detected risks (weather dealbreakers, event closures) to the `VENUE_RISK_EVENTS` table.
  - Batches evaluations for the top 3 candidates into one call.

### 6. Synthesiser
- **Model:** Gemini 2.5 Flash
- **Goal:** Final ranking and action execution.
- **Features:** 
  - Consolidates explanations, consensus, and action drafts into **one** batch LLM call.
  - Applies "Memory Alerts" if historical risks are found in Snowflake.
  - **Auth0 CIBA**: Triggers mobile push notifications for action approval.
  - Executes Gmail messages using tokens from the Auth0 Vault.

---

## Latency & Performance

Through sequential phases of "Hyper-Optimization," the system achieves record-breaking speeds:

| Stage | Latency | Optimization |
| :--- | :--- | :--- |
| **Cold Search** | **5.5 - 7.8s** | Batch LLM Calls + Parallel Agents |
| **Warm (Cache)** | **< 1s** | TTL-based In-Memory Caching |
| **Snowflake Check** | **~0.8s** | Single-call Batch Queries |

---

## Data Schema (Snowflake)

**`VENUE_RISK_EVENTS`**
- `EVENT_ID` (VARCHAR): Unique identifier.
- `VENUE_NAME` (VARCHAR): Display name.
- `VENUE_ID` (VARCHAR): Source ID (Yelp/Google).
- `RISK_DESCRIPTION` (VARCHAR): The specific veto reason.
- `WEATHER_CONTEXT` (VARCHAR): Environmental state at time of veto.
- `VETO_TIMESTAMP` (TIMESTAMP): When the risk was recorded.

**`CAFE_VIBE_VECTORS`**
- Stores 50-dimension embeddings for spatial similarity and heatmap rendering.

---

## Frontend Features

- **Mapbox 3D**: Dynamic buildings layer + pitch/bearing auto-flight.
- **Ranked Pins**: Distinct visual hierarchy (Gold/Silver/Bronze) with pulsating Red pins for Historical Risks.
- **Safety Veto Panel**: High-contrast UI listing Snowflake-sourced historical issues.
- **Vibe Heatmap**: Real-time layer rendering for 50 aesthetic dimensions.
- **Preferences Modal**: Direct sync with Auth0 `app_metadata`.

---

## Environment Configuration

- **Backend**: `.env` manages Snowflake, Auth0, and Search API secrets.
- **Frontend**: Handles Mapbox tokens and Auth0 redirect URIs.
- **Logs**: Structured CLI logging (`[SCOUT]`, `[VIBE]`, etc.) streamed via WebSockets.
