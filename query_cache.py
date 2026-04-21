"""
Short-TTL cache for upstream flight queries (FlightRadar / AviationStack).

Same 5-minute window as our TSA-style scrape cadence: avoid hammering providers
and keep responses stable for rapid retries (e.g. app refresh).
"""

import copy
import json
import time
from typing import Optional

# Seconds — align with TSA wait scrape interval in the app.
CACHE_TTL_SECONDS = 300

_store: dict[str, tuple[float, dict]] = {}


def cache_key(path: str, params: dict) -> str:
    """Stable key from route + normalized query string lists."""
    norm = {k: (params.get(k) or [None])[0] for k in sorted(params.keys())}
    return json.dumps({"path": path, "q": norm}, sort_keys=True)


def get_cached(path: str, params: dict) -> Optional[dict]:
    key = cache_key(path, params)
    row = _store.get(key)
    if not row:
        return None
    ts, payload = row
    if time.monotonic() - ts > CACHE_TTL_SECONDS:
        del _store[key]
        return None
    out = copy.deepcopy(payload)
    out["served_from_cache"] = True
    out["flight_data_ttl_seconds"] = CACHE_TTL_SECONDS
    return out


def set_cached(path: str, params: dict, payload: dict) -> None:
    """Store a copy without volatile cache metadata fields."""
    key = cache_key(path, params)
    clean = {
        k: v
        for k, v in payload.items()
        if k not in ("served_from_cache", "flight_data_ttl_seconds")
    }
    _store[key] = (time.monotonic(), copy.deepcopy(clean))


def annotate_fresh(payload: dict) -> dict:
    """Mark a freshly computed response (not from cache)."""
    payload["served_from_cache"] = False
    payload["flight_data_ttl_seconds"] = CACHE_TTL_SECONDS
    return payload
