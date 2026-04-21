"""GET /api/aircraft-history?flight=AA100

Returns the chain of flights the same aircraft (tail) has flown today, leading
up to the user's flight. Powers the "Where's your plane?" timeline on the
flight confirmation screen — UPS-style tracker so a delayed user can see
exactly where their inbound aircraft has been.

Two-step lookup:
  1. Hit /flights for the user's flight → extract aircraft.registration
  2. Hit /flights again with that registration → every leg the tail flew today
  3. Sort chronologically, mark which leg becomes the user's flight, return.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError
from zoneinfo import ZoneInfo
from rate_limit import check_rate_limit

AVIATIONSTACK_BASE = "https://api.aviationstack.com/v1"

# Trimmed coord/timezone DB — same set as index.py for the "Where's your plane?"
# pins. Kept inline to avoid cross-file imports on Vercel's flat function model.
AIRPORT_COORDS = {
    "JFK": (40.6413, -73.7781), "EWR": (40.6895, -74.1745), "LGA": (40.7769, -73.8740),
    "BOS": (42.3656, -71.0096), "PHL": (39.8744, -75.2424), "CLT": (35.2140, -80.9431),
    "ATL": (33.6407, -84.4277), "MIA": (25.7959, -80.2870), "FLL": (26.0742, -80.1506),
    "MCO": (28.4312, -81.3081), "TPA": (27.9755, -82.5332), "IAD": (38.9531, -77.4565),
    "DCA": (38.8512, -77.0402), "BWI": (39.1754, -76.6684), "DTW": (42.2124, -83.3534),
    "ORD": (41.9742, -87.9073), "MDW": (41.7868, -87.7522), "DFW": (32.8998, -97.0403),
    "IAH": (29.9902, -95.3368), "HOU": (29.6454, -95.2789), "MSP": (44.8848, -93.2223),
    "STL": (38.7487, -90.3700), "MCI": (39.2976, -94.7139), "AUS": (30.1975, -97.6664),
    "SAT": (29.5337, -98.4698), "MSY": (29.9934, -90.2580), "BNA": (36.1263, -86.6774),
    "DEN": (39.8561, -104.6737), "PHX": (33.4373, -112.0078), "SLC": (40.7884, -111.9778),
    "LAX": (33.9416, -118.4085), "SFO": (37.6213, -122.3790), "SEA": (47.4502, -122.3088),
    "SAN": (32.7338, -117.1933), "PDX": (45.5898, -122.5951), "LAS": (36.0840, -115.1537),
    "HNL": (21.3187, -157.9224), "ANC": (61.1743, -149.9962),
    "LHR": (51.4700, -0.4543), "CDG": (49.0097, 2.5479), "FRA": (50.0379, 8.5622),
    "AMS": (52.3105, 4.7683), "MAD": (40.4983, -3.5676), "FCO": (41.8003, 12.2389),
    "DXB": (25.2528, 55.3644), "DOH": (25.2731, 51.6081),
    "HND": (35.5494, 139.7798), "NRT": (35.7720, 140.3929), "ICN": (37.4602, 126.4407),
    "HKG": (22.3080, 113.9185), "SIN": (1.3644, 103.9915), "BKK": (13.6900, 100.7501),
    "SYD": (-33.9461, 151.1772), "MEL": (-37.6690, 144.8410),
    "GRU": (-23.4356, -46.4731), "MEX": (19.4363, -99.0721),
    "YYZ": (43.6777, -79.6248), "YVR": (49.1967, -123.1815),
}


def _coords(iata):
    if not iata:
        return None, None
    return AIRPORT_COORDS.get(iata.upper(), (None, None))


def _api_key():
    return os.environ.get("AVIATIONSTACK_API_KEY", "")


def _get(endpoint, params):
    """Wrapper around the AviationStack REST API with a 20s timeout."""
    key = _api_key()
    if not key:
        return None, "AVIATIONSTACK_API_KEY not configured"

    params["access_key"] = key
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
                msg = err.get("message") or err.get("info") or "AviationStack error"
                return None, msg
            return data.get("data", []), None
    except URLError:
        return None, "Aircraft tracking temporarily unavailable."
    except Exception:
        return None, "Unexpected error fetching aircraft history."


def _fix_tz(time_str, tz_name):
    """Replace AviationStack's fake +00:00 with the airport's real offset."""
    if not time_str or not tz_name:
        return time_str
    try:
        tz = ZoneInfo(tz_name)
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", time_str)
        if date_match:
            dt = datetime.fromisoformat(date_match.group(1))
            offset = tz.utcoffset(dt)
            if offset is not None:
                total = int(offset.total_seconds())
                sign = "+" if total >= 0 else "-"
                h, rem = divmod(abs(total), 3600)
                m = rem // 60
                return re.sub(r"[+-]\d{2}:\d{2}$", f"{sign}{h:02d}:{m:02d}", time_str)
    except Exception:
        pass
    return time_str


def _extract_aircraft_id(flight_obj):
    """Pull the strongest available aircraft identifier out of a flight record.

    AviationStack's `aircraft` block is inconsistent — not every flight has
    every field, and the registration is what we actually need to query history
    by tail. Returns (registration, icao24) or (None, None) if nothing usable.
    """
    aircraft = flight_obj.get("aircraft") or {}
    if not isinstance(aircraft, dict):
        return None, None
    registration = aircraft.get("registration")
    icao24 = aircraft.get("icao24")
    return registration, icao24


def _format_leg(f, user_flight_iata=None):
    """Compress an AviationStack flight record down to just what the timeline needs."""
    dep = f.get("departure") or {}
    arr = f.get("arrival") or {}
    airline = f.get("airline") or {}
    flight = f.get("flight") or {}

    dep_iata = (dep.get("iata") or "").upper()
    arr_iata = (arr.get("iata") or "").upper()
    dep_lat, dep_lon = _coords(dep_iata)
    arr_lat, arr_lon = _coords(arr_iata)

    flight_iata = flight.get("iata") or ""
    is_user_leg = bool(user_flight_iata) and flight_iata.upper() == user_flight_iata.upper()

    return {
        "flight_iata": flight_iata or None,
        "flight_number": flight.get("number"),
        "airline": airline.get("name"),
        "status": f.get("flight_status") or "unknown",
        "from": {
            "iata": dep_iata or None,
            "airport": dep.get("airport"),
            "scheduled": _fix_tz(dep.get("scheduled"), dep.get("timezone")),
            "actual": _fix_tz(dep.get("actual"), dep.get("timezone")),
            "latitude": dep_lat,
            "longitude": dep_lon,
            "timezone": dep.get("timezone"),
        },
        "to": {
            "iata": arr_iata or None,
            "airport": arr.get("airport"),
            "scheduled": _fix_tz(arr.get("scheduled"), arr.get("timezone")),
            "actual": _fix_tz(arr.get("actual"), arr.get("timezone")),
            "latitude": arr_lat,
            "longitude": arr_lon,
            "timezone": arr.get("timezone"),
        },
        "delay_minutes": (arr.get("delay") or dep.get("delay") or 0) or None,
        "is_user_flight": is_user_leg,
    }


def _aircraft_matches(flight_obj, registration, icao24):
    """True if the given flight is operated by the same aircraft (tail) we're tracking."""
    aircraft = flight_obj.get("aircraft") or {}
    if not isinstance(aircraft, dict):
        return False
    if registration:
        their_reg = aircraft.get("registration")
        if their_reg and their_reg.upper() == registration.upper():
            return True
    if icao24:
        their_icao = aircraft.get("icao24")
        if their_icao and their_icao.upper() == icao24.upper():
            return True
    return False


