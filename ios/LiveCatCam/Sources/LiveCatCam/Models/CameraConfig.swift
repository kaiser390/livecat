import Foundation

struct CameraConfig: Codable, Sendable {
    var serverIP: String = "192.168.123.101"
    var camID: String = "CAM-1"
    var srtPort: Int = 9000
    var metadataPort: Int = 8081
    var resolution: Resolution = .hd1080p
    var fps: Int = 30
    var bitrate: Int = 8_000_000
    var streamProtocol: StreamProtocol = .udp

    enum StreamProtocol: String, Codable, Sendable, CaseIterable {
        case udp = "UDP"
        // case fec = "UDP+FEC"  // Reserved — enable when live_auto.py FEC receiver is ready
        case srt = "SRT"

        var description: String {
            switch self {
            case .udp: return "UDP — lowest latency"
            // case .fec: return "UDP+FEC — loss recovery (live_auto.py)"
            case .srt: return "SRT — reliable, best quality"
            }
        }
    }

    enum Resolution: String, Codable, Sendable, CaseIterable {
        case hd720p = "720p"
        case hd1080p = "1080p"

        var width: Int {
            switch self {
            case .hd720p: return 1280
            case .hd1080p: return 1920
            }
        }

        var height: Int {
            switch self {
            case .hd720p: return 720
            case .hd1080p: return 1080
            }
        }
    }

    var srtURL: String {
        "srt://\(serverIP):\(srtPort)?mode=caller"
    }

    var webSocketURL: URL? {
        URL(string: "ws://\(serverIP):\(metadataPort)")
    }

    static let cam1 = CameraConfig(camID: "CAM-1", srtPort: 9000)
    static let cam2 = CameraConfig(camID: "CAM-2", srtPort: 9001)

    // MARK: - Persistence

    private static let storageKey = "LiveCatCameraConfig"

    static func save(_ config: CameraConfig) {
        if let data = try? JSONEncoder().encode(config) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }

    static func load() -> CameraConfig {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let config = try? JSONDecoder().decode(CameraConfig.self, from: data)
        else {
            return CameraConfig()
        }
        return config
    }
}
