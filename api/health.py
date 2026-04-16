from http.server import BaseHTTPRequestHandler
import json
from datetime import datetime, timezone


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        result = {
            "service": "tarmac-api",
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoints": {
                "/api": "Flight search (params: flight, dep_iata, arr_iata, limit)",
                "/api/delays": "Delayed flights only (params: dep_iata, arr_iata, limit)",
                "/api/place-cost": "Place cost + visit duration estimate (params: name, category, lat, lon)",
                "/api/brand": "Brand logo lookup via Brandfetch (params: domain)",
                "/api/nearby": "Yelp-backed nearby places with real ratings/hours (params: lat, lon). 5m edge cache.",
                "/api/plan": "AI-curated 3-stop layover plan (POST body: flight, airport, places[], budget, time_available, mood).",
                "/api/aircraft-history": "Where's-your-plane timeline — every leg the aircraft has flown today (params: flight).",
                "/api/health": "This health check",
            },
        }

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
        return
