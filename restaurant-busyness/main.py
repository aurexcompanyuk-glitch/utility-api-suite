"""
Restaurant & Cafe Busyness API
Tells you how busy restaurants, cafes, and bars are right now, plus a
predicted busyness curve for the day — similar in spirit to Google's
"Popular Times".

Data model:
  - Each venue has a base weekly busyness curve (24 values/day, by
    weekday vs weekend) representative of its category.
  - A small deterministic daily jitter is applied per venue so the
    curve varies day to day without being random noise on every request.
  - Live crowdsourced check-ins (POST /v1/venues/{id}/checkin) are
    blended into the baseline to reflect real-time conditions — the more
    recent check-ins a venue has, the more the live estimate leans on
    them over the predicted baseline.

No external API keys required to run. The venue store is in-memory
(swap `VENUES`/`CHECKINS` for a real database in production); the curve
generator is isolated in `predict_curve()` so it can later be replaced
with real historical data (e.g. from a Google Places-style source)
without touching the rest of the API.

Run locally:  uvicorn main:app --reload
"""

import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="Restaurant & Cafe Busyness API",
    version="1.0.0",
    description="Real-time and predicted busyness for restaurants, cafes, and bars.",
)


# ---------------------------------------------------------------------------
# Venue data (in-memory demo dataset)
# ---------------------------------------------------------------------------

class Category(str, Enum):
    restaurant = "restaurant"
    cafe = "cafe"
    bar = "bar"


class Venue(BaseModel):
    id: str
    name: str
    category: Category
    address: str
    city: str
    lat: float
    lng: float
    price_level: int  # 1-4, like $-$$$$
    rating: float


VENUES: dict[str, Venue] = {}


def _seed_venues():
    demo = [
        ("The Copper Kettle", Category.cafe, "14 High Street", "London", 51.5074, -0.1278, 2, 4.4),
        ("Bean & Barrel", Category.cafe, "88 Baker Street", "London", 51.5205, -0.1567, 2, 4.6),
        ("Trattoria Milano", Category.restaurant, "22 Via Roma", "London", 51.5099, -0.1180, 3, 4.5),
        ("The Rusty Anchor", Category.bar, "5 Ocean Drive", "London", 51.5033, -0.1195, 2, 4.1),
        ("Sakura Sushi House", Category.restaurant, "9 Park Avenue", "London", 51.5142, -0.0931, 3, 4.7),
        ("Corner Espresso", Category.cafe, "3 King's Road", "London", 51.4875, -0.1687, 1, 4.3),
        ("The Gilded Fork", Category.restaurant, "41 Regent Street", "London", 51.5101, -0.1367, 4, 4.6),
        ("Blue Moon Tavern", Category.bar, "17 Camden High St", "London", 51.5390, -0.1426, 2, 4.0),
        ("Morning Glory Cafe", Category.cafe, "60 Portobello Rd", "London", 51.5170, -0.2040, 1, 4.2),
        ("Spice Route", Category.restaurant, "31 Brick Lane", "London", 51.5225, -0.0715, 2, 4.4),
    ]
    for name, cat, addr, city, lat, lng, price, rating in demo:
        vid = hashlib.sha1(name.encode()).hexdigest()[:10]
        VENUES[vid] = Venue(
            id=vid, name=name, category=cat, address=addr, city=city,
            lat=lat, lng=lng, price_level=price, rating=rating,
        )


_seed_venues()


# ---------------------------------------------------------------------------
# Busyness prediction
# ---------------------------------------------------------------------------

