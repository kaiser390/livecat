import Foundation

struct CameraConfig: Codable, Sendable {
    var serverIP: String = "192.168.123.106"
    var camID: String = "CAM-1"
    var srtPort: Int = 9000
    var metadataPort: Int = 8081
    var resolution: Resolution = .hd1080p
    var fps: Int = 30
    var bitrate: Int = 8_000_000

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
}
