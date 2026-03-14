import Foundation
import Network
import os

/// UDP+FEC streamer: sends MPEG-TS over UDP with XOR parity packets.
///
/// Every `fecGroupSize` chunks, one XOR parity chunk is appended.
/// A server-side receiver (live_auto.py) can reconstruct any single lost
/// packet within the group using the parity, reducing block corruption.
///
/// FEC packet marker: byte[0]=0xFE, byte[1]=0xC0 (not a valid TS sync byte)
final class FECStreamer: @unchecked Sendable, VideoStreaming {
    private let config: CameraConfig
    private var connection: NWConnection?
    private var isActive = false
    private let queue = DispatchQueue(label: "com.livecat.fec", qos: .userInteractive)

    // FEC state — all accessed exclusively on `queue`
    private let fecGroupSize = 2
    private var fecBuffer: [[UInt8]] = []
    private var groupID: UInt8 = 0

    // Stats
    private var chunksSent: UInt64 = 0
    private var fecSent: UInt64 = 0

    // MPEG-TS muxer
    private let muxer: UDPStreamer

    init(config: CameraConfig) {
        self.config = config
        self.muxer = UDPStreamer(config: config)
    }

    // MARK: - VideoStreaming

    func start() throws {
        // Guard + setup must be atomic — but NWConnection init is safe here
        // (start() is called from AppState on MainActor, not re-entrantly)
        guard !isActive else { return }

        let host = NWEndpoint.Host(config.serverIP)
        let port = NWEndpoint.Port(integerLiteral: UInt16(config.srtPort))
        connection = NWConnection(host: host, port: port, using: .udp)
        connection?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                Log.streaming.info("[FEC] Ready → \(self?.config.serverIP ?? ""):\(self?.config.srtPort ?? 0)")
            case .failed(let error):
                Log.streaming.error("[FEC] Failed: \(error)")
                self?.reconnect()
            default: break
            }
        }
        connection?.start(queue: queue)

        // NOTE: muxer is used only for buildTSData/buildAudioTSData — do NOT start() it
        isActive = true
        fecBuffer = []
        groupID = 0
        Log.streaming.info("[FEC] UDP+FEC started (group=\(self.fecGroupSize))")
    }

    func write(encodedData: Data, isKeyframe: Bool = false) {
        queue.async { [self] in
            guard isActive, let connection else { return }
            let tsData = muxer.buildTSData(encodedData: encodedData, isKeyframe: isKeyframe)
            sendWithFEC(tsData, over: connection)
        }
    }

    func writeAudio(aacData: Data) {
        queue.async { [self] in
            guard isActive, let connection else { return }
            let tsData = muxer.buildAudioTSData(aacData: aacData)
            sendWithFEC(tsData, over: connection)
        }
    }

    func stop() {
        queue.sync {
            isActive = false
            connection?.cancel()
            connection = nil
        }
        Log.streaming.info("[FEC] Stopped. data=\(self.chunksSent) fec=\(self.fecSent)")
    }

    // MARK: - FEC (called on queue)

    private func sendWithFEC(_ tsData: Data, over connection: NWConnection) {
        // Precondition: running on `queue`
        let maxChunk = 1316
        var offset = 0
        while offset < tsData.count {
            let end = min(offset + maxChunk, tsData.count)
            let aligned = offset + ((end - offset) / 188) * 188
            let chunkEnd = aligned > offset ? aligned : end
            let chunk = Array(tsData[offset..<chunkEnd])

            connection.send(content: Data(chunk), completion: .contentProcessed { [weak self] _ in
                self?.chunksSent += 1
            })

            fecBuffer.append(chunk)
            if fecBuffer.count >= fecGroupSize {
                sendFECPacket(over: connection)
            }
            offset = chunkEnd
        }
    }

    private func sendFECPacket(over connection: NWConnection) {
        // Precondition: running on `queue`
        guard !fecBuffer.isEmpty else { return }
        let maxLen = fecBuffer.map(\.count).max() ?? 0
        var parity = [UInt8](repeating: 0, count: maxLen)
        for chunk in fecBuffer {
            for i in 0..<chunk.count { parity[i] ^= chunk[i] }
        }
        var packet = Data(capacity: 4 + maxLen)
        packet.append(0xFE); packet.append(0xC0)
        packet.append(groupID); packet.append(UInt8(fecBuffer.count))
        packet.append(contentsOf: parity)
        connection.send(content: packet, completion: .contentProcessed { [weak self] _ in
            self?.fecSent += 1
        })
        groupID = groupID &+ 1
        fecBuffer.removeAll(keepingCapacity: true)
    }

    private func reconnect() {
        // Called from connection stateUpdateHandler (runs on queue)
        guard isActive else { return }
        connection?.cancel()
        connection = nil
        isActive = false  // reset so start() guard passes
        queue.asyncAfter(deadline: .now() + 2) { [weak self] in
            try? self?.start()
        }
    }
}
