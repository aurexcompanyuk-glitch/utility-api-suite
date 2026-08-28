"""BestTime.app API client.

Wraps the endpoints this app needs and normalizes their responses into
the app's own shapes, so route handlers never depend on BestTime's
payload structure directly.

IMPORTANT — response parsing is deliberately defensive. Every field is
read with .get() and validated, so a change on BestTime's side degrades
to a null/absent value rather than raising. Run
`python scripts/verify_besttime.py` against a live key to confirm the
endpoints and field names below match the current API.

Endpoints used (BestTime API v1):
  POST /forecasts            create/refresh a venue forecast   (private key)
  GET  /forecasts/live       live foot traffic for a venue     (private key)
  GET  /forecasts/week/raw   raw weekly forecast               (public key)
  POST /venues/search        async venue radar search          (private key)
  GET  /venues/progress      poll a venue search job           (private key)
  GET  /venues/filter        filter venues in a collection     (private key)
  GET  /venues               list venues in a collection       (private key)
  GET  /keys/{key}           key status / remaining credits    (private key)
"""

import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


class BestTimeError(RuntimeError):
    """Raised when BestTime returns an error or an unusable payload."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _as_int(value: Any) -> Optional[int]:
    """Coerce to int, returning None for anything non-numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _clamp_score(value: Any) -> Optional[int]:
    """BestTime busyness values are percentages (0-100)."""
    n = _as_int(value)
    if n is None:
        return None
    return max(0, min(100, n))


class BestTimeClient:
    def __init__(
        self,
        private_key: str,
        base_url: str = "https://besttime.app/api/v1",
        public_key: Optional[str] = None,
        timeout: float = 20.0,
    ):
        self._private_key = private_key
        self._public_key = public_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, params: dict) -> dict:
        """Issue a request and return the decoded JSON body.

        BestTime signals failure both via HTTP status and via a
        "status": "error" field in a 200 body, so both are checked.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        clean = {k: v for k, v in params.items() if v is not None}

        client = await self._get_client()
        try:
            response = await client.request(method, url, params=clean)
        except httpx.TimeoutException as exc:
            raise BestTimeError(f"BestTime request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise BestTimeError(f"BestTime request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError:
            raise BestTimeError(
                f"BestTime returned non-JSON response (HTTP {response.status_code})",
                response.status_code,
            )

        if not isinstance(body, dict):
            raise BestTimeError("BestTime returned an unexpected payload type",
                                response.status_code)

        if response.status_code >= 400 or str(body.get("status", "")).lower() == "error":
            message = (
                body.get("message")
                or body.get("error")
                or f"BestTime returned HTTP {response.status_code}"
            )
            raise BestTimeError(str(message), response.status_code)

        return body

    # -- Key status ------------------------------------------------------

    async def key_status(self) -> dict:
        """Remaining credits / key validity. Useful as a health check."""
        return await self._request("GET", f"/keys/{self._private_key}", {})

    # -- Forecasts -------------------------------------------------------

    async def create_forecast(self, venue_name: str, venue_address: str,
                              collection_id: Optional[str] = None) -> dict:
        """Create (or refresh) a venue forecast. Costs credits."""
        body = await self._request("POST", "/forecasts", {
            "api_key_private": self._private_key,
            "venue_name": venue_name,
            "venue_address": venue_address,
            "collection_id": collection_id,
        })
        return parse_forecast(body)

    async def live_busyness(self, venue_id: Optional[str] = None,
                            venue_name: Optional[str] = None,
                            venue_address: Optional[str] = None) -> dict:
        """Live foot traffic. Identify the venue by id, or by name+address."""
        if not venue_id and not (venue_name and venue_address):
            raise ValueError("live_busyness needs venue_id, or venue_name and venue_address")

        body = await self._request("GET", "/forecasts/live", {
            "api_key_private": self._private_key,
            "venue_id": venue_id,
            "venue_name": venue_name,
            "venue_address": venue_address,
        })
        return parse_live(body)

    async def week_forecast(self, venue_id: str) -> dict:
        """Raw weekly forecast for a venue already in your account."""
        body = await self._request("GET", "/forecasts/week/raw", {
            # This endpoint accepts the public key; fall back to private.
            "api_key_public": self._public_key or self._private_key,
            "venue_id": venue_id,
        })
        return parse_week(body)

    # -- Venue discovery -------------------------------------------------

    async def search_venues(self, query: str, lat: float, lng: float,
                            radius: int = 2000, limit: int = 20,
                            fast: bool = True) -> dict:
        """Start a venue radar search. Returns job/collection identifiers;
        results are collected via `search_progress`."""
        body = await self._request("POST", "/venues/search", {
            "api_key_private": self._private_key,
            "q": query,
            "lat": lat,
            "lng": lng,
            "radius": radius,
            "num": limit,
            "fast": str(bool(fast)).lower(),
        })
        return {
            "job_id": body.get("job_id"),
            "collection_id": body.get("collection_id"),
            "count": _as_int(body.get("count")),
            "venues": [parse_venue(v) for v in _venue_list(body)],
        }

    async def search_progress(self, job_id: str,
                              collection_id: Optional[str] = None) -> dict:
        """Poll a venue search job started by `search_venues`."""
        body = await self._request("GET", "/venues/progress", {
            "api_key_private": self._private_key,
            "job_id": job_id,
            "collection_id": collection_id,
        })
        return {
            "job_finished": bool(body.get("job_finished", False)),
            "count": _as_int(body.get("count")),
            "venues": [parse_venue(v) for v in _venue_list(body)],
        }

    async def filter_venues(self, collection_id: Optional[str] = None,
                            busy_min: Optional[int] = None,
                            busy_max: Optional[int] = None,
                            day_int: Optional[int] = None,
                            hour_min: Optional[int] = None,
                            hour_max: Optional[int] = None,
                            now: bool = False, live: bool = False,
                            limit: int = 50) -> list[dict]:
        """Filter venues in a collection by busyness/time."""
        body = await self._request("GET", "/venues/filter", {
            "api_key_private": self._private_key,
            "collection_id": collection_id,
            "busy_min": busy_min,
            "busy_max": busy_max,
            "day_int": day_int,
            "hour_min": hour_min,
            "hour_max": hour_max,
            "now": str(bool(now)).lower(),
            "live": str(bool(live)).lower(),
            "limit": limit,
        })
        return [parse_venue(v) for v in _venue_list(body)]

    async def list_venues(self, collection_id: Optional[str] = None) -> list[dict]:
        """All venues stored in your BestTime account/collection."""
        body = await self._request("GET", "/venues", {
            "api_key_private": self._private_key,
            "collection_id": collection_id,
        })
        return [parse_venue(v) for v in _venue_list(body)]


# ---------------------------------------------------------------------------
# Response normalization
#
# BestTime nests venue data under a few different keys depending on the
# endpoint, so each parser accepts the variants rather than assuming one.
# ---------------------------------------------------------------------------

def _venue_list(body: dict) -> list[dict]:
    """Pull the venue array out of a response, whatever it is called."""
    for key in ("venues", "results", "venue_list", "data"):
        value = body.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


def parse_venue(raw: dict) -> dict:
    """Normalize one BestTime venue object into this app's venue shape."""
    info = raw.get("venue_info") if isinstance(raw.get("venue_info"), dict) else raw

    venue_types = info.get("venue_types")
    if not isinstance(venue_types, list):
        venue_types = []

    forecast = raw.get("venue_forecasted_busyness", raw.get("forecasted_busyness"))
    live = raw.get("venue_live_busyness", raw.get("live_busyness"))

    return {
        "venue_id": info.get("venue_id") or raw.get("venue_id"),
        "name": info.get("venue_name") or raw.get("venue_name"),
        "address": info.get("venue_address") or raw.get("venue_address"),
        "lat": _as_float(info.get("venue_lat")),
        "lng": _as_float(info.get("venue_lng")),
        "timezone": info.get("venue_timezone"),
        "venue_type": info.get("venue_type") or raw.get("venue_type"),
        "venue_types": [str(t) for t in venue_types],
        "price_level": _as_int(info.get("price_level") or raw.get("price_level")),
        "rating": _as_float(info.get("rating") or raw.get("rating")),
        "forecasted_busyness": _clamp_score(forecast),
        "live_busyness": _clamp_score(live),
    }


