# Measured venue data

`london_measured_venues.json` holds the venues BestTime actually has foot
traffic for, harvested with `scripts/harvest_venues.py`.

Each entry is:

| Field | Meaning |
|---|---|
| `id` | BestTime `venue_id` |
| `n` | Venue name |
| `k` | Kind — `restaurant`, `cafe`, `pub`, `bar`, `bakery`, `market` |
| `a` | Address |
| `lat` / `lng` | Coordinates |
| `w` | 168 busyness values, **Monday 00:00 → Sunday 23:00 local time** |

## About `w`

BestTime serves its weeks starting at 06:00, not midnight — see
`DAY_RAW_START_HOUR` in `besttime.py` and the tests that pin it. The
harvest script applies that correction once, so `w[hour_of_week]` can be
read directly. Index for "now" is `weekday_monday_first * 24 + hour`.

These are real measurements, not estimates. Do not blend them with the
simulated curves in `rhythms.py` without carrying the distinction through
to whatever the user sees.

## Refreshing

Building the set costs BestTime forecast credits (about 2 per venue via
the radar search). Re-reading a venue's week afterwards is **free** with
the public key, so re-run the harvest freely; only adding new venues costs
anything.
