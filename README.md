# Tarmac API — Vercel Serverless Backend

Flight data API for the Tarmac iOS app, deployed as Python serverless functions on Vercel.

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

### 1. Create a GitHub Repo

```bash
cd tarmac-api
git init
git add .
git commit -m "Initial Tarmac API"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/tarmac-api.git
git push -u origin main
```

### 2. Deploy on Vercel

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub
2. Click **"Add New Project"** → Import your `tarmac-api` repo
3. Vercel auto-detects the Python functions — just click **Deploy**

### 3. Set Your API Key

1. In Vercel dashboard → your project → **Settings** → **Environment Variables**
2. Add:
   - **Key:** `AVIATION_API_KEY`
   - **Value:** Your AviationStack API key
3. **Redeploy** (Deployments tab → click the 3 dots → Redeploy)

### 4. Test the Endpoints

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
| `airline`   | Airline name                       | Delta    |
| `status`    | Flight status                      | active   |
| `limit`     | Max results (default 10)           | 25       |

### `GET /api/delays`
Returns only delayed flights, sorted by severity.

| Param       | Description              | Example |
|-------------|--------------------------|---------|
| `dep_iata`  | Departure airport IATA   | JFK     |
| `arr_iata`  | Arrival airport IATA     | ORD     |
| `limit`     | Max results (default 25) | 50      |

### `GET /api/health`
Service health check — also confirms if your API key is configured.

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
                Text(flight.flightIata)
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

- AviationStack free tier: 100 requests/month. Consider caching.
- `pandas` was removed from requirements — not needed for JSON responses.
- CORS headers are included so the API also works from web clients.
