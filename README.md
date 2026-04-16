# Tarmac API — Vercel Serverless Backend

Python serverless backend for the **Tarmac** iOS app (flight-delay sightseeing planner). Deployed on Vercel, built on `http.server.BaseHTTPRequestHandler` with a thin `requests` dependency. Flight data comes from AviationStack; places from Yelp; per-venue cost + AI plan from OpenRouter (Gemini); logos from Brandfetch.

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api` | `GET` | Flight lookup (AviationStack) |
| `/api/delays` | `GET` | Delayed flights sorted by severity (AviationStack) |
| `/api/nearby` | `GET` | Yelp-backed POIs with real ratings, open-now, photos |
| `/api/place-cost` | `GET` | Per-venue USD + visit-duration estimate via OpenRouter |
| `/api/plan` | `POST` | AI-curated 3-stop layover plan via OpenRouter |
| `/api/brand` | `GET` | Brand logo lookup via Brandfetch |
| `/api/aircraft-history` | `GET` | Every leg the user's tail aircraft has flown today |
| `/api/health` | `GET` | Status + env-var check |

## Project Structure

```
tarmac-api/
├── api/
│   ├── index.py          # /api — flight search (AviationStack)
│   ├── delays.py         # /api/delays — delayed flights, sorted
│   ├── nearby.py         # /api/nearby — Yelp Fusion with parallel open-now diff
│   ├── place-cost.py     # /api/place-cost — OpenRouter USD + visit-minute estimate
│   ├── plan.py           # /api/plan — AI 3-stop layover planner
│   ├── brand.py          # /api/brand — Brandfetch logo lookup
│   ├── aircraft-history.py  # /api/aircraft-history — tail timeline (AvStk)
│   └── health.py         # /api/health — env + endpoint listing
├── vercel.json           # function runtime + CORS headers
├── requirements.txt      # runtime dependencies
├── TarmacAPI.swift       # drop-in SwiftUI client (copy into Xcode)
└── README.md
```

## Deployment

### 1. Environment variables (Vercel → Settings → Environment Variables)

| Variable | Required for | Notes |
|---|---|---|
| `AVIATIONSTACK_API_KEY` | `/api`, `/api/delays`, `/api/aircraft-history` | [aviationstack.com](https://aviationstack.com) |
| `YELP_API_KEY` | `/api/nearby` | [yelp.com/developers](https://www.yelp.com/developers) |
| `OPENROUTER_API_KEY` | `/api/place-cost`, `/api/plan` | [openrouter.ai](https://openrouter.ai) |
| `BRANDFETCH_CLIENT_ID` | `/api/brand` | [brandfetch.com](https://brandfetch.com) |
| `OPENROUTER_PRICE_MODEL` | `/api/place-cost` | override default `google/gemini-3.1-flash-lite-preview` |
| `OPENROUTER_PLAN_MODEL` | `/api/plan` | override default plan model |

### 2. Deploy

```bash
# Vercel CLI
vercel --prod

