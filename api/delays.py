from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

AVIATIONSTACK_BASE = "https://api.aviationstack.com/v1"

from fr24_delays import get_delayed_flights_fr24
from query_cache import annotate_fresh, get_cached, set_cached
from rate_limit import check_rate_limit

DELAYS_PATH = "/api/delays"


def get_api_key():
    return os.environ.get("AVIATIONSTACK_API_KEY", "")


def aviationstack_get(endpoint, params, api_key_override=None):
    """Make a GET request to the AviationStack API."""
    api_key = api_key_override or get_api_key()
    if not api_key:
        return None, "AVIATIONSTACK_API_KEY not configured"

    params["access_key"] = api_key
    url = f"{AVIATIONSTACK_BASE}/{endpoint}?{urlencode(params)}"

    try:
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "TarmacAPI/1.0",
        })
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                err = data["error"]
                msg = err.get("message") or err.get("info") or "AviationStack API error"
                return None, msg
            return data.get("data", []), None
    except URLError as e:
        return None, f"AviationStack request failed: {e}"
    except Exception as e:
        return None, str(e)


def classify_severity(minutes):
    if minutes >= 180:
        return "severe"
    elif minutes >= 60:
        return "significant"
    elif minutes >= 30:
        return "moderate"
    else:
        return "minor"


def get_delayed_flights_aviationstack(api_key, params):
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["25"])[0])

    api_params = {}
    if dep_iata:
        api_params["dep_iata"] = dep_iata.strip().upper()
    if arr_iata:
        api_params["arr_iata"] = arr_iata.strip().upper()

    data, error = aviationstack_get("flights", api_params, api_key_override=api_key)
    if error:
        return {"success": False, "error": error}

    delayed = []
    for f in (data or []):
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        airline = f.get("airline") or {}
        flight = f.get("flight") or {}

        dep_delay = dep.get("delay") or 0
        arr_delay = arr.get("delay") or 0
        max_delay = max(dep_delay, arr_delay)

        if max_delay <= 0:
            continue

        delayed.append({
            "flight_iata": flight.get("iata") or "N/A",
            "airline": airline.get("name") or "N/A",
            "status": f.get("flight_status") or "delayed",
            "delay": {
                "departure_minutes": dep_delay,
                "arrival_minutes": arr_delay,
                "max_minutes": max_delay,
                "severity": classify_severity(max_delay),
            },
            "departure": {
                "airport": dep.get("airport") or "N/A",
                "iata": dep.get("iata") or "N/A",
                "terminal": dep.get("terminal"),
                "gate": dep.get("gate"),
                "scheduled": dep.get("scheduled"),
                "estimated": dep.get("estimated"),
                "actual": dep.get("actual"),
                "delay_minutes": dep_delay if dep_delay > 0 else None,
                "latitude": None,
                "longitude": None,
            },
            "arrival": {
                "airport": arr.get("airport") or "N/A",
                "iata": arr.get("iata") or "N/A",
                "terminal": arr.get("terminal"),
                "gate": arr.get("gate"),
                "scheduled": arr.get("scheduled"),
                "estimated": arr.get("estimated"),
                "actual": arr.get("actual"),
                "delay_minutes": arr_delay if arr_delay > 0 else None,
                "latitude": None,
                "longitude": None,
            },
        })

    delayed.sort(key=lambda x: x["delay"]["max_minutes"], reverse=True)
    delayed = delayed[:limit]

    return {"success": True, "count": len(delayed), "delayed_flights": delayed, "data_source": "aviationstack"}


def get_delayed_flights(params):
    api_key = get_api_key()
    return get_delayed_flights_aviationstack(api_key, params)


def get_delayed_flights_unified(api_key, params):
    """
    Prefer FlightRadar airport boards when dep_iata/arr_iata are set (no API key required).
    Optional AviationStack when AVIATIONSTACK_API_KEY is set.
    """
    cached = get_cached(DELAYS_PATH, params)
    if cached is not None:
        return cached

    use_fr = os.environ.get("USE_FLIGHTRADAR", "1").lower() not in ("0", "false", "no")
    dep = (params.get("dep_iata") or [None])[0]
    arr = (params.get("arr_iata") or [None])[0]

    if use_fr and (dep or arr):
        frd = get_delayed_flights_fr24(params)
        if frd is not None:
            if frd.get("success"):
                annotate_fresh(frd)
                set_cached(DELAYS_PATH, params, frd)
                return frd
            annotate_fresh(frd)
            return frd

    key = (api_key or "").strip()
    if key:
        result = get_delayed_flights_aviationstack(key, params)
        if result.get("success"):
            annotate_fresh(result)
            set_cached(DELAYS_PATH, params, result)
            return result
        return result

    return {
        "success": False,
        "error": "Add ?dep_iata= or ?arr_iata= for FlightRadar delays, or set AVIATIONSTACK_API_KEY for AviationStack.",
        "data_source": "none",
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if check_rate_limit(self):
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        api_key = os.environ.get("AVIATIONSTACK_API_KEY", "")
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        result = get_delayed_flights_unified(api_key, params)

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
