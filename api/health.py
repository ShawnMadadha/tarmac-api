from http.server import BaseHTTPRequestHandler
import json
import os
from datetime import datetime, timezone


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        has_key = bool(os.environ.get("AVIATION_API_KEY", ""))

        result = {
            "service": "tarmac-api",
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_key_configured": has_key,
            "endpoints": {
                "/api": "Flight search (params: flight, dep_iata, arr_iata, airline, status, limit)",
                "/api/delays": "Delayed flights only (params: dep_iata, arr_iata, limit)",
                "/api/health": "This health check",
            },
        }

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
        return
