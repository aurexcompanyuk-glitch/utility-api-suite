"""Simulated busyness provider — the fallback when no BestTime key is set.

Keeps the API fully functional for local development, tests, and demos
without spending BestTime credits. Curves are realistic in shape
(cafes peak at breakfast, restaurants at lunch/dinner, bars at night)
and deterministic per venue per day, so results are stable within a day.
"""

import difflib
import hashlib
import random
from datetime import date, datetime
from typing import Optional

from busyness import clamp_score, haversine_km, score_to_level

# 24-hour baseline curves (0-100). Index 0 = midnight, 23 = 11pm.
BASE_CURVES = {
    "cafe": {
        "weekday": [2, 1, 1, 1, 1, 2, 15, 45, 65, 55, 40, 45, 60, 50, 35, 30, 25, 20, 15, 10, 8, 5, 3, 2],
        "weekend": [5, 3, 2, 1, 1, 2, 8, 20, 45, 70, 75, 70, 65, 55, 45, 35, 25, 18, 12, 8, 6, 5, 4, 3],
    },
    "restaurant": {
        "weekday": [3, 2, 1, 1, 1, 1, 3, 8, 12, 15, 20, 45, 70, 55, 25, 15, 20, 40, 75, 85, 70, 40, 15, 6],
        "weekend": [8, 5, 3, 2, 1, 1, 2, 5, 10, 20, 35, 55, 80, 75, 45, 25, 30, 50, 80, 90, 85, 65, 35, 15],
    },
    "bar": {
        "weekday": [15, 8, 3, 1, 1, 1, 1, 2, 3, 3, 4, 6, 10, 12, 10, 8, 10, 20, 40, 55, 65, 60, 45, 25],
        "weekend": [40, 25, 12, 5, 2, 1, 1, 1, 2, 3, 4, 6, 12, 15, 12, 10, 15, 30, 55, 75, 90, 95, 85, 60],
    },
}

from venues_data import VENUE_ROWS


def _build_demo_venues() -> dict[str, dict]:
    venues = {}
    for name, cat, addr, city, lat, lng, price, rating in VENUE_ROWS:
        vid = "sim_" + hashlib.sha1(name.encode()).hexdigest()[:10]
        venues[vid] = {
            "venue_id": vid,
            "name": name,
            "address": f"{addr}, {city}",
            "city": city,
            "lat": lat,
            "lng": lng,
            "timezone": "Europe/London",
            "venue_type": cat.upper(),
            "venue_types": [cat.upper()],
            "price_level": price,
            "rating": rating,
        }
    return venues


DEMO_VENUES: dict[str, dict] = _build_demo_venues()


def _category(venue: dict) -> str:
    raw = (venue.get("venue_type") or "").lower()
    return raw if raw in BASE_CURVES else "restaurant"


def day_curve(venue: dict, target: date) -> list[int]:
    """Deterministic 24-hour curve: same venue + date always matches."""
    is_weekend = target.weekday() >= 5
    base = BASE_CURVES[_category(venue)]["weekend" if is_weekend else "weekday"]
    rng = random.Random(f"{venue['venue_id']}-{target.isoformat()}")
    return [clamp_score(v + rng.randint(-8, 8)) for v in base]


def current_baseline(venue: dict, now: datetime) -> int:
    """Busyness right now, interpolated between the two nearest hours."""
    curve = day_curve(venue, now.date())
    frac = now.minute / 60
    return clamp_score(curve[now.hour] * (1 - frac) + curve[(now.hour + 1) % 24] * frac)


def week_forecast(venue: dict, start: date) -> list[dict]:
    """Seven days of curves, shaped like the BestTime week response."""
    from datetime import timedelta
    days = []
    for offset in range(7):
        target = start + timedelta(days=offset)
        curve = day_curve(venue, target)
        days.append({
            "day_int": target.weekday(),
            "day_name": target.strftime("%A"),
            "date": target.isoformat(),
            "open_hour": 7 if _category(venue) == "cafe" else 11,
            "close_hour": 18 if _category(venue) == "cafe" else 23,
            "hourly_busyness": curve,
            "peak_hours": [{"hour": curve.index(max(curve)), "busyness": max(curve)}],
            "quiet_hours": [h for h, v in enumerate(curve) if v < 15],
            "busy_hours": [h for h, v in enumerate(curve) if v >= 70],
        })
    return days


# Everyday search words mapped to venue categories, so "coffee" finds
# cafes and "drinks" finds bars rather than matching nothing.
QUERY_SYNONYMS = {
    "cafe": ["coffee", "cafe", "café", "espresso", "breakfast", "brunch", "tea", "bakery"],
    "restaurant": ["restaurant", "food", "eat", "dinner", "lunch", "sushi", "pizza",
                   "italian", "indian", "curry", "burger", "thai", "chinese"],
    "bar": ["bar", "pub", "drinks", "drink", "beer", "wine", "cocktail", "tavern", "night"],
}


def _categories_for_query(q: str) -> set[str]:
    return {cat for cat, words in QUERY_SYNONYMS.items()
            if any(word in q for word in words)}


def match_score(venue: dict, query: str) -> float:
    """How well a venue matches a free-text query, from 0 to 1.

    Exact and prefix name matches rank hardest, then fuzzy name
    similarity (so "copper kettle" still finds "The Copper Kettle" and
    typos degrade gracefully), then city, address, and category.
    """
    if not query:
        return 0.1

    q = query.lower().strip()
    name = venue["name"].lower()
    city = venue.get("city", "").lower()
    address = venue.get("address", "").lower()

    if q == name:
        return 1.0
    if name.startswith(q):
        return 0.95
    if q in name:
        return 0.9

    # Every word of the query appearing in the name, in any order.
    words = [w for w in q.split() if len(w) > 2]
    if words and all(w in name for w in words):
        return 0.85

    fuzzy = difflib.SequenceMatcher(None, q, name).ratio()
    if fuzzy > 0.7:
        return 0.6 + (fuzzy - 0.7) * 0.8   # 0.6 - 0.84

    if q == city:
        return 0.55
    if q in city or q in address:
        return 0.5
    if _category(venue) in _categories_for_query(q):
        return 0.4
    if any(w in name or w in address or w in city for w in words):
        return 0.3

    return 0.0


def search(query: Optional[str] = None, lat: Optional[float] = None,
           lng: Optional[float] = None, radius: Optional[int] = None,
           min_score: float = 0.25) -> list[dict]:
    """Search demo venues by name, city, address, or category.

    Results are ranked by match quality; location, when given, filters
    by radius and breaks ties between equally good matches.
    """
    candidates = list(DEMO_VENUES.values())

    if lat is not None and lng is not None and radius:
        candidates = [
            v for v in candidates
            if haversine_km(lat, lng, v["lat"], v["lng"]) * 1000 <= radius
        ]

    if not query:
        return candidates

    scored = []
    for venue in candidates:
        score = match_score(venue, query)
        if score >= min_score:
            distance = (haversine_km(lat, lng, venue["lat"], venue["lng"])
                        if lat is not None and lng is not None else 0.0)
            scored.append((score, -distance, venue))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [venue for _, _, venue in scored]


def search_everywhere(query: str, limit: int = 24) -> list[dict]:
    """Name search across every city, ignoring location entirely.

    Used when someone searches a venue by name without saying where.
    """
    return search(query, min_score=0.5)[:limit]
