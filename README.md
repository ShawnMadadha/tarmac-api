# Tarmac API — Vercel Serverless Backend

Flight data API for the Tarmac iOS app, deployed as Python serverless functions on Vercel. Powered by [AirLabs](https://airlabs.co/) (1,000 free requests/month).

## Project Structure

```
tarmac-api/
├── api/
│   ├── index.py        # Main flight search endpoint
│   ├── delays.py       # Delayed flights only endpoint
│   └── health.py       # Health check / status
├── vercel.json         # Vercel routing config
├── requirements.txt    # Python dependencies
├── TarmacAPI.swift     # Drop-in SwiftUI service (for Xcode)
└── README.md
```

## Deployment Steps

### 1. Get an AirLabs API Key

1. Sign up at [airlabs.co](https://airlabs.co/) (free)
2. Copy your API key from the dashboard

### 2. Deploy on Vercel

1. Push this repo to GitHub
2. Go to [vercel.com](https://vercel.com) and import the repo
3. In **Settings → Environment Variables**, add:
   - **Key:** `AIRLABS_API_KEY`
   - **Value:** Your AirLabs API key
4. Click **Deploy**

### 3. Test the Endpoints

```
https://your-project.vercel.app/api/health
https://your-project.vercel.app/api?dep_iata=MCO
https://your-project.vercel.app/api?flight=AA100
https://your-project.vercel.app/api/delays?dep_iata=JFK
```

## API Endpoints

### `GET /api`
Search flights with filters.

| Param       | Description                        | Example  |
|-------------|------------------------------------|----------|
| `flight`    | IATA flight code                   | AA100    |
| `dep_iata`  | Departure airport IATA             | MCO      |
| `arr_iata`  | Arrival airport IATA               | LAX      |
| `limit`     | Max results (default 10)           | 25       |

### `GET /api/delays`
Returns only delayed flights, sorted by severity.

| Param       | Description              | Example |
|-------------|--------------------------|---------|
| `dep_iata`  | Departure airport IATA   | JFK     |
| `arr_iata`  | Arrival airport IATA     | ORD     |
| `limit`     | Max results (default 25) | 50      |

### `GET /api/health`
Service health check — confirms if your API key is configured.

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

## Notes

- AirLabs free tier: 1,000 requests/month.
- No third-party Python packages required — uses only stdlib `urllib`.
- CORS headers are included so the API also works from web clients.
