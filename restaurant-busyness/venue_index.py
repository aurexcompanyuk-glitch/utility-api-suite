"""Remembers which BestTime venue_id a name and address resolved to.

BestTime charges 2 credits to look a venue up by name, but only 1 to
read it by id — and 1 per *ten* venues read from a collection. Resolving
the same name repeatedly is therefore the most expensive thing the app
can do, and the cost is pure waste: the answer never changes.

This index resolves a name once and remembers the id, so every later
request is an id read. It persists to disk because re-resolving after a
restart costs real money; an in-memory-only cache would quietly re-buy
the same answers on every deploy.

Swap the JSON file for a database table when running more than one
process — `_load` / `_save` are the only two places that touch storage.
"""

import json
import logging
import os
import re
import threading
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_PATH = os.environ.get(
    "VENUE_INDEX_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venue-index.json"),
)

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Fold trivial differences so "The Ivy," and "the ivy" agree."""
    lowered = str(text or "").lower().strip()
    lowered = _PUNCT.sub(" ", lowered)
    return _SPACE.sub(" ", lowered).strip()


def make_key(name: str, address: str = "") -> str:
    return f"{normalise(name)}|{normalise(address)}"


class VenueIndex:
    def __init__(self, path: str = DEFAULT_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._map: dict[str, Optional[str]] = self._load()
        # Counters make the saving visible in /health rather than theoretical.
        self.hits = 0
        self.misses = 0

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._map, fh)
            os.replace(tmp, self._path)   # atomic, so a crash can't truncate it
        except OSError as exc:
            log.warning("Could not persist venue index: %s", exc)

    def get(self, name: str, address: str = "") -> Optional[str]:
        """The known venue_id, or None if this name was never resolved."""
        key = make_key(name, address)
        with self._lock:
            if key in self._map:
                self.hits += 1
                return self._map[key]
            self.misses += 1
            return None

    def known(self, name: str, address: str = "") -> bool:
        """True when this name was resolved before — including to nothing.

        A remembered miss matters as much as a hit: without it, a venue
        BestTime does not cover would be re-bought on every single search.
        """
        with self._lock:
            return make_key(name, address) in self._map

    def put(self, name: str, address: str, venue_id: Optional[str]) -> None:
        """Remember a resolution. `None` records a confirmed absence."""
        key = make_key(name, address)
        with self._lock:
            if self._map.get(key) == venue_id and key in self._map:
                return
            self._map[key] = venue_id
            self._save()

    def stats(self) -> dict:
        with self._lock:
            resolved = sum(1 for v in self._map.values() if v)
            return {
                "entries": len(self._map),
                "resolved": resolved,
                "known_absent": len(self._map) - resolved,
                "hits": self.hits,
                "misses": self.misses,
                "credits_saved_estimate": self.hits,
            }

    def clear(self) -> None:
        with self._lock:
            self._map = {}
            self._save()


index = VenueIndex()


class CreditMeter:
    """Counts what the app has spent with BestTime, by endpoint.

    Published rates (Aug 2026): 2 credits for a lookup by name, 1 by
    venue id, 1 per 10 venues via the collection filter. Tracking spend
    locally means a mistake shows up in /health immediately rather than
    on next month's bill.
    """

    RATES = {"by_name": 2.0, "by_id": 1.0, "by_filter": 0.1, "forecast": 1.0}

    def __init__(self):
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self._credits = 0.0

    def record(self, kind: str, units: int = 1) -> None:
        """`units` is the number of venues, not the number of requests."""
        with self._lock:
            self._calls[kind] = self._calls.get(kind, 0) + units
            self._credits += self.RATES.get(kind, 1.0) * units

    def stats(self) -> dict:
        with self._lock:
            return {
                "calls": dict(self._calls),
                "credits_spent_estimate": round(self._credits, 1),
                "note": "Estimated from published rates; BestTime's own count is authoritative.",
            }

    def reset(self) -> None:
        with self._lock:
            self._calls, self._credits = {}, 0.0


meter = CreditMeter()
