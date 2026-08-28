"""
Restaurant & Cafe Busyness API

Tells you how busy restaurants, cafes, and bars are right now, plus a
forecast for the rest of the week.

Data sources, in priority order:
  1. BestTime.app  — real foot-traffic data, used when
     BESTTIME_API_KEY_PRIVATE is set.
  2. Simulated     — realistic per-category curves, used when no key is
     configured (local dev, tests, demos) or when BestTime is
     unreachable and ALLOW_SIMULATED_FALLBACK is on.

Crowdsourced check-ins are blended on top of whichever source is active.
They matter most where BestTime reports no live coverage for a venue.

The BestTime private key is only ever used server-side and is never
included in a response.

Run locally:  uvicorn main:app --reload
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import geocoding
import osm
import rhythms
import simulated
from besttime import BestTimeClient, BestTimeError
from busyness import (
    CheckinLevel,
    Confidence,
    blend,
    checkins,
    haversine_km,
    score_to_level,
)
from cache import TTLCache
from config import settings

log = logging.getLogger("busyness")

live_cache = TTLCache()
forecast_cache = TTLCache()
venue_cache = TTLCache()

client: Optional[BestTimeClient] = None
osm_client = osm.OverpassClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    if settings.besttime_enabled:
        client = BestTimeClient(
            private_key=settings.besttime_private_key,
            public_key=settings.besttime_public_key,
            base_url=settings.besttime_base_url,
            timeout=settings.request_timeout,
        )
        log.info("BestTime provider enabled")
    else:
        log.warning(
            "BESTTIME_API_KEY_PRIVATE not set — serving simulated data. "
            "See .env.example."
        )
    yield
    if client is not None:
        await client.aclose()


app = FastAPI(
    title="Restaurant & Cafe Busyness API",
    version="2.0.0",
    description="Real-time and forecast busyness for restaurants, cafes, and bars, "
                "powered by BestTime.app foot-traffic data with crowdsourced check-ins.",
    lifespan=lifespan,
)


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _using_besttime() -> bool:
    return client is not None


def _simulated_allowed() -> bool:
    return settings.allow_simulated_fallback or not settings.besttime_enabled


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def home():
    """Serve the web app, falling back to the API index if it is absent."""
    page = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(page):
        return FileResponse(page)
    return JSONResponse(api_index())


@app.get("/api", tags=["meta"])
def api_index():
    return {
        "name": "Restaurant & Cafe Busyness API",
        "data_source": "besttime" if _using_besttime() else "simulated",
        "endpoints": [
            "GET  /v1/venues/search",
            "GET  /v1/venues/{venue_id}",
            "GET  /v1/venues/{venue_id}/live",
            "GET  /v1/venues/{venue_id}/forecast",
            "POST /v1/venues",
            "POST /v1/venues/{venue_id}/checkin",
            "GET  /v1/busy-now",
        ],
        "web_app": "/",
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
async def health():
    """Liveness plus data-source status. Never returns the API key."""
    source = "besttime" if _using_besttime() else "simulated"
    result = {
        "status": "ok",
        "data_source": source,
        "simulated_fallback_enabled": settings.allow_simulated_fallback,
        "time": datetime.now(timezone.utc).isoformat(),
        "cache": {
            "live": live_cache.stats(),
            "forecast": forecast_cache.stats(),
            "venues": venue_cache.stats(),
        },
    }

    if _using_besttime():
        try:
            key_info = await client.key_status()
            # Surface remaining credits without echoing the key itself.
            result["besttime"] = {
                "reachable": True,
                "credits": key_info.get("credits", key_info.get("api_key_credits")),
            }
        except BestTimeError as exc:
            result["besttime"] = {"reachable": False, "error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Venue search
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Unified search — one box for venue names, places, and categories
# ---------------------------------------------------------------------------

# Words that describe a kind of place rather than a specific one. A query
# made only of these is an area search; anything else is treated as a
# venue name first.
CATEGORY_WORDS = {
    "restaurant", "restaurants", "cafe", "cafes", "café", "coffee", "bar",
    "bars", "pub", "pubs", "food", "eat", "drink", "drinks", "breakfast",
    "brunch", "lunch", "dinner", "takeaway", "bakery", "bistro", "pizzeria",
    "sushi", "pizza", "burger", "burgers", "curry", "indian", "chinese",
    "italian", "thai", "mexican", "japanese", "tapas", "steakhouse", "beer",
    "wine", "cocktails", "tea", "espresso", "diner", "grill", "nearby", "near",
    "me", "open", "busy", "quiet", "best", "good", "top", "place", "places",
}

SPLIT_WORDS = (" in ", " near ", " around ", " at ", " by ")


def _split_query(raw: str) -> tuple[str, Optional[str]]:
    """Split "sushi in Leeds" into ("sushi", "Leeds").

    Splits on the last separator so venue names containing one — "Dog
    in the Pond in Bristol" — resolve the way a person would read them.
    """
    text = raw.strip()
    lowered = text.lower()
    best = None
    for word in SPLIT_WORDS:
        index = lowered.rfind(word)
        if index > 0 and (best is None or index > best[0]):
            best = (index, word)
    if best is None:
        return text, None
    index, word = best
    return text[:index].strip(), text[index + len(word):].strip() or None


def _looks_like_a_place_only(term: str) -> bool:
    """True when the term names a city rather than a venue."""
    return geocoding.lookup_known_city(term) is not None and len(term.split()) <= 3


def _is_category_only(term: str) -> bool:
    """True when every word describes a kind of venue, not a name."""
    words = [w.strip(",.!?") for w in term.lower().split() if w.strip(",.!?")]
    return bool(words) and all(w in CATEGORY_WORDS for w in words)


@app.get("/v1/search", tags=["Search"])
async def unified_search(
    q: str = Query(..., min_length=1, max_length=200,
                   description="Venue name, place, or category — "
                               "'The Copper Kettle', 'coffee in Leeds', 'Manchester'"),
    near: Optional[str] = Query(None, description="Optional place or 'lat,lng' to search around"),
    radius: int = Query(5000, ge=100, le=50000),
    limit: int = Query(24, ge=1, le=100),
):
    """Search by venue name, place, or category — the app's main entry point.

    Handles "The Copper Kettle", "coffee in Leeds", "Manchester", and
    "51.5074, -0.1278" through one parameter, so the UI needs one box.
    """
    term, where = _split_query(q)
    place_text = near or where

    # "Manchester" on its own means "show me what's busy in Manchester".
    if not place_text and _looks_like_a_place_only(term):
        place_text, term = term, ""

    location = await geocoding.geocode(place_text) if place_text else None
    if place_text and location is None:
        raise HTTPException(404, f"Could not find a place called '{place_text}'")

    interpretation = {
        "query": q,
        "term": term or None,
        "place": location["name"] if location else None,
        "mode": "area" if (not term or _is_category_only(term)) else "venue",
    }

    if _using_besttime():
        return await _besttime_search(term, location, radius, limit, interpretation)

    if not _simulated_allowed():
        raise HTTPException(503, "No data source available")
    return _simulated_unified_search(term, location, radius, limit, interpretation)


def _simulated_unified_search(term, location, radius, limit, interpretation) -> dict:
    lat = location["lat"] if location else None
    lng = location["lng"] if location else None

    if term and not location:
        # A name with no place: look everywhere rather than nowhere.
        venues = simulated.search_everywhere(term, limit)
    else:
        venues = simulated.search(term, lat, lng, radius if location else None)[:limit]

    now = datetime.now(timezone.utc)
    results = []
    for v in venues:
        baseline = simulated.current_baseline(v, now)
        results.append({
            **_public_venue(v),
            "busyness": blend(baseline, v["venue_id"], now, "predicted", Confidence.estimated),
            "distance_km": (round(haversine_km(lat, lng, v["lat"], v["lng"]), 2)
                            if lat is not None else None),
        })

    return {"source": "simulated", "interpretation": interpretation,
            "count": len(results), "results": results}


async def _besttime_search(term, location, radius, limit, interpretation) -> dict:
    """Resolve a search against BestTime.

    A venue-shaped query is looked up by name and address first, since
    that answers "how busy is this specific place" in one call. Area
    queries, and venue lookups that find nothing, use the radar search.
    """
    if interpretation["mode"] == "venue" and term:
        address = location["name"] if location else ""
        cache_key = f"named:{term.lower()}|{address.lower()}"
        cached = venue_cache.get(cache_key)
        if cached is not None:
            return {**cached, "cached": True}

        try:
            live = await client.live_busyness(venue_name=term, venue_address=address)
        except (BestTimeError, ValueError) as exc:
            log.info("Named lookup failed for %r: %s — trying area search", term, exc)
            live = None

        if live and live.get("venue_id"):
            baseline = (live["live_busyness"] if live.get("live_available")
                        else live.get("forecasted_busyness"))
            source = "live" if live.get("live_available") else "forecast"
            payload = {
                "source": "besttime",
                "interpretation": interpretation,
                "count": 1,
                "results": [{
                    "venue_id": live["venue_id"],
                    "name": live.get("venue_name") or term,
                    "address": address or None,
                    "timezone": live.get("timezone"),
                    "busyness": blend(baseline, live["venue_id"], None, source,
                                      Confidence.measured if live.get("live_available")
                                      else Confidence.forecast),
                    "live_available": bool(live.get("live_available")),
                    "distance_km": None,
                }],
            }
            venue_cache.set(cache_key, payload, settings.live_cache_ttl)
            return {**payload, "cached": False}

    # Area search needs coordinates.
    if location is None:
        raise HTTPException(
            400,
            "Add a place to search — try 'coffee in Manchester', or include "
            "a venue's address so it can be found."
        )

    try:
        result = await client.search_venues(
            term or "restaurant", location["lat"], location["lng"],
            radius=radius, limit=limit,
        )
    except BestTimeError as exc:
        return _fallback_or_error(
            exc,
            lambda: _simulated_unified_search(term, location, radius, limit, interpretation),
        )

    results = []
    for v in result["venues"]:
        baseline = v.get("live_busyness")
        source, conf = "live", Confidence.measured
        if baseline is None:
            baseline = v.get("forecasted_busyness")
            source, conf = "forecast", Confidence.forecast
        results.append({
            **v,
            "busyness": blend(baseline, v.get("venue_id") or "", None, source, conf),
            "distance_km": (round(haversine_km(location["lat"], location["lng"],
                                               v["lat"], v["lng"]), 2)
                            if v.get("lat") is not None and v.get("lng") is not None
                            else None),
        })

    return {"source": "besttime", "interpretation": interpretation,
            "job_id": result.get("job_id"), "collection_id": result.get("collection_id"),
            "count": len(results), "results": results}


@app.get("/v1/coverage", tags=["Search"])
async def coverage(
    place: str = Query(..., description="Place to survey, e.g. 'Manchester'"),
    radius: int = Query(1500, ge=100, le=10000),
    kind: Optional[str] = Query(None, description="Limit to one kind, e.g. 'restaurant'"),
    limit: int = Query(200, ge=1, le=400),
):
    """How many real venues exist here, and how many BestTime can score.

    Answers the question directly: OpenStreetMap supplies the complete
    venue list (every mapped place), and this reports what share of it
    BestTime actually has data for. Expect the covered share to be well
    under 100% — no provider measures every venue on earth.
    """
    location = await geocoding.geocode(place)
    if location is None:
        raise HTTPException(404, f"Could not find a place called '{place}'")

    try:
        venues = await osm_client.find(
            location["lat"], location["lng"], radius,
            [kind] if kind else None, limit,
        )
    except osm.OverpassError as exc:
        raise HTTPException(502, f"OpenStreetMap lookup failed: {exc}")

    by_kind: dict[str, int] = {}
    for v in venues:
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1

    result = {
        "place": location["name"],
        "radius_m": radius,
        "total_venues": len(venues),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "venue_source": "openstreetmap",
        "besttime_configured": _using_besttime(),
    }

    if not _using_besttime():
        result["note"] = (
            "BestTime is not configured, so no venue here has measured busyness. "
            "Every score would be estimated from typical hours for its kind."
        )
        return result

    # Sample rather than querying every venue: each lookup costs a credit.
    sample = venues[:min(len(venues), 12)]
    measured = forecast_only = missing = 0
    for v in sample:
        try:
            live = await client.live_busyness(
                venue_name=v["name"], venue_address=v.get("address") or location["name"])
        except (BestTimeError, ValueError):
            missing += 1
            continue
        if live.get("live_available"):
            measured += 1
        elif live.get("forecasted_busyness") is not None:
            forecast_only += 1
        else:
            missing += 1

    result["besttime_sample"] = {
        "sampled": len(sample),
        "live_busyness": measured,
        "forecast_only": forecast_only,
        "no_data": missing,
        "note": "A sample, not the full set — each lookup costs a BestTime credit.",
    }
    return result


@app.get("/v1/geocode", tags=["Search"])
async def geocode_place(q: str = Query(..., min_length=1, max_length=200)):
    """Resolve a place name to coordinates. Useful for debugging search."""
    location = await geocoding.geocode(q)
    if location is None:
        raise HTTPException(404, f"Could not find a place called '{q}'")
    return location


@app.get("/v1/venues/search", tags=["Venues"])
async def search_venues(
    q: str = Query("restaurant", description="What to look for, e.g. 'coffee', 'sushi'"),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    radius: int = Query(2000, ge=100, le=50000, description="Search radius in metres"),
    limit: int = Query(20, ge=1, le=100),
):
    """Find venues near a location.

    With BestTime configured this runs a radar search (which costs
    credits and may take a few seconds); otherwise it searches the
    simulated demo set.
    """
    if _using_besttime():
        if lat is None or lng is None:
            raise HTTPException(400, "lat and lng are required when using BestTime search")

        cache_key = f"search:{q}:{lat:.4f}:{lng:.4f}:{radius}:{limit}"
        cached = venue_cache.get(cache_key)
        if cached is not None:
            return {"source": "besttime", "cached": True, **cached}

        try:
            result = await client.search_venues(q, lat, lng, radius=radius, limit=limit)
        except BestTimeError as exc:
            return _fallback_or_error(exc, lambda: _simulated_search(q, lat, lng, radius, limit))

        payload = {
            "count": len(result["venues"]),
            "job_id": result.get("job_id"),
            "collection_id": result.get("collection_id"),
            "results": result["venues"],
        }
        # A radar search may still be running; only cache finished results.
        if result["venues"]:
            venue_cache.set(cache_key, payload, settings.forecast_cache_ttl)
        return {"source": "besttime", "cached": False, **payload}

    if not _simulated_allowed():
        raise HTTPException(503, "No data source available")
    return {"source": "simulated", "cached": False, **_simulated_search(q, lat, lng, radius, limit)}


def _simulated_search(q, lat, lng, radius, limit) -> dict:
    venues = simulated.search(q, lat, lng, radius)[:limit]
    now = datetime.now(timezone.utc)
    results = []
    for v in venues:
        baseline = simulated.current_baseline(v, now)
        results.append({
            **_public_venue(v),
            "busyness": blend(baseline, v["venue_id"], now, "predicted", Confidence.estimated),
            "distance_km": (round(haversine_km(lat, lng, v["lat"], v["lng"]), 2)
                            if lat is not None and lng is not None else None),
        })
    return {"count": len(results), "results": results}


@app.get("/v1/venues/search/progress", tags=["Venues"])
async def search_progress(
    job_id: str = Query(..., description="job_id returned by /v1/venues/search"),
    collection_id: Optional[str] = Query(None),
):
    """Poll a BestTime radar search that was still running."""
    if not _using_besttime():
        raise HTTPException(400, "Search jobs only exist when BestTime is configured")
    try:
        return await client.search_progress(job_id, collection_id)
    except BestTimeError as exc:
        raise HTTPException(502, f"BestTime error: {exc}")


# ---------------------------------------------------------------------------
# Adding a venue
# ---------------------------------------------------------------------------

class AddVenueRequest(BaseModel):
    venue_name: str = Field(..., min_length=1, max_length=200)
    venue_address: str = Field(..., min_length=1, max_length=300)


@app.post("/v1/venues", tags=["Venues"], status_code=201)
async def add_venue(req: AddVenueRequest):
    """Add a venue by name and address, generating its forecast.

    This costs BestTime credits, so the result is cached.
    """
    if not _using_besttime():
        raise HTTPException(400, "Adding venues requires BestTime to be configured")

    try:
        result = await client.create_forecast(
            req.venue_name, req.venue_address, settings.collection_id
        )
    except BestTimeError as exc:
        raise HTTPException(502, f"BestTime error: {exc}")

    venue = result["venue"]
    if venue.get("venue_id"):
        forecast_cache.set(f"week:{venue['venue_id']}", result["week"],
                           settings.forecast_cache_ttl)
    return {"venue": venue, "days_forecast": len(result["week"])}


# ---------------------------------------------------------------------------
# Venue detail + live busyness
# ---------------------------------------------------------------------------

@app.get("/v1/venues/{venue_id}", tags=["Venues"])
async def get_venue(venue_id: str):
    """Venue details with its current busyness."""
    if venue_id.startswith("sim_") or not _using_besttime():
        venue = simulated.DEMO_VENUES.get(venue_id)
        if not venue:
            raise HTTPException(404, "Venue not found")
        now = datetime.now(timezone.utc)
        baseline = simulated.current_baseline(venue, now)
        return {
            **_public_venue(venue),
            "busyness": blend(baseline, venue_id, now, "predicted", Confidence.estimated),
            "source": "simulated",
        }

    live = await _live_busyness(venue_id)
    return {
        "venue_id": venue_id,
        "name": live.get("venue_name"),
        "timezone": live.get("timezone"),
        "local_time": live.get("local_time"),
        "busyness": live["busyness"],
        "source": "besttime",
    }


@app.get("/v1/venues/{venue_id}/live", tags=["Venues"])
async def get_live(venue_id: str):
    """Live busyness for a venue, blended with recent check-ins.

    `live_available` reports whether BestTime has real-time coverage for
    this venue; when it is false the score falls back to the forecast
    and any check-ins carry proportionally more weight.
    """
    if venue_id.startswith("sim_") or not _using_besttime():
        venue = simulated.DEMO_VENUES.get(venue_id)
        if not venue:
            raise HTTPException(404, "Venue not found")
        now = datetime.now(timezone.utc)
        baseline = simulated.current_baseline(venue, now)
        return {
            "venue_id": venue_id,
            "busyness": blend(baseline, venue_id, now, "predicted", Confidence.estimated),
            "live_available": False,
            "source": "simulated",
        }

    return await _live_busyness(venue_id)


async def _live_busyness(venue_id: str) -> dict:
    """Fetch (cached) live data for a venue and blend in check-ins."""
    cache_key = f"live:{venue_id}"
    data = live_cache.get(cache_key)
    cached = data is not None

    if data is None:
        try:
            data = await client.live_busyness(venue_id=venue_id)
        except BestTimeError as exc:
            if exc.status_code == 404:
                raise HTTPException(404, "Venue not found in BestTime")
            if _simulated_allowed():
                log.warning("BestTime live lookup failed for %s: %s", venue_id, exc)
                raise HTTPException(502, f"BestTime unavailable: {exc}")
            raise HTTPException(502, f"BestTime error: {exc}")
        live_cache.set(cache_key, data, settings.live_cache_ttl)

    # Prefer real live data; fall back to the forecast for this moment.
    if data.get("live_available") and data.get("live_busyness") is not None:
        baseline, baseline_source = data["live_busyness"], "live"
        confidence = Confidence.measured
    else:
        baseline, baseline_source = data.get("forecasted_busyness"), "forecast"
        confidence = Confidence.forecast

    return {
        "venue_id": venue_id,
        "venue_name": data.get("venue_name"),
        "timezone": data.get("timezone"),
        "local_time": data.get("local_time"),
        "busyness": blend(baseline, venue_id, None, baseline_source, confidence),
        "live_available": bool(data.get("live_available")),
        "forecasted_busyness": data.get("forecasted_busyness"),
        "live_vs_forecast_delta": data.get("delta"),
        "cached": cached,
        "source": "besttime",
    }


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

@app.get("/v1/venues/{venue_id}/forecast", tags=["Venues"])
async def get_forecast(
    venue_id: str,
    day: Optional[int] = Query(None, ge=0, le=6,
                               description="0=Monday ... 6=Sunday. Omit for the full week."),
):
    """Hour-by-hour busyness forecast for a venue."""
    if venue_id.startswith("sim_") or not _using_besttime():
        venue = simulated.DEMO_VENUES.get(venue_id)
        if not venue:
            raise HTTPException(404, "Venue not found")
        week = simulated.week_forecast(venue, date.today())
        days = [d for d in week if d["day_int"] == day] if day is not None else week
        return {"venue_id": venue_id, "source": "simulated", "days": _decorate(days)}

    cache_key = f"week:{venue_id}"
    week = forecast_cache.get(cache_key)
    cached = week is not None

    if week is None:
        try:
            result = await client.week_forecast(venue_id)
        except BestTimeError as exc:
            if exc.status_code == 404:
                raise HTTPException(404, "Venue not found in BestTime")
            raise HTTPException(502, f"BestTime error: {exc}")
        week = result["week"]
        forecast_cache.set(cache_key, week, settings.forecast_cache_ttl)

    days = [d for d in week if d.get("day_int") == day] if day is not None else week
    if day is not None and not days:
        raise HTTPException(404, f"No forecast available for day {day}")

    return {"venue_id": venue_id, "source": "besttime", "cached": cached,
            "days": _decorate(days)}


def _decorate(days: list[dict]) -> list[dict]:
    """Attach a human-readable level to each hour of each day."""
    out = []
    for d in days:
        hours = [
            {"hour": h, "busyness_score": score, "level": score_to_level(score)}
            for h, score in enumerate(d.get("hourly_busyness") or [])
        ]
        out.append({**d, "hours": hours})
    return out


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------

class CheckinRequest(BaseModel):
    level: CheckinLevel = Field(..., description="How busy the venue looks right now")


@app.post("/v1/venues/{venue_id}/checkin", tags=["Check-ins"])
async def submit_checkin(venue_id: str, req: CheckinRequest):
    """Report how busy a venue is right now.

    Reports decay over two hours and are blended into the venue's
    busyness score, weighted by how many and how recent they are.
    """
    if venue_id.startswith("sim_") and venue_id not in simulated.DEMO_VENUES:
        raise HTTPException(404, "Venue not found")

    now = datetime.now(timezone.utc)
    checkins.add(venue_id, req.level, now)

    if venue_id.startswith("sim_") or not _using_besttime():
        venue = simulated.DEMO_VENUES.get(venue_id)
        baseline = simulated.current_baseline(venue, now) if venue else None
        busyness = blend(baseline, venue_id, now, "predicted", Confidence.estimated)
    else:
        # Reflect the new check-in immediately rather than serving a stale blend.
        try:
            live = await _live_busyness(venue_id)
            busyness = live["busyness"]
        except HTTPException:
            busyness = blend(None, venue_id, now)

    return {"venue_id": venue_id, "accepted_level": req.level, "busyness": busyness}


# ---------------------------------------------------------------------------
# Busiest right now
# ---------------------------------------------------------------------------

@app.get("/v1/busy-now", tags=["Venues"])
async def busy_now(
    min_score: int = Query(0, ge=0, le=100),
    limit: int = Query(10, ge=1, le=100),
    collection_id: Optional[str] = Query(None),
):
    """Venues that are busiest at this moment, most crowded first."""
    if _using_besttime():
        try:
            venues = await client.filter_venues(
                collection_id=collection_id or settings.collection_id,
                busy_min=min_score or None,
                now=True,
                live=True,
                limit=limit,
            )
        except BestTimeError as exc:
            return _fallback_or_error(exc, lambda: _simulated_busy_now(min_score, limit))

        results = []
        for v in venues:
            baseline = v.get("live_busyness")
            source, conf = "live", Confidence.measured
            if baseline is None:
                baseline = v.get("forecasted_busyness")
                source, conf = "forecast", Confidence.forecast
            results.append({
                **v,
                "busyness": blend(baseline, v.get("venue_id") or "", None, source, conf),
            })
        results = [r for r in results
                   if (r["busyness"]["busyness_score"] or 0) >= min_score]
        results.sort(key=lambda x: x["busyness"]["busyness_score"] or 0, reverse=True)
        return {"source": "besttime", "count": len(results), "results": results[:limit]}

    if not _simulated_allowed():
        raise HTTPException(503, "No data source available")
    return {"source": "simulated", **_simulated_busy_now(min_score, limit)}


def _simulated_busy_now(min_score: int, limit: int) -> dict:
    now = datetime.now(timezone.utc)
    results = []
    for v in simulated.DEMO_VENUES.values():
        baseline = simulated.current_baseline(v, now)
        busyness = blend(baseline, v["venue_id"], now, "predicted", Confidence.estimated)
        if busyness["busyness_score"] >= min_score:
            results.append({**_public_venue(v), "busyness": busyness})
    results.sort(key=lambda x: x["busyness"]["busyness_score"], reverse=True)
    return {"count": len(results[:limit]), "results": results[:limit]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _public_venue(v: dict) -> dict:
    """Venue fields safe to expose to clients."""
    return {
        "venue_id": v["venue_id"],
        "name": v["name"],
        "address": v.get("address"),
        "lat": v.get("lat"),
        "lng": v.get("lng"),
        "timezone": v.get("timezone"),
        "venue_type": v.get("venue_type"),
        "price_level": v.get("price_level"),
        "rating": v.get("rating"),
    }


def _fallback_or_error(exc: BestTimeError, fallback):
    """Degrade to simulated data on a BestTime outage, if allowed."""
    if settings.allow_simulated_fallback:
        log.warning("BestTime unavailable, falling back to simulated data: %s", exc)
        return {"source": "simulated_fallback", "besttime_error": str(exc), **fallback()}
    raise HTTPException(502, f"BestTime error: {exc}")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.detail, "status": exc.status_code})
