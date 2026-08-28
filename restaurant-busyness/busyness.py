"""Shared busyness vocabulary: levels, crowdsourced check-ins, blending.

This layer is provider-agnostic — it works the same whether the
underlying numbers came from BestTime or the simulated engine.
"""

import math
import threading
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional


class BusynessLevel(str, Enum):
    not_busy = "not_busy"
    moderate = "moderate"
    busy = "busy"
    very_busy = "very_busy"


class Confidence(str, Enum):
    """How much the number is worth trusting.

    The distinction matters: an estimate derived from a typical rhythm
    for the kind of venue is NOT a measurement, and must never be
    presented as one.
    """
    measured = "measured"      # BestTime live foot traffic, right now
    forecast = "forecast"      # BestTime's own history for THIS venue
    reported = "reported"      # people on the ground, recently
    estimated = "estimated"    # typical rhythm for this KIND of venue
    unknown = "unknown"        # nothing at all


# Plain-English explanation shown to users, per confidence level.
CONFIDENCE_TEXT = {
    Confidence.measured: "Live foot traffic measured now",
    Confidence.forecast: "Forecast from this venue's own history",
    Confidence.reported: "Reported by people here recently",
    Confidence.estimated: "Estimated from typical hours for this kind of place — not measured",
    Confidence.unknown: "No busyness data for this venue",
}

# Ordered best-to-worst, so a mix of inputs reports its weakest link.
_CONFIDENCE_RANK = [
    Confidence.measured, Confidence.forecast,
    Confidence.reported, Confidence.estimated, Confidence.unknown,
]


def score_to_level(score: int) -> str:
    if score < 26:
        return BusynessLevel.not_busy
    if score < 51:
        return BusynessLevel.moderate
    if score < 76:
        return BusynessLevel.busy
    return BusynessLevel.very_busy


def clamp_score(value: float) -> int:
    return int(round(max(0, min(100, value))))


class CheckinLevel(str, Enum):
    quiet = "quiet"
    moderate = "moderate"
    busy = "busy"
    packed = "packed"


CHECKIN_SCORE = {
    CheckinLevel.quiet: 10,
    CheckinLevel.moderate: 40,
    CheckinLevel.busy: 70,
    CheckinLevel.packed: 95,
}

CHECKIN_WINDOW = timedelta(hours=2)
# A check-in's influence decays linearly to zero across CHECKIN_WINDOW,
# and the blend never fully overrides the provider's own data.
MAX_CHECKIN_WEIGHT = 0.75
CHECKINS_FOR_FULL_WEIGHT = 5


class CheckinStore:
    """Thread-safe store of recent crowdsourced busyness reports.

    Check-ins matter most where BestTime has no live coverage: when
    `venue_live_busyness_available` is false, user reports are the only
    real-time signal available.
    """

    def __init__(self):
        self._data: dict[str, list[tuple[datetime, int]]] = {}
        self._lock = threading.Lock()

    def add(self, venue_id: str, level: CheckinLevel,
            now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._data.setdefault(venue_id, []).append((now, CHECKIN_SCORE[level]))

    def recent(self, venue_id: str,
               now: Optional[datetime] = None) -> list[tuple[datetime, int]]:
        """Fresh check-ins, pruning expired ones as a side effect."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            entries = self._data.get(venue_id)
            if not entries:
                return []
            fresh = [(ts, score) for ts, score in entries if now - ts <= CHECKIN_WINDOW]
            if fresh:
                self._data[venue_id] = fresh
            else:
                self._data.pop(venue_id, None)
            return list(fresh)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


checkins = CheckinStore()


def _checkin_signal(entries: list[tuple[datetime, int]],
                    now: datetime) -> tuple[Optional[float], float]:
    """Time-decayed average of recent check-ins, plus a blend weight.

    Returns (weighted_average, weight). Weight rises with the number of
    reports and falls as they age, capped at MAX_CHECKIN_WEIGHT.
    """
    if not entries:
        return None, 0.0

    window = CHECKIN_WINDOW.total_seconds()
    total_weight = 0.0
    weighted_sum = 0.0
    for ts, score in entries:
        age = (now - ts).total_seconds()
        freshness = max(0.0, 1.0 - age / window)
        total_weight += freshness
        weighted_sum += score * freshness

    if total_weight <= 0:
        return None, 0.0

    average = weighted_sum / total_weight
    confidence = min(total_weight / CHECKINS_FOR_FULL_WEIGHT, 1.0)
    return average, confidence * MAX_CHECKIN_WEIGHT


def blend(baseline: Optional[int], venue_id: str, now: Optional[datetime] = None,
          baseline_source: str = "predicted",
          baseline_confidence: Confidence = Confidence.estimated) -> dict:
    """Combine a provider baseline with recent check-ins into one result.

    Either input may be missing: with no baseline the check-ins stand
    alone, and with no check-ins the baseline passes through unchanged.

    Every result carries a `confidence` and a plain-English
    `confidence_note`, so a number estimated from a generic rhythm is
    never mistaken for a measurement.
    """
    now = now or datetime.now(timezone.utc)
    entries = checkins.recent(venue_id, now)
    checkin_avg, weight = _checkin_signal(entries, now)

    if baseline is None and checkin_avg is None:
        return {
            "busyness_score": None,
            "level": None,
            "source": "unavailable",
            "confidence": Confidence.unknown,
            "confidence_note": CONFIDENCE_TEXT[Confidence.unknown],
            "recent_checkins": 0,
        }

    if baseline is None:
        score = clamp_score(checkin_avg)
        source = "checkins"
        confidence = Confidence.reported
    elif checkin_avg is None:
        score = clamp_score(baseline)
        source = baseline_source
        confidence = baseline_confidence
    else:
        score = clamp_score(baseline * (1 - weight) + checkin_avg * weight)
        source = f"{baseline_source}+checkins"
        # A blend is only as trustworthy as its weaker input.
        confidence = max(
            (baseline_confidence, Confidence.reported),
            key=lambda c: _CONFIDENCE_RANK.index(c),
        )

    return {
        "busyness_score": score,
        "level": score_to_level(score),
        "source": source,
        "confidence": confidence,
        "confidence_note": CONFIDENCE_TEXT[confidence],
        "recent_checkins": len(entries),
    }


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
