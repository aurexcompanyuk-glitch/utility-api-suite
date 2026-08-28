"""Turn place names into coordinates, so users can type "Manchester"
instead of "53.4808, -2.2426".

Two tiers:
  1. A built-in table of major cities — instant, offline, no rate limit.
     Covers the common case without a network round trip.
  2. OpenStreetMap's Nominatim for anything else — free, no API key.
     Results are cached; Nominatim's usage policy asks for a
     identifying User-Agent and at most one request per second.

If both miss, callers get None and can ask the user to be more specific.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "BusyOrNot/1.0 (restaurant busyness app)"

# name -> (lat, lng, display name)
CITIES: dict[str, tuple[float, float, str]] = {
    # United Kingdom
    "london": (51.5074, -0.1278, "London, UK"),
    "manchester": (53.4808, -2.2426, "Manchester, UK"),
    "birmingham": (52.4862, -1.8904, "Birmingham, UK"),
    "leeds": (53.8008, -1.5491, "Leeds, UK"),
    "glasgow": (55.8642, -4.2518, "Glasgow, UK"),
    "edinburgh": (55.9533, -3.1883, "Edinburgh, UK"),
    "liverpool": (53.4084, -2.9916, "Liverpool, UK"),
    "bristol": (51.4545, -2.5879, "Bristol, UK"),
    "sheffield": (53.3811, -1.4701, "Sheffield, UK"),
    "newcastle": (54.9783, -1.6178, "Newcastle upon Tyne, UK"),
    "nottingham": (52.9548, -1.1581, "Nottingham, UK"),
    "cardiff": (51.4816, -3.1791, "Cardiff, UK"),
    "belfast": (54.5973, -5.9301, "Belfast, UK"),
    "brighton": (50.8225, -0.1372, "Brighton, UK"),
    "oxford": (51.7520, -1.2577, "Oxford, UK"),
    "cambridge": (52.2053, 0.1218, "Cambridge, UK"),
    "york": (53.9600, -1.0873, "York, UK"),
    "bath": (51.3811, -2.3590, "Bath, UK"),
    "leicester": (52.6369, -1.1398, "Leicester, UK"),
    "coventry": (52.4068, -1.5197, "Coventry, UK"),
    "southampton": (50.9097, -1.4044, "Southampton, UK"),
    "portsmouth": (50.8198, -1.0880, "Portsmouth, UK"),
    "reading": (51.4543, -0.9781, "Reading, UK"),
    "aberdeen": (57.1497, -2.0943, "Aberdeen, UK"),
    "dublin": (53.3498, -6.2603, "Dublin, Ireland"),
    # Europe
    "paris": (48.8566, 2.3522, "Paris, France"),
    "berlin": (52.5200, 13.4050, "Berlin, Germany"),
    "madrid": (40.4168, -3.7038, "Madrid, Spain"),
    "barcelona": (41.3851, 2.1734, "Barcelona, Spain"),
    "rome": (41.9028, 12.4964, "Rome, Italy"),
    "milan": (45.4642, 9.1900, "Milan, Italy"),
    "amsterdam": (52.3676, 4.9041, "Amsterdam, Netherlands"),
    "brussels": (50.8503, 4.3517, "Brussels, Belgium"),
    "lisbon": (38.7223, -9.1393, "Lisbon, Portugal"),
    "vienna": (48.2082, 16.3738, "Vienna, Austria"),
    "prague": (50.0755, 14.4378, "Prague, Czechia"),
    "copenhagen": (55.6761, 12.5683, "Copenhagen, Denmark"),
    "stockholm": (59.3293, 18.0686, "Stockholm, Sweden"),
    "oslo": (59.9139, 10.7522, "Oslo, Norway"),
    "zurich": (47.3769, 8.5417, "Zurich, Switzerland"),
    "munich": (48.1351, 11.5820, "Munich, Germany"),
    "athens": (37.9838, 23.7275, "Athens, Greece"),
    # North America
    "new york": (40.7128, -74.0060, "New York, USA"),
    "nyc": (40.7128, -74.0060, "New York, USA"),
    "los angeles": (34.0522, -118.2437, "Los Angeles, USA"),
    "chicago": (41.8781, -87.6298, "Chicago, USA"),
    "san francisco": (37.7749, -122.4194, "San Francisco, USA"),
    "seattle": (47.6062, -122.3321, "Seattle, USA"),
    "boston": (42.3601, -71.0589, "Boston, USA"),
    "austin": (30.2672, -97.7431, "Austin, USA"),
    "miami": (25.7617, -80.1918, "Miami, USA"),
    "toronto": (43.6532, -79.3832, "Toronto, Canada"),
    "vancouver": (49.2827, -123.1207, "Vancouver, Canada"),
    # Rest of world
    "sydney": (-33.8688, 151.2093, "Sydney, Australia"),
    "melbourne": (-37.8136, 144.9631, "Melbourne, Australia"),
    "tokyo": (35.6762, 139.6503, "Tokyo, Japan"),
    "singapore": (1.3521, 103.8198, "Singapore"),
    "hong kong": (22.3193, 114.1694, "Hong Kong"),
    "dubai": (25.2048, 55.2708, "Dubai, UAE"),
}

_cache: dict[str, Optional[dict]] = {}
_last_request_at = 0.0
_rate_lock = asyncio.Lock()


def parse_coordinates(text: str) -> Optional[dict]:
    """Accept a raw "lat, lng" string so power users can still paste one."""
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 2:
        return None
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {"lat": lat, "lng": lng, "name": f"{lat:.4f}, {lng:.4f}", "source": "coordinates"}


def lookup_known_city(place: str) -> Optional[dict]:
    """Match against the built-in table. Offline and instant."""
    key = place.lower().strip().rstrip(",.")
    if key in CITIES:
        lat, lng, label = CITIES[key]
        return {"lat": lat, "lng": lng, "name": label, "source": "builtin"}

    # "restaurants in central london" -> london
    for name, (lat, lng, label) in CITIES.items():
        if name in key:
            return {"lat": lat, "lng": lng, "name": label, "source": "builtin"}
    return None


async def geocode(place: str, timeout: float = 10.0) -> Optional[dict]:
    """Resolve a place name to coordinates.

    Tries raw coordinates, then the built-in city table, then Nominatim.
    Returns None when nothing matches.
    """
    if not place or not place.strip():
        return None

    place = place.strip()

    direct = parse_coordinates(place)
    if direct:
        return direct

    known = lookup_known_city(place)
    if known:
        return known

    cache_key = place.lower()
    if cache_key in _cache:
        return _cache[cache_key]

    result = await _nominatim(place, timeout)
    _cache[cache_key] = result
    return result


async def _nominatim(place: str, timeout: float) -> Optional[dict]:
    """Query OpenStreetMap, respecting its one-request-per-second policy."""
    global _last_request_at

    async with _rate_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        _last_request_at = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                NOMINATIM_URL,
                params={"q": place, "format": "json", "limit": 1},
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            results = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Geocoding failed for %r: %s", place, exc)
        return None

    if not isinstance(results, list) or not results:
        return None

    top = results[0]
    try:
        return {
            "lat": float(top["lat"]),
            "lng": float(top["lon"]),
            "name": top.get("display_name", place),
            "source": "nominatim",
        }
    except (KeyError, TypeError, ValueError):
        return None
