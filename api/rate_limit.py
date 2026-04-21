"""
In-memory sliding-window rate limiter for Vercel serverless functions.

Each Vercel function instance runs in its own process, so this provides
per-instance protection. Across cold starts the counters reset, which is
fine — the goal is preventing sustained abuse, not exact global accounting.

Usage in any handler:

    from rate_limit import check_rate_limit

    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if check_rate_limit(self):
                return  # 429 already sent
            # ... normal handler logic
"""

import time
from http.server import BaseHTTPRequestHandler

# Config
WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 30  # 30 req/min per IP — generous for normal use

# In-memory store: { ip: [timestamp, timestamp, ...] }
_hits: dict[str, list[float]] = {}

# Prevent unbounded memory growth — evict stale IPs periodically
_LAST_CLEANUP = [0.0]
_CLEANUP_INTERVAL = 300  # every 5 min


def _get_client_ip(handler: BaseHTTPRequestHandler) -> str:
    """Extract client IP, respecting Vercel's forwarded headers."""
    # Vercel sets x-forwarded-for; first entry is the real client
    forwarded = handler.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    # x-real-ip as fallback
    real = handler.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    # Last resort: peer address
    return handler.client_address[0] if handler.client_address else "unknown"


def _cleanup():
    now = time.monotonic()
    if now - _LAST_CLEANUP[0] < _CLEANUP_INTERVAL:
        return
    _LAST_CLEANUP[0] = now
    cutoff = now - WINDOW_SECONDS
    stale = [ip for ip, hits in _hits.items() if not hits or hits[-1] < cutoff]
    for ip in stale:
        del _hits[ip]


def check_rate_limit(handler: BaseHTTPRequestHandler, max_requests: int = MAX_REQUESTS_PER_WINDOW) -> bool:
    """Check if the request should be rate-limited.

    Returns True if the request was blocked (429 already sent).
    Returns False if the request is allowed to proceed.
    """
    _cleanup()

    ip = _get_client_ip(handler)
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS

    # Get or create hit list for this IP
    hits = _hits.get(ip, [])
    # Remove expired entries
    hits = [t for t in hits if t > cutoff]

    if len(hits) >= max_requests:
        # Rate limited
        handler.send_response(429)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Retry-After", str(WINDOW_SECONDS))
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        body = {"success": False, "error": "Too many requests. Please try again later."}
        handler.wfile.write(__import__("json").dumps(body).encode("utf-8"))
        _hits[ip] = hits
        return True

    # Allow request, record hit
    hits.append(now)
    _hits[ip] = hits
    return False
