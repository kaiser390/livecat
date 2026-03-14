import Foundation
import os

/// SRT streamer — stub (libsrt not linked; SRT mode unavailable in this build).
///
/// To enable real SRT: add libsrt.xcframework back to project.yml and
/// import libsrt, then restore the full C-API implementation.
final class SRTStreamer: @unchecked Sendable, VideoStreaming {

    private let config: CameraConfig
    private let muxer: UDPStreamer

    init(config: CameraConfig) {
        self.config = config
        self.muxer = UDPStreamer(config: config)
    }

    // MARK: - VideoStreaming

    func start() throws {
        throw SRTError.unavailable
    }

    func write(encodedData: Data, isKeyframe: Bool) {
        // no-op in stub
    }

    func writeAudio(aacData: Data) {
        // no-op in stub
    }

    func stop() {
        Log.streaming.info("[SRT] Stub stopped")
    }

    // MARK: - Error

    enum SRTError: LocalizedError {
        case unavailable

        var errorDescription: String? {
            "SRT: libsrt not linked in this build. Use UDP or UDP+FEC mode."
        }
    }
}
