# Busy or Not — restaurant & cafe busyness

Shows how busy restaurants, cafes, and bars are right now, plus an
hour-by-hour forecast for the week. Backed by
[BestTime.app](https://besttime.app) foot-traffic data, with
crowdsourced check-ins layered on top.

A FastAPI backend serves both the JSON API and a dependency-free web app
from a single process.

## Quick start

```bash
cd restaurant-busyness
pip install -r requirements.txt

cp .env.example .env       # add your BestTime keys (optional)
uvicorn main:app --reload
```

- Web app: <http://localhost:8000/>
- API docs: <http://localhost:8000/docs>

**It runs with no API key.** Without `BESTTIME_API_KEY_PRIVATE` the app
serves realistic simulated data over 60+ demo venues across 20 cities, so you can develop
and demo the whole thing offline. The header badge always shows which
source is live.

## Configuration

Set in `.env` (see `.env.example`):

| Variable | Purpose |
|---|---|
| `BESTTIME_API_KEY_PRIVATE` | **Required for real data.** Server-side only. |
| `BESTTIME_API_KEY_PUBLIC` | Used for read-only forecast endpoints. |
| `BESTTIME_COLLECTION_ID` | Restrict queries to one BestTime collection. |
| `LIVE_CACHE_TTL` | Seconds to cache live busyness (default 300). |
| `FORECAST_CACHE_TTL` | Seconds to cache weekly forecasts (default 86400). |
| `ALLOW_SIMULATED_FALLBACK` | Serve simulated data if BestTime is down (default true). |

> **Keep the private key private.** It is read from the environment,
> used only server-side, and never returned in a response — that is why
> the browser talks to this API rather than to BestTime directly.
> `.env` is gitignored.

BestTime bills per request, so every outbound call is cached
(`LIVE_CACHE_TTL` / `FORECAST_CACHE_TTL`). Raise the TTLs to cut cost,
lower them for fresher data. `GET /health` reports cache hit rates and
your remaining credits.

## Searching

One box handles everything. `GET /v1/search?q=…` works out what you meant:

| You type | It does |
|---|---|
| `The Copper Kettle` | Finds that venue by name and shows its busyness |
| `coper kettel` | Fuzzy-matches to the same venue — typos are fine |
| `Manchester` | Lists what's busy across that city |
| `coffee in Leeds` | Category search in a place |
| `sushi near Bristol` | Same, with `near`/`around`/`at` as separators |
| `51.5074, -0.1278` | Raw coordinates still work |

The response's `interpretation` object reports how the query was read
(`term`, `place`, and `mode` — `venue` or `area`), so the UI can explain
itself and you can debug a surprising result.

Place names resolve through a built-in table of ~60 major cities (instant,
offline), falling back to OpenStreetMap's Nominatim for anything else. No
API key needed for geocoding.

## Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/v1/search` | **Main entry point** — search by venue name, city, or category |
| GET | `/v1/geocode` | Resolve a place name to coordinates |
| GET | `/v1/venues/search` | Lower-level: venues near explicit `lat`/`lng` |
| GET | `/v1/venues/search/progress` | Poll a still-running BestTime radar search |
| POST | `/v1/venues` | Add a venue by name + address (creates its forecast) |
| GET | `/v1/venues/{id}` | Venue details with current busyness |
| GET | `/v1/venues/{id}/live` | Live busyness, blended with check-ins |
| GET | `/v1/venues/{id}/forecast` | Hourly forecast; `?day=0..6` for one day |
| POST | `/v1/venues/{id}/checkin` | Report busyness now (`quiet`/`moderate`/`busy`/`packed`) |
| GET | `/v1/busy-now` | Busiest venues right now |
| GET | `/health` | Status, active data source, cache stats, credits |

```bash
curl "http://localhost:8000/v1/search?q=The%20Copper%20Kettle"
curl "http://localhost:8000/v1/search?q=coffee%20in%20Leeds"
curl "http://localhost:8000/v1/busy-now?min_score=60"
curl -X POST "http://localhost:8000/v1/venues/<id>/checkin" \
     -H "Content-Type: application/json" -d '{"level":"busy"}'
```

## How the busyness score works

Every score is 0–100, mapped to `not_busy` (<26), `moderate` (<51),
`busy` (<76), `very_busy` (76+). The `source` field on each response
says where the number came from.

1. **Baseline** — BestTime's live foot traffic when available, otherwise
   its forecast for the current hour. BestTime does not have real-time
   coverage for every venue; `live_available` tells you which you got.
2. **Check-ins** — user reports are weighted by how many there are and
   how recent, decaying to zero over two hours and capped at 75%
   influence so they can nudge but never fully override real data.
3. **Blend** — the two are combined. Check-ins matter most exactly where
   BestTime has no live coverage, and with no baseline at all they
   stand alone.

## Verifying the BestTime integration

The client parses BestTime responses defensively, but field names can
drift. Run this against a live key to confirm every endpoint still
matches:

```bash
export BESTTIME_API_KEY_PRIVATE=pri_...
python scripts/verify_besttime.py                       # free: key status only
python scripts/verify_besttime.py \
    --venue-name "Starbucks" --venue-address "Seattle"  # uses credits
python scripts/verify_besttime.py --search              # uses credits
```

It reports PASS/WARN/FAIL per endpoint and flags any expected field that
came back missing — including whether hourly data is indexed from
midnight, which the app assumes.

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

70 tests, all against the simulated provider — no key or network needed.
BestTime response parsing is covered by feeding known payload shapes
through the client's parsers.

## Architecture

```
main.py         FastAPI routes; picks BestTime or simulated per request
besttime.py     BestTime API client + response normalization
simulated.py    Fallback engine: per-category curves, name matching
venues_data.py  Demo venue dataset (fictional names, many cities)
geocoding.py    Place name -> coordinates (built-in table + Nominatim)
busyness.py     Levels, check-in store, decay + blending
cache.py        TTL cache (swap for Redis if running multiple workers)
config.py       Environment-based settings
static/         Web app (vanilla JS, no build step)
scripts/        Live API verification
```

Routes never touch BestTime's payload shape directly — `besttime.py`
normalizes everything first, so swapping in another data provider means
writing one new module, not editing endpoints.

## Deploying

Works on Railway, Render, or Fly.io as-is:

- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set `BESTTIME_API_KEY_PRIVATE` as a secret environment variable —
  never commit it.

The in-memory venue store and check-in store reset on restart and are
per-process. Move both to a database (and the cache to Redis) before
running more than one worker.
