from http.server import BaseHTTPRequestHandler
import json
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError
from zoneinfo import ZoneInfo

AVIATIONSTACK_BASE = "https://api.aviationstack.com/v1"

# Airport coordinates database — covers major worldwide airports.
# AviationStack doesn't return lat/lon so we provide them server-side.
AIRPORT_COORDS = {
    # US Eastern
    "JFK": (40.6413, -73.7781), "EWR": (40.6895, -74.1745), "LGA": (40.7769, -73.8740),
    "BOS": (42.3656, -71.0096), "PHL": (39.8744, -75.2424), "CLT": (35.2140, -80.9431),
    "ATL": (33.6407, -84.4277), "MIA": (25.7959, -80.2870), "FLL": (26.0742, -80.1506),
    "MCO": (28.4312, -81.3081), "TPA": (27.9755, -82.5332), "IAD": (38.9531, -77.4565),
    "DCA": (38.8512, -77.0402), "BWI": (39.1754, -76.6684), "DTW": (42.2124, -83.3534),
    "CLE": (41.4058, -81.8539), "PIT": (40.4957, -80.2413), "RDU": (35.8776, -78.7875),
    "JAX": (30.4941, -81.6879), "BUF": (42.9405, -78.7322), "IND": (39.7173, -86.2944),
    "CMH": (39.9980, -82.8919), "CVG": (39.0489, -84.6678), "PBI": (26.6832, -80.0956),
    "RSW": (26.5362, -81.7552), "RIC": (37.5052, -77.3197), "SRQ": (27.3954, -82.5544),
    "SYR": (43.1112, -76.1063), "ORF": (36.8946, -76.2012), "CHS": (32.8986, -80.0405),
    "SAV": (32.1276, -81.2021), "MYR": (33.6797, -78.9283), "GSP": (34.8957, -82.2189),
    # US Central
    "ORD": (41.9742, -87.9073), "MDW": (41.7868, -87.7522), "DFW": (32.8998, -97.0403),
    "IAH": (29.9902, -95.3368), "HOU": (29.6454, -95.2789), "MSP": (44.8848, -93.2223),
    "STL": (38.7487, -90.3700), "MCI": (39.2976, -94.7139), "AUS": (30.1975, -97.6664),
    "SAT": (29.5337, -98.4698), "MSY": (29.9934, -90.2580), "MKE": (42.9472, -87.8966),
    "OMA": (41.3032, -95.8941), "BNA": (36.1263, -86.6774), "MEM": (35.0424, -89.9767),
    "OKC": (35.3931, -97.6007), "DSM": (41.5340, -93.6631), "TUL": (36.1984, -95.8881),
    # US Mountain
    "DEN": (39.8561, -104.6737), "PHX": (33.4373, -112.0078), "SLC": (40.7884, -111.9778),
    "ABQ": (35.0402, -106.6090), "ELP": (31.8067, -106.3778), "TUS": (32.1161, -110.9410),
    "BOI": (43.5644, -116.2228), "COS": (38.8058, -104.7008),
    # US Pacific
    "LAX": (33.9416, -118.4085), "SFO": (37.6213, -122.3790), "SEA": (47.4502, -122.3088),
    "SAN": (32.7338, -117.1933), "PDX": (45.5898, -122.5951), "SJC": (37.3626, -121.9290),
    "OAK": (37.7213, -122.2208), "SMF": (38.6954, -121.5908), "LAS": (36.0840, -115.1537),
    "BUR": (34.2007, -118.3585), "ONT": (34.0560, -117.6012), "SNA": (33.6757, -117.8678),
    # US Hawaii / Alaska / Territories
    "HNL": (21.3187, -157.9224), "OGG": (20.8986, -156.4305), "ANC": (61.1743, -149.9962),
    "PSE": (18.0083, -66.5630), "SJU": (18.4394, -66.0018), "STT": (18.3373, -64.9733),
    "STX": (17.7019, -64.7986), "GUM": (13.4834, 144.7959),
    # Canada
    "YYZ": (43.6777, -79.6248), "YVR": (49.1967, -123.1815), "YUL": (45.4706, -73.7408),
    "YYC": (51.1315, -114.0131), "YOW": (45.3225, -75.6692), "YEG": (53.3097, -113.5797),
    # Europe
    "LHR": (51.4700, -0.4543), "LGW": (51.1537, -0.1821), "CDG": (49.0097, 2.5479),
    "FRA": (50.0379, 8.5622), "AMS": (52.3105, 4.7683), "MAD": (40.4983, -3.5676),
    "FCO": (41.8003, 12.2389), "IST": (41.2753, 28.7519), "MUC": (48.3538, 11.7861),
    "ZRH": (47.4647, 8.5492), "BCN": (41.2974, 2.0833), "DUB": (53.4264, -6.2499),
    "ORY": (48.7233, 2.3794), "VIE": (48.1103, 16.5697), "CPH": (55.6180, 12.6560),
    "OSL": (60.1976, 11.1004), "ARN": (59.6519, 17.9186), "HEL": (60.3172, 24.9633),
    "LIS": (38.7813, -9.1359), "ATH": (37.9364, 23.9445), "PRG": (50.1008, 14.2600),
    "WAW": (52.1657, 20.9671), "BRU": (50.9014, 4.4844), "MAN": (53.3537, -2.2750),
    "EDI": (55.9508, -3.3615),
    # Middle East
    "DXB": (25.2528, 55.3644), "AUH": (24.4330, 54.6511), "DOH": (25.2731, 51.6081),
    "RUH": (24.9576, 46.6988), "JED": (21.6796, 39.1565), "TLV": (32.0114, 34.8867),
    "AMM": (31.7226, 35.9932), "BAH": (26.2708, 50.6336), "MCT": (23.5933, 58.2844),
    "KWI": (29.2267, 47.9689),
    # Asia
    "HND": (35.5494, 139.7798), "NRT": (35.7720, 140.3929), "ICN": (37.4602, 126.4407),
    "PEK": (40.0799, 116.6031), "PVG": (31.1443, 121.8083), "HKG": (22.3080, 113.9185),
    "SIN": (1.3644, 103.9915), "BKK": (13.6900, 100.7501), "DEL": (28.5562, 77.1000),
    "BOM": (19.0896, 72.8656), "KUL": (2.7456, 101.7099), "MNL": (14.5086, 121.0198),
    "CGK": (6.1256, 106.6558), "TPE": (25.0777, 121.2330),
    # Oceania
    "SYD": (-33.9461, 151.1772), "MEL": (-37.6690, 144.8410), "BNE": (-27.3842, 153.1175),
    "AKL": (-37.0082, 174.7850), "WLG": (-41.3272, 174.8053),
    # Latin America / Caribbean
    "GRU": (-23.4356, -46.4731), "MEX": (19.4363, -99.0721), "BOG": (4.7016, -74.1469),
    "SCL": (-33.3930, -70.7858), "LIM": (-12.0219, -77.1143), "EZE": (-34.8222, -58.5358),
    "GIG": (-22.8100, -43.2506), "CUN": (21.0365, -86.8771), "PTY": (9.0714, -79.3835),
    "SJO": (9.9939, -84.2088), "UIO": (-0.1292, -78.3575), "MDE": (6.1645, -75.4231),
    # Africa
    "JNB": (-26.1392, 28.2460), "CPT": (-33.9649, 18.6017), "CAI": (30.1219, 31.4056),
    "NBO": (-1.3192, 36.9278), "ADD": (8.9779, 38.7993), "LOS": (6.5774, 3.3211),
    "CMN": (33.3675, -7.5898), "ALG": (36.6910, 3.2154),
}


