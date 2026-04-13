from http.server import BaseHTTPRequestHandler
from FlightRadar24 import FlightRadar24API
from datetime import datetime, timezone
import json
import types
from urllib.parse import urlparse, parse_qs


def unix_to_iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


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

    dep_delay = calc_delay(dep_sched_ts, dep_real_ts or dep_est_ts)
    arr_delay = calc_delay(arr_sched_ts, arr_real_ts or arr_est_ts)

    num = ident.get("number") or {}
    origin_pos = origin.get("position") or {}
    dest_pos = dest.get("position") or {}
    origin_code = origin.get("code") or {}
    dest_code = dest.get("code") or {}

    return {
        "flight_iata": num.get("default") or "N/A",
        "flight_icao": ident.get("callsign") or "N/A",
        "airline": airline.get("name") or "N/A",
        "status": status.get("text") or "unknown",
        "departure": {
            "airport": origin.get("name") or "N/A",
            "iata": origin_code.get("iata") or "N/A",
            "terminal": None,
            "gate": None,
            "scheduled": unix_to_iso(dep_sched_ts),
            "estimated": unix_to_iso(dep_est_ts),
            "actual": unix_to_iso(dep_real_ts),
            "delay_minutes": dep_delay,
            "latitude": origin_pos.get("latitude"),
            "longitude": origin_pos.get("longitude"),
        },
        "arrival": {
            "airport": dest.get("name") or "N/A",
            "iata": dest_code.get("iata") or "N/A",
            "terminal": None,
            "gate": None,
            "scheduled": unix_to_iso(arr_sched_ts),
            "estimated": unix_to_iso(arr_est_ts),
            "actual": unix_to_iso(arr_real_ts),
            "delay_minutes": arr_delay,
            "latitude": dest_pos.get("latitude"),
            "longitude": dest_pos.get("longitude"),
        },
        "is_delayed": bool(dep_delay and dep_delay > 0) or bool(arr_delay and arr_delay > 0),
    }


def get_flights(params):
    flight_iata = params.get("flight", [None])[0]
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["10"])[0])

    fr_api = FlightRadar24API()
    formatted = []

    try:
        if flight_iata:
            results = fr_api.search(query=flight_iata, limit=limit * 2)
            # Live flights are under the "live" key, not "flights"
            candidates = results.get("live", [])

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
                    formatted.append(format_flight(details))
                except Exception:
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

        return {"success": True, "count": len(formatted), "flights": formatted}

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
