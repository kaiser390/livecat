import Foundation

struct MetadataMessage: Codable, Sendable {

    // MARK: - Top-level fields

    let camID: String
    let trackingState: String
    let activityScore: Double
    let catPositions: [CatPosition]
    let motorPosition: MotorPosition
    let timestamp: Double
    let cats: [CatInfo]
    let huntSignals: [String]

    // MARK: - Nested types

    struct CatPosition: Codable, Sendable {
        let x: Double
        let y: Double
        let w: Double
        let h: Double
        let confidence: Double
    }

    struct MotorPosition: Codable, Sendable {
        let pan: Double
        let tilt: Double
    }

    struct CatInfo: Codable, Sendable {
        let id: String
        let bbox: [Double]   // [x1, y1, x2, y2]
        let pose: String
        let speed: Double
        let center: [Double]  // [cx, cy]
        let airborneFrames: Int
        let frontLegAngle: Double

        enum CodingKeys: String, CodingKey {
            case id, bbox, pose, speed, center
            case airborneFrames = "airborne_frames"
            case frontLegAngle = "front_leg_angle"
        }
    }

    // MARK: - CodingKeys (match server snake_case)

    enum CodingKeys: String, CodingKey {
        case camID = "cam_id"
        case trackingState = "tracking_state"
        case activityScore = "activity_score"
        case catPositions = "cat_positions"
        case motorPosition = "motor_position"
        case timestamp
        case cats
        case huntSignals = "hunt_signals"
    }
}

// MARK: - Registration message

struct RegistrationMessage: Codable, Sendable {
    let type: String
    let camID: String

    enum CodingKeys: String, CodingKey {
        case type
        case camID = "cam_id"
    }

    static func register(camID: String) -> RegistrationMessage {
        RegistrationMessage(type: "register", camID: camID)
    }
}

struct RegistrationResponse: Codable, Sendable {
    let type: String
    let camID: String?

    enum CodingKeys: String, CodingKey {
        case type
        case camID = "cam_id"
    }
}