def get_airport_coords(iata):
    """Return (lat, lon) tuple for an airport IATA code, or (None, None)."""
    if not iata:
        return None, None
    return AIRPORT_COORDS.get(iata.upper(), (None, None))


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


def fix_timezone(time_str, tz_name):
    """Replace the fake +00:00 offset with the real offset from the timezone name.

    AviationStack returns local airport wall-clock times but labels them +00:00.
    We use the timezone name (e.g. 'America/New_York') from the response to
    compute the correct UTC offset and swap it in.
    """
    if not time_str:
        return None
    if not tz_name:
        return time_str

    try:
        tz = ZoneInfo(tz_name)
        # Parse the date portion to get the correct offset for that date
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})', time_str)
        if date_match:
            dt = datetime.fromisoformat(date_match.group(1))
            offset = tz.utcoffset(dt)
            if offset is not None:
                total_seconds = int(offset.total_seconds())
                sign = "+" if total_seconds >= 0 else "-"
                hours, remainder = divmod(abs(total_seconds), 3600)
                minutes = remainder // 60
                offset_str = f"{sign}{hours:02d}:{minutes:02d}"
                return re.sub(r'[+-]\d{2}:\d{2}$', offset_str, time_str)
    except Exception:
        pass

    return time_str


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
    dep_tz = dep.get("timezone")
    arr_tz = arr.get("timezone")

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
        "flight_date": f.get("flight_date"),
        "departure": {
            "airport": dep.get("airport") or "N/A",
            "iata": dep_iata or "N/A",
            "terminal": dep.get("terminal"),
            "gate": dep.get("gate"),
            "scheduled": fix_timezone(dep.get("scheduled"), dep_tz),
            "estimated": fix_timezone(dep.get("estimated"), dep_tz),
            "actual": fix_timezone(dep.get("actual"), dep_tz),
            "delay_minutes": dep_delay if dep_delay > 0 else None,
            "latitude": get_airport_coords(dep_iata)[0],
            "longitude": get_airport_coords(dep_iata)[1],
        },
        "arrival": {
            "airport": arr.get("airport") or "N/A",
            "iata": arr_iata or "N/A",
            "terminal": arr.get("terminal"),
            "gate": arr.get("gate"),
            "scheduled": fix_timezone(arr.get("scheduled"), arr_tz),
            "estimated": fix_timezone(arr.get("estimated"), arr_tz),
            "actual": fix_timezone(arr.get("actual"), arr_tz),
            "delay_minutes": arr_delay if arr_delay > 0 else None,
            "latitude": get_airport_coords(arr_iata)[0],
            "longitude": get_airport_coords(arr_iata)[1],
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
        api_params["flight_iata"] = flight_iata.strip().upper().replace(" ", "")
    if dep_iata:
        api_params["dep_iata"] = dep_iata.strip().upper()
    if arr_iata:
        api_params["arr_iata"] = arr_iata.strip().upper()

    # When searching by flight number, request today's date to get the
    # current/upcoming flight instead of old landed ones.
    if flight_iata and "flight_date" not in api_params:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        api_params["flight_date"] = today

    data, error = aviationstack_get("flights", api_params)
    if error:
        return {"success": False, "error": error}

    # Sort: scheduled > active > landed, newest first
    results = list(data or [])
    results.sort(key=lambda f: f.get("flight_date") or "0000-00-00", reverse=True)
    results.sort(key=lambda f: (
        0 if (f.get("flight_status") or "") == "scheduled" else
        1 if (f.get("flight_status") or "") == "active" else
        2
    ))

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
