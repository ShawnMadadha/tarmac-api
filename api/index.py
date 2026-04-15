from http.server import BaseHTTPRequestHandler
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

# AviationStack free tier uses HTTP only (HTTPS requires paid plan).
# This is safe because the call is server-side from Vercel, not from the client.
AVIATIONSTACK_BASE = "http://api.aviationstack.com/v1"

# AviationStack returns local airport times labelled as +00:00.
# We strip the offset so the iOS app treats them as local times.
# Map airport IATA -> UTC offset string for correct timezone labelling.
AIRPORT_TZ_OFFSETS = {
    # US Eastern
    "JFK": "-04:00", "EWR": "-04:00", "LGA": "-04:00", "BOS": "-04:00",
    "PHL": "-04:00", "CLT": "-04:00", "ATL": "-04:00", "MIA": "-04:00",
    "FLL": "-04:00", "MCO": "-04:00", "TPA": "-04:00", "IAD": "-04:00",
    "DCA": "-04:00", "BWI": "-04:00", "DTW": "-04:00", "CLE": "-04:00",
    "PIT": "-04:00", "RDU": "-04:00", "JAX": "-04:00", "BUF": "-04:00",
    "IND": "-04:00", "CMH": "-04:00", "CVG": "-04:00", "SYR": "-04:00",
    "RIC": "-04:00", "PBI": "-04:00", "RSW": "-04:00", "SRQ": "-04:00",
    # US Central
    "ORD": "-05:00", "DFW": "-05:00", "IAH": "-05:00", "HOU": "-05:00",
    "MSP": "-05:00", "STL": "-05:00", "MCI": "-05:00", "AUS": "-05:00",
    "SAT": "-05:00", "MSY": "-05:00", "MKE": "-05:00", "OMA": "-05:00",
    "MDW": "-05:00", "BNA": "-05:00", "MEM": "-05:00", "OKC": "-05:00",
    # US Mountain
    "DEN": "-06:00", "PHX": "-07:00", "SLC": "-06:00", "ABQ": "-06:00",
    "ELP": "-06:00", "TUS": "-07:00", "BOI": "-06:00",
    # US Pacific
    "LAX": "-07:00", "SFO": "-07:00", "SEA": "-07:00", "SAN": "-07:00",
    "PDX": "-07:00", "SJC": "-07:00", "OAK": "-07:00", "SMF": "-07:00",
    "LAS": "-07:00", "BUR": "-07:00", "ONT": "-07:00", "SNA": "-07:00",
    # US Hawaii / Alaska
    "HNL": "-10:00", "OGG": "-10:00", "ANC": "-08:00",
    # Europe
    "LHR": "+01:00", "LGW": "+01:00", "CDG": "+02:00", "FRA": "+02:00",
    "AMS": "+02:00", "MAD": "+02:00", "FCO": "+02:00", "IST": "+03:00",
    "MUC": "+02:00", "ZRH": "+02:00", "BCN": "+02:00", "DUB": "+01:00",
    # Asia
    "HND": "+09:00", "NRT": "+09:00", "ICN": "+09:00", "PEK": "+08:00",
    "PVG": "+08:00", "HKG": "+08:00", "SIN": "+08:00", "BKK": "+07:00",
    "DEL": "+05:30", "DXB": "+04:00", "DOH": "+03:00",
    # Others
    "SYD": "+10:00", "MEL": "+10:00", "GRU": "-03:00", "MEX": "-06:00",
    "BOG": "-05:00", "SCL": "-04:00", "LIM": "-05:00", "YYZ": "-04:00",
    "YVR": "-07:00", "YUL": "-04:00",
}


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


def fix_timezone(time_str, airport_iata):
    """Replace the fake +00:00 offset with the airport's real timezone offset.

    AviationStack returns local airport wall-clock times but labels them +00:00.
    We swap in the correct offset so iOS parses the time correctly.
    """
    if not time_str or not airport_iata:
        return time_str
    tz = AIRPORT_TZ_OFFSETS.get(airport_iata.upper())
    if not tz:
        return time_str
    # Replace +00:00 at the end with the real offset
    return re.sub(r'[+-]\d{2}:\d{2}$', tz, time_str)


def status_priority(status):
    """Sort priority: active > scheduled > landed."""
    s = (status or "").lower()
    if s == "active":
        return 0
    if s == "scheduled":
        return 1
    return 2


def format_flight(f):
    dep = f.get("departure") or {}
    arr = f.get("arrival") or {}
    airline = f.get("airline") or {}
    flight = f.get("flight") or {}

    dep_delay = dep.get("delay") or 0
    arr_delay = arr.get("delay") or 0
    airline_iata = airline.get("iata")
    dep_iata = dep.get("iata") or ""
    arr_iata = arr.get("iata") or ""

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
            "iata": dep_iata or "N/A",
            "terminal": dep.get("terminal"),
            "gate": dep.get("gate"),
            "scheduled": fix_timezone(dep.get("scheduled"), dep_iata),
            "estimated": fix_timezone(dep.get("estimated"), dep_iata),
            "actual": fix_timezone(dep.get("actual"), dep_iata),
            "delay_minutes": dep_delay if dep_delay > 0 else None,
            "latitude": None,
            "longitude": None,
        },
        "arrival": {
            "airport": arr.get("airport") or "N/A",
            "iata": arr_iata or "N/A",
            "terminal": arr.get("terminal"),
            "gate": arr.get("gate"),
            "scheduled": fix_timezone(arr.get("scheduled"), arr_iata),
            "estimated": fix_timezone(arr.get("estimated"), arr_iata),
            "actual": fix_timezone(arr.get("actual"), arr_iata),
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

    # Sort: active/scheduled first, then newest flight_date first
    results = list(data or [])
    results.sort(key=lambda f: f.get("flight_date") or "0000-00-00", reverse=True)
    results.sort(key=lambda f: status_priority(f.get("flight_status")))

    formatted = [format_flight(f) for f in results[:limit]]
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
