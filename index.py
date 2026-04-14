from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
import json
import re
import types
from urllib.parse import urlparse, parse_qs

try:
    from FlightRadar24 import FlightRadar24API
    IMPORT_ERROR = None
except Exception as e:
    FlightRadar24API = None
    IMPORT_ERROR = str(e)


def sched_to_iso(ts, tz_offset_seconds=0):
    """Convert an FR24 *scheduled* timestamp to ISO 8601.

    FR24 encodes scheduled times as local airport wall-clock time stuffed into
    a UTC-labelled unix timestamp. We pull the digits back out and re-label
    them with the airport's real UTC offset.
    """
    if not ts:
        return None
    naive = datetime.utcfromtimestamp(int(ts))
    tz = timezone(timedelta(seconds=tz_offset_seconds))
    return naive.replace(tzinfo=tz).isoformat(timespec="seconds")


def real_to_iso(ts, tz_offset_seconds=0):
    """Convert an FR24 *actual / estimated* timestamp to ISO 8601.

    Unlike scheduled times, actual and estimated timestamps are true UTC.
    We convert to the airport's local timezone for display.
    """
    if not ts:
        return None
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    local_tz = timezone(timedelta(seconds=tz_offset_seconds))
    return dt.astimezone(local_tz).isoformat(timespec="seconds")


def calc_delay(scheduled_ts, other_ts):
    if not scheduled_ts or not other_ts:
        return None
    diff = int((other_ts - scheduled_ts) / 60)
    return diff if diff > 0 else None


def format_flight(details):
    ident = details.get("identification") or {}
    airline = details.get("airline") or {}
    airport = details.get("airport") or {}
    time = details.get("time") or {}
    status = details.get("status") or {}

    origin = airport.get("origin") or {}
    dest = airport.get("destination") or {}

    sched = time.get("scheduled") or {}
    real = time.get("real") or {}
    estimated = time.get("estimated") or {}

    dep_sched_ts = sched.get("departure")
    dep_real_ts = real.get("departure")
    dep_est_ts = estimated.get("departure")
    arr_sched_ts = sched.get("arrival")
    arr_real_ts = real.get("arrival")
    arr_est_ts = estimated.get("arrival") or (time.get("other") or {}).get("eta")

    dep_tz = (origin.get("timezone") or {}).get("offset") or 0
    arr_tz = (dest.get("timezone") or {}).get("offset") or 0

    dep_delay = calc_delay(dep_sched_ts, dep_real_ts or dep_est_ts)
    arr_delay = calc_delay(arr_sched_ts, arr_real_ts or arr_est_ts)

    num = ident.get("number") or {}
    origin_pos = origin.get("position") or {}
    dest_pos = dest.get("position") or {}
    origin_code = origin.get("code") or {}
    dest_code = dest.get("code") or {}
    origin_info = origin.get("info") or {}
    dest_info = dest.get("info") or {}

    airline_code = (airline.get("code") or {})
    flight_num = num.get("default") or "N/A"

    # Extract airline IATA from airline.code, or fall back to the prefix of the flight number
    airline_iata = airline_code.get("iata") or airline_code.get("icao") or None
    if not airline_iata and flight_num != "N/A":
        m = re.match(r"^([A-Z]{2})", flight_num)
        if m:
            airline_iata = m.group(1)
    airline_iata = airline_iata or "N/A"

    # Extract the numeric part from "DL1" -> "1" for display like "Delta Air Lines 1"
    flight_number_only = ""
    if flight_num != "N/A":
        m = re.search(r"\d+", flight_num)
        if m:
            flight_number_only = m.group()

    return {
        "flight_iata": flight_num,
        "flight_icao": ident.get("callsign") or "N/A",
        "airline": airline.get("name") or "N/A",
        "airline_iata": airline_iata,
        "airline_logo": f"https://images.kiwi.com/airlines/64/{airline_iata}.png" if airline_iata != "N/A" else None,
        "flight_display": f"{airline.get('name', 'N/A')} {flight_number_only}" if flight_number_only else flight_num,
        "status": status.get("text") or "unknown",
        "departure": {
            "airport": origin.get("name") or "N/A",
            "iata": origin_code.get("iata") or origin_code.get("icao") or "N/A",
            "terminal": origin_info.get("terminal"),
            "gate": origin_info.get("gate"),
            "scheduled": sched_to_iso(dep_sched_ts, dep_tz),
            "estimated": real_to_iso(dep_est_ts, dep_tz),
            "actual": real_to_iso(dep_real_ts, dep_tz),
            "delay_minutes": dep_delay,
            "latitude": origin_pos.get("latitude"),
            "longitude": origin_pos.get("longitude"),
        },
        "arrival": {
            "airport": dest.get("name") or "N/A",
            "iata": dest_code.get("iata") or dest_code.get("icao") or "N/A",
            "terminal": dest_info.get("terminal"),
            "gate": dest_info.get("gate"),
            "scheduled": sched_to_iso(arr_sched_ts, arr_tz),
            "estimated": real_to_iso(arr_est_ts, arr_tz),
            "actual": real_to_iso(arr_real_ts, arr_tz),
            "delay_minutes": arr_delay,
            "latitude": dest_pos.get("latitude"),
            "longitude": dest_pos.get("longitude"),
        },
        "is_delayed": bool(dep_delay and dep_delay > 0) or bool(arr_delay and arr_delay > 0),
    }


