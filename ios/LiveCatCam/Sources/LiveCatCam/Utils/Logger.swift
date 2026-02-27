import Foundation
import os

enum Log {
    static let camera = os.Logger(subsystem: "com.livecat.cam", category: "camera")
    static let tracking = os.Logger(subsystem: "com.livecat.cam", category: "tracking")
    static let network = os.Logger(subsystem: "com.livecat.cam", category: "network")
    static let motor = os.Logger(subsystem: "com.livecat.cam", category: "motor")
    static let streaming = os.Logger(subsystem: "com.livecat.cam", category: "streaming")
    static let app = os.Logger(subsystem: "com.livecat.cam", category: "app")
}
