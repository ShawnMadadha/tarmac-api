from http.server import BaseHTTPRequestHandler
import os
import re
import requests
from urllib.parse import urlparse, parse_qs
from rate_limit import check_rate_limit


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

# When Brandfetch has no logo for a domain it still returns HTTP 200 with a
# tiny placeholder (transparent pixel, ~300 bytes). Treat anything under this
# threshold as "no logo" so the iOS client falls back to the SF Symbol.
# Real brand logos from Brandfetch are ≥ several KB.
_MIN_LOGO_BYTES = 1024


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if check_rate_limit(self):
            return

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

        # Brandfetch bounces missing logos to their docs page (text/html) or returns
        # a tiny placeholder pixel. Treat anything that isn't a real image as a 404
        # so the iOS client falls back to its SF Symbol.
        content_type = response.headers.get("Content-Type", "")
        body = response.content
        if (
            response.status_code != 200
            or not content_type.startswith("image/")
            or len(body) < _MIN_LOGO_BYTES
        ):
            self._not_found()
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # Cache at the edge — logos don't change often and missing ones stay missing.
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)
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
