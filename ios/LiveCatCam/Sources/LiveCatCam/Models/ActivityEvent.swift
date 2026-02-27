import Foundation

enum ActivityEventType: String, Codable, Sendable {
    case climb
    case jump
    case run
    case interact
    case hunt

    var baseScore: Double {
        switch self {
        case .climb: return 80
        case .jump: return 70
        case .run: return 60
        case .interact: return 90
        case .hunt: return 85
        }
    }

    var cooldownSeconds: TimeInterval { 30 }

    var minimumDuration: TimeInterval {
        switch self {
        case .climb: return 2
        case .jump: return 0.5
        case .run: return 1
        case .interact: return 3
        case .hunt: return 5
        }
    }
}

struct ActivityEvent: Sendable {
    let type: ActivityEventType
    let cameraID: String
    let catIDs: [String]
    let score: Double
    let timestamp: TimeInterval
    let duration: TimeInterval
}
