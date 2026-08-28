"""Simulated busyness provider — the fallback when no BestTime key is set.

Keeps the API fully functional for local development, tests, and demos
without spending BestTime credits. Curves are realistic in shape
(cafes peak at breakfast, restaurants at lunch/dinner, bars at night)
and deterministic per venue per day, so results are stable within a day.
"""

import hashlib
import random
from datetime import date, datetime
from typing import Optional

from busyness import clamp_score, score_to_level

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

DEMO_VENUES_RAW = [
    ("The Copper Kettle", "cafe", "14 High Street", "London", 51.5074, -0.1278, 2, 4.4),
    ("Bean & Barrel", "cafe", "88 Baker Street", "London", 51.5205, -0.1567, 2, 4.6),
    ("Trattoria Milano", "restaurant", "22 Via Roma", "London", 51.5099, -0.1180, 3, 4.5),
    ("The Rusty Anchor", "bar", "5 Ocean Drive", "London", 51.5033, -0.1195, 2, 4.1),
    ("Sakura Sushi House", "restaurant", "9 Park Avenue", "London", 51.5142, -0.0931, 3, 4.7),
    ("Corner Espresso", "cafe", "3 King's Road", "London", 51.4875, -0.1687, 1, 4.3),
    ("The Gilded Fork", "restaurant", "41 Regent Street", "London", 51.5101, -0.1367, 4, 4.6),
    ("Blue Moon Tavern", "bar", "17 Camden High St", "London", 51.5390, -0.1426, 2, 4.0),
    ("Morning Glory Cafe", "cafe", "60 Portobello Rd", "London", 51.5170, -0.2040, 1, 4.2),
    ("Spice Route", "restaurant", "31 Brick Lane", "London", 51.5225, -0.0715, 2, 4.4),
]


def _build_demo_venues() -> dict[str, dict]:
    venues = {}
    for name, cat, addr, city, lat, lng, price, rating in DEMO_VENUES_RAW:
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


def search(query: Optional[str] = None, lat: Optional[float] = None,
           lng: Optional[float] = None, radius: Optional[int] = None) -> list[dict]:
    """Name/address/type search over the demo venue set."""
    results = list(DEMO_VENUES.values())
    if query:
        q = query.lower().strip()
        categories = _categories_for_query(q)
        results = [
            v for v in results
            if q in v["name"].lower()
            or q in v["address"].lower()
            or q in v["venue_type"].lower()
            or _category(v) in categories
        ]
    if lat is not None and lng is not None and radius:
        from busyness import haversine_km
        results = [
            v for v in results
            if haversine_km(lat, lng, v["lat"], v["lng"]) * 1000 <= radius
        ]
    return results
