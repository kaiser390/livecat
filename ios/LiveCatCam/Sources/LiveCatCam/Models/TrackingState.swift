import Foundation

enum TrackingState: String, Codable, Sendable {
    case idle
    case searching
    case tracking
    case lost

    var serverValue: String { rawValue }
}