# 24-hour baseline curves (0-100), representative shape per category.
# Index 0 = midnight-1am ... index 23 = 11pm-midnight.
BASE_CURVES = {
    Category.cafe: {
        "weekday": [2, 1, 1, 1, 1, 2, 15, 45, 65, 55, 40, 45, 60, 50, 35, 30, 25, 20, 15, 10, 8, 5, 3, 2],
        "weekend": [5, 3, 2, 1, 1, 2, 8, 20, 45, 70, 75, 70, 65, 55, 45, 35, 25, 18, 12, 8, 6, 5, 4, 3],
    },
    Category.restaurant: {
        "weekday": [3, 2, 1, 1, 1, 1, 3, 8, 12, 15, 20, 45, 70, 55, 25, 15, 20, 40, 75, 85, 70, 40, 15, 6],
        "weekend": [8, 5, 3, 2, 1, 1, 2, 5, 10, 20, 35, 55, 80, 75, 45, 25, 30, 50, 80, 90, 85, 65, 35, 15],
    },
    Category.bar: {
        "weekday": [15, 8, 3, 1, 1, 1, 1, 2, 3, 3, 4, 6, 10, 12, 10, 8, 10, 20, 40, 55, 65, 60, 45, 25],
        "weekend": [40, 25, 12, 5, 2, 1, 1, 1, 2, 3, 4, 6, 12, 15, 12, 10, 15, 30, 55, 75, 90, 95, 85, 60],
    },
}


def _clamp(v: float, lo: float = 0, hi: float = 100) -> int:
    return int(round(max(lo, min(hi, v))))


def predict_curve(venue: Venue, date) -> list[int]:
    """Deterministic per-day baseline curve: same venue + same date
    always produces the same curve, so results are stable within a day
    but vary day to day without needing external data."""
    is_weekend = date.weekday() >= 5
    base = BASE_CURVES[venue.category]["weekend" if is_weekend else "weekday"]
    rng = random.Random(f"{venue.id}-{date.isoformat()}")
    return [_clamp(v + rng.randint(-8, 8)) for v in base]


class CheckinLevel(str, Enum):
    quiet = "quiet"          # ~10
    moderate = "moderate"    # ~40
    busy = "busy"            # ~70
    packed = "packed"        # ~95


LEVEL_SCORE = {
    CheckinLevel.quiet: 10,
    CheckinLevel.moderate: 40,
    CheckinLevel.busy: 70,
    CheckinLevel.packed: 95,
}

CHECKIN_WINDOW = timedelta(hours=2)
CHECKINS: dict[str, list[tuple[datetime, int]]] = {}  # venue_id -> [(ts, score)]


def _recent_checkins(venue_id: str, now: datetime) -> list[int]:
    entries = CHECKINS.get(venue_id, [])
    fresh = [(ts, score) for ts, score in entries if now - ts <= CHECKIN_WINDOW]
    CHECKINS[venue_id] = fresh
    return [score for _, score in fresh]


def current_busyness(venue: Venue, now: datetime) -> dict:
    curve = predict_curve(venue, now.date())
    hour = now.hour
    frac = now.minute / 60
    next_hour = (hour + 1) % 24
    baseline = curve[hour] * (1 - frac) + curve[next_hour] * frac

    scores = _recent_checkins(venue.id, now)
    if scores:
        live_avg = sum(scores) / len(scores)
        weight = min(len(scores) / 5, 0.75)  # more reports = more trust, capped
        value = baseline * (1 - weight) + live_avg * weight
        source = "live" if weight >= 0.75 else "blended"
    else:
        value = baseline
        source = "predicted"

    score = _clamp(value)
    return {
        "busyness_score": score,
        "level": _score_to_level(score),
        "source": source,
        "recent_checkins": len(scores),
    }


