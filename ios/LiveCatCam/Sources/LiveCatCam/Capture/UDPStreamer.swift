import Foundation
import Network
import os

/// Streams H.264 video to the server via MPEG-TS over UDP.
///
/// Pipeline: VideoEncoder (Annex-B H.264) → MPEG-TS muxer → UDP packets
final class UDPStreamer: @unchecked Sendable, VideoStreaming {
    private let config: CameraConfig
    private var connection: NWConnection?
    private var isActive = false

    // MPEG-TS state
    private var patCc: UInt8 = 0
    private var pmtCc: UInt8 = 0
    private var videoCc: UInt8 = 0
    private var audioCc: UInt8 = 0
    private var packetsSent: UInt64 = 0
    private var bytesSent: UInt64 = 0
    private var frameCount: UInt64 = 0
    private var audioFrameCount: UInt64 = 0
    private let startTime = CFAbsoluteTimeGetCurrent()

    // Constants
    private let tsPacketSize = 188
    private let patPid: UInt16 = 0x0000
    private let pmtPid: UInt16 = 0x1000
    private let videoPid: UInt16 = 0x0100
    private let audioPid: UInt16 = 0x0101
    private let h264StreamType: UInt8 = 0x1B
    private let aacStreamType: UInt8 = 0x0F

    init(config: CameraConfig) {
        self.config = config
    }

