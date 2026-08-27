# Restaurant & Cafe Busyness API

Tells you how busy restaurants, cafes, and bars are right now, plus a
predicted busyness curve for the rest of the day — similar in spirit to
Google's "Popular Times".

No external API keys required. Busyness is generated from realistic
per-category, time-of-day/day-of-week curves (deterministic per venue
per day), then blended with live crowdsourced check-ins when people
report how busy a place looks.

## Run locally

```bash
cd restaurant-busyness
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` for interactive API docs.

## Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/v1/venues` | List venues, filter by `category`/`city`/`query`, sort by `name`\|`busyness`\|`rating`\|`distance` |
| GET | `/v1/venues/{venue_id}` | Venue details + current busyness |
| GET | `/v1/venues/{venue_id}/forecast` | 24-hour predicted busyness curve for a date (defaults to today) |
| POST | `/v1/venues/{venue_id}/checkin` | Report live busyness (`quiet`\|`moderate`\|`busy`\|`packed`) |
| GET | `/v1/busy-now` | Currently busiest venues, sorted descending |

## Example

```bash
curl "http://localhost:8000/v1/busy-now?category=cafe&limit=5"

curl -X POST "http://localhost:8000/v1/venues/<venue_id>/checkin" \
  -H "Content-Type: application/json" \
  -d '{"level": "busy"}'
```

## Notes on data

- `VENUES` and `CHECKINS` are in-memory (10 demo venues seeded on
  startup) — swap in a real database for production.
- `predict_curve()` isolates the busyness-prediction logic so it can
  later be replaced with real historical data (e.g. from a Google
  Places-style source) without changing any endpoint.
- Check-ins older than 2 hours automatically age out of the live
  estimate.
