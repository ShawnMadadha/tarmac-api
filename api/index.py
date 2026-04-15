from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError

AIRLABS_BASE = "https://airlabs.co/api/v9"


def get_api_key():
    return os.environ.get("AIRLABS_API_KEY", "")


def airlabs_get(endpoint, params):
    """Make a GET request to the AirLabs API."""
    api_key = get_api_key()
    if not api_key:
        return None, "AIRLABS_API_KEY not configured"

    params["api_key"] = api_key
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
    url = f"{AIRLABS_BASE}/{endpoint}?{qs}"

    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                return None, data["error"].get("message", "AirLabs API error")
            return data.get("response", []), None
    except URLError as e:
        return None, f"AirLabs request failed: {e}"
    except Exception as e:
        return None, str(e)


def calc_delay(dep_delayed, arr_delayed):
    dep = dep_delayed or 0
    arr = arr_delayed or 0
    return dep > 0 or arr > 0


def format_flight(f):
    dep_delay = f.get("delayed") or f.get("dep_delayed") or 0
    arr_delay = f.get("arr_delayed") or 0

    return {
        "flight_iata": f.get("flight_iata") or "N/A",
        "flight_icao": f.get("flight_icao") or "N/A",
        "airline": f.get("airline_name") or "N/A",
        "airline_iata": f.get("airline_iata"),
        "airline_logo": (
            f"https://airlabs.co/img/airline/m/{f['airline_iata']}.png"
            if f.get("airline_iata")
            else None
        ),
        "flight_display": f.get("flight_iata") or f.get("flight_icao") or "N/A",
        "status": f.get("status") or "unknown",
        "departure": {
            "airport": f.get("dep_name") or "N/A",
            "iata": f.get("dep_iata") or "N/A",
            "terminal": f.get("dep_terminal"),
            "gate": f.get("dep_gate"),
            "scheduled": f.get("dep_time"),
            "estimated": f.get("dep_estimated"),
            "actual": f.get("dep_actual"),
            "delay_minutes": dep_delay if dep_delay > 0 else None,
            "latitude": f.get("dep_lat"),
            "longitude": f.get("dep_lng"),
        },
        "arrival": {
            "airport": f.get("arr_name") or "N/A",
            "iata": f.get("arr_iata") or "N/A",
            "terminal": f.get("arr_terminal"),
            "gate": f.get("arr_gate"),
            "scheduled": f.get("arr_time"),
            "estimated": f.get("arr_estimated"),
            "actual": f.get("arr_actual"),
            "delay_minutes": arr_delay if arr_delay > 0 else None,
            "latitude": f.get("arr_lat"),
            "longitude": f.get("arr_lng"),
        },
        "is_delayed": calc_delay(dep_delay, arr_delay),
    }


def get_flights(params):
    flight_iata = params.get("flight", [None])[0]
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["10"])[0])

    api_params = {}

    if flight_iata:
        api_params["flight_iata"] = flight_iata
    if dep_iata:
        api_params["dep_iata"] = dep_iata
    if arr_iata:
        api_params["arr_iata"] = arr_iata

    data, error = airlabs_get("flights", api_params)
    if error:
        return {"success": False, "error": error}

    formatted = [format_flight(f) for f in (data or [])[:limit]]
    return {"success": True, "count": len(formatted), "flights": formatted}


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
