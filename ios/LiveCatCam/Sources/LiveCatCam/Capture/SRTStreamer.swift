import Foundation
import Network
import os

/// UDP+FEC streamer: wraps UDPStreamer and appends XOR parity packets.
///
/// Every `fecGroupSize` MPEG-TS chunks, one XOR parity chunk is sent.
/// A server-side receiver (live_auto.py) can reconstruct any single lost packet
/// within the group using the parity, eliminating block corruption.
///
/// FEC packet format (188 bytes):
///   [0]    = 0xFE  (FEC marker, not a valid TS sync byte)
///   [1]    = 0xC0  (FEC identifier)
///   [2]    = group_id (0-255, wraps)
///   [3]    = group_size (number of data packets in group)
///   [4..N] = XOR of all data packets in group (188 bytes each)
///
/// For direct OBS connection, use UDPStreamer (UDP mode) instead.
final class SRTStreamer: @unchecked Sendable, VideoStreaming {
    private let config: CameraConfig
    private var connection: NWConnection?
    private var isActive = false

    // FEC state
    private let fecGroupSize = 4        // 4 data + 1 parity per group
    private var fecBuffer: [[UInt8]] = []
    private var groupID: UInt8 = 0

    // Stats
    private var chunksSent: UInt64 = 0
    private var fecPacketsSent: UInt64 = 0

    // Underlying UDP muxer
    private let udpStreamer: UDPStreamer

    init(config: CameraConfig) {
        self.config = config
        self.udpStreamer = UDPStreamer(config: config)
    }

    func start() throws {
        guard !isActive else { return }

        let host = NWEndpoint.Host(config.serverIP)
        let port = NWEndpoint.Port(integerLiteral: UInt16(config.srtPort))
        connection = NWConnection(host: host, port: port, using: .udp)
        connection?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                Log.streaming.info("[FEC] UDP+FEC ready → \(self?.config.serverIP ?? ""):\(self?.config.srtPort ?? 0)")
            case .failed(let error):
                Log.streaming.error("[FEC] Connection failed: \(error)")
                self?.reconnect()
            default: break
            }
        }
        connection?.start(queue: .global(qos: .userInteractive))

        // Also start underlying muxer (we intercept its send)
        // We override write() so we bypass UDPStreamer's send
        try udpStreamer.start()
        isActive = true
        fecBuffer = []
        groupID = 0
        chunksSent = 0
        fecPacketsSent = 0
        Log.streaming.info("[FEC] UDP+FEC streamer started (group=\(self.fecGroupSize))")
    }

    func write(encodedData: Data, isKeyframe: Bool = false) {
        guard isActive, let connection else { return }
        // Build MPEG-TS via UDPStreamer's muxer, then intercept
        // We call UDPStreamer to get MPEG-TS bytes, then send with FEC
        let tsData = udpStreamer.buildTSData(encodedData: encodedData, isKeyframe: isKeyframe)
        sendWithFEC(tsData, over: connection)
    }

    func writeAudio(aacData: Data) {
        guard isActive, let connection else { return }
        let tsData = udpStreamer.buildAudioTSData(aacData: aacData)
        sendWithFEC(tsData, over: connection)
    }

    func stop() {
        isActive = false
        udpStreamer.stop()
        connection?.cancel()
        connection = nil
        Log.streaming.info("[FEC] Stopped. data=\(self.chunksSent) fec=\(self.fecPacketsSent)")
    }

    // MARK: - FEC Send

    private func sendWithFEC(_ tsData: Data, over connection: NWConnection) {
        let maxChunk = 1316  // 7 × 188
        var offset = 0

        while offset < tsData.count {
            let end = min(offset + maxChunk, tsData.count)
            let aligned = offset + ((end - offset) / 188) * 188
            let chunkEnd = aligned > offset ? aligned : end
            let chunk = Array(tsData[offset..<chunkEnd])

            // Send data chunk
            connection.send(content: Data(chunk), completion: .contentProcessed { [weak self] err in
                if let err { Log.streaming.error("[FEC] send error: \(err)") }
                else { self?.chunksSent += 1 }
            })

            // Accumulate for FEC
            fecBuffer.append(chunk)
            if fecBuffer.count >= fecGroupSize {
                sendFECPacket(over: connection)
            }

            offset = chunkEnd
        }
    }

    private func sendFECPacket(over connection: NWConnection) {
        guard !fecBuffer.isEmpty else { return }

        // XOR all chunks in group (pad shorter ones with 0)
        let maxLen = fecBuffer.map(\.count).max() ?? 0
        var parity = [UInt8](repeating: 0, count: maxLen)
        for chunk in fecBuffer {
            for i in 0..<chunk.count { parity[i] ^= chunk[i] }
        }

        // Build FEC packet header (4 bytes) + parity data
        var fecPacket = Data(capacity: 4 + maxLen)
        fecPacket.append(0xFE)                   // FEC marker
        fecPacket.append(0xC0)                   // FEC ID
        fecPacket.append(groupID)                // group ID
        fecPacket.append(UInt8(fecBuffer.count)) // group size
        fecPacket.append(contentsOf: parity)

        connection.send(content: fecPacket, completion: .contentProcessed { [weak self] _ in
            self?.fecPacketsSent += 1
        })

        groupID = groupID &+ 1
        fecBuffer.removeAll(keepingCapacity: true)
    }

    private func reconnect() {
        guard isActive else { return }
        connection?.cancel()
        connection = nil
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { [weak self] in
            try? self?.start()
        }
    }
}
