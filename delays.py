from http.server import BaseHTTPRequestHandler
import requests
import json
import os
from urllib.parse import urlparse, parse_qs


def get_delayed_flights(api_key, params):
    """Fetch flights and filter to only delayed ones with enriched delay data."""
    limit = params.get("limit", ["25"])[0]
    dep_iata = params.get("dep_iata", [None])[0]
    arr_iata = params.get("arr_iata", [None])[0]

    url = f"http://api.aviationstack.com/v1/flights?access_key={api_key}&limit={limit}&offset=0"

    if dep_iata:
        url += f"&dep_iata={dep_iata}"
    if arr_iata:
        url += f"&arr_iata={arr_iata}"

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
        delayed = []

        for f in flights:
            dep = f.get("departure", {})
            arr = f.get("arrival", {})
            dep_delay = dep.get("delay")
            arr_delay = arr.get("delay")

            # Only include flights with actual delays
            if (dep_delay and int(dep_delay) > 0) or (
                arr_delay and int(arr_delay) > 0
            ):
                flight_info = f.get("flight", {})
                airline_info = f.get("airline", {})

                dep_delay_min = int(dep_delay) if dep_delay else 0
                arr_delay_min = int(arr_delay) if arr_delay else 0
                max_delay = max(dep_delay_min, arr_delay_min)

                # Categorize delay severity
                if max_delay >= 180:
                    severity = "severe"
                elif max_delay >= 60:
                    severity = "significant"
                elif max_delay >= 30:
                    severity = "moderate"
                else:
                    severity = "minor"

                delayed.append(
                    {
                        "flight_iata": flight_info.get("iata", "N/A"),
                        "airline": airline_info.get("name", "N/A"),
                        "status": f.get("flight_status", "unknown"),
                        "delay": {
                            "departure_minutes": dep_delay_min,
                            "arrival_minutes": arr_delay_min,
                            "max_minutes": max_delay,
                            "severity": severity,
                        },
                        "departure": {
                            "airport": dep.get("airport", "N/A"),
                            "iata": dep.get("iata", "N/A"),
                            "terminal": dep.get("terminal"),
                            "gate": dep.get("gate"),
                            "scheduled": dep.get("scheduled"),
                            "estimated": dep.get("estimated"),
                            "actual": dep.get("actual"),
                        },
                        "arrival": {
                            "airport": arr.get("airport", "N/A"),
                            "iata": arr.get("iata", "N/A"),
                            "scheduled": arr.get("scheduled"),
                            "estimated": arr.get("estimated"),
                        },
                    }
                )

        # Sort by most delayed first
        delayed.sort(key=lambda x: x["delay"]["max_minutes"], reverse=True)

        return {"success": True, "count": len(delayed), "delayed_flights": delayed}

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        api_key = os.environ.get("AVIATION_API_KEY", "")

        if not api_key:
            result = {
                "success": False,
                "error": "AVIATION_API_KEY not configured.",
            }
        else:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            result = get_delayed_flights(api_key, params)

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
        return
