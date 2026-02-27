import SwiftUI
import AVFoundation

/// Persistent app settings using @AppStorage
final class AppSettings: ObservableObject {
    static let shared = AppSettings()

    @AppStorage("serverIP") var serverIP: String = "192.168.123.106"
    @AppStorage("udpPort") var udpPort: Int = 9000
    @AppStorage("wsPort") var wsPort: Int = 8081
    @AppStorage("videoQuality") var videoQuality: VideoQuality = .hd1080
    @AppStorage("audioEnabled") var audioEnabled: Bool = true
    @AppStorage("autoReconnect") var autoReconnect: Bool = true

    private init() {}
}

enum VideoQuality: String, CaseIterable {
    case hd720 = "720p"
    case hd1080 = "1080p"

    var width: Int32 {
        switch self {
        case .hd720: return 1280
        case .hd1080: return 1920
        }
    }

    var height: Int32 {
        switch self {
        case .hd720: return 720
        case .hd1080: return 1080
        }
    }

    var bitrate: Int {
        switch self {
        case .hd720: return 3_000_000
        case .hd1080: return 6_000_000
        }
    }

    var preset: AVCaptureSession.Preset {
        switch self {
        case .hd720: return .hd1280x720
        case .hd1080: return .hd1920x1080
        }
    }
}

extension AVCaptureSession.Preset {
    init(quality: VideoQuality) {
        switch quality {
        case .hd720: self = .hd1280x720
        case .hd1080: self = .hd1920x1080
        }
    }
}
