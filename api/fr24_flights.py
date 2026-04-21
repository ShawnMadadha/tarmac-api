"""
Flight lookups via JeanExtreme002/FlightRadarAPI (FlightRadar24 unofficial SDK).

Used when `flight=` is present; returns the same JSON shape as AviationStack
formatting in `index.py`. Live hex flight IDs get full details; schedule-only
hits fall through to AviationStack.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _normalize_flight_code(code: str | None) -> str:
    if not code:
        return ""
    return code.replace(" ", "").upper()


def _is_live_hex_id(fid: str | None) -> bool:
    if not fid or len(fid) > 16:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in fid)


def _pick_live_candidates(buckets: dict, wanted: str, limit: int) -> list[dict]:
    """Prefer exact IATA flight number (e.g. DL123), then prefix matches."""
    wanted = _normalize_flight_code(wanted)
    live = list(buckets.get("live") or [])
    exact = []
    partial = []
    for item in live:
        det = item.get("detail") or {}
        fn = _normalize_flight_code(det.get("flight"))
        if not fn:
            continue
        if fn == wanted:
            exact.append(item)
        elif fn.startswith(wanted) or wanted.startswith(fn):
            partial.append(item)
    ordered = exact + partial
    out = []
    seen = set()
    for item in ordered:
        fid = item.get("id")
        if fid in seen:
            continue
        seen.add(fid)
        if _is_live_hex_id(str(fid)):
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _make_flight_stub(flight_id: str, flight_number_label: str):
    from FlightRadar24.entities.flight import Flight

    fn = _normalize_flight_code(flight_number_label) or "XX000"
    pad = "XXXXXXXXXXXX"
    info = ["0"] * 20
    info[13] = (fn + pad)[:20]
    return Flight(flight_id, info)


def _unix_to_iso(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _delay_minutes(details: dict) -> tuple[int | None, int | None]:
    t = details.get("time") or {}
    sch = t.get("scheduled") or {}
    real = t.get("real") or {}
    dep_delay = arr_delay = None
    sd, rd = sch.get("departure"), real.get("departure")
    if sd is not None and rd is not None:
        try:
            dep_delay = max(0, int((int(rd) - int(sd)) / 60))
        except (TypeError, ValueError):
            pass
    sa, ra = sch.get("arrival"), real.get("arrival")
    if sa is not None and ra is not None:
        try:
            arr_delay = max(0, int((int(ra) - int(sa)) / 60))
        except (TypeError, ValueError):
            pass
    if dep_delay is None:
        hist = details.get("historical") or {}
        raw = hist.get("delay")
        if raw not in (None, "", "null"):
            try:
                dep_delay = max(0, abs(int(int(raw) / 60)))
            except (TypeError, ValueError):
                pass
    return dep_delay, arr_delay


def _row_from_details(details: dict) -> dict:
    ident = details.get("identification") or {}
    num = ident.get("number") or {}
    flight_iata = num.get("default") or "N/A"
    flight_icao = ident.get("callsign") or "N/A"

    airline = details.get("airline") or {}
    airline_name = airline.get("name") or "N/A"

    st = details.get("status") or {}
    status = st.get("text") or ("live" if st.get("live") else "unknown")

    ap = details.get("airport") or {}
    orig = ap.get("origin") or {}
    dest = ap.get("destination") or {}
    oc = orig.get("code") or {}
    dc = dest.get("code") or {}

    oiata = oc.get("iata") or "N/A"
    diata = dc.get("iata") or "N/A"

    opos = orig.get("position") or {}
    dpos = dest.get("position") or {}

    oinfo = orig.get("info") or {}
    dinfo = dest.get("info") or {}

    tm = details.get("time") or {}
    sch = tm.get("scheduled") or {}
    est = tm.get("estimated") or {}
    real = tm.get("real") or {}

    dep_delay, arr_delay = _delay_minutes(details)

    def fget(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    return {
        "flight_iata": flight_iata,
        "flight_icao": flight_icao,
        "airline": airline_name,
        "status": status,
        "departure": {
            "airport": orig.get("name") or "N/A",
            "iata": oiata,
            "terminal": oinfo.get("terminal"),
            "gate": oinfo.get("gate"),
            "scheduled": _unix_to_iso(sch.get("departure")),
            "estimated": _unix_to_iso(est.get("departure")),
            "actual": _unix_to_iso(real.get("departure")),
            "delay_minutes": dep_delay,
            "latitude": fget(opos.get("latitude")),
            "longitude": fget(opos.get("longitude")),
        },
        "arrival": {
            "airport": dest.get("name") or "N/A",
            "iata": diata,
            "terminal": dinfo.get("terminal"),
            "gate": dinfo.get("gate"),
            "scheduled": _unix_to_iso(sch.get("arrival")),
            "estimated": _unix_to_iso(est.get("arrival")),
            "actual": _unix_to_iso(real.get("arrival")),
            "delay_minutes": arr_delay,
            "latitude": fget(dpos.get("latitude")),
            "longitude": fget(dpos.get("longitude")),
        },
        "is_delayed": (dep_delay or 0) > 0 or (arr_delay or 0) > 0,
    }


def _passes_filters(row: dict, dep_iata: str | None, arr_iata: str | None) -> bool:
    if dep_iata and row["departure"]["iata"].upper() != dep_iata.strip().upper():
        return False
    if arr_iata and row["arrival"]["iata"].upper() != arr_iata.strip().upper():
        return False
    return True


def get_flights_fr24(params: dict) -> dict | None:
    """
    Returns AviationStack-shaped payload or None if FR24 should be skipped
    (import error / no flight param).
    """
    try:
        from FlightRadar24 import FlightRadar24API
    except ImportError:
        return None

    flight_q = (params.get("flight") or [None])[0]
    if not flight_q:
        return None

    limit = int((params.get("limit") or ["5"])[0] or 5)
    dep_f = (params.get("dep_iata") or [None])[0]
    arr_f = (params.get("arr_iata") or [None])[0]

    fr_api = FlightRadar24API(timeout=18)
    search_limit = max(50, min(200, limit * 15))

    try:
        buckets = fr_api.search(flight_q.strip(), limit=search_limit)
    except Exception as e:
        return {
            "success": False,
            "error": f"FlightRadar search failed: {e}",
            "data_source": "flightradar24",
        }

    candidates = _pick_live_candidates(buckets, flight_q, limit)
    rows: list[dict] = []

    for hit in candidates:
        fid = str(hit.get("id"))
        if not _is_live_hex_id(fid):
            continue
        det = hit.get("detail") or {}
        fn = det.get("flight") or flight_q
        try:
            stub = _make_flight_stub(fid, fn)
            details = fr_api.get_flight_details(stub)
        except Exception:
            continue
        row = _row_from_details(details)
        if _passes_filters(row, dep_f, arr_f):
            rows.append(row)
        if len(rows) >= limit:
            break

    return {
        "success": True,
        "count": len(rows),
        "flights": rows,
        "data_source": "flightradar24",
    }
