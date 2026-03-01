"""
Node 5 -- The COST ANALYST (Financial)
"No-surprises" auditor: scrapes true cost and compares to Snowflake history.

Scraping Strategy:
  1. Firecrawl /map    -> discover "Pricing" / "Menu" page on venue website
  2. Firecrawl /scrape -> extract page content as markdown
  3. Gemini            -> extract structured pricing from content

Fallback Tiers:
  - Confirmed pricing  -> value_score from Gemini assessment
  - Estimated pricing   -> value_score capped at 0.5 with estimation note
  - Unknown pricing     -> value_score 0.3 with uncertainty warning

Tools: Firecrawl, Gemini
"""

import asyncio
import json
import logging
from typing import Optional

import httpx

from app.models.state import PathfinderState
from app.services.gemini import generate_content
from app.core.config import settings

logger = logging.getLogger(__name__)


# -- Firecrawl ----------------------------------------------------------
_FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"


async def _firecrawl_map(website_url: str) -> list[str]:
    """
    Use Firecrawl /map to discover sub-pages on a venue website.
    Returns a list of page URLs, filtered for pricing-related pages.
    """
    if not settings.FIRECRAWL_API_KEY:
        return []

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # 10-second strict wrapper
                resp = await asyncio.wait_for(
                    client.post(
                        f"{_FIRECRAWL_BASE}/map",
                        headers={"Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}"},
                        json={
                            "url": website_url,
                            "search": "pricing rates cost fees menu package book reserve",
                        },
                    ),
                    timeout=10.0
                )
                if resp.status_code == 429:
                    raise httpx.HTTPStatusError("429 Too Many Requests", request=resp.request, response=resp)
                resp.raise_for_status()
                data = resp.json()

            all_links = data.get("links", [])

            # Filter for pricing / menu / rates pages
            pricing_keywords = ["pric", "rate", "cost", "fee", "menu", "book", "package"]
            relevant = [
                link for link in all_links
                if any(kw in link.lower() for kw in pricing_keywords)
            ]

            return relevant if relevant else all_links[:3]

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning("Firecrawl /map rate limited (429). Retrying %s in %ss...", website_url, wait_time)
                await asyncio.sleep(wait_time)
                continue
            logger.warning("Firecrawl /map failed for %s: %s", website_url, exc)
            return []
        except httpx.HTTPError as exc:
            logger.warning("Firecrawl /map network error for %s: %s", website_url, exc)
            return []
        except asyncio.TimeoutError:
            logger.warning("⚠️ Firecrawl /map SKIPPED %s: Website took longer than 10 seconds.", website_url)
            return []
        except Exception as exc:
            logger.warning("❌ Firecrawl /map error for %s: %s", website_url, exc)
            return []


async def _firecrawl_scrape(page_url: str) -> Optional[str]:
    """
    Use Firecrawl /scrape to extract page content as markdown.
    Returns the markdown text of the page.
    """
    if not settings.FIRECRAWL_API_KEY:
        return None

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # 10-second strict wrapper
                resp = await asyncio.wait_for(
                    client.post(
                        f"{_FIRECRAWL_BASE}/scrape",
                        headers={"Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}"},
                        json={
                            "url": page_url,
                            "formats": ["markdown"],
                        },
                    ),
                    timeout=10.0
                )
                if resp.status_code == 429:
                    raise httpx.HTTPStatusError("429 Too Many Requests", request=resp.request, response=resp)
                resp.raise_for_status()
                data = resp.json()

            return data.get("data", {}).get("markdown", "")

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning("Firecrawl /scrape rate limited (429). Retrying %s in %ss...", page_url, wait_time)
                await asyncio.sleep(wait_time)
                continue
            logger.warning("Firecrawl /scrape failed for %s: %s", page_url, exc)
            return None
        except httpx.HTTPError as exc:
            logger.warning("Firecrawl /scrape network error for %s: %s", page_url, exc)
            return None
        except asyncio.TimeoutError:
            logger.warning("⚠️ Firecrawl /scrape SKIPPED %s: Website took longer than 10 seconds.", page_url)
            return None
        except Exception as exc:
            logger.warning("❌ Firecrawl /scrape error for %s: %s", page_url, exc)
            return None



# -- Pricing extraction via Gemini --------------------------------------

