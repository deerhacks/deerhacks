"""
Mapbox Isochrone API service.

Fetches GeoJSON isochrone polygons representing reachable areas
from a given point within a specified travel time.
"""

import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_ISOCHRONE_URL = "https://api.mapbox.com/isochrone/v1/mapbox"


async def get_isochrone(
    lat: float,
    lng: float,
    profile: str = "driving",
    contour_minutes: int = 15,
) -> Optional[dict]:
    """
    Fetch an isochrone polygon from the Mapbox Isochrone API.

    Parameters
    ----------
    lat, lng : float
        Centre point coordinates.
    profile : str
        Travel mode: "driving", "walking", or "cycling".
    contour_minutes : int
        Maximum travel time in minutes (1–60).

    Returns
    -------
    dict | None
        A GeoJSON FeatureCollection, or None on failure.
    """
    token = settings.MAPBOX_ACCESS_TOKEN
    if not token:
        logger.warning("Mapbox: no MAPBOX_ACCESS_TOKEN configured — skipping isochrone")
        return None

    url = f"{_ISOCHRONE_URL}/{profile}/{lng},{lat}"
    params = {
        "contours_minutes": str(contour_minutes),
        "polygons": "true",
        "access_token": token,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        # Validate it looks like GeoJSON
        if data.get("type") == "FeatureCollection" and data.get("features"):
            return data

        logger.warning("Mapbox isochrone returned unexpected shape for (%s, %s)", lat, lng)
        return data if data.get("type") else None

    except httpx.HTTPStatusError as exc:
        logger.warning("Mapbox isochrone HTTP %s for (%s, %s): %s",
                       exc.response.status_code, lat, lng, exc)
        return None
    except httpx.HTTPError as exc:
        logger.warning("Mapbox isochrone request failed for (%s, %s): %s", lat, lng, exc)
        return None