def _score_to_level(score: int) -> str:
    if score < 26:
        return "not_busy"
    if score < 51:
        return "moderate"
    if score < 76:
        return "busy"
    return "very_busy"


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["meta"])
def index():
    return {
        "name": "Restaurant & Cafe Busyness API",
        "endpoints": [
            "GET /v1/venues",
            "GET /v1/venues/{venue_id}",
            "GET /v1/venues/{venue_id}/forecast",
            "POST /v1/venues/{venue_id}/checkin",
            "GET /v1/busy-now",
        ],
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/venues", tags=["Venues"])
def list_venues(
    category: Optional[Category] = Query(None, description="Filter by venue category"),
    query: Optional[str] = Query(None, description="Search venue name or address"),
    city: Optional[str] = Query(None, description="Filter by city"),
    lat: Optional[float] = Query(None, description="User latitude, for distance sort"),
    lng: Optional[float] = Query(None, description="User longitude, for distance sort"),
    sort: str = Query("name", pattern="^(name|busyness|rating|distance)$"),
):
    """List venues with current busyness, optionally filtered and sorted."""
    now = datetime.now(timezone.utc)
    results = list(VENUES.values())

    if category:
        results = [v for v in results if v.category == category]
    if city:
        results = [v for v in results if v.city.lower() == city.lower()]
    if query:
        q = query.lower()
        results = [v for v in results if q in v.name.lower() or q in v.address.lower()]

    enriched = []
    for v in results:
        busyness = current_busyness(v, now)
        distance_km = _haversine_km(lat, lng, v.lat, v.lng) if lat is not None and lng is not None else None
        enriched.append({**v.model_dump(), "busyness": busyness, "distance_km": round(distance_km, 2) if distance_km is not None else None})

    if sort == "busyness":
        enriched.sort(key=lambda x: x["busyness"]["busyness_score"], reverse=True)
    elif sort == "rating":
        enriched.sort(key=lambda x: x["rating"], reverse=True)
    elif sort == "distance" and lat is not None and lng is not None:
        enriched.sort(key=lambda x: x["distance_km"])
    else:
        enriched.sort(key=lambda x: x["name"])

    return {"count": len(enriched), "results": enriched}


@app.get("/v1/venues/{venue_id}", tags=["Venues"])
def get_venue(venue_id: str):
    """Get full details for a venue, including current busyness."""
    venue = VENUES.get(venue_id)
    if not venue:
        raise HTTPException(404, "Venue not found")
    now = datetime.now(timezone.utc)
    return {**venue.model_dump(), "busyness": current_busyness(venue, now)}


@app.get("/v1/venues/{venue_id}/forecast", tags=["Venues"])
def get_forecast(
    venue_id: str,
    date: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """24-hour predicted busyness curve for a venue on a given date."""
    venue = VENUES.get(venue_id)
    if not venue:
        raise HTTPException(404, "Venue not found")

    now = datetime.now(timezone.utc)
    target_date = now.date()
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "date must be in YYYY-MM-DD format")

    curve = predict_curve(venue, target_date)
    return {
        "venue_id": venue_id,
        "date": target_date.isoformat(),
        "is_weekend": target_date.weekday() >= 5,
        "hourly_busyness": [
            {"hour": h, "busyness_score": score, "level": _score_to_level(score)}
            for h, score in enumerate(curve)
        ],
        "current": current_busyness(venue, now) if target_date == now.date() else None,
    }


class CheckinRequest(BaseModel):
    level: CheckinLevel = Field(..., description="How busy it looks right now")


@app.post("/v1/venues/{venue_id}/checkin", tags=["Venues"])
def submit_checkin(venue_id: str, req: CheckinRequest):
    """Report live busyness for a venue. Recent check-ins are blended
    into the venue's real-time busyness estimate (weighted by volume,
    decayed out of the estimate after 2 hours)."""
    venue = VENUES.get(venue_id)
    if not venue:
        raise HTTPException(404, "Venue not found")

    now = datetime.now(timezone.utc)
    score = LEVEL_SCORE[req.level]
    CHECKINS.setdefault(venue_id, []).append((now, score))

    return {
        "venue_id": venue_id,
        "accepted_level": req.level,
        "busyness": current_busyness(venue, now),
    }


@app.get("/v1/busy-now", tags=["Venues"])
def busy_now(
    category: Optional[Category] = Query(None),
    min_score: int = Query(0, ge=0, le=100, description="Only include venues at or above this busyness score"),
    limit: int = Query(10, ge=1, le=100),
):
    """Currently busiest venues, most crowded first."""
    now = datetime.now(timezone.utc)
    results = list(VENUES.values())
    if category:
        results = [v for v in results if v.category == category]

    enriched = [{**v.model_dump(), "busyness": current_busyness(v, now)} for v in results]
    enriched = [v for v in enriched if v["busyness"]["busyness_score"] >= min_score]
    enriched.sort(key=lambda x: x["busyness"]["busyness_score"], reverse=True)

    return {"count": len(enriched[:limit]), "results": enriched[:limit]}


# ---------------------------------------------------------------------------
# Error handler — clean JSON errors
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.detail, "status": exc.status_code})
