from http.server import BaseHTTPRequestHandler
import json
import os
import re
import requests
from urllib.parse import urlparse, parse_qs


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-3.1-flash-lite-preview"


def _extract_json_object(text):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Sometimes model output includes trailing commas/newlines; best-effort cleanup.
        candidate = re.sub(r",\s*}", "}", candidate)
        candidate = re.sub(r",\s*]", "]", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


def _clamp_cost(value):
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return min(250, max(0, numeric))


def _clamp_visit_minutes(value):
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    # Layover escape: quick stops vs museums; cap at 4h for a single stop guess.
    return min(240, max(5, numeric))


def _estimate_place(openrouter_key, model, place_name, category, latitude, longitude):
    prompt = (
        "For this **specific named venue** (exact business name + rough location), estimate:\n"
        "1) Typical spend in USD for ONE person (one visit).\n"
        "2) Typical time in minutes a traveler would spend there on an airport layover "
        "(in-and-out visit, not a full vacation day).\n\n"
        f"Venue name: {place_name}\n"
        f"Search/category context: {category or 'unknown'}\n"
        f"Latitude: {latitude or 'unknown'}\n"
        f"Longitude: {longitude or 'unknown'}\n\n"
        "Return ONLY strict JSON with this schema:\n"
        '{"min_usd": number, "max_usd": number, "estimated_usd": number, '
        '"visit_duration_minutes": number, "confidence": "low"|"medium"|"high"}\n'
        "Rules: min_usd <= estimated_usd <= max_usd, all non-negative, realistic for that venue. "
        "If the venue is free (e.g. many parks), use 0 for USD fields. "
        "visit_duration_minutes: integer 5–240, realistic for this venue type "
        "(e.g. coffee grab ~10–20, sit-down meal ~30–60, large museum ~60–120)."
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You output only valid JSON with numeric fields. No markdown."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 220
    }

    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=20)
    response.raise_for_status()
    data = response.json()

    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices returned by OpenRouter")

    message = choices[0].get("message", {})
    content = message.get("content", "")
    parsed = _extract_json_object(content)
    if not parsed:
        raise ValueError("Model output did not contain valid JSON")

    estimated = _clamp_cost(parsed.get("estimated_usd"))
    min_usd = _clamp_cost(parsed.get("min_usd"))
    max_usd = _clamp_cost(parsed.get("max_usd"))
    confidence = parsed.get("confidence", "low")
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"

    if estimated is None and min_usd is not None and max_usd is not None:
        estimated = int(round((min_usd + max_usd) / 2))
    if estimated is None:
        raise ValueError("Estimated cost missing from model output")

    if min_usd is None:
        min_usd = max(0, estimated - 5)
    if max_usd is None:
        max_usd = estimated + 5

    if min_usd > max_usd:
        min_usd, max_usd = max_usd, min_usd
    estimated = min(max(estimated, min_usd), max_usd)

    visit_min = _clamp_visit_minutes(parsed.get("visit_duration_minutes"))
    if visit_min is None:
        visit_min = 30

    return {
        "estimated_usd": estimated,
        "min_usd": min_usd,
        "max_usd": max_usd,
        "visit_duration_minutes": visit_min,
        "confidence": confidence,
        "model": model,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        model = os.environ.get("OPENROUTER_PRICE_MODEL", DEFAULT_MODEL)
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        place_name = (params.get("name", [""])[0] or "").strip()[:200]
        category = (params.get("category", [""])[0] or "").strip()[:100]
        latitude = (params.get("lat", [""])[0] or "").strip()[:20]
        longitude = (params.get("lon", [""])[0] or "").strip()[:20]

        if not place_name:
            result = {"success": False, "error": "Query param 'name' is required."}
        elif not openrouter_key:
            result = {"success": False, "error": "Service temporarily unavailable."}
        else:
            try:
                estimate = _estimate_place(
                    openrouter_key=openrouter_key,
                    model=model,
                    place_name=place_name,
                    category=category,
                    latitude=latitude,
                    longitude=longitude,
                )
                result = {"success": True, "place": place_name, "estimate": estimate}
            except requests.exceptions.RequestException:
                result = {"success": False, "error": "Estimation service temporarily unavailable."}
            except Exception:
                result = {"success": False, "error": "Unable to generate estimate."}

        self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
        return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        return
