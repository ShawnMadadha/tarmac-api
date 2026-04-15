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
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "TarmacAPI/1.0",
        })
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                return None, data["error"].get("message", "AirLabs API error")
            return data.get("response", []), None
    except URLError as e:
        return None, f"AirLabs request failed: {e}"
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


def get_delayed_flights(params):
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["25"])[0])

    api_params = {}
    if dep_iata:
        api_params["dep_iata"] = dep_iata
    if arr_iata:
        api_params["arr_iata"] = arr_iata

    # Use the dedicated delays endpoint for departure delays
    data, error = airlabs_get("delays", api_params)

    if error:
        # Fall back to flights endpoint filtered for delayed status
        flight_params = dict(api_params)
        data, error = airlabs_get("flights", flight_params)
        if error:
            return {"success": False, "error": error}
        # Filter to only delayed flights
        data = [f for f in (data or []) if (f.get("delayed") or 0) > 0]

    delayed = []
    for f in (data or []):
        dep_delay = f.get("delayed") or f.get("dep_delayed") or 0
        arr_delay = f.get("arr_delayed") or 0
        max_delay = max(dep_delay, arr_delay)

        if max_delay <= 0:
            continue

        delayed.append({
            "flight_iata": f.get("flight_iata") or "N/A",
            "airline": f.get("airline_name") or "N/A",
            "status": f.get("status") or "delayed",
            "delay": {
                "departure_minutes": dep_delay,
                "arrival_minutes": arr_delay,
                "max_minutes": max_delay,
                "severity": classify_severity(max_delay),
            },
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
        })

    delayed.sort(key=lambda x: x["delay"]["max_minutes"], reverse=True)
    delayed = delayed[:limit]

    return {"success": True, "count": len(delayed), "delayed_flights": delayed}


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
        result = get_delayed_flights(params)

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
