from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

# AviationStack free tier uses HTTP only (HTTPS requires paid plan).
# This is safe because the call is server-side from Vercel, not from the client.
AVIATIONSTACK_BASE = "http://api.aviationstack.com/v1"


def get_api_key():
    return os.environ.get("AVIATIONSTACK_API_KEY", "")


def aviationstack_get(endpoint, params):
    """Make a GET request to the AviationStack API."""
    api_key = get_api_key()
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


def format_flight(f):
    dep = f.get("departure") or {}
    arr = f.get("arrival") or {}
    airline = f.get("airline") or {}
    flight = f.get("flight") or {}

    dep_delay = dep.get("delay") or 0
    arr_delay = arr.get("delay") or 0
    airline_iata = airline.get("iata")

    return {
        "flight_iata": flight.get("iata") or "N/A",
        "flight_icao": flight.get("icao") or "N/A",
        "airline": airline.get("name") or "N/A",
        "airline_iata": airline_iata,
        "airline_logo": (
            f"https://images.kiwi.com/airlines/64/{airline_iata}.png"
            if airline_iata
            else None
        ),
        "flight_display": (
            f"{airline.get('name', '')} {flight.get('number', '')}".strip()
            or flight.get("iata")
            or "N/A"
        ),
        "status": f.get("flight_status") or "unknown",
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
        "is_delayed": (dep_delay > 0) or (arr_delay > 0),
    }


def get_flights(params):
    flight_iata = params.get("flight", [None])[0]
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    limit = int(params.get("limit", ["10"])[0])

    api_params = {}

    if flight_iata:
        # Normalize: remove spaces, uppercase
        api_params["flight_iata"] = flight_iata.strip().upper().replace(" ", "")
    if dep_iata:
        api_params["dep_iata"] = dep_iata.strip().upper()
    if arr_iata:
        api_params["arr_iata"] = arr_iata.strip().upper()

    data, error = aviationstack_get("flights", api_params)
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
