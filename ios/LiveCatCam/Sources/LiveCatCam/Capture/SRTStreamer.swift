import Foundation
import os
import libsrt

/// SRT streamer using libsrt C API (caller mode).
///
/// Pipeline: VideoEncoder → MPEG-TS muxer (via UDPStreamer) → SRT socket → OBS
///
/// OBS setup: Sources → Media Source → Input: srt://0.0.0.0:9000?mode=listener
final class SRTStreamer: @unchecked Sendable, VideoStreaming {

    private let config: CameraConfig
    private var sock: SRTSOCKET = SRT_INVALID_SOCK
    private var isActive = false
    private let queue = DispatchQueue(label: "com.livecat.srt", qos: .userInteractive)

    // MPEG-TS muxer (reuse UDPStreamer's mux logic, skip its UDP send)
    private let muxer: UDPStreamer

    init(config: CameraConfig) {
        self.config = config
        self.muxer = UDPStreamer(config: config)
    }

    // MARK: - VideoStreaming

    func start() throws {
        guard !isActive else { return }

        srt_startup()

        sock = srt_create_socket()
        guard sock != SRT_INVALID_SOCK else {
            throw SRTError.socketCreate
        }

        // Options
        var latency: Int32 = 200  // ms
        srt_setsockopt(sock, 0, SRTO_RCVLATENCY, &latency, Int32(MemoryLayout<Int32>.size))
        srt_setsockopt(sock, 0, SRTO_PEERLATENCY, &latency, Int32(MemoryLayout<Int32>.size))

        var streamID = "OLiveCam"
        streamID.withUTF8 { ptr in
            _ = srt_setsockopt(sock, 0, SRTO_STREAMID, ptr.baseAddress, Int32(ptr.count))
        }

        // Connect (caller mode)
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(config.srtPort).bigEndian
        inet_pton(AF_INET, config.serverIP, &addr.sin_addr)

        let result = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { saPtr in
                srt_connect(sock, saPtr, Int32(MemoryLayout<sockaddr_in>.size))
            }
        }

        guard result != SRT_ERROR else {
            let errMsg = String(cString: srt_getlasterror_str())
            srt_close(sock)
            sock = SRT_INVALID_SOCK
            throw SRTError.connect(errMsg)
        }

        isActive = true
        Log.streaming.info("[SRT] Connected → \(self.config.serverIP):\(self.config.srtPort)")
    }

    func write(encodedData: Data, isKeyframe: Bool = false) {
        guard isActive, sock != SRT_INVALID_SOCK else { return }
        let tsData = muxer.buildTSData(encodedData: encodedData, isKeyframe: isKeyframe)
        sendSRT(tsData)
    }

    func writeAudio(aacData: Data) {
        guard isActive, sock != SRT_INVALID_SOCK else { return }
        let tsData = muxer.buildAudioTSData(aacData: aacData)
        sendSRT(tsData)
    }

    func stop() {
        guard isActive else { return }
        isActive = false
        if sock != SRT_INVALID_SOCK {
            srt_close(sock)
            sock = SRT_INVALID_SOCK
        }
        srt_cleanup()
        Log.streaming.info("[SRT] Stopped")
    }

    // MARK: - Private

    private func sendSRT(_ data: Data) {
        let maxChunk = 1316  // 7 × 188 bytes, fits in SRT payload
        var offset = 0
        while offset < data.count {
            let end = min(offset + maxChunk, data.count)
            let chunk = Array(data[offset..<end])
            let sent = chunk.withUnsafeBytes { ptr in
                srt_sendmsg(sock, ptr.baseAddress, Int32(chunk.count), -1, 0)
            }
            if sent == SRT_ERROR {
                let errMsg = String(cString: srt_getlasterror_str())
                Log.streaming.error("[SRT] sendmsg error: \(errMsg)")
                reconnect()
                return
            }
            offset = end
        }
    }

    private func reconnect() {
        guard isActive else { return }
        Log.streaming.info("[SRT] Reconnecting...")
        if sock != SRT_INVALID_SOCK {
            srt_close(sock)
            sock = SRT_INVALID_SOCK
        }
        queue.asyncAfter(deadline: .now() + 2) { [weak self] in
            try? self?.start()
        }
    }

    // MARK: - Error

    enum SRTError: LocalizedError {
        case socketCreate
        case connect(String)

        var errorDescription: String? {
            switch self {
            case .socketCreate: return "SRT: Failed to create socket"
            case .connect(let msg): return "SRT: Connect failed — \(msg)"
            }
        }
    }
}
