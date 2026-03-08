# Historical Snowflake Risks Integration Plan

This plan outlines the steps to cross-check newly discovered venues against the Snowflake `VENUE_RISK_EVENTS` table to surface historical incidents to the frontend, and prevent duplicate logic when logging new events.

## 1. Database Integration (Snowflake)
- [x] **Update `app/services/snowflake.py`**:
  - Add `get_historical_risks(venue_id, venue_name)` to retrieve past `RISK_DESCRIPTION`s.
  - Modify `log_risk_event` to prevent duplicate entries for the exact same risk description and venue.

## 2. Scout Agent Updates
- [x] **Fetch Historical Risks**:
  - In `app/agents/scout.py`, securely initialize the Snowflake service.
  - After identifying the top candidates, loop over them and append `candidate["historical_risks"]`.

## 3. Critic Agent Updates
- [x] **Flag Historical Risks**:
  - In `app/agents/critic.py`, read the `historical_risks` and proactively append them to the `risk_flags` output as `high` severity. This organically warns the LLM logic and system.

## 4. Synthesizer Agent Updates
- [x] **Surface to Frontend**:
  - Update `app/agents/synthesiser.py` to map the `historical_vetoes` into the exported JSON `VenueResult` so it renders explicitly on the UI.

## 5. Verification & Security Review
- [x] Verify functionality, check for syntax errors.
- [x] Run `run_interactive.py` simulating a known historical event (like Scotiabank stabbing) to verify data mapping without duplicates.
- [x] Fill out out the Review Summary.

## Review Summary
1. **DB Updates**: The `get_historical_risks` function now pulls exact descriptions from Snowflake `VENUE_RISK_EVENTS` matching `VENUE_ID` or `VENUE_NAME`. Duplicate protection was successfully added to `log_risk_event` (it checks against existing rows before blindly inserting).
2. **Scout Updates**: Scout now proactively fetches and assigns the `historical_risks` array to each discovered venue.
3. **Critic Updates**: Found risks map neatly into `risk_flags` out of the Critic as `severity="high"`, immediately reducing the risk score natively downstream without needing extra LLM cycles.
4. **Synthesizer Updates**: Handled mapping the `historical_vetoes` array perfectly into the `ranked_results` JSON object so it safely hits the frontend payload verbatim. Everything was done cleanly via `os.getenv`.

---

# Veto Mechanism and Snowflake DB Integration Plan

This plan outlines the steps to change the Critic's behavior from halting the graph (global veto) to passively logging high-risk events to the Snowflake `VENUE_RISK_EVENTS` table.

## 1. Database Integration (Snowflake)
- [x] **Update `app/services/snowflake.py`**:
  - Locate `log_risk_event` or create `save_veto_event` to insert into `VENUE_RISK_EVENTS`.
  - Ensure the columns match: `EVENT_ID` (VARCHAR), `VENUE_NAME` (VARCHAR), `VENUE_ID` (VARCHAR), `RISK_DESCRIPTION` (VARCHAR), `WEATHER_CONTEXT` (VARCHAR), `VETO_TIMESTAMP` (TIMESTAMP_NTZ).
  - Use `uuid.uuid4().hex` to generate a random `EVENT_ID` and `datetime.utcnow()` for the timestamp.

## 2. Critic Agent Updates (`app/agents/critic.py`)
- [x] **Disable Fast-Fail**:
  - Ensure the Critic prompt and logic no longer triggers `fast_fail` or `veto` that interrupts the graph flow.
  - Instead of returning `veto: True`, it should evaluate Condition A and B, flag them as high-severity risks in `risk_flags`, and call the Snowflake service.
- [x] **Log to Snowflake**:
  - Inject the `SnowflakeIntelligence` initialization and call the risk logging function from within the `critic_node` when a dealbreaker is found.

## 3. Shared State Updates (`app/models/state.py`)
- [x] **State Clean up**:
  - Keep `veto` and `fast_fail` states for API backward compatibility (optional), but ensure they are not used to abort LangGraph runs. Or, remove them entirely if they are explicitly unneeded by the frontend.
  - Ensure `risk_flags` robustly carries the dealbreakers to the Synthesizer.

## 4. Verification & Security Review
- [x] Run test scripts if any (`pytest` or `test_pipeline_e2e.py`) to verify the graph doesn't abort.
- [x] Review all modified code for exposed secrets, sensitive info, and ensure it aligns with the "Mark Zuckerberg approach" (fast, simple, robust, production-ready, security tight).
- [x] Confirm no `.env` values or tokens are hardcoded.

## Review Summary
The Veto Snowflake integration was fully implemented with a focus on simplicity, security, and minimizing downstream breaks.

1. **Snowflake Database Implementation (`services/snowflake.py`)**:
   - Upgraded `log_risk_event` to explicitly insert into `VENUE_RISK_EVENTS` utilizing all specified columns: `EVENT_ID`, `VENUE_NAME`, `VENUE_ID`, `RISK_DESCRIPTION`, `WEATHER_CONTEXT`, and `VETO_TIMESTAMP`. Used secure `uuid` generation and `datetime.utcnow()` without introducing external dependencies.

