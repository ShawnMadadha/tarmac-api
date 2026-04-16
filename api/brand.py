from http.server import BaseHTTPRequestHandler
import os
import re
import requests
from urllib.parse import urlparse, parse_qs


# Permissive domain syntax check: letters, digits, dots, hyphens only.
# Doesn't validate TLD or structure — just blocks obvious junk / injection attempts
# before we hand the string to Brandfetch.
_DOMAIN_RE = re.compile(r"^[a-z0-9.\-]+$")

# Brandfetch's Logo Link API enforces hotlinking protection — requests without a
# Referer / from unknown origins get bounced to their docs page. We proxy through
# the backend so we can set a Referer matching the domain registered in our
# Brandfetch dashboard, and so the iOS client doesn't need to know about
# Brandfetch at all (cleaner API surface, rotatable provider).
_REFERER = "https://tarmac-api.vercel.app/"
_USER_AGENT = "Tarmac/1.0 (+https://tarmac-api.vercel.app)"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        domain = (params.get("domain", [""])[0] or "").strip().lower()[:253]
        if domain.startswith("www."):
            domain = domain[4:]

        client_id = os.environ.get("BRANDFETCH_CLIENT_ID", "")

        if not domain or not _DOMAIN_RE.match(domain) or not client_id:
            self._not_found()
            return

        brandfetch_url = f"https://cdn.brandfetch.io/{domain}?c={client_id}"
        headers = {"Referer": _REFERER, "User-Agent": _USER_AGENT}

        try:
            response = requests.get(
                brandfetch_url,
                headers=headers,
                timeout=10,
                allow_redirects=True,
            )
        except requests.exceptions.RequestException:
            self._not_found()
            return

        # Brandfetch bounces missing logos to their docs page (text/html). Treat
        # anything that isn't an image as "no logo available."
        content_type = response.headers.get("Content-Type", "")
        if response.status_code != 200 or not content_type.startswith("image/"):
            self._not_found()
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        # Cache at the edge — logos don't change often and missing ones stay missing.
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(response.content)
        return

    def _not_found(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b"Not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        return