def get_flights(params):
    if IMPORT_ERROR:
        return {"success": False, "error": f"Import failed: {IMPORT_ERROR}"}

    flight_iata = params.get("flight", [None])[0]
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["10"])[0])

    fr_api = FlightRadar24API()
    formatted = []
    debug_errors = []

    try:
        if flight_iata:
            needle = flight_iata.strip().upper().replace(" ", "")
            results = fr_api.search(query=flight_iata, limit=limit * 4)
            # "live" = currently airborne, "schedule" = upcoming/on-ground
            candidates = results.get("live", []) + results.get("schedule", [])

            # Filter to exact flight number matches only — search()
            # returns prefix matches (e.g. "AA123" also returns AA1234).
            exact = [
                c for c in candidates
                if (c.get("detail", {}).get("flight") or "").upper().replace(" ", "") == needle
            ]
            # Fall back to all candidates only if no exact match found
            if exact:
                candidates = exact

            for item in candidates:
                if len(formatted) >= limit:
                    break
                flight_id = item.get("id")
                if not flight_id:
                    continue
                try:
                    # get_flight_details() needs an object with a .id attribute
                    ref = types.SimpleNamespace(id=flight_id)
                    details = fr_api.get_flight_details(ref)
                    entry = format_flight(details)
                    # Skip entries where details were too incomplete to be useful
                    if entry.get("flight_iata", "N/A") == "N/A" and entry.get("departure", {}).get("iata", "N/A") == "N/A":
                        debug_errors.append(f"skipped-na:{flight_id}")
                        continue
                    formatted.append(entry)
                except Exception as ex:
                    debug_errors.append(f"{flight_id}:{type(ex).__name__}:{str(ex)[:200]}")
                    continue
        else:
            flights = fr_api.get_flights()

            for f in flights:
                if len(formatted) >= limit:
                    break
                if dep_iata and getattr(f, "origin_airport_iata", None) != dep_iata:
                    continue
                if arr_iata and getattr(f, "destination_airport_iata", None) != arr_iata:
                    continue
                try:
                    details = fr_api.get_flight_details(f)
                    formatted.append(format_flight(details))
                except Exception:
                    continue

        result = {"success": True, "count": len(formatted), "flights": formatted}
        if debug_errors:
            result["_debug"] = debug_errors
            result["_candidates"] = len(candidates) if flight_iata else 0
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        result = get_flights(params)

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