def parse_live(body: dict) -> dict:
    """Normalize GET /forecasts/live."""
    analysis = body.get("analysis") if isinstance(body.get("analysis"), dict) else {}
    info = body.get("venue_info") if isinstance(body.get("venue_info"), dict) else {}

    live_available = bool(analysis.get("venue_live_busyness_available", False))
    forecast_available = bool(analysis.get("venue_forecast_busyness_available", False))

    return {
        "venue_id": info.get("venue_id"),
        "venue_name": info.get("venue_name"),
        "timezone": info.get("venue_timezone"),
        "local_time": info.get("venue_current_localtime_iso"),
        "live_busyness": _clamp_score(analysis.get("venue_live_busyness")),
        "forecasted_busyness": _clamp_score(analysis.get("venue_forecasted_busyness")),
        "live_available": live_available,
        "forecast_available": forecast_available,
        "delta": _as_int(analysis.get("venue_live_forecasted_delta")),
    }


def parse_forecast(body: dict) -> dict:
    """Normalize POST /forecasts into venue details + a weekly curve."""
    info = body.get("venue_info") if isinstance(body.get("venue_info"), dict) else {}
    return {
        "venue": parse_venue({"venue_info": info}),
        "week": _parse_day_analysis(body.get("analysis")),
    }


def parse_week(body: dict) -> dict:
    """Normalize GET /forecasts/week/raw."""
    info = body.get("venue_info") if isinstance(body.get("venue_info"), dict) else {}
    week = _parse_day_analysis(body.get("analysis"))
    if not week:
        week = _parse_day_analysis(body.get("week_raw"))
    return {"venue": parse_venue({"venue_info": info}), "week": week}


def _parse_day_analysis(analysis: Any) -> list[dict]:
    """Turn BestTime's per-day analysis into 7 normalized day objects.

    `day_raw` is a 24-element list of busyness percentages. Index 0 is
    treated as midnight local time; verify_besttime.py cross-checks this
    against each day's reported opening hour.
    """
    if not isinstance(analysis, list):
        return []

    days = []
    for entry in analysis:
        if not isinstance(entry, dict):
            continue
        day_info = entry.get("day_info") if isinstance(entry.get("day_info"), dict) else {}
        raw = entry.get("day_raw")
        hourly = [_clamp_score(v) or 0 for v in raw] if isinstance(raw, list) else []

        days.append({
            "day_int": _as_int(day_info.get("day_int")),
            "day_name": day_info.get("day_text"),
            "open_hour": _as_int(day_info.get("venue_open")),
            "close_hour": _as_int(day_info.get("venue_closed")),
            "hourly_busyness": hourly,
            "peak_hours": entry.get("peak_hours") if isinstance(entry.get("peak_hours"), list) else [],
            "quiet_hours": entry.get("quiet_hours") if isinstance(entry.get("quiet_hours"), list) else [],
            "busy_hours": entry.get("busy_hours") if isinstance(entry.get("busy_hours"), list) else [],
        })
    return days
