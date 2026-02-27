import Foundation

enum ServerCommand: Sendable {
    case setMode(String)
    case setZoom(Double)
    case gotoPosition(pan: Double, tilt: Double)
    case cameraZoom(factor: Double)
    case cameraFocus(x: Double, y: Double)
    case cameraExposure(x: Double, y: Double)
    case cameraReset
    case unknown(String)
}

struct ServerCommandMessage: Codable, Sendable {
    // Legacy format: {"type":"set_zoom","zoom":2.0}
    let type: String?
    let mode: String?
    let zoom: Double?
    let pan: Double?
    let tilt: Double?
    // PC remote control format: {"cmd":"zoom","factor":2.0}
    let cmd: String?
    let factor: Double?
    let x: Double?
    let y: Double?
}

extension ServerCommand {
    static func parse(from data: Data) -> ServerCommand? {
        guard let msg = try? JSONDecoder().decode(ServerCommandMessage.self, from: data) else {
            return nil
        }

        // PC remote control format: {"cmd":"zoom","factor":2.0}
        if let cmd = msg.cmd {
            switch cmd {
            case "zoom":
                guard let factor = msg.factor else { return nil }
                return .cameraZoom(factor: factor)
            case "focus":
                guard let x = msg.x, let y = msg.y else { return nil }
                return .cameraFocus(x: x, y: y)
            case "exposure":
                guard let x = msg.x, let y = msg.y else { return nil }
                return .cameraExposure(x: x, y: y)
            case "reset":
                return .cameraReset
            default:
                return .unknown(cmd)
            }
        }

        // Legacy format: {"type":"set_zoom","zoom":2.0}
        guard let type = msg.type else { return nil }
        switch type {
        case "set_mode":
            guard let mode = msg.mode else { return nil }
            return .setMode(mode)
        case "set_zoom":
            guard let zoom = msg.zoom else { return nil }
            return .setZoom(zoom)
        case "goto_position":
            guard let pan = msg.pan, let tilt = msg.tilt else { return nil }
            return .gotoPosition(pan: pan, tilt: tilt)
        default:
            return .unknown(type)
        }
    }
}
