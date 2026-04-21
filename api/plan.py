from http.server import BaseHTTPRequestHandler
import json
import os
import re
import requests
from rate_limit import check_rate_limit


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-3.1-flash-lite-preview"


def _extract_json_object(text):
    """Model output is instructed to be pure JSON, but we tolerate markdown-fenced
    or slightly malformed output so one sloppy token doesn't break the request."""
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
        candidate = re.sub(r",\s*}", "}", candidate)
        candidate = re.sub(r",\s*]", "]", candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None


def _build_prompt(airport, flight, time_available, budget, mood, places):
    # Keep the place list compact — names + ids + cost + visit mins is all the model
    # needs to pick a coherent 3-stop plan. Truncating to ~40 keeps the prompt small
    # even when the client's Yelp result set is large.
    lines = []
    for p in places[:40]:
        name = str(p.get("name", "")).strip()[:80]
        pid = str(p.get("id", "")).strip()[:80]
        cat = str(p.get("category", "")).strip()[:40]
        cost = p.get("cost") or 0
        visit = p.get("visit_minutes") or p.get("visitDurationMinutes") or 30
        if not name or not pid:
            continue
        lines.append(f"- id={pid} | {name} | {cat} | ${cost} | ~{visit} min")
    catalog = "\n".join(lines) if lines else "(no places provided)"

    return (
        "You are planning a short airport-layover excursion. Pick the best 3 stops "
        "from the candidate list that together FIT the time/budget window and tell a "
        "coherent story for the given mood. Return STRICT JSON only.\n\n"
        f"Airport: {airport or 'unknown'}\n"
        f"Flight: {flight or 'unknown'}\n"
        f"Minutes available to explore: {time_available}\n"
        f"Budget (USD): {budget}\n"
        f"Mood / vibe: {mood or 'relaxed'}\n\n"
        "Candidate places (choose exactly 3 distinct ids from this list):\n"
        f"{catalog}\n\n"
        "Schema:\n"
        '{"plan_title": "short punchy name like \'Coffee & City Views\'", '
        '"stops": [{"id": "<exact id from list>", "hype": "one spicy sentence, max 18 words, no emoji"}], '
        '"why": "one sentence explaining why this arc works"}\n'
        "Rules: exactly 3 stops, each id MUST appear in the candidate list, "
        "sum(cost) must not exceed the budget, aim to fit within the time window "
        "(walk/drive ~8 min between stops). Hype lines should reference the specific venue."
    )


def _call_openrouter(key, model, prompt):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output only valid JSON. No markdown, no commentary."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 450,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices from OpenRouter")
    return choices[0].get("message", {}).get("content", "")


def _validate_plan(parsed, places):
    """Cross-check the model's picks against the candidate ids — the LLM occasionally
    hallucinates an id. We keep only real ones and fail the request if fewer than 3
    survive so the client can retry / fall back gracefully."""
    if not isinstance(parsed, dict):
        return None
    stops_raw = parsed.get("stops")
    if not isinstance(stops_raw, list):
        return None

    valid_ids = {str(p.get("id", "")): p for p in places if p.get("id")}
    seen = set()
    clean_stops = []
    for s in stops_raw:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).strip()
        if not sid or sid not in valid_ids or sid in seen:
            continue
        seen.add(sid)
        hype = str(s.get("hype", "")).strip()[:240]
        clean_stops.append({"id": sid, "hype": hype, "name": valid_ids[sid].get("name", "")})

    if len(clean_stops) < 3:
        return None

    return {
        "plan_title": str(parsed.get("plan_title", "Your Tarmac Plan")).strip()[:80],
        "why": str(parsed.get("why", "")).strip()[:240],
        "stops": clean_stops[:3],
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if check_rate_limit(self, max_requests=10):
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 100_000:  # 100 KB max body
            self._json({"success": False, "error": "Request body too large"}, 413)
            return
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"success": False, "error": "Invalid JSON body"}, 400)
            return

        places = body.get("places") or []
        if not isinstance(places, list) or len(places) < 3:
            self._json({"success": False, "error": "Need at least 3 candidate places"}, 400)
            return

        airport = str(body.get("airport", "") or "")[:8]
        flight = str(body.get("flight", "") or "")[:16]
        mood = str(body.get("mood", "") or "")[:60]
        try:
            time_available = int(body.get("time_available") or 180)
            budget = int(body.get("budget") or 50)
        except (TypeError, ValueError):
            time_available, budget = 180, 50
        time_available = max(30, min(720, time_available))
        budget = max(0, min(2000, budget))

        key = os.environ.get("OPENROUTER_API_KEY", "")
        model = os.environ.get("OPENROUTER_PLAN_MODEL", DEFAULT_MODEL)
        if not key:
            self._json({"success": False, "error": "Plan service not configured"}, 503)
            return

        prompt = _build_prompt(airport, flight, time_available, budget, mood, places)
        try:
            content = _call_openrouter(key, model, prompt)
            parsed = _extract_json_object(content)
            plan = _validate_plan(parsed, places)
        except requests.exceptions.RequestException as e:
            self._json({"success": False, "error": f"Plan service error: {e}"}, 502)
            return
        except Exception as e:
            self._json({"success": False, "error": f"Unable to generate plan: {e}"}, 500)
            return

        if not plan:
            self._json({"success": False, "error": "Plan output did not pass validation"}, 502)
            return

        self._json({"success": True, "plan": plan, "model": model})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Plan output is user-specific (mood + budget + live places) — do not cache.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