def get_aircraft_history(params):
    flight_iata = (params.get("flight", [None])[0] or "").strip().upper().replace(" ", "")
    if not flight_iata:
        return {"success": False, "error": "Missing required `flight` query parameter."}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Step 1: pull the user's flight to learn which aircraft it's on.
    flights, err = _get("flights", {"flight_iata": flight_iata, "flight_date": today})
    if err:
        return {"success": False, "error": err}
    if not flights:
        return {"success": False, "error": f"No flight found for {flight_iata} today."}

    user_flight = flights[0]
    registration, icao24 = _extract_aircraft_id(user_flight)
    airline_iata = ((user_flight.get("airline") or {}).get("iata") or "").upper()

    if not registration and not icao24:
        return {
            "success": False,
            "error": "Aircraft tail number not available for this flight yet — "
                     "try again closer to departure.",
            "user_flight": _format_leg(user_flight, flight_iata),
        }
    if not airline_iata:
        return {
            "success": False,
            "error": "Airline code missing from flight record; can't trace the aircraft.",
            "user_flight": _format_leg(user_flight, flight_iata),
        }

    # Step 2: pull this airline's flights today and filter locally by tail.
    # AviationStack doesn't support filtering by aircraft registration/ICAO24
    # directly — `aircraft_iata` matches the aircraft *type* (e.g. B738), not the
    # specific tail. So we paginate the airline's day and intersect ourselves.
    matching = []
    seen_keys = set()  # dedupe by flight_iata + scheduled departure
    for offset in (0, 100, 200, 300):
        page, page_err = _get("flights", {
            "airline_iata": airline_iata,
            "flight_date": today,
            "limit": 100,
            "offset": offset,
        })
        if page_err or not page:
            break
        for f in page:
            if not _aircraft_matches(f, registration, icao24):
                continue
            key = (
                ((f.get("flight") or {}).get("iata") or ""),
                ((f.get("departure") or {}).get("scheduled") or ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            matching.append(f)
        if len(page) < 100:
            break  # reached end of airline's day

    if not matching:
        # Couldn't find any other legs — at least return the user's flight as a
        # single-leg timeline so the UI shows something useful.
        matching = [user_flight]

    matching.sort(key=lambda f: ((f.get("departure") or {}).get("scheduled") or "0"))
    formatted = [_format_leg(f, flight_iata) for f in matching]

    # Defensive: ensure the user's flight is in the timeline at least once.
    if not any(leg["is_user_flight"] for leg in formatted):
        formatted.append(_format_leg(user_flight, flight_iata))
        formatted.sort(key=lambda l: ((l.get("from") or {}).get("scheduled") or "0"))

    return {
        "success": True,
        "aircraft_registration": registration,
        "aircraft_icao24": icao24,
        "airline": airline_iata,
        "leg_count": len(formatted),
        "legs": formatted,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if check_rate_limit(self):
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "public, s-maxage=300")
        self.end_headers()

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        result = get_aircraft_history(params)
        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
