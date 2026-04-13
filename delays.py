from http.server import BaseHTTPRequestHandler
from FlightRadar24 import FlightRadar24API
from datetime import datetime, timezone
import json
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


def get_delayed_flights(params):
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["25"])[0])

    fr_api = FlightRadar24API()
    delayed = []

    try:
        flights = fr_api.get_flights()

        candidates = []
        for f in flights:
            if dep_iata and getattr(f, "origin_airport_iata", None) != dep_iata:
                continue
            if arr_iata and getattr(f, "destination_airport_iata", None) != arr_iata:
                continue
            candidates.append(f)

        for f in candidates:
            if len(delayed) >= limit:
                break
            try:
                details = fr_api.get_flight_details(f)

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

                if not dep_delay and not arr_delay:
                    continue

                dep_delay_min = dep_delay or 0
                arr_delay_min = arr_delay or 0
                max_delay = max(dep_delay_min, arr_delay_min)

                if max_delay >= 180:
                    severity = "severe"
                elif max_delay >= 60:
                    severity = "significant"
                elif max_delay >= 30:
                    severity = "moderate"
                else:
                    severity = "minor"

                num = ident.get("number") or {}
                origin_code = origin.get("code") or {}
                dest_code = dest.get("code") or {}

                delayed.append({
                    "flight_iata": num.get("default") or "N/A",
                    "airline": airline.get("name") or "N/A",
                    "status": status.get("text") or "unknown",
                    "delay": {
                        "departure_minutes": dep_delay_min,
                        "arrival_minutes": arr_delay_min,
                        "max_minutes": max_delay,
                        "severity": severity,
                    },
                    "departure": {
                        "airport": origin.get("name") or "N/A",
                        "iata": origin_code.get("iata") or "N/A",
                        "terminal": None,
                        "gate": None,
                        "scheduled": unix_to_iso(dep_sched_ts),
                        "estimated": unix_to_iso(dep_est_ts),
                        "actual": unix_to_iso(dep_real_ts),
                    },
                    "arrival": {
                        "airport": dest.get("name") or "N/A",
                        "iata": dest_code.get("iata") or "N/A",
                        "scheduled": unix_to_iso(arr_sched_ts),
                        "estimated": unix_to_iso(arr_est_ts),
                    },
                })
            except Exception:
                continue

        delayed.sort(key=lambda x: x["delay"]["max_minutes"], reverse=True)
        return {"success": True, "count": len(delayed), "delayed_flights": delayed}

    except Exception as e:
        return {"success": False, "error": str(e)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        result = get_delayed_flights(params)

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
