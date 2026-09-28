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
| `rating` / `reviews` | Google rating and review count, or `null` |
| `price` | 1–4, or `null` when not published |
| `type` / `types` | BestTime's own category and its tag list |
| `dwellMin` / `dwellMax` | Typical minutes spent at the venue |
| `days` | Seven entries, Monday first — see below — or `null` |

Each `days` entry carries `open`, `close`, `hours` (a printable string),
`rankMean` (1 = busiest day of that venue's week), `dayMean`, `dayMax`,
`peak`, `quiet`, `arrive` and `leave`.

Ten of the 53 venues have `days: null`: the free BestTime query quota ran
out mid-harvest. Their `w` curves are complete and real — only the extra
detail is missing, and the app says so rather than filling the gap in.

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
