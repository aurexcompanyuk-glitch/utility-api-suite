#!/usr/bin/env python3
"""Build the measured-venue dataset from BestTime.

Two phases, with very different costs:

  discover   POST /venues/search — finds venues Google has foot traffic
             for near a query and forecasts them. Costs ~2 credits per
             venue, so this is the phase that spends money.
  harvest    GET /forecasts/week/raw — reads a week for a venue that is
             already forecast. Free with the public key, so re-running
             this is cheap and safe.

Run discovery once per area, then harvest as often as you like.

    export BESTTIME_API_KEY_PRIVATE=pri_...
    export BESTTIME_API_KEY_PUBLIC=pub_...

    python scripts/harvest_venues.py discover "pub London Shoreditch" --num 15
    python scripts/harvest_venues.py harvest -o data/london_measured_venues.json
"""

import argparse
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import besttime  # noqa: E402
from besttime import BestTimeClient, BestTimeError  # noqa: E402

# Kinds are inferred from the name, because BestTime's own venue_type is
# absent from the radar response and inconsistent elsewhere.
PATTERNS = [
    ("market", r"\bmarket\b"),
    ("bakery", r"\b(bakery|bread|pastry|p[aâ]tisserie|patisserie)\b"),
    ("cafe", r"\b(cafe|caf[eé]|coffee|espresso|roaster|brunch|tea room)\b"),
    ("bar", r"\b(bar|cocktail|wine|taproom|lounge)\b"),
    ("pub", r"\b(pub|tavern|inn|arms|crown|bells|head|hare|fountain)\b"),
]


def classify(name: str, fallback: str) -> str:
    lowered = (name or "").lower()
    for kind, pattern in PATTERNS:
        if re.search(pattern, lowered):
            return kind
    return fallback


async def discover(args) -> int:
    client = _client()
    try:
        result = await client.search_venues(args.query, args.lat, args.lng,
                                            radius=args.radius, limit=args.num)
    except BestTimeError as exc:
        print(f"search failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.aclose()

    print(f"job {result['job_id']} in collection {result['collection_id']}")
    print("Venues are forecast in the background; run `harvest` in a minute.")
    return 0


async def harvest(args) -> int:
    client = _client()
    try:
        venues = await client.list_venues(args.collection)
    except BestTimeError as exc:
        print(f"could not list venues: {exc}", file=sys.stderr)
        return 1

    out, skipped = [], []
    try:
        for venue in venues:
            venue_id = venue.get("venue_id")
            name = venue.get("name") or ""
            try:
                week = await client.week_forecast(venue_id)
            except BestTimeError as exc:
                skipped.append(f"{name}: {exc}")
                continue

            # week_forecast already re-indexes to local midnight.
            hours = [h for day in week["week"] for h in day["hourly_busyness"]]
            if len(hours) != 168:
                skipped.append(f"{name}: got {len(hours)} hours, expected 168")
                continue

            out.append({
                "id": venue_id,
                "n": name,
                "k": classify(name, args.default_kind),
                "a": (venue.get("address") or "").replace(" United Kingdom", "").strip(),
                "lat": venue.get("lat"),
                "lng": venue.get("lng"),
                "w": hours,
            })
            print(f"  ok   {name}")
    finally:
        await client.aclose()

    out.sort(key=lambda v: (v["n"] or "").lower())
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    print(f"\nwrote {len(out)} venues to {args.out}")
    for line in skipped:
        print(f"  skipped {line}")
    return 0


def _client() -> BestTimeClient:
    key = os.environ.get("BESTTIME_API_KEY_PRIVATE")
    if not key:
        print("BESTTIME_API_KEY_PRIVATE is not set.", file=sys.stderr)
        raise SystemExit(2)
    return BestTimeClient(
        private_key=key,
        public_key=os.environ.get("BESTTIME_API_KEY_PUBLIC"),
        base_url=os.environ.get("BESTTIME_BASE_URL", "https://besttime.app/api/v1"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="cmd", required=True)

    d = subs.add_parser("discover", help="find and forecast venues (costs credits)")
    d.add_argument("query")
    d.add_argument("--lat", type=float, default=51.5074)
    d.add_argument("--lng", type=float, default=-0.1278)
    d.add_argument("--radius", type=int, default=2000)
    d.add_argument("--num", type=int, default=15)
    d.set_defaults(fn=discover)

    h = subs.add_parser("harvest", help="read weekly curves (free)")
    h.add_argument("-o", "--out", default="data/london_measured_venues.json")
    h.add_argument("--collection", default=None)
    h.add_argument("--default-kind", default="restaurant")
    h.set_defaults(fn=harvest)

    args = parser.parse_args()
    return asyncio.run(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
