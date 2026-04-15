# Tarmac API — Vercel Serverless Backend

Flight data API for the **Tarmac** iOS app, deployed as Python serverless functions on Vercel. Powered by [AviationStack](https://aviationstack.com/) for real-time flight tracking, delays, gates, and terminal info.

## Project Structure

```
tarmac-api/
├── api/
│   ├── index.py        # Main flight search endpoint
│   ├── delays.py       # Delayed flights endpoint (sorted by severity)
│   └── health.py       # Health check / status
├── vercel.json         # Vercel routing & function config
├── requirements.txt    # Python dependencies
├── TarmacAPI.swift     # Drop-in SwiftUI service (for Xcode)
└── README.md
```

## Features

- Real-time flight status (scheduled, active, landed, cancelled, diverted)
- Departure & arrival times with automatic timezone correction
- Delay detection with severity classification (minor / moderate / significant / severe)
- Gate, terminal, and boarding info
- Airport coordinates for 200+ airports worldwide
- CORS-enabled for web and mobile clients

## Deployment

### 1. Get an AviationStack API Key

1. Sign up at [aviationstack.com](https://aviationstack.com/)
2. Copy your API key from the dashboard

### 2. Deploy on Vercel

1. Push this repo to GitHub
2. Go to [vercel.com](https://vercel.com) and import the repo
3. In **Settings → Environment Variables**, add:
   - **Key:** `AVIATIONSTACK_API_KEY`
   - **Value:** Your AviationStack API key
4. Click **Deploy**

### 3. Test the Endpoints

```
https://your-project.vercel.app/api/health
https://your-project.vercel.app/api?flight=AA100
https://your-project.vercel.app/api?dep_iata=JFK
https://your-project.vercel.app/api/delays?dep_iata=ATL
```

## API Endpoints

### `GET /api`
Search flights by flight number or airport code.

| Param       | Description                        | Example  |
|-------------|------------------------------------|----------|
| `flight`    | IATA flight code                   | AA100    |
| `dep_iata`  | Departure airport IATA             | MCO      |
| `arr_iata`  | Arrival airport IATA               | LAX      |
| `limit`     | Max results (default 10)           | 25       |

**Response includes:** flight status, airline name & logo, scheduled/estimated/actual times, delay minutes, gate, terminal, and airport coordinates.

### `GET /api/delays`
Returns only delayed flights, sorted by delay severity.

| Param       | Description              | Example |
|-------------|--------------------------|---------|
| `dep_iata`  | Departure airport IATA   | JFK     |
| `arr_iata`  | Arrival airport IATA     | ORD     |
| `limit`     | Max results (default 25) | 50      |

**Severity levels:** minor (<30 min), moderate (30–59 min), significant (60–179 min), severe (180+ min)

### `GET /api/health`
Service health check — confirms API key configuration and lists available endpoints.

## Xcode Integration

1. Copy `TarmacAPI.swift` into your Xcode project
2. Update `baseURL` with your Vercel deployment URL
3. Use it in any SwiftUI view:

```swift
struct FlightListView: View {
    @StateObject private var api = TarmacAPI()

    var body: some View {
        List(api.flights) { flight in
            VStack(alignment: .leading) {
                Text(flight.flightIata ?? "N/A")
                    .font(.headline)
                Text("\(flight.departure.airport) → \(flight.arrival.airport)")
                    .font(.subheadline)
                if flight.isDelayed {
                    Text("DELAYED")
                        .foregroundColor(.red)
                }
            }
        }
        .task {
            await api.searchFlights(depAirport: "MCO")
        }
    }
}
```

## Tech Stack

- **Runtime:** Python 3.x (stdlib only — no third-party packages)
- **Hosting:** Vercel Serverless Functions
- **Flight Data:** AviationStack REST API
- **Timezone Handling:** `zoneinfo.ZoneInfo` for accurate local time conversion