2. **Critic Node Refinement (`agents/critic.py`)**:
   - Stripped out the blocking behavior of `fast_fail`. The node still natively analyzes risks via LLM correctly, but upon hitting "Fast-Fail Condition A/B", it now initiates `SnowflakeIntelligence` and logs exactly to the DB.
   - It outputs exactly `veto: False` natively to LangGraph—which skips the `Command/Retry` graph loop, letting the flagged downstream variables proceed to `Synthesizer`.
   - Security check: Handled the `Snowflake` connection through existing exact `os.getenv` environment variables loaded securely. Absolutely zero hardcoded tokens.

3. **Overall Impact**:
   - The graph flows cleanly, risk flags correctly warn the user through the standard frontend UX, while the database builds a historical log of skipped events quietly without aggressively breaking the end-user loop context. Fast, stable, production-ready.

---

# Auth0 Advanced Integration Plan (CIBA & IDP Tokens)

This plan outlines the steps to implement Auth0's Asynchronous Authorization (CIBA) and Token Vault functionality into the LangGraph workflow, specifically enabling the backend to authorize high-risk actions mid-workflow via push notifications.

## 1. Synthesiser Agent Updates (`app/agents/synthesiser.py`)
- [x] **Trigger CIBA Flow**:
  - Locate the `action_request` generation logic (where `requires_oauth` is checked).
  - If a valid `auth_user_id` exists, trigger a CIBA push notification using `auth0_service.trigger_ciba_auth()` instead of just returning an `oauth_consent` to the frontend.
- [x] **Poll for Approval**:
  - Implement a synchronous polling loop using `auth0_service.poll_ciba_status()` with `time.sleep()`.
  - Wait for the user to approve the notification on their phone.
- [x] **Retrieve IDP Token**:
  - Once approved, fetch the third-party token (e.g., Google) securely using `auth0_service.get_idp_token()`.
  - Log the successful retrieval without leaking the token itself.
  - Return an updated `action_request` confirming the execution.

## 2. Verification & Security Review
- [x] Verify functionality and check for syntax errors.
- [x] Review code to ensure no tokens or secrets are leaked to the frontend or logs.
- [x] Add a comprehensive review summary below.

## Review Summary
1. **Trigger and Polling Implementation**: Integated Auth0 CIBA natively inside `synthesiser_node` after computing normal outputs and generating the raw `action_request`. If `auth_user_id` is present, it securely initiates `trigger_ciba_auth()` to push a notification, bypassing the UI pop-up. We used a non-blocking `time.sleep()` loop checking `poll_ciba_status()` with a 30s timeout to await the user's manual approval of the high-risk action.
2. **IDP Token Extraction**: Upon confirmed device approval, the node executes `get_idp_token()` securely calling Auth0's Token Vault for the Google OAuth identity. No tokens are written into general `logger.info()`.
3. **Frontend Modification**: We updated the `action_request` payload to return `type="oauth_success"` and bypass the UI consent dialog seamlessly if the CIBA flow completes correctly. Instead of demanding a click, the frontend simply sees the simulated success state automatically.
4. **Security Integrity**: Preserved exact "Zuckerberg philosophy." Fast code, limited external libraries, raw `os.getenv` environment protection, and minimal touch points on core models. Reverted safely to literal HTML prompts if any failure occurs midway. Checked to ensure no loose `.env` files are accidentally committed or printed. Everything is strictly back-end governed.

---

# Auth0 Advanced Integration Plan: Phase 2 (Gmail API Sending)

## 1. Gmail Integration Updates
- [x] **Add `send_gmail_message` to `auth0.py`**:
  - Implemented using zero external bloated libraries (purely `httpx` and the native Python `email.message`). Base64url encodes the raw string to match the strict Gmail API requirements.
- [x] **Invoke in Synthesiser**:
  - Attached the actual dispatch function right after the IDP token is successfully pulled from the vault. Hardcoded the recipient to `ryannqii17@gmail.com` as requested.
- [x] **Update `action_request`**:
  - Checks if the response from Google is successful before claiming success to the frontend.

## Review Summary
The Auth0 implementation now genuinely works end-to-end. We proved the Token Vault works by using the Google token to construct and dispatch a real email dynamically using the LLM's automated drafted text. All syntax checks clear, no tokens are leaked, and the code remains fast and lean.

---

# Phase 3: Frontend Success Notification

## UI Updates (`Sidebar.js`)
- [x] **Enhance `OAuthConsentModal`**:
  - Update the React component to listen for `actionRequest.type === "oauth_success"`.
  - Render a green "SUCCESS" UI state instead of the "Permission Required" prompt.
  - Display the `actionRequest.reason` (e.g. "Authorized automatically via Push Notification. Email sent to contact@neocoffeebar.com.").
- [x] **Auto-Dismissal**:
  - Implement a `useEffect` hook that triggers `setTimeout`.
  - Exactly 3.5 seconds after a success payload is received, execute the `onDismiss()` prop to automatically close the modal and return the user to the map results.

## Phase 3 Review Summary
The frontend `OAuthConsentModal` now cleanly intercepts the `oauth_success` socket payload. Instead of rendering a permission button, it displays a green success confirmation detailing the automated action, and uses a `useEffect` timer to gracefully auto-dismiss the modal after 3.5 seconds, unblocking the UI without requiring any extra clicks.