_COST_PROMPT = """You are the PATHFINDER Cost Analyst. You will be provided with Markdown text from a venue's website. Your job is to extract or estimate costs.

Venue: {name}
Category: {category}
Group size: {group_size}

Website content:
{content}

CRITICAL INSTRUCTIONS:
1. If the provided text is empty, truncated, or mentions "Access Denied/Timeout", you MUST return 0.0 for all numerical fields and set pricing_confidence to "unknown". NEVER return null or None for numerical values. Use 0.0.
2. Search the text for ANY pricing signals: "$" signs, numbers, hourly rates, per-person fees, packages, menu prices, rental costs, booking rates, membership fees.
3. Extract the base_cost (per person or per hour).
4. Identify hidden_costs (service fees, minimum spends, shoe rentals, equipment fees, cleaning fees, parking fees).
5. Calculate total_cost_of_attendance for a group of {group_size}.
6. If you find EXPLICIT prices on the page, use them and set pricing_confidence to "confirmed", and set price_source to "official_site".
7. If the website content is empty, missing, or prices are NOT explicitly listed, AND it's not an access denied/timeout case, ESTIMATE based on:
   - Typical Toronto market rates for this type of venue/activity
   - The venue's category and perceived quality
   Set pricing_confidence to "estimated", and set price_source to "gemini_estimate".
8. Set the recommended_action parameter based on Auth0 Secure Action Rules:
   - Tier A (Confirmed): recommended_action = "authorize_payment"
   - Tier B (Estimated): recommended_action = "prepare_outreach" (intent usually "booking_inquiry")
   - Tier C (Unknown): recommended_action = "prepare_outreach" (intent usually "availability_check" or "commercial_leasing")

SCHEMA (STRICT JSON):
Respond with ONLY a valid JSON object (no markdown, no extra text):
{{
  "base_cost": <float, primary cost>
  "hidden_costs": [
    {{"label": "<fee name>", "amount": <float>}}
  ],
  "total_cost_of_attendance": <float, base + all hidden costs>,
  "per_person": <float, total / group_size>,
  "value_score": <float 0.0 to 1.0, subjective value for money>,
  "pricing_confidence": "<confirmed | estimated | unknown>",
  "price_source": "<official_site | flyer | gemini_estimate | none>",
  "notes": "<pricing observations, source of estimates, or warnings>",
  "recommended_action": "<authorize_payment | prepare_outreach | none>",
  "outreach_intent": "<booking_inquiry | availability_check | commercial_leasing | none>"
}}
"""


async def _extract_pricing(
    venue: dict, content: str, group_size: int
) -> dict:
    """Use Gemini to extract structured pricing from scraped content."""
    prompt = _COST_PROMPT.format(
        name=venue.get("name", "Unknown"),
        category=venue.get("category", "venue"),
        group_size=group_size,
        content=content[:50000],  # Increased to support multi-page combined content
    )

    try:
        raw = await generate_content(prompt=prompt, model="gemini-2.5-flash")
        if not raw:
            return _no_data_fallback(venue)

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]

        result = json.loads(cleaned.strip())
        return _apply_confidence_tier(result, venue, group_size)

    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Cost extraction failed for %s: %s", venue.get("name"), exc)
        return _no_data_fallback(venue)


def _apply_confidence_tier(result: dict, venue: dict, group_size: int) -> dict:
    """
    Apply tiered value_score and notes based on pricing confidence.

    Tiers:
      confirmed -> use Gemini's value_score as-is
      estimated -> cap value_score at 0.5, add estimation warning
      unknown   -> value_score 0.3, add high-uncertainty warning
    """
    confidence = result.get("pricing_confidence", "unknown")
    base = result.get("base_cost", 0)
    if base is None:
        base = 0
        result["base_cost"] = 0

    if confidence == "unknown" or base == 0:
        # -- Tier C: No price found --
        result["value_score"] = 0.3
        result["pricing_confidence"] = "unknown"
        result["price_source"] = "none"
        result["recommended_action"] = "prepare_outreach"
        if not result.get("outreach_intent") or result.get("outreach_intent") == "none":
            result["outreach_intent"] = "availability_check"
        result["notes"] = (
            "High uncertainty. Rates are quote-based or unlisted. "
            "Budget fit is unverified. Recommend contacting venue directly."
        )

    elif confidence == "estimated":
        # -- Tier B: Estimated price --
        result["value_score"] = min(result.get("value_score", 0.5), 0.5)
        result["price_source"] = result.get("price_source", "gemini_estimate")
        result["recommended_action"] = "prepare_outreach"
        if not result.get("outreach_intent") or result.get("outreach_intent") == "none":
            result["outreach_intent"] = "booking_inquiry"
        est_note = result.get("notes", "")
        result["notes"] = (
            f"Estimated from Toronto market rates for {venue.get('category', 'this venue type')}. "
            f"{est_note}"
        ).strip()

    else:
        # -- Tier A: Confirmed --
        result["recommended_action"] = "authorize_payment"
        result["outreach_intent"] = "none"

    # Ensure per_person is always calculated
    tca = result.get("total_cost_of_attendance", 0)
    if tca is None:
        tca = 0
        result["total_cost_of_attendance"] = 0
        
    value_score = result.get("value_score", 0.5)
    if value_score is None:
        value_score = 0.5
        result["value_score"] = value_score
        
    if tca > 0 and group_size > 0:
        result["per_person"] = round(tca / group_size, 2)
    else:
        result["per_person"] = 0

    return result


