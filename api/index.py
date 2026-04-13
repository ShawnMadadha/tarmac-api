from http.server import BaseHTTPRequestHandler
import requests
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs


def get_flights(api_key, params):
    """Fetch flights from AviationStack API and return structured JSON."""
    limit = params.get("limit", ["10"])[0]
    flight_iata = params.get("flight", [None])[0]
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]
    airline = params.get("airline", [None])[0]
    status = params.get("status", [None])[0]
    flight_date = params.get("date", [datetime.now(timezone.utc).strftime("%Y-%m-%d")])[0]

    url = f"http://api.aviationstack.com/v1/flights?access_key={api_key}&limit={limit}&offset=0&flight_date={flight_date}"

    # Append optional filters
    if flight_iata:
        url += f"&flight_iata={flight_iata}"
    if dep_iata:
        url += f"&dep_iata={dep_iata}"
    if arr_iata:
        url += f"&arr_iata={arr_iata}"
    if airline:
        url += f"&airline_name={airline}"
    if status:
        url += f"&flight_status={status}"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            return {
                "success": False,
                "error": data["error"].get("message", "Unknown API error"),
            }

        flights = data.get("data", [])
        if not flights:
            return {"success": True, "count": 0, "flights": []}

        formatted = []
        for f in flights:
            dep = f.get("departure", {})
            arr = f.get("arrival", {})
            flight_info = f.get("flight", {})
            airline_info = f.get("airline", {})

            # Calculate delay info
            dep_delay = dep.get("delay")
            arr_delay = arr.get("delay")

            formatted.append(
                {
                    "flight_iata": flight_info.get("iata", "N/A"),
                    "flight_icao": flight_info.get("icao", "N/A"),
                    "airline": airline_info.get("name", "N/A"),
                    "status": f.get("flight_status", "unknown"),
                    "departure": {
                        "airport": dep.get("airport", "N/A"),
                        "iata": dep.get("iata", "N/A"),
                        "terminal": dep.get("terminal"),
                        "gate": dep.get("gate"),
                        "scheduled": dep.get("scheduled"),
                        "estimated": dep.get("estimated"),
                        "actual": dep.get("actual"),
                        "delay_minutes": int(dep_delay) if dep_delay else None,
                    },
                    "arrival": {
                        "airport": arr.get("airport", "N/A"),
                        "iata": arr.get("iata", "N/A"),
                        "terminal": arr.get("terminal"),
                        "gate": arr.get("gate"),
                        "scheduled": arr.get("scheduled"),
                        "estimated": arr.get("estimated"),
                        "actual": arr.get("actual"),
                        "delay_minutes": int(arr_delay) if arr_delay else None,
                    },
                    "is_delayed": (dep_delay is not None and int(dep_delay) > 0)
                    or (arr_delay is not None and int(arr_delay) > 0),
                }
            )

        return {"success": True, "count": len(formatted), "flights": formatted}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        api_key = os.environ.get("AVIATION_API_KEY", "")

        if not api_key:
            result = {
                "success": False,
                "error": "AVIATION_API_KEY not configured in Vercel environment variables.",
            }
        else:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            result = get_flights(api_key, params)

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
        return

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        return
