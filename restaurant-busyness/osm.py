"""OpenStreetMap venue lookup via the Overpass API.

This is the "every single place" layer: OSM has essentially every mapped
venue on earth — restaurants, gyms, pharmacies, parks, stations — and it
is free, needs no API key, and has no billing account.

What it does NOT have is busyness. OSM tells you a place exists and
where; BestTime tells you how full it is. The app combines them and is
explicit about which venues actually carry measured data.

Overpass is a free, shared, volunteer-run service. Be a good citizen:
results are cached, queries are bounded by radius and count, one request
runs at a time, and a descriptive User-Agent is sent. See
https://operations.osmfoundation.org/policies/nominatim/ and the
Overpass usage policy.
"""

import asyncio
import logging
from typing import Any, Optional

import httpx

import rhythms

log = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",   # community mirror
]
USER_AGENT = "BusyOrNot/1.0 (venue busyness app)"

# OSM tag -> this app's venue kind. Keys are (tag, value).
TAG_KINDS: dict[tuple[str, str], str] = {
    ("amenity", "restaurant"): "restaurant",
    ("amenity", "fast_food"): "fast_food",
    ("amenity", "cafe"): "cafe",
    ("amenity", "bar"): "bar",
    ("amenity", "pub"): "pub",
    ("amenity", "biergarten"): "pub",
    ("amenity", "nightclub"): "nightclub",
    ("amenity", "pharmacy"): "pharmacy",
    ("amenity", "clinic"): "clinic",
    ("amenity", "doctors"): "clinic",
    ("amenity", "hospital"): "hospital",
    ("amenity", "bank"): "bank",
    ("amenity", "post_office"): "post",
    ("amenity", "cinema"): "cinema",
    ("amenity", "theatre"): "theatre",
    ("amenity", "library"): "library",
    ("amenity", "fuel"): "fuel",
    ("shop", "supermarket"): "supermarket",
    ("shop", "convenience"): "convenience",
    ("shop", "bakery"): "bakery",
    ("shop", "mall"): "shopping",
    ("shop", "department_store"): "shopping",
    ("shop", "hairdresser"): "salon",
    ("leisure", "fitness_centre"): "gym",
    ("leisure", "sports_centre"): "gym",
    ("leisure", "swimming_pool"): "pool",
    ("leisure", "park"): "park",
    ("leisure", "garden"): "park",
    ("tourism", "museum"): "museum",
    ("tourism", "gallery"): "museum",
    ("tourism", "hotel"): "hotel",
    ("railway", "station"): "station",
    ("public_transport", "station"): "station",
}

# Grouped by OSM key so the query stays compact.
_BY_KEY: dict[str, set[str]] = {}
for (key, value) in TAG_KINDS:
    _BY_KEY.setdefault(key, set()).add(value)


class OverpassError(RuntimeError):
    pass


def _values_for(kinds: Optional[list[str]]) -> dict[str, set[str]]:
    """Restrict the query to the OSM values matching the wanted kinds."""
    if not kinds:
        return _BY_KEY
    wanted = set(kinds)
    out: dict[str, set[str]] = {}
    for (key, value), kind in TAG_KINDS.items():
        if kind in wanted:
            out.setdefault(key, set()).add(value)
    return out or _BY_KEY


def build_query(lat: float, lng: float, radius: int,
                kinds: Optional[list[str]] = None, limit: int = 200) -> str:
    """An Overpass QL query for every matching venue within a radius.

    `nwr` covers nodes, ways and relations, since a large venue is often
    mapped as a building outline rather than a point; `out center` gives
    each one a single coordinate.
    """
    clauses = []
    for key, values in _values_for(kinds).items():
        pattern = "|".join(sorted(values))
        clauses.append(f'  nwr["{key}"~"^({pattern})$"](around:{radius},{lat},{lng});')
    body = "\n".join(clauses)
    return f"[out:json][timeout:30];\n(\n{body}\n);\nout center tags {limit};"


def _name_of(tags: dict) -> Optional[str]:
    for key in ("name", "name:en", "brand", "operator"):
        value = tags.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _kind_of(tags: dict) -> Optional[str]:
    for key, value in tags.items():
        kind = TAG_KINDS.get((key, str(value)))
        if kind:
            return kind
    return None


def _address_of(tags: dict) -> Optional[str]:
    parts = []
    if tags.get("addr:housenumber") and tags.get("addr:street"):
        parts.append(f"{tags['addr:housenumber']} {tags['addr:street']}")
    elif tags.get("addr:street"):
        parts.append(str(tags["addr:street"]))
    for key in ("addr:suburb", "addr:city", "addr:town"):
        if tags.get(key):
            parts.append(str(tags[key]))
            break
    return ", ".join(parts) or None


def parse_elements(body: dict) -> list[dict]:
    """Turn an Overpass response into this app's venue shape.

    Unnamed features are dropped — an unnamed node is not a place a
    person can look up or visit.
    """
    elements = body.get("elements")
    if not isinstance(elements, list):
        return []

    venues, seen = [], set()
    for el in elements:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags")
        if not isinstance(tags, dict):
            continue

        name = _name_of(tags)
        kind = _kind_of(tags)
        if not name or not kind:
            continue

        centre = el.get("center") if isinstance(el.get("center"), dict) else el
        lat, lng = centre.get("lat"), centre.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue

        osm_id = f"{el.get('type', 'node')}/{el.get('id')}"
        if osm_id in seen:
            continue
        seen.add(osm_id)

        venues.append({
            "venue_id": "osm:" + osm_id,
            "name": name,
            "kind": kind,
            "kind_label": rhythms.label_for(kind),
            "group": rhythms.group_for(kind),
            "address": _address_of(tags),
            "lat": float(lat),
            "lng": float(lng),
            "source": "openstreetmap",
            "website": tags.get("website") or tags.get("contact:website"),
            "opening_hours": tags.get("opening_hours"),
        })
    return venues


class OverpassClient:
    def __init__(self, timeout: float = 40.0, urls: Optional[list[str]] = None):
        self._timeout = timeout
        self._urls = urls or OVERPASS_URLS
        # Overpass asks for modest concurrency; one request at a time is polite.
        self._gate = asyncio.Semaphore(1)

    async def find(self, lat: float, lng: float, radius: int = 1500,
                   kinds: Optional[list[str]] = None, limit: int = 200) -> list[dict]:
        """Every mapped venue of the wanted kinds within `radius` metres."""
        query = build_query(lat, lng, radius, kinds, limit)
        last_error: Optional[Exception] = None

        async with self._gate:
            for url in self._urls:
                try:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        response = await client.post(
                            url, data={"data": query},
                            headers={"User-Agent": USER_AGENT},
                        )
                    if response.status_code in (429, 504):
                        # Rate-limited or overloaded — try the next mirror.
                        last_error = OverpassError(
                            f"Overpass busy (HTTP {response.status_code})")
                        continue
                    response.raise_for_status()
                    return parse_elements(response.json())
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    log.warning("Overpass mirror %s failed: %s", url, exc)
                    continue

        raise OverpassError(
            f"No Overpass mirror responded: {last_error}") from last_error