def _no_data_fallback(venue: dict = None) -> dict:
    """Fallback when scraping fails entirely -- mapped to Tier C Unknown."""
    name = venue.get("name", "This venue") if venue else "This venue"
    return {
        "base_cost": 0,
        "hidden_costs": [],
        "total_cost_of_attendance": 0,
        "per_person": 0,
        "value_score": 0.3,
        "pricing_confidence": "unknown",
        "price_source": "none",
        "recommended_action": "prepare_outreach",
        "outreach_intent": "availability_check",
        "notes": (
            f"High uncertainty. {name} does not publish rates online. "
            "Budget fit is unverified. Recommend contacting venue directly."
        ),
    }

# -- Main pipeline per venue -------------------------------------------

async def _guess_pricing_pages(website: str, venue_name: str, category: str) -> list[str]:
    """Ask Gemini to guess common pricing URLs for a venue based on its main domain."""
    base_url = website.rstrip('/')
    
    prompt = f"""
    You are an expert web crawler. 
    Venue Name: {venue_name}
    Category: {category}
    Main Website: {base_url}
    
    Predict the SINGLE most likely URL on this website where pricing, booking, or rate information would be found.
    Common examples: {base_url}/pricing, {base_url}/rates, {base_url}/book-now, {base_url}/menu
    
    Return EXACTLY a JSON array of strings containing just that 1 URL (e.g., ["https://example.com/pricing"]), and nothing else.
    """
    try:
        raw = await generate_content(prompt=prompt, model="gemini-2.5-flash")
        if not raw:
            return []
            
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("\n", 1)[-1]
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
            
        urls = json.loads(cleaned.strip())
        if isinstance(urls, list):
            # Ensure they actually start with the base URL to prevent hallucinations
            return [url for url in urls if url.startswith("http")]
        return []
        
    except Exception as e:
        logger.warning(f"Failed to guess pricing pages for {website}: {e}")
        return []


async def _is_website_alive(url: str) -> bool:
    """Fast circuit breaker to check if a domain is reachable before firing expensive scrapes."""
    try:
        # Use a very short 3-second timeout just to check if the server exists
        async with httpx.AsyncClient(timeout=3.0, verify=False) as client:
            resp = await client.head(url, follow_redirects=True)
            return resp.status_code < 400
    except Exception as e:
        logger.warning(f"Site {url} appears dead/unreachable ({e}). Tripping circuit breaker.")
        return False


async def _analyze_venue_cost(venue: dict, group_size: int) -> dict:
    """
    Full cost pipeline for a single venue:
    1. Try Gemini pre-scoping to guess pricing URLs (cheap & fast)
    2. Try Firecrawl /map to find pricing pages if guessing fails (expensive but thorough)
    3. Firecrawl /scrape to get page content (always scrape website as fallback)
    4. Use Gemini to extract structured pricing
    """
    website = venue.get("website", "")
    combined_content = ""

    if website:
        # Step 0: Check for social media links (Firecrawl gets 403 on these)
        if any(domain in website.lower() for domain in ["instagram.com", "facebook.com", "fb.com", "tiktok.com", "twitter.com", "x.com"]):
            logger.info("Skipping scraping for social media URL (Firecrawl 403 Forbidden): %s", website)
            # Default to an estimated price fallback immediately
            fallback = _no_data_fallback(venue)
            fallback["notes"] = f"Estimated from typical market rates. The venue link provided ({website}) is a social media page, which cannot be scraped for pricing automatically. Recommend contacting venue directly via DM."
            fallback["price_source"] = "gemini_estimate"
            fallback["pricing_confidence"] = "estimated"
            fallback["value_score"] = 0.5
            return fallback

        # Step 0.5: Circuit Breaker - Is the site even alive?
        is_alive = await _is_website_alive(website)
        if not is_alive:
            logger.info("Circuit Breaker Tripped: Skipping %s entirely as base domain is dead.", website)
            fallback = _no_data_fallback(venue)
            fallback["notes"] = f"Estimated from typical market rates. The venue's official website ({website}) is unresponsive or down. Recommend calling to confirm."
            fallback["price_source"] = "gemini_estimate"
            fallback["pricing_confidence"] = "estimated"
            fallback["value_score"] = 0.5
            return fallback

        # Step 1: Pre-scope with Gemini
        logger.info(f"Gemini pre-scoping pricing URL for {website}")
        pricing_pages = await _guess_pricing_pages(website, venue.get("name", ""), venue.get("category", ""))
        
        # Step 2: Fallback to Firecrawl map if no valid guesses
        if not pricing_pages:
            logger.info(f"Pre-scoping returned no results, falling back to Firecrawl /map for {website}")
            pricing_pages = await _firecrawl_map(website)

        # Step 3: Scrape up to 1 pricing page, plus always include the homepage
        pages_to_scrape = pricing_pages[:1]
        if website not in pages_to_scrape:
            pages_to_scrape.append(website)

        logger.info("Cost Analyst concurrently scraping pages: %s", pages_to_scrape)
        
        # We run the scrapes in parallel. The 10s wait_for wrapper inside _firecrawl_scrape
        # will protect us from slow sites hanging this whole process. Using return_exceptions=True
        # prevents one bad site link from interrupting the other healthy site links.
        scrape_tasks = [_firecrawl_scrape(url) for url in pages_to_scrape]
        scrape_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)
        
        content_parts = []
        for target, content in zip(pages_to_scrape, scrape_results):
            if isinstance(content, str) and content.strip():
                content_parts.append(f"--- Content from {target} ---\n{content}\n")
            elif isinstance(content, Exception):
                logger.warning(f"Cost Analyst explicitly caught an exception scraping {target}: {content}")

        combined_content = "\n".join(content_parts)

    if not combined_content:
        logger.warning("Venue %s had NO scraped content (Firecrawl returned nothing). Forwarding to Gemini for pure estimation.", venue.get('name'))
    else:
        logger.debug("Venue %s scraped content length: %s", venue.get('name'), len(combined_content))

    # Step 3: Extract pricing with Gemini (it will auto-estimate if combined_content is empty)
    return await _extract_pricing(venue, combined_content, group_size)


