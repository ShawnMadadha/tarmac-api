"""
Delayed flights from FlightRadar24 airport boards (JeanExtreme002/FlightRadarAPI).

Replaces AviationStack when `AVIATION_API_KEY` is not set. Uses departure / arrival
schedules vs real/estimated times to infer delays.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _severity(max_minutes: int) -> str:
    if max_minutes >= 180:
        return "severe"
    if max_minutes >= 60:
        return "significant"
    if max_minutes >= 30:
        return "moderate"
    return "minor"


def _leg_delay_minutes(time_block: dict, leg: str) -> int:
    t = time_block or {}
    sch = t.get("scheduled") or {}
    real = t.get("real") or {}
    est = t.get("estimated") or {}
    s = sch.get(leg)
    r = real.get(leg) if real else None
    if r is None and est:
        r = est.get(leg)
    if s is not None and r is not None:
        return max(0, int((int(r) - int(s)) / 60))
    return 0


def _board_rows(schedule: dict, board: str) -> List[dict]:
    b = (schedule or {}).get(board) or {}
    return list(b.get("data") or [])


def _row_to_delayed_entry(
    row: dict,
    dep_airport_iata: str,
    arr_airport_iata: Optional[str],
) -> Optional[dict]:
    fl = row.get("flight") or {}
    ident = fl.get("identification") or {}
    num = ident.get("number") or {}
    flight_iata = num.get("default") or "N/A"

    airline_info = fl.get("airline") or fl.get("owner") or {}
    airline_name = airline_info.get("name") or "N/A"

    status = (fl.get("status") or {}).get("text") or "unknown"

    ap = fl.get("airport") or {}
    orig = ap.get("origin") or {}
    dest = ap.get("destination") or {}

    ocode = (orig.get("code") or {}) if orig else {}
    dcode = (dest.get("code") or {}) if dest else {}
    o_iata = ocode.get("iata") or dep_airport_iata
    d_iata = dcode.get("iata")

    if arr_airport_iata and d_iata and d_iata.upper() != arr_airport_iata.strip().upper():
        return None

    t = fl.get("time") or {}
    dep_delay = _leg_delay_minutes(t, "departure")
    arr_delay = _leg_delay_minutes(t, "arrival")
    max_delay = max(dep_delay, arr_delay)
    if max_delay <= 0:
        return None

    oinfo = orig.get("info") or {}
    dinfo = dest.get("info") or {}
    opos = orig.get("position") or {}
    dpos = dest.get("position") or {}

    def iso_ts(key):
        # We don't have ISO strings in board rows; keep None — clients use delay object most.
        return None

    return {
        "flight_iata": flight_iata,
        "airline": airline_name,
        "status": status,
        "delay": {
            "departure_minutes": dep_delay,
            "arrival_minutes": arr_delay,
            "max_minutes": max_delay,
            "severity": _severity(max_delay),
        },
        "departure": {
            "airport": orig.get("name") or dep_airport_iata,
            "iata": o_iata or dep_airport_iata,
            "terminal": oinfo.get("terminal"),
            "gate": oinfo.get("gate"),
            "scheduled": iso_ts("departure"),
            "estimated": iso_ts("departure"),
            "actual": iso_ts("departure"),
            "latitude": opos.get("latitude"),
            "longitude": opos.get("longitude"),
        },
        "arrival": {
            "airport": dest.get("name") or (d_iata or "N/A"),
            "iata": d_iata or "N/A",
            "scheduled": iso_ts("arrival"),
            "estimated": iso_ts("arrival"),
            "latitude": dpos.get("latitude"),
            "longitude": dpos.get("longitude"),
        },
    }


def get_delayed_flights_fr24(params: dict) -> Optional[dict]:
    """
    Build delayed_flights from FR24 airport schedule boards.
    Expects dep_iata and/or arr_iata (same as legacy AviationStack usage).
    """
    try:
        from FlightRadar24 import FlightRadar24API
    except ImportError:
        return None

    dep_iata = (params.get("dep_iata") or [None])[0]
    arr_iata = (params.get("arr_iata") or [None])[0]
    limit = int((params.get("limit") or ["25"])[0] or 25)

    if not dep_iata and not arr_iata:
        return {
            "success": False,
            "error": "Pass dep_iata and/or arr_iata to list delayed flights (FlightRadar airport board).",
            "data_source": "flightradar24",
        }

    fr_api = FlightRadar24API(timeout=22)
    flight_limit = min(100, max(limit * 4, 40))

    delayed: List[dict] = []

    try:
        if dep_iata:
            detail = fr_api.get_airport_details(dep_iata.strip(), flight_limit=flight_limit)
            sched = (
                detail.get("airport", {})
                .get("pluginData", {})
                .get("schedule", {})
            )
            for row in _board_rows(sched, "departures"):
                entry = _row_to_delayed_entry(
                    row, dep_airport_iata=dep_iata.strip().upper(), arr_airport_iata=arr_iata
                )
                if entry:
                    delayed.append(entry)

        if arr_iata and not dep_iata:
            detail = fr_api.get_airport_details(arr_iata.strip(), flight_limit=flight_limit)
            sched = (
                detail.get("airport", {})
                .get("pluginData", {})
                .get("schedule", {})
            )
            for row in _board_rows(sched, "arrivals"):
                fl = row.get("flight") or {}
                t = fl.get("time") or {}
                dep_delay = _leg_delay_minutes(t, "departure")
                arr_delay = _leg_delay_minutes(t, "arrival")
                max_delay = max(dep_delay, arr_delay)
                if max_delay <= 0:
                    continue

                ident = fl.get("identification") or {}
                num = ident.get("number") or {}
                flight_iata = num.get("default") or "N/A"
                airline_info = fl.get("airline") or fl.get("owner") or {}
                airline_name = airline_info.get("name") or "N/A"
                status = (fl.get("status") or {}).get("text") or "unknown"
                ap = fl.get("airport") or {}
                orig = ap.get("origin") or {}
                dest = ap.get("destination") or {}
                ocode = (orig.get("code") or {}) if orig else {}
                dcode = (dest.get("code") or {}) if dest else {}
                o_iata = ocode.get("iata") or "N/A"
                d_iata = dcode.get("iata") or arr_iata.strip().upper()
                oinfo = orig.get("info") or {}
                dinfo = dest.get("info") or {}
                opos = orig.get("position") or {}
                dpos = dest.get("position") or {}

                delayed.append(
                    {
                        "flight_iata": flight_iata,
                        "airline": airline_name,
                        "status": status,
                        "delay": {
                            "departure_minutes": dep_delay,
                            "arrival_minutes": arr_delay,
                            "max_minutes": max_delay,
                            "severity": _severity(max_delay),
                        },
                        "departure": {
                            "airport": orig.get("name") or o_iata,
                            "iata": o_iata,
                            "terminal": oinfo.get("terminal"),
                            "gate": oinfo.get("gate"),
                            "scheduled": None,
                            "estimated": None,
                            "actual": None,
                            "latitude": opos.get("latitude"),
                            "longitude": opos.get("longitude"),
                        },
                        "arrival": {
                            "airport": dest.get("name") or arr_iata,
                            "iata": d_iata,
                            "scheduled": None,
                            "estimated": None,
                            "latitude": dpos.get("latitude"),
                            "longitude": dpos.get("longitude"),
                        },
                    }
                )

    except Exception as e:
        return {
            "success": False,
            "error": f"FlightRadar airport board failed: {e}",
            "data_source": "flightradar24",
        }

    # If both dep and arr: we only added from departures board with filter — dedupe and sort
    delayed.sort(key=lambda x: x["delay"]["max_minutes"], reverse=True)
    delayed = delayed[:limit]

    return {
        "success": True,
        "count": len(delayed),
        "delayed_flights": delayed,
        "data_source": "flightradar24",
    }