# or import the repo at vercel.com
```

### 3. Smoke-test

```bash
curl https://your-project.vercel.app/api/health
curl "https://your-project.vercel.app/api?flight=AA100"
curl "https://your-project.vercel.app/api/nearby?lat=28.4312&lon=-81.3081"
curl "https://your-project.vercel.app/api/place-cost?name=Starbucks&category=Coffee&lat=28.5&lon=-81.3"
```

## Endpoint Reference

### `GET /api` — Flight lookup

Calls AviationStack's `/flights` endpoint, normalizes the payload, and injects airport coordinates + IANA timezones server-side (AviationStack returns naive timestamps with a fake `+00:00` offset). Responses cached server-side for 5 min.

| Param | Description | Example |
|---|---|---|
| `flight` | IATA flight code | `AA100` |
| `dep_iata` | Departure airport IATA | `MCO` |
| `arr_iata` | Arrival airport IATA | `LAX` |
| `limit` | Max results (default 10) | `25` |

**Response fields:** flight status, airline name + logo, `scheduled` / `estimated` / `actual` times, delay minutes, **gate, terminal**, airport coordinates, IANA timezone.

### `GET /api/delays` — Delayed flights

| Param | Description | Example |
|---|---|---|
| `dep_iata` | Departure airport | `JFK` |
| `arr_iata` | Arrival airport | `ORD` |
| `limit` | Max (default 25) | `50` |

**Severity buckets:** minor (<30m), moderate (30–59m), significant (60–179m), severe (180m+).

### `GET /api/nearby` — Yelp POIs

Fetches restaurants, coffee, parks, culture, and shopping categories in parallel (10 concurrent Yelp calls, ~8s timeout, 5-min edge cache). For each bucket we fire one unfiltered + one `open_now=true` search and diff the id sets so the client gets accurate per-venue open status.

| Param | Description | Example |
|---|---|---|
| `lat` | Latitude | `28.4312` |
| `lon` | Longitude | `-81.3081` |

**Response:** `{ success, places: [{id, name, category, rating, review_count, price, is_open_now, latitude, longitude, phone, yelp_url, image_url, distance_meters, address}], count }`

### `GET /api/place-cost` — Per-venue price + duration

Calls OpenRouter (Gemini-class model) with a strict JSON prompt to estimate USD + visit-duration for a specific named venue. Clamped to realistic ranges (`$0–250`, `5–240 min`).

| Param | Description |
|---|---|
| `name` | Venue name (required) |
| `category` | Search category context |
| `lat`, `lon` | Coordinates |

**Response:** `{ success, place, estimate: {estimated_usd, min_usd, max_usd, visit_duration_minutes, confidence, model} }`

### `POST /api/plan` — AI 3-stop planner

Picks 3 coherent stops from the candidate list against the user's mood, budget, and time window. Model output is cross-checked against the provided id list to reject hallucinated stops (fewer than 3 valid ids → request fails so the client can fall back).

**Request body:**
```json
{
  "flight": "AA 100",
  "airport": "MCO",
  "time_available": 180,
  "budget": 50,
  "mood": "make-the-most-of-it",
  "places": [
    { "id": "roast-master", "name": "Roast Master Coffee", "category": "Coffee", "cost": 5, "visit_minutes": 10 },
    …
  ]
}
```

**Response:**
```json
{
  "success": true,
  "plan": {
    "plan_title": "Coffee & City Views",
    "why": "Short walk, one caffeine hit, one landmark — fits easily inside the window.",
    "stops": [
      { "id": "roast-master", "name": "Roast Master Coffee", "hype": "Local roaster everyone pretends is a secret." },
      …
    ]
  },
  "model": "google/gemini-3.1-flash-lite-preview"
}
```

### `GET /api/brand` — Logo lookup

| Param | Description |
|---|---|
| `domain` | Business website host (e.g. `starbucks.com`) |

Streams back a PNG from Brandfetch's CDN.

### `GET /api/aircraft-history` — Where's-your-plane timeline

Returns the chain of flights the same physical aircraft (tail) has flown today, ordered chronologically, with the user's flight flagged. Powers the "Where's your plane?" UPS-style tracker on the flight confirmation screen so a delayed user can see exactly where their inbound aircraft has been.

Two-step lookup against AviationStack:

1. `GET /flights?flight_iata=X&flight_date=today` — pull the user's flight, extract `aircraft.registration` + `aircraft.icao24` + `airline.iata`.
2. Paginate `GET /flights?airline_iata=NK&flight_date=today` (offsets 0/100/200/300) and intersect locally by tail. AviationStack's `aircraft_iata` filter only matches aircraft *type* (e.g. `B738`), not the specific registration, so filtering happens server-side here.

| Param | Description | Example |
|---|---|---|
| `flight` | IATA flight code | `NK2411` |

**Response:**
```json
{
  "success": true,
  "aircraft_registration": "N932NK",
  "aircraft_icao24": "AD775D",
  "airline": "NK",
  "leg_count": 2,
  "legs": [
    {
      "flight_iata": "NK2411",
      "airline": "Spirit Airlines",
      "status": "active",
      "from": { "iata": "MCO", "scheduled": "...", "actual": "...", "latitude": 28.43, "longitude": -81.30, "timezone": "America/New_York" },
      "to":   { "iata": "DTW", "scheduled": "...", "actual": null, "latitude": 42.21, "longitude": -83.35, "timezone": "America/Detroit" },
      "delay_minutes": 12,
      "is_user_flight": true
    },
    { "flight_iata": "NK752", "from": { "iata": "DTW" }, "to": { "iata": "BOS" }, "status": "scheduled", "is_user_flight": false }
  ]
}
```

If the aircraft tail isn't published yet (common pre-departure), the endpoint returns a friendly error plus the user's flight as a single-leg fallback so the UI still has something to show.

### `GET /api/health` — Status

Returns `{service, status, timestamp, endpoints}` — a one-line description of every route. Useful as a Vercel smoke-test.

## Xcode Integration

Copy `TarmacAPI.swift` into your Xcode project and update `baseURL`:

```swift
static let baseURL = "https://your-project.vercel.app"
```

The iOS app calls `/api` for flight lookup, `/api/nearby` for POIs, `/api/place-cost` for per-venue estimates, `/api/plan` for the AI planner, and `/api/brand` for logos. See the `tarmac` frontend repo for full client code.

## Tech Stack

- **Runtime:** Python 3.x
- **Dependencies:** `requests` only — everything else is stdlib (`http.server`, `urllib`, `json`, `zoneinfo`)
- **Hosting:** Vercel Serverless Functions (`@vercel/python@4.5.0`, 30s max duration)
- **Caching:** 5-min in-memory server cache for flight endpoints; 5-min edge cache on `/api/nearby`
- **LLM:** OpenRouter (default `google/gemini-3.1-flash-lite-preview`)
- **Timezones:** `zoneinfo.ZoneInfo`
