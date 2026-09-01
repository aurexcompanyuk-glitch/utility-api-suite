"""Configuration, loaded from the environment.

The BestTime private key must NEVER be committed or exposed to clients.
It is read from the BESTTIME_API_KEY_PRIVATE environment variable and is
only ever used server-side. See .env.example.
"""

import os
from dataclasses import dataclass
from typing import Optional


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    besttime_private_key: Optional[str]
    besttime_public_key: Optional[str]
    besttime_base_url: str
    collection_id: Optional[str]
    request_timeout: float
    live_cache_ttl: int
    forecast_cache_ttl: int
    allow_simulated_fallback: bool

    @property
    def besttime_enabled(self) -> bool:
        """Real data is only used when a private key is configured."""
        return bool(self.besttime_private_key)


def load_settings() -> Settings:
    # Optional: load a local .env during development. Never required.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    return Settings(
        besttime_private_key=os.environ.get("BESTTIME_API_KEY_PRIVATE") or None,
        besttime_public_key=os.environ.get("BESTTIME_API_KEY_PUBLIC") or None,
        besttime_base_url=os.environ.get("BESTTIME_BASE_URL", "https://besttime.app/api/v1"),
        collection_id=os.environ.get("BESTTIME_COLLECTION_ID") or None,
        request_timeout=float(os.environ.get("BESTTIME_TIMEOUT", "20")),
        # BestTime bills per request, so responses are cached. Live busyness
        # changes fast (short TTL); weekly forecasts barely change (long TTL).
        live_cache_ttl=_get_int("LIVE_CACHE_TTL", 300),            # 5 minutes
        forecast_cache_ttl=_get_int("FORECAST_CACHE_TTL", 86400),  # 24 hours
        allow_simulated_fallback=_get_bool("ALLOW_SIMULATED_FALLBACK", True),
    )


settings = load_settings()
