import Foundation

// MARK: - Models

struct FlightResponse: Codable {
    let success: Bool
    let count: Int?
    let flights: [Flight]?
    let error: String?
}

struct DelayResponse: Codable {
    let success: Bool
    let count: Int?
    let delayedFlights: [DelayedFlight]?
    let error: String?
    
    enum CodingKeys: String, CodingKey {
        case success, count, error
        case delayedFlights = "delayed_flights"
    }
}

struct Flight: Codable, Identifiable {
    var id: String { flightIata }
    
    let flightIata: String
    let flightIcao: String
    let airline: String
    let status: String
    let departure: AirportInfo
    let arrival: AirportInfo
    let isDelayed: Bool
    
    enum CodingKeys: String, CodingKey {
        case flightIata = "flight_iata"
        case flightIcao = "flight_icao"
        case airline, status, departure, arrival
        case isDelayed = "is_delayed"
    }
}

struct DelayedFlight: Codable, Identifiable {
    var id: String { flightIata }
    
    let flightIata: String
    let airline: String
    let status: String
    let delay: DelayInfo
    let departure: AirportInfo
    let arrival: AirportInfo
    
    enum CodingKeys: String, CodingKey {
        case flightIata = "flight_iata"
        case airline, status, delay, departure, arrival
    }
}

struct AirportInfo: Codable {
    let airport: String
    let iata: String
    let terminal: String?
    let gate: String?
    let scheduled: String?
    let estimated: String?
    let actual: String?
    let delayMinutes: Int?
    
    enum CodingKeys: String, CodingKey {
        case airport, iata, terminal, gate, scheduled, estimated, actual
        case delayMinutes = "delay_minutes"
    }
}

struct DelayInfo: Codable {
    let departureMinutes: Int
    let arrivalMinutes: Int
    let maxMinutes: Int
    let severity: String
    
    enum CodingKeys: String, CodingKey {
        case departureMinutes = "departure_minutes"
        case arrivalMinutes = "arrival_minutes"
        case maxMinutes = "max_minutes"
        case severity
    }
}

// MARK: - API Service

class TarmacAPI: ObservableObject {
    
    // ⚠️ Replace with your actual Vercel deployment URL
    static let baseURL = "https://YOUR-PROJECT.vercel.app"
    
    @Published var flights: [Flight] = []
    @Published var delayedFlights: [DelayedFlight] = []
    @Published var isLoading = false
    @Published var errorMessage: String?
    
    // MARK: - Search Flights
    
    /// Search for flights with optional filters.
    /// - Parameters:
    ///   - flightCode: IATA flight code (e.g., "AA100")
    ///   - depAirport: Departure airport IATA code (e.g., "JFK")
    ///   - arrAirport: Arrival airport IATA code (e.g., "LAX")
    ///   - limit: Max number of results (default 10)
    func searchFlights(
        flightCode: String? = nil,
        depAirport: String? = nil,
        arrAirport: String? = nil,
        limit: Int = 10
    ) async {
        await MainActor.run { isLoading = true; errorMessage = nil }
        
        var components = URLComponents(string: "\(Self.baseURL)/api")!
        var queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        
        if let flight = flightCode, !flight.isEmpty {
            queryItems.append(URLQueryItem(name: "flight", value: flight))
        }
        if let dep = depAirport, !dep.isEmpty {
            queryItems.append(URLQueryItem(name: "dep_iata", value: dep))
        }
        if let arr = arrAirport, !arr.isEmpty {
            queryItems.append(URLQueryItem(name: "arr_iata", value: arr))
        }
        
        components.queryItems = queryItems
        
        guard let url = components.url else {
            await MainActor.run { errorMessage = "Invalid URL"; isLoading = false }
            return
        }
        
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoded = try JSONDecoder().decode(FlightResponse.self, from: data)
            
            await MainActor.run {
                if decoded.success {
                    flights = decoded.flights ?? []
                } else {
                    errorMessage = decoded.error ?? "Unknown error"
                }
                isLoading = false
            }
        } catch {
            await MainActor.run {
                errorMessage = "Network error: \(error.localizedDescription)"
                isLoading = false
            }
        }
    }
    
    // MARK: - Get Delays
    
    /// Fetch only delayed flights, sorted by severity.
    /// - Parameters:
    ///   - depAirport: Filter by departure airport IATA code
    ///   - arrAirport: Filter by arrival airport IATA code
    func fetchDelays(
        depAirport: String? = nil,
        arrAirport: String? = nil
    ) async {
        await MainActor.run { isLoading = true; errorMessage = nil }
        
        var components = URLComponents(string: "\(Self.baseURL)/api/delays")!
        var queryItems: [URLQueryItem] = []
        
        if let dep = depAirport, !dep.isEmpty {
            queryItems.append(URLQueryItem(name: "dep_iata", value: dep))
        }
        if let arr = arrAirport, !arr.isEmpty {
            queryItems.append(URLQueryItem(name: "arr_iata", value: arr))
        }
        
        if !queryItems.isEmpty {
            components.queryItems = queryItems
        }
        
        guard let url = components.url else {
            await MainActor.run { errorMessage = "Invalid URL"; isLoading = false }
            return
        }
        
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoded = try JSONDecoder().decode(DelayResponse.self, from: data)
            
            await MainActor.run {
                if decoded.success {
                    delayedFlights = decoded.delayedFlights ?? []
                } else {
                    errorMessage = decoded.error ?? "Unknown error"
                }
                isLoading = false
            }
        } catch {
            await MainActor.run {
                errorMessage = "Network error: \(error.localizedDescription)"
                isLoading = false
            }
        }
    }
}