# -- Node entry point ---------------------------------------------------

def cost_analyst_node(state: PathfinderState) -> PathfinderState:
    """
    Compute Total Cost of Attendance (TCA) per venue.

    Steps
    -----
    1. For each venue, run the Firecrawl -> Gemini pipeline.
    2. Write cost_profiles dict to state.
    """
    candidates = state.get("candidate_venues", [])
    intent = state.get("parsed_intent", {})
    group_size = intent.get("group_size", 1)

    if not candidates:
        logger.info("Cost Analyst: no candidates to analyze")
        return {"cost_profiles": {}}

    async def _analyze_all():
        return await asyncio.gather(*[_analyze_venue_cost(v, group_size) for v in candidates])

    try:
        results = asyncio.run(_analyze_all())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        results = asyncio.run(_analyze_all())
    except Exception as exc:
        logger.error("Cost Analyst failed: %s", exc)
        results = [_no_data_fallback(v) for v in candidates]

    cost_profiles = {}
    requires_deposit = False
    highest_cost = 0

    for venue, result in zip(candidates, results):
        vid = venue.get("venue_id", "")
        cost_profiles[vid] = result
        
        # Determine if a deposit/payment is required for the CIBA demo
        # If any venue has a high cost (> $100), we'll trigger the Auth0 CIBA flow
        base_cost = result.get("base_cost", 0)
        if base_cost > highest_cost:
            highest_cost = base_cost
        if base_cost > 100:
            requires_deposit = True

    scored = sum(1 for v in cost_profiles.values() if v.get("base_cost", 0) > 0)
    logger.info("Cost Analyst priced %d/%d venues", scored, len(candidates))

    # --- CIBA Human-in-the-Loop Auth Flow ---
    auth_user_id = state.get("auth_user_id")
    payment_authorized = state.get("payment_authorized", False)
    
    # If the system detected a costly venue and we haven't paid yet, push a notification
    if requires_deposit and auth_user_id and not payment_authorized:
        logger.info(f"High cost detected (${highest_cost}). Triggering CIBA Auth for user {auth_user_id}")
        
        from app.services.auth0 import auth0_service
        try:
            # Trigger the push notification to the user's phone
            prompt_msg = f"Pathfinder: Authorize ${highest_cost} deposit for your group activity?"
            req_id = asyncio.run(auth0_service.trigger_ciba_auth(auth_user_id, prompt_msg))
            
            if req_id:
                # Return the state with the pending request ID. 
                # LangGraph should interpret this as an Interrupt/Wait state (handled in orchestration)
                return {
                    "cost_profiles": cost_profiles,
                    "ciba_auth_req_id": req_id,
                    "payment_authorized": False
                }
        except RuntimeError:
            import nest_asyncio
            nest_asyncio.apply()
            prompt_msg = f"Pathfinder: Authorize ${highest_cost} deposit for your group activity?"
            req_id = asyncio.run(auth0_service.trigger_ciba_auth(auth_user_id, prompt_msg))
            if req_id:
                return {
                    "cost_profiles": cost_profiles,
                    "ciba_auth_req_id": req_id,
                    "payment_authorized": False
                }
        except Exception as e:
            logger.warning(f"Failed to trigger CIBA: {e}")

    # If already authorized or no deposit required, proceed normally
    return {
        "cost_profiles": cost_profiles,
        "payment_authorized": payment_authorized
    }
