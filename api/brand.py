from http.server import BaseHTTPRequestHandler
import os
import re
from urllib.parse import urlparse, parse_qs


# Permissive domain syntax check: letters, digits, dots, hyphens only.
# Doesn't validate TLD or structure — just blocks obvious junk / injection attempts
# before we hand the string to Brandfetch.
_DOMAIN_RE = re.compile(r"^[a-z0-9.\-]+$")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        domain = (params.get("domain", [""])[0] or "").strip().lower()[:253]
        if domain.startswith("www."):
            domain = domain[4:]

        client_id = os.environ.get("BRANDFETCH_CLIENT_ID", "")

        if not domain or not _DOMAIN_RE.match(domain) or not client_id:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        redirect_url = f"https://cdn.brandfetch.io/{domain}?c={client_id}"
        self.send_response(302)
        self.send_header("Location", redirect_url)
        self.send_header("Access-Control-Allow-Origin", "*")
        # Cache at the edge — logos don't change often and missing ones stay missing.
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        return