    func start() throws {
        guard !isActive else { return }

        let host = NWEndpoint.Host(config.serverIP)
        let port = NWEndpoint.Port(integerLiteral: UInt16(config.srtPort))

        connection = NWConnection(host: host, port: port, using: .udp)

        connection?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                Log.streaming.info("UDP connection ready → \(self?.config.serverIP ?? "unknown"):\(self?.config.srtPort ?? 0)")
            case .failed(let error):
                Log.streaming.error("UDP connection failed: \(error)")
                self?.reconnect()
            case .cancelled:
                Log.streaming.info("UDP connection cancelled")
            default:
                break
            }
        }

        connection?.start(queue: .global(qos: .userInteractive))
        isActive = true
        packetsSent = 0
        bytesSent = 0
        frameCount = 0

        // Reset continuity counters
        patCc = 0
        pmtCc = 0
        videoCc = 0
        audioCc = 0
        audioFrameCount = 0

        Log.streaming.info("MPEG-TS/UDP streamer started → \(self.config.serverIP):\(self.config.srtPort)")
    }

    /// Build MPEG-TS data for a video frame (used by SRTStreamer FEC wrapper)
    func buildTSData(encodedData: Data, isKeyframe: Bool) -> Data {
        var tsData = Data()
        tsData.append(buildPAT())
        tsData.append(buildPMT())
        let elapsed = CFAbsoluteTimeGetCurrent() - startTime
        let pts = UInt64(elapsed * 90000)
        tsData.append(buildPES(from: encodedData, pts: pts, isKeyframe: isKeyframe))
        frameCount += 1
        return tsData
    }

    /// Build MPEG-TS data for an audio frame (used by SRTStreamer FEC wrapper)
    func buildAudioTSData(aacData: Data) -> Data {
        let elapsed = CFAbsoluteTimeGetCurrent() - startTime
        let pts = UInt64(elapsed * 90000)
        var pesPacket = Data()
        pesPacket.append(contentsOf: [0x00, 0x00, 0x01])
        pesPacket.append(0xC0)
        let pesLen = UInt16(min(3 + 5 + aacData.count, 65535))
        pesPacket.append(UInt8((pesLen >> 8) & 0xFF))
        pesPacket.append(UInt8(pesLen & 0xFF))
        pesPacket.append(0x80); pesPacket.append(0x80); pesPacket.append(0x05)
        pesPacket.append(encodePTS(pts: pts))
        pesPacket.append(aacData)
        audioFrameCount += 1
        return muxIntoTS(pesData: pesPacket, pid: audioPid, isKeyframe: false, cc: &audioCc)
    }

    func write(encodedData: Data, isKeyframe: Bool = false) {
        guard isActive, let connection else { return }

        // Build MPEG-TS packets
        var tsData = Data()

        // Send PAT + PMT on EVERY frame (376 bytes overhead, negligible vs video)
        // This ensures any receiver can join the stream at any point
        let pat = buildPAT()
        let pmt = buildPMT()
        tsData.append(pat)
        tsData.append(pmt)

        // Verify PAT/PMT integrity
        if frameCount == 0 || frameCount % 60 == 0 {
            Log.streaming.info("[MUX] PAT sync=0x\(String(pat[0], radix:16)) PID=0x\(String(format:"%02X%02X", pat[1], pat[2]))")
            Log.streaming.info("[MUX] PMT sync=0x\(String(pmt[0], radix:16)) PID=0x\(String(format:"%02X%02X", pmt[1], pmt[2]))")
        }

        // Calculate PTS (90kHz clock)
        let elapsed = CFAbsoluteTimeGetCurrent() - startTime
        let pts = UInt64(elapsed * 90000)

        // Scan input H.264 data for NAL types (debug)
        if isKeyframe || frameCount % 60 == 0 {
            var nalTypes: [UInt8] = []
            var scanOff = 0
            let bytes = [UInt8](encodedData)
            while scanOff < bytes.count - 4 {
                if bytes[scanOff] == 0 && bytes[scanOff+1] == 0 && bytes[scanOff+2] == 0 && bytes[scanOff+3] == 1 {
                    if scanOff + 4 < bytes.count {
                        nalTypes.append(bytes[scanOff+4] & 0x1F)
                    }
                    scanOff += 4
                } else {
                    scanOff += 1
                }
            }
            let names = nalTypes.map { t -> String in
                switch t { case 1: return "P"; case 5: return "IDR"; case 6: return "SEI"; case 7: return "SPS"; case 8: return "PPS"; default: return "\(t)" }
            }
            Log.streaming.info("[MUX] frame#\(self.frameCount) key=\(isKeyframe) inputNALs=\(names) inputSize=\(encodedData.count)B")
        }

        // Mux H.264 NAL units into PES → TS packets
        let pesPackets = buildPES(from: encodedData, pts: pts, isKeyframe: isKeyframe)
        tsData.append(pesPackets)

        frameCount += 1

        // Debug: log TS packet composition periodically
        if frameCount <= 3 || frameCount % 60 == 0 {
            let tsPacketCount = tsData.count / tsPacketSize
            var pidCounts: [UInt16: Int] = [:]
            for i in 0..<tsPacketCount {
                let base = i * tsPacketSize
                if tsData[base] == 0x47 {
                    let pid = (UInt16(tsData[base+1] & 0x1F) << 8) | UInt16(tsData[base+2])
                    pidCounts[pid, default: 0] += 1
                }
            }
            let pidInfo = pidCounts.map { "0x\(String(format:"%04X", $0.key)):\($0.value)" }.joined(separator: " ")
            Log.streaming.info("[MUX] frame#\(self.frameCount) totalTS=\(tsPacketCount) PIDs=[\(pidInfo)] totalBytes=\(tsData.count)")
        }

        // Send over UDP
        sendChunks(tsData, over: connection)

        // Log send stats periodically
        if frameCount <= 3 || frameCount % 300 == 0 {
            Log.streaming.info("[MUX] Stats: sent=\(self.packetsSent)pkts \(self.bytesSent)B vFrames=\(self.frameCount) aFrames=\(self.audioFrameCount)")
        }
    }

    func stop() {
        isActive = false
        connection?.cancel()
        connection = nil
        Log.streaming.info("MPEG-TS/UDP streamer stopped. Sent \(self.packetsSent) packets, \(self.bytesSent) bytes")
    }

    // MARK: - MPEG-TS Packet Construction

    /// Build a PAT (Program Association Table)
    private func buildPAT() -> Data {
        var packet = Data(count: tsPacketSize)
        packet[0] = 0x47  // Sync byte
        packet[1] = 0x40  // PUSI=1, PID high=0
        packet[2] = 0x00  // PID low=0 (PAT)
        packet[3] = 0x10 | (patCc & 0x0F)  // No adaptation, payload only
        patCc = (patCc + 1) & 0x0F

        // PAT payload
        var offset = 4
        packet[offset] = 0x00  // Pointer field
        offset += 1

        // Table header
        packet[offset] = 0x00  // Table ID (PAT)
        offset += 1

        let sectionLength: UInt16 = 13  // Fixed for single program
        packet[offset] = 0xB0 | UInt8((sectionLength >> 8) & 0x0F)
        offset += 1
        packet[offset] = UInt8(sectionLength & 0xFF)
        offset += 1

        // Transport stream ID
        packet[offset] = 0x00; offset += 1
        packet[offset] = 0x01; offset += 1

        // Version, current
        packet[offset] = 0xC1; offset += 1

        // Section number, last section
        packet[offset] = 0x00; offset += 1
        packet[offset] = 0x00; offset += 1

        // Program 1 → PMT PID
        packet[offset] = 0x00; offset += 1  // Program number high
        packet[offset] = 0x01; offset += 1  // Program number low
        packet[offset] = 0xE0 | UInt8((pmtPid >> 8) & 0x1F); offset += 1
        packet[offset] = UInt8(pmtPid & 0xFF); offset += 1

        // CRC32
        let crc = crc32mpeg(data: packet, from: 5, length: offset - 5)
        packet[offset] = UInt8((crc >> 24) & 0xFF); offset += 1
        packet[offset] = UInt8((crc >> 16) & 0xFF); offset += 1
        packet[offset] = UInt8((crc >> 8) & 0xFF); offset += 1
        packet[offset] = UInt8(crc & 0xFF); offset += 1

        // Fill rest with 0xFF
        for i in offset..<tsPacketSize {
            packet[i] = 0xFF
        }

        return packet
    }

    /// Build a PMT (Program Map Table)
    private func buildPMT() -> Data {
        var packet = Data(count: tsPacketSize)
        packet[0] = 0x47  // Sync byte
        packet[1] = 0x40 | UInt8((pmtPid >> 8) & 0x1F)  // PUSI=1
        packet[2] = UInt8(pmtPid & 0xFF)
        packet[3] = 0x10 | (pmtCc & 0x0F)
        pmtCc = (pmtCc + 1) & 0x0F

        var offset = 4
        packet[offset] = 0x00  // Pointer field
        offset += 1

        // Table header
        packet[offset] = 0x02  // Table ID (PMT)
        offset += 1

        let sectionLength: UInt16 = 23  // 18 + 5 for audio stream entry
        packet[offset] = 0xB0 | UInt8((sectionLength >> 8) & 0x0F)
        offset += 1
        packet[offset] = UInt8(sectionLength & 0xFF)
        offset += 1

        // Program number
        packet[offset] = 0x00; offset += 1
        packet[offset] = 0x01; offset += 1

        // Version, current
        packet[offset] = 0xC1; offset += 1

        // Section number, last section
        packet[offset] = 0x00; offset += 1
        packet[offset] = 0x00; offset += 1

        // PCR PID
        packet[offset] = 0xE0 | UInt8((videoPid >> 8) & 0x1F); offset += 1
        packet[offset] = UInt8(videoPid & 0xFF); offset += 1

        // Program info length = 0
        packet[offset] = 0xF0; offset += 1
        packet[offset] = 0x00; offset += 1

        // Stream 1: H.264 video
        packet[offset] = h264StreamType; offset += 1
        packet[offset] = 0xE0 | UInt8((videoPid >> 8) & 0x1F); offset += 1
        packet[offset] = UInt8(videoPid & 0xFF); offset += 1
        packet[offset] = 0xF0; offset += 1  // ES info length = 0
        packet[offset] = 0x00; offset += 1

        // Stream 2: AAC audio
        packet[offset] = aacStreamType; offset += 1
        packet[offset] = 0xE0 | UInt8((audioPid >> 8) & 0x1F); offset += 1
        packet[offset] = UInt8(audioPid & 0xFF); offset += 1
        packet[offset] = 0xF0; offset += 1  // ES info length = 0
        packet[offset] = 0x00; offset += 1

        // CRC32
        let crc = crc32mpeg(data: packet, from: 5, length: offset - 5)
        packet[offset] = UInt8((crc >> 24) & 0xFF); offset += 1
        packet[offset] = UInt8((crc >> 16) & 0xFF); offset += 1
        packet[offset] = UInt8((crc >> 8) & 0xFF); offset += 1
        packet[offset] = UInt8(crc & 0xFF); offset += 1

        // Fill rest with 0xFF
        for i in offset..<tsPacketSize {
            packet[i] = 0xFF
        }

        return packet
    }

    /// Build PES packets from H.264 Annex-B data, then wrap in TS packets
    private func buildPES(from h264Data: Data, pts: UInt64, isKeyframe: Bool) -> Data {
        // PES header for video
        var pesPacket = Data()

        // PES start code
        pesPacket.append(contentsOf: [0x00, 0x00, 0x01])

        // Stream ID (video)
        pesPacket.append(0xE0)

        // PES packet length (0 = unbounded for video)
        pesPacket.append(contentsOf: [0x00, 0x00])

        // PES header flags: data_alignment_indicator=1
        pesPacket.append(0x84)  // 10 0 0 0 1 00 — MPEG-2, data alignment

        // PTS flag set
        pesPacket.append(0x80)  // PTS only (10 00 0000)

        // PES header data length = 5 (PTS is 5 bytes)
        pesPacket.append(0x05)

        // PTS (5 bytes, 33-bit value in special encoding)
        pesPacket.append(encodePTS(pts: pts))

        // PES payload = H.264 data
        pesPacket.append(h264Data)

        // Now split PES into 188-byte TS packets
        return muxIntoTS(pesData: pesPacket, pid: videoPid, isKeyframe: isKeyframe, cc: &videoCc)
    }

    /// Write AAC audio data (ADTS frame) into MPEG-TS and send via UDP
    func writeAudio(aacData: Data) {
        guard isActive, let connection else { return }

        // Calculate audio PTS (90kHz clock)
        let elapsed = CFAbsoluteTimeGetCurrent() - startTime
        let pts = UInt64(elapsed * 90000)

        // Build audio PES
        var pesPacket = Data()
        pesPacket.append(contentsOf: [0x00, 0x00, 0x01])  // PES start code
        pesPacket.append(0xC0)  // Stream ID: audio stream 0

        // PES packet length (audio frames are small enough to specify length)
        let pesPayloadLen = 3 + 5 + aacData.count  // flags(1) + pts_flags(1) + header_len(1) + PTS(5) + data
        let pesLen = UInt16(min(pesPayloadLen, 65535))
        pesPacket.append(UInt8((pesLen >> 8) & 0xFF))
        pesPacket.append(UInt8(pesLen & 0xFF))

        pesPacket.append(0x80)  // MPEG-2, no alignment needed for audio
        pesPacket.append(0x80)  // PTS only
        pesPacket.append(0x05)  // PES header data length = 5

        pesPacket.append(encodePTS(pts: pts))
        pesPacket.append(aacData)

        // Mux into TS packets
        let tsData = muxIntoTS(pesData: pesPacket, pid: audioPid, isKeyframe: false, cc: &audioCc)

        audioFrameCount += 1

        // Send over UDP
        sendChunks(tsData, over: connection)
    }

    /// Encode a 33-bit PTS into the 5-byte MPEG-TS format
    private func encodePTS(pts: UInt64) -> Data {
        var data = Data(count: 5)
        let pts33 = pts & 0x1FFFFFFFF  // 33-bit

        // Format: 0010 xxx1 | xxxxxxxx | xxxxxxx1 | xxxxxxxx | xxxxxxx1
        data[0] = 0x21 | (UInt8((pts33 >> 29) & 0x0E))          // 0010 [32..30] 1
        data[1] = UInt8((pts33 >> 22) & 0xFF)                     // [29..22]
        data[2] = UInt8((pts33 >> 14) & 0xFE) | 0x01              // [21..15] 1
        data[3] = UInt8((pts33 >> 7) & 0xFF)                      // [14..7]
        data[4] = UInt8((pts33 << 1) & 0xFE) | 0x01               // [6..0] 1

        return data
    }

    /// Split PES data into TS packets
    private func muxIntoTS(pesData: Data, pid: UInt16, isKeyframe: Bool, cc: inout UInt8) -> Data {
        var result = Data()
        var offset = 0
        var first = true

        while offset < pesData.count {
            var packet = Data(count: tsPacketSize)
            packet[0] = 0x47  // Sync byte

            // PID + PUSI
            if first {
                packet[1] = 0x40 | UInt8((pid >> 8) & 0x1F)  // PUSI=1
            } else {
                packet[1] = UInt8((pid >> 8) & 0x1F)
            }
            packet[2] = UInt8(pid & 0xFF)

            let payloadSize = tsPacketSize - 4  // 184
            let remaining = pesData.count - offset

            if first && isKeyframe {
                // First packet of keyframe: add adaptation field with RAI + PCR
                let pcrValue = UInt64((CFAbsoluteTimeGetCurrent() - startTime) * 90000)
                let adaptLen = 8  // 1 flags + 6 PCR + 1 stuffing
                let payloadRoom = tsPacketSize - 4 - 1 - adaptLen  // 188 - 4 - 1 - 8 = 175

                packet[3] = 0x30 | (cc & 0x0F)  // adaptation + payload
                cc = (cc + 1) & 0x0F

                packet[4] = UInt8(adaptLen)  // adaptation_field_length
                packet[5] = 0x50  // RAI=1 (0x40) + PCR_flag=1 (0x10)

                // PCR (6 bytes): 33-bit base + 6 reserved + 9-bit extension
                let pcrBase = pcrValue & 0x1FFFFFFFF
                packet[6] = UInt8((pcrBase >> 25) & 0xFF)
                packet[7] = UInt8((pcrBase >> 17) & 0xFF)
                packet[8] = UInt8((pcrBase >> 9) & 0xFF)
                packet[9] = UInt8((pcrBase >> 1) & 0xFF)
                packet[10] = UInt8((pcrBase & 1) << 7) | 0x7E  // 1 bit base + 6 reserved bits
                packet[11] = 0x00  // 9-bit extension = 0

                // Stuffing
                packet[12] = 0xFF

                let copyLen = min(remaining, payloadRoom)
                let payloadStart = 4 + 1 + adaptLen
                packet.replaceSubrange(payloadStart..<(payloadStart + copyLen),
                                      with: pesData[offset..<(offset + copyLen)])
                // Fill any remaining space
                for i in (payloadStart + copyLen)..<tsPacketSize {
                    packet[i] = 0xFF
                }
                offset += copyLen
                first = false
            } else if remaining >= payloadSize {
                // Full payload
                packet[3] = 0x10 | (cc & 0x0F)
                cc = (cc + 1) & 0x0F
                packet.replaceSubrange(4..<tsPacketSize, with: pesData[offset..<(offset + payloadSize)])
                offset += payloadSize
                first = false
            } else {
                // Need adaptation field for stuffing
                // Layout: [4 TS header][1 adapt_len][1 flags][N stuffing][remaining payload] = 188
                let stuffingLength = payloadSize - remaining - 2  // -2 for adapt_len + flags bytes
                if stuffingLength >= 0 {
                    packet[3] = 0x30 | (cc & 0x0F)  // adaptation + payload
                    cc = (cc + 1) & 0x0F
                    packet[4] = UInt8(stuffingLength + 1)  // adaptation_field_length (includes flags)
                    packet[5] = 0x00  // flags
                    for i in 0..<stuffingLength {
                        packet[6 + i] = 0xFF
                    }
                    let headerLen = 6 + stuffingLength
                    packet.replaceSubrange(headerLen..<(headerLen + remaining),
                                          with: pesData[offset..<(offset + remaining)])
                } else {
                    // remaining is 183 or 184
                    packet[3] = 0x10 | (cc & 0x0F)
                    cc = (cc + 1) & 0x0F
                    packet.replaceSubrange(4..<(4 + remaining), with: pesData[offset..<(offset + remaining)])
                    for i in (4 + remaining)..<tsPacketSize {
                        packet[i] = 0xFF
                    }
                }
                offset = pesData.count
                first = false
            }

            result.append(packet)
        }

        return result
    }

    /// Send TS data over UDP, split into MTU-safe chunks
    private func sendChunks(_ tsData: Data, over connection: NWConnection) {
        let maxUDPPayload = 1316  // 7 TS packets * 188 bytes
        var sendOffset = 0
        while sendOffset < tsData.count {
            let chunkEnd = min(sendOffset + maxUDPPayload, tsData.count)
            let alignedEnd = sendOffset + ((chunkEnd - sendOffset) / tsPacketSize) * tsPacketSize
            let end = alignedEnd > sendOffset ? alignedEnd : chunkEnd

            let chunk = tsData[sendOffset..<end]
            connection.send(content: chunk, completion: .contentProcessed { [weak self] error in
                if let error {
                    Log.streaming.error("UDP send error: \(error)")
                } else if let self {
                    self.packetsSent += 1
                    self.bytesSent += UInt64(chunk.count)
                }
            })
            sendOffset = end
        }
    }

    // MARK: - CRC32 for MPEG-TS

    private func crc32mpeg(data: Data, from start: Int, length: Int) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for i in start..<(start + length) {
            let byte = data[i]
            for bit in 0..<8 {
                let msb = (crc >> 31) & 1
                crc <<= 1
                if ((UInt32(byte) >> (7 - bit)) & 1) ^ msb == 1 {
                    crc ^= 0x04C11DB7
                }
            }
        }
        return crc
    }

    // MARK: - Reconnection

    private func reconnect() {
        guard isActive else { return }
        Log.streaming.info("Reconnecting UDP...")
        connection?.cancel()
        connection = nil
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) { [weak self] in
            try? self?.start()
        }
    }
}
