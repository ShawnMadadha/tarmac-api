from http.server import BaseHTTPRequestHandler
import os
import json
import requests
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed


# Yelp Fusion category aliases (see https://docs.developer.yelp.com/docs/resources-categories).
# Keys match the client's category chips so the iOS side can keep its filter UI unchanged.
# Values are comma-joined Yelp aliases; Yelp ORs them in the search request.
_CATEGORY_MAP = {
    "Food": "restaurants,food",
    "Coffee": "coffee,coffeeroasteries,cafes",
    "Parks": "parks,playgrounds",
    "Culture": "museums,galleries,musicvenues,theater,historicaltours,landmarks",
    "Shopping": "shopping,fashion,bookstores",
}

_YELP_SEARCH = "https://api.yelp.com/v3/businesses/search"
_SEARCH_RADIUS_M = 12_000  # 12 km — wide enough to cover "within 5 miles" UX copy.
_PER_CATEGORY_LIMIT = 10


def _yelp_search(session: requests.Session, headers: dict, yelp_categories: str,
                 lat: float, lon: float, open_now: bool) -> list:
    """One Yelp search call. Returns [] on any failure so a single bad category
    doesn't poison the whole response."""
    params = {
        "categories": yelp_categories,
        "latitude": lat,
        "longitude": lon,
        "limit": _PER_CATEGORY_LIMIT,
        "radius": _SEARCH_RADIUS_M,
        "sort_by": "best_match",
    }
    if open_now:
        params["open_now"] = "true"
    try:
        r = session.get(_YELP_SEARCH, headers=headers, params=params, timeout=8)
        if r.status_code != 200:
            return []
        return r.json().get("businesses", [])
    except requests.exceptions.RequestException:
        return []


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            lat = float(params.get("lat", ["0"])[0])
            lon = float(params.get("lon", ["0"])[0])
        except ValueError:
            self._json({"success": False, "error": "invalid coordinates"}, 400)
            return
        if lat == 0.0 and lon == 0.0:
            self._json({"success": False, "error": "lat/lon required"}, 400)
            return

        api_key = os.environ.get("YELP_API_KEY", "")
        if not api_key:
            self._json({"success": False, "error": "YELP_API_KEY not configured"}, 503)
            return

        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

        # For each of our 5 categories we fire two Yelp searches in parallel: one
        # unfiltered (authoritative list of venues), one with open_now=true. Diffing
        # the ID sets tells us which are open *right now* per-venue — accurate rather
        # than a category-time heuristic. Ten parallel requests fits well under
        # Vercel's 10s hobby-tier function timeout.
        tasks = []
        for cat, yelp_cats in _CATEGORY_MAP.items():
            tasks.append((cat, yelp_cats, False))
            tasks.append((cat, yelp_cats, True))

        results: dict[str, dict[str, list]] = {cat: {"all": [], "open": []} for cat in _CATEGORY_MAP}
        session = requests.Session()
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {
                ex.submit(_yelp_search, session, headers, yelp_cats, lat, lon, open_now): (cat, open_now)
                for (cat, yelp_cats, open_now) in tasks
            }
            for f in as_completed(futures):
                cat, open_now = futures[f]
                key = "open" if open_now else "all"
                results[cat][key] = f.result()

        all_places: list[dict] = []
        for cat, buckets in results.items():
            open_ids = {b["id"] for b in buckets["open"]}
            for b in buckets["all"]:
                # Yelp's is_closed means "permanently closed" — exclude outright.
                if b.get("is_closed"):
                    continue
                coords = b.get("coordinates") or {}
                location = b.get("location") or {}
                all_places.append({
                    "id": b.get("id", ""),
                    "name": b.get("name", ""),
                    "category": cat,
                    "rating": b.get("rating", 0),
                    "review_count": b.get("review_count", 0),
                    "price": b.get("price", ""),
                    "is_open_now": b["id"] in open_ids,
                    "latitude": coords.get("latitude"),
                    "longitude": coords.get("longitude"),
                    "phone": b.get("display_phone", ""),
                    "yelp_url": b.get("url", ""),
                    "image_url": b.get("image_url", ""),
                    "distance_meters": b.get("distance", 0),
                    "address": ", ".join(location.get("display_address", [])),
                })

        # De-dupe by Yelp id — a place can appear under multiple categories (e.g., a
        # museum cafe shows in both Culture and Coffee). Keep the first occurrence.
        seen: set[str] = set()
        deduped: list[dict] = []
        for p in all_places:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            deduped.append(p)

        self._json({"success": True, "places": deduped, "count": len(deduped)})

    def _json(self, payload: dict, code: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # Yelp data doesn't change often — 5 min edge cache keeps real users snappy
        # and dramatically lowers Yelp API burn on repeated opens.
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
