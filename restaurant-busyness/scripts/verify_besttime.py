#!/usr/bin/env python3
"""Verify this app's BestTime integration against the live API.

Run this from a machine that can reach besttime.app. It checks each
endpoint the app depends on and reports whether the response contains
the fields the client expects, so any API drift shows up as a clear
mismatch instead of a runtime bug.

Usage:
    export BESTTIME_API_KEY_PRIVATE=pri_...
    python scripts/verify_besttime.py
    python scripts/verify_besttime.py --venue-name "Starbucks" \
        --venue-address "Seattle" --write-venues

Costs: the key-status check is free. Live and forecast checks consume
credits, so they only run against a venue you name explicitly, and the
radar search only runs with --search.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from besttime import BestTimeClient, BestTimeError  # noqa: E402

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"


def report(status: str, label: str, detail: str = "") -> None:
    symbol = {PASS: "✓", FAIL: "✗", WARN: "!", INFO: "·"}[status]
    line = f"  {symbol} [{status}] {label}"
    if detail:
        line += f"\n        {detail}"
    print(line)


def check_fields(obj: dict, required: list[str], label: str) -> bool:
    """Report which expected fields came back populated vs missing."""
    missing = [f for f in required if obj.get(f) is None]
    if not missing:
        report(PASS, label, f"all {len(required)} expected fields present")
        return True
    if len(missing) == len(required):
        report(FAIL, label, f"none of the expected fields present: {missing}")
        return False
    report(WARN, label, f"missing/null: {missing}")
    return True


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venue-name", help="Venue to test forecast/live against")
    parser.add_argument("--venue-address", help="Address of --venue-name")
    parser.add_argument("--venue-id", help="Existing BestTime venue_id to test")
    parser.add_argument("--search", action="store_true",
                        help="Also test the radar search (costs credits)")
    parser.add_argument("--lat", type=float, default=51.5074)
    parser.add_argument("--lng", type=float, default=-0.1278)
    args = parser.parse_args()

    key = os.environ.get("BESTTIME_API_KEY_PRIVATE")
    if not key:
        print("BESTTIME_API_KEY_PRIVATE is not set.", file=sys.stderr)
        return 2

    client = BestTimeClient(
        private_key=key,
        public_key=os.environ.get("BESTTIME_API_KEY_PUBLIC"),
        base_url=os.environ.get("BESTTIME_BASE_URL", "https://besttime.app/api/v1"),
    )
    failures = 0

    try:
        print("\n1. Key status  GET /keys/{key}")
        try:
            info = await client.key_status()
            report(PASS, "reachable", f"keys present: {sorted(info)[:8]}")
        except BestTimeError as exc:
            report(FAIL, "key status", str(exc))
            failures += 1

        venue_id = args.venue_id

        if args.venue_name and args.venue_address:
            print("\n2. Create forecast  POST /forecasts")
            try:
                result = await client.create_forecast(args.venue_name, args.venue_address)
                venue = result["venue"]
                venue_id = venue_id or venue.get("venue_id")
                if not check_fields(venue, ["venue_id", "name", "lat", "lng"], "venue_info parsed"):
                    failures += 1

                week = result["week"]
                if not week:
                    report(FAIL, "weekly analysis", "no days parsed from 'analysis'")
                    failures += 1
                else:
                    report(PASS, "weekly analysis", f"{len(week)} days parsed")
                    day = week[0]
                    hourly = day.get("hourly_busyness") or []
                    if len(hourly) != 24:
                        report(FAIL, "day_raw length",
                               f"expected 24 hourly values, got {len(hourly)}")
                        failures += 1
                    else:
                        report(PASS, "day_raw length", "24 hourly values")
                        # Confirms index 0 == midnight: the quietest hours of a
                        # venue's day should sit in the small hours, not midday.
                        peak = hourly.index(max(hourly))
                        report(INFO, f"{day.get('day_name')} peak at index {peak}",
                               f"open={day.get('open_hour')} close={day.get('close_hour')} "
                               f"curve={hourly}")
                        if day.get("open_hour") is not None and max(hourly) > 0:
                            if peak < day["open_hour"]:
                                report(WARN, "index alignment",
                                       "peak falls before opening hour — day_raw may not "
                                       "start at midnight; check DAY_RAW offset")
                            else:
                                report(PASS, "index alignment",
                                       "peak falls within opening hours")
            except BestTimeError as exc:
                report(FAIL, "create forecast", str(exc))
                failures += 1
        else:
            print("\n2. Create forecast  (skipped — pass --venue-name and --venue-address)")

        if venue_id:
            print("\n3. Live busyness  GET /forecasts/live")
            try:
                live = await client.live_busyness(venue_id=venue_id)
                report(PASS, "request ok",
                       f"live_available={live.get('live_available')} "
                       f"live={live.get('live_busyness')} "
                       f"forecast={live.get('forecasted_busyness')}")
                if live.get("live_busyness") is None and live.get("forecasted_busyness") is None:
                    report(FAIL, "busyness values",
                           "neither live nor forecast busyness parsed — check field names")
                    failures += 1
                elif not live.get("live_available"):
                    report(INFO, "live coverage",
                           "BestTime has no real-time data for this venue; the app "
                           "falls back to the forecast and weights check-ins higher")
            except BestTimeError as exc:
                report(FAIL, "live busyness", str(exc))
                failures += 1

            print("\n4. Week forecast  GET /forecasts/week/raw")
            try:
                week_result = await client.week_forecast(venue_id)
                if week_result["week"]:
                    report(PASS, "parsed", f"{len(week_result['week'])} days")
                else:
                    report(WARN, "parsed", "no days returned — endpoint path or key type "
                                           "may differ; the app falls back to POST /forecasts")
            except BestTimeError as exc:
                report(WARN, "week forecast", f"{exc} (app can use POST /forecasts instead)")
        else:
            print("\n3-4. Live/week checks  (skipped — no venue_id available)")

        if args.search:
            print("\n5. Radar search  POST /venues/search")
            try:
                result = await client.search_venues("restaurant", args.lat, args.lng,
                                                    radius=1500, limit=5)
                report(PASS, "request ok",
                       f"job_id={result.get('job_id')} venues={len(result['venues'])}")
                if result["venues"]:
                    check_fields(result["venues"][0], ["venue_id", "name"], "venue parsed")
            except BestTimeError as exc:
                report(FAIL, "radar search", str(exc))
                failures += 1
        else:
            print("\n5. Radar search  (skipped — pass --search to test, costs credits)")

    finally:
        await client.aclose()

    print("\n" + "=" * 60)
    if failures:
        print(f"{failures} check(s) FAILED — the client needs updating to match the API.")
    else:
        print("All executed checks passed.")
    print("=" * 60)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
