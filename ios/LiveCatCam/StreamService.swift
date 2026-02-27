import Foundation
import AVFoundation
import VideoToolbox
import Network

/// MPEG-TS muxer + UDP sender.
/// Encodes raw video via VTCompressionSession (H.264) and muxes into
/// 188-byte MPEG-TS packets with PAT/PMT/PES, then sends over UDP.
final class StreamService {
    // MARK: - Constants

    private static let tsPacketSize = 188
    private static let patPID: UInt16 = 0x0000
    private static let pmtPID: UInt16 = 0x1000  // 4096
    private static let videoPID: UInt16 = 0x0100 // 256
    private static let audioPID: UInt16 = 0x0101 // 257

    // MARK: - State

    private var udpConnection: NWConnection?
    private var compressionSession: VTCompressionSession?
    private let sendQueue = DispatchQueue(label: "com.livecatcam.stream")

    private var videoContinuityCounter: UInt8 = 0
    private var audioContinuityCounter: UInt8 = 0
    private var patContinuityCounter: UInt8 = 0
    private var pmtContinuityCounter: UInt8 = 0
    private var frameCount: UInt64 = 0
    private var lastSPSPPS: (sps: Data, pps: Data)?

    private(set) var isConnected = false
    var bitrate: Int = 6_000_000

    // MARK: - Connect / Disconnect

    func connect(host: String, port: UInt16) {
        let endpoint = NWEndpoint.hostPort(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!
        )
        let params = NWParameters.udp
        params.allowLocalEndpointReuse = true

        udpConnection = NWConnection(to: endpoint, using: params)
        udpConnection?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                self?.isConnected = true
            case .failed, .cancelled:
                self?.isConnected = false
            default:
                break
            }
        }
        udpConnection?.start(queue: sendQueue)
        isConnected = true
    }

    func disconnect() {
        udpConnection?.cancel()
        udpConnection = nil
        isConnected = false
        destroyCompressor()
        resetCounters()
    }

    private func resetCounters() {
        videoContinuityCounter = 0
        audioContinuityCounter = 0
        patContinuityCounter = 0
        pmtContinuityCounter = 0
        frameCount = 0
        lastSPSPPS = nil
    }

    // MARK: - H.264 Hardware Encoder

    func setupCompressor(width: Int32, height: Int32, bitrate: Int) {
        self.bitrate = bitrate
        destroyCompressor()

        var session: VTCompressionSession?
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: width, height: height,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: nil,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputHandler: { [weak self] status, flags, sampleBuffer in
                guard status == noErr, let sampleBuffer else { return }
                self?.handleEncodedFrame(sampleBuffer)
            },
            compressionSessionOut: &session
        )

        guard status == noErr, let session else { return }

        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ProfileLevel,
                             value: kVTProfileLevel_H264_Main_AutoLevel)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AverageBitRate,
                             value: bitrate as CFNumber)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameInterval,
                             value: 60 as CFNumber) // IDR every 2s at 30fps
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AllowFrameReordering,
                             value: kCFBooleanFalse) // No B-frames for low latency
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_H264EntropyMode,
                             value: kVTH264EntropyMode_CABAC)

        // Data rate limits: [bytes per second, seconds]
        let limits: [Int] = [bitrate / 8 * 2, 1]
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_DataRateLimits,
                             value: limits as CFArray)

        VTCompressionSessionPrepareToEncodeFrames(session)
        compressionSession = session
    }

    private func destroyCompressor() {
        if let session = compressionSession {
            VTCompressionSessionInvalidate(session)
            compressionSession = nil
        }
    }

    // MARK: - Encode Video Frame

    func encodeVideoFrame(_ sampleBuffer: CMSampleBuffer) {
        guard let session = compressionSession,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let duration = CMSampleBufferGetDuration(sampleBuffer)

        // Force IDR every 60 frames
        var properties: CFDictionary?
        if frameCount % 60 == 0 {
            properties = [kVTEncodeFrameOptionKey_ForceKeyFrame: true] as CFDictionary
        }
        frameCount += 1

        VTCompressionSessionEncodeFrame(
            session, imageBuffer: pixelBuffer,
            presentationTimeStamp: pts, duration: duration,
            frameProperties: properties,
            infoFlagsOut: nil
        )
    }

    // MARK: - Handle Encoded H.264

    private func handleEncodedFrame(_ sampleBuffer: CMSampleBuffer) {
        // Check if this is a keyframe
        let isKeyframe: Bool = {
            guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[CFString: Any]],
                  let first = attachments.first else { return false }
            return !(first[kCMSampleAttachmentKey_NotSync] as? Bool ?? true)
        }()

        // Convert to Annex B
        guard let annexBData = CameraService.convertToAnnexB(
            sampleBuffer: sampleBuffer,
            prependParameterSets: isKeyframe
        ) else { return }

        // Cache SPS/PPS
        if isKeyframe,
           let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
           let params = CameraService.extractSPSandPPS(from: formatDesc) {
            lastSPSPPS = params
        }

        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let ptsValue = UInt64(CMTimeGetSeconds(pts) * 90000) // 90kHz clock

        sendFrame(annexBData, pid: Self.videoPID, pts: ptsValue, isKeyframe: isKeyframe, isVideo: true)
    }

    // MARK: - Send Audio

    func sendAudioBuffer(_ sampleBuffer: CMSampleBuffer) {
        guard isConnected else { return }

        // Get raw PCM and we'll send it as-is in PES
        // For simplicity, extract raw audio data
        guard let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

        var totalLength: Int = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        let status = CMBlockBufferGetDataPointer(
            dataBuffer, atOffset: 0, lengthAtOffsetOut: nil,
            totalLengthOut: &totalLength, dataPointerOut: &dataPointer
        )
        guard status == kCMBlockBufferNoErr, let ptr = dataPointer, totalLength > 0 else { return }

        let audioData = Data(bytes: ptr, count: totalLength)
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let ptsValue = UInt64(CMTimeGetSeconds(pts) * 90000)

        sendFrame(audioData, pid: Self.audioPID, pts: ptsValue, isKeyframe: false, isVideo: false)
    }

    // MARK: - MPEG-TS Muxing

    private func sendFrame(_ data: Data, pid: UInt16, pts: UInt64, isKeyframe: Bool, isVideo: Bool) {
        guard isConnected else { return }

        var packets = Data()

        // Send PAT + PMT before keyframes
        if isKeyframe {
            packets.append(buildPAT())
            packets.append(buildPMT())
        }

        // Build PES packet
        let pesPacket = buildPES(payload: data, pts: pts, isVideo: isVideo)

        // Split PES into 188-byte TS packets
        let tsPayloadMax = Self.tsPacketSize - 4 // 184 bytes without adaptation
        var offset = 0
        var isFirst = true

        while offset < pesPacket.count {
            var packet = Data(capacity: Self.tsPacketSize)

            let remaining = pesPacket.count - offset
            var payloadSize = min(remaining, tsPayloadMax)

            // Adaptation field for keyframe (first packet of IDR)
            var hasAdaptation = false
            var adaptationField = Data()

            if isFirst && isKeyframe && isVideo {
                hasAdaptation = true
                var flags: UInt8 = 0x40 // random_access_indicator
                adaptationField.append(flags)
                payloadSize = min(remaining, tsPayloadMax - 2) // -2 for adaptation length + flags
            }

            // Need stuffing?
            let headerSize = 4 + (hasAdaptation ? 1 + adaptationField.count : 0)
            let stuffingNeeded = Self.tsPacketSize - headerSize - payloadSize

            if stuffingNeeded > 0 && !hasAdaptation {
                hasAdaptation = true
                if stuffingNeeded == 1 {
                    // Just adaptation_field_length = 0
                    adaptationField = Data()
                } else {
                    // adaptation_field_length + flags + stuffing
                    var flags: UInt8 = 0x00
                    adaptationField = Data([flags])
                    adaptationField.append(Data(repeating: 0xFF, count: stuffingNeeded - 2))
                }
            }

            // TS Header
            let cc = isVideo ? nextVideoCC() : nextAudioCC()
            let adaptationControl: UInt8 = hasAdaptation ? 0x30 : 0x10 // both or payload only

            packet.append(0x47) // Sync byte
            packet.append(UInt8((isFirst ? 0x40 : 0x00) | ((pid >> 8) & 0x1F))) // PUSI + PID high
            packet.append(UInt8(pid & 0xFF)) // PID low
            packet.append(adaptationControl | cc) // Adaptation + CC

            if hasAdaptation {
                packet.append(UInt8(adaptationField.count)) // adaptation_field_length
                packet.append(adaptationField)
            }

            // Payload
            let payloadEnd = min(offset + payloadSize, pesPacket.count)
            let actualPayload = pesPacket[offset..<payloadEnd]
            packet.append(actualPayload)

            // Pad to 188 bytes if needed
            if packet.count < Self.tsPacketSize {
                packet.append(Data(repeating: 0xFF, count: Self.tsPacketSize - packet.count))
            }

            packets.append(packet)
            offset = payloadEnd
            isFirst = false
        }

        // Send all packets in one UDP datagram (up to ~7 TS packets per UDP)
        sendUDP(packets)
    }

    // MARK: - PES Packet

    private func buildPES(payload: Data, pts: UInt64, isVideo: Bool) -> Data {
        var pes = Data()

        // PES start code: 00 00 01
        pes.append(contentsOf: [0x00, 0x00, 0x01])

        // Stream ID: 0xE0 for video, 0xC0 for audio
        pes.append(isVideo ? 0xE0 : 0xC0)

        // PES packet length (0 = unbounded for video)
        let pesLength = isVideo ? 0 : min(payload.count + 8, 65535)
        pes.append(UInt8((pesLength >> 8) & 0xFF))
        pes.append(UInt8(pesLength & 0xFF))

        // Flags: 10 (MPEG-2), PTS present
        pes.append(0x80) // marker bits
        pes.append(0x80) // PTS flag

        // PES header data length
        pes.append(5) // PTS is 5 bytes

        // PTS encoding (5 bytes)
        pes.append(encodePTS(pts))

        // Payload
        pes.append(payload)

        return pes
    }

    private func encodePTS(_ pts: UInt64) -> Data {
        var data = Data(count: 5)
        let pts33 = pts & 0x1FFFFFFFF // 33-bit PTS

        data[0] = UInt8(0x21 | ((pts33 >> 29) & 0x0E)) // '0010' marker, PTS[32..30], marker
        data[1] = UInt8((pts33 >> 22) & 0xFF)
        data[2] = UInt8(0x01 | ((pts33 >> 14) & 0xFE)) // PTS[22..15], marker
        data[3] = UInt8((pts33 >> 7) & 0xFF)
        data[4] = UInt8(0x01 | ((pts33 << 1) & 0xFE))  // PTS[7..0], marker

        return data
    }

    // MARK: - PAT (Program Association Table)

    private func buildPAT() -> Data {
        var packet = Data(count: Self.tsPacketSize)
        packet[0] = 0x47 // Sync
        packet[1] = 0x40 // PUSI, PID=0
        packet[2] = 0x00
        packet[3] = 0x10 | nextPATCC() // Payload only

        // Pointer field
        packet[4] = 0x00

        // PAT table
        let tableStart = 5
        packet[tableStart + 0] = 0x00  // table_id = 0 (PAT)
        packet[tableStart + 1] = 0xB0  // section_syntax_indicator=1, length high
        packet[tableStart + 2] = 0x0D  // section_length = 13
        packet[tableStart + 3] = 0x00  // transport_stream_id
        packet[tableStart + 4] = 0x01
        packet[tableStart + 5] = 0xC1  // version=0, current=1
        packet[tableStart + 6] = 0x00  // section_number
        packet[tableStart + 7] = 0x00  // last_section_number

        // Program 1 -> PMT PID 0x1000
        packet[tableStart + 8] = 0x00  // program_number high
        packet[tableStart + 9] = 0x01  // program_number low
        packet[tableStart + 10] = 0xE0 | UInt8((Self.pmtPID >> 8) & 0x1F) // reserved + PMT PID high
        packet[tableStart + 11] = UInt8(Self.pmtPID & 0xFF)

        // CRC32 (4 bytes) — simplified, some decoders accept 0xFFFFFFFF
        let crc = crc32mpeg(Data(packet[(tableStart)..<(tableStart + 12)]))
        packet[tableStart + 12] = UInt8((crc >> 24) & 0xFF)
        packet[tableStart + 13] = UInt8((crc >> 16) & 0xFF)
        packet[tableStart + 14] = UInt8((crc >> 8) & 0xFF)
        packet[tableStart + 15] = UInt8(crc & 0xFF)

        // Fill rest with 0xFF
        for i in (tableStart + 16)..<Self.tsPacketSize {
            packet[i] = 0xFF
        }

        return packet
    }

    // MARK: - PMT (Program Map Table)

    private func buildPMT() -> Data {
        var packet = Data(count: Self.tsPacketSize)
        packet[0] = 0x47 // Sync
        packet[1] = 0x40 | UInt8((Self.pmtPID >> 8) & 0x1F) // PUSI + PID high
        packet[2] = UInt8(Self.pmtPID & 0xFF)
        packet[3] = 0x10 | nextPMTCC()

        // Pointer field
        packet[4] = 0x00

        let tableStart = 5
        packet[tableStart + 0] = 0x02   // table_id = 2 (PMT)
        packet[tableStart + 1] = 0xB0   // section_syntax_indicator
        packet[tableStart + 2] = 0x17   // section_length = 23
        packet[tableStart + 3] = 0x00   // program_number
        packet[tableStart + 4] = 0x01
        packet[tableStart + 5] = 0xC1   // version=0, current=1
        packet[tableStart + 6] = 0x00   // section_number
        packet[tableStart + 7] = 0x00   // last_section_number
        packet[tableStart + 8] = 0xE0 | UInt8((Self.videoPID >> 8) & 0x1F) // PCR PID
        packet[tableStart + 9] = UInt8(Self.videoPID & 0xFF)
        packet[tableStart + 10] = 0xF0  // program_info_length
        packet[tableStart + 11] = 0x00

        // Video stream entry (H.264 = stream_type 0x1B)
        packet[tableStart + 12] = 0x1B  // stream_type = H.264
        packet[tableStart + 13] = 0xE0 | UInt8((Self.videoPID >> 8) & 0x1F)
        packet[tableStart + 14] = UInt8(Self.videoPID & 0xFF)
        packet[tableStart + 15] = 0xF0  // ES_info_length
        packet[tableStart + 16] = 0x00

        // Audio stream entry (AAC = stream_type 0x0F)
        packet[tableStart + 17] = 0x0F  // stream_type = AAC
        packet[tableStart + 18] = 0xE0 | UInt8((Self.audioPID >> 8) & 0x1F)
        packet[tableStart + 19] = UInt8(Self.audioPID & 0xFF)
        packet[tableStart + 20] = 0xF0
        packet[tableStart + 21] = 0x00

        // CRC32
        let crc = crc32mpeg(Data(packet[(tableStart)..<(tableStart + 22)]))
        packet[tableStart + 22] = UInt8((crc >> 24) & 0xFF)
        packet[tableStart + 23] = UInt8((crc >> 16) & 0xFF)
        packet[tableStart + 24] = UInt8((crc >> 8) & 0xFF)
        packet[tableStart + 25] = UInt8(crc & 0xFF)

        // Fill rest with 0xFF
        for i in (tableStart + 26)..<Self.tsPacketSize {
            packet[i] = 0xFF
        }

        return packet
    }

    // MARK: - CRC32/MPEG2

    private func crc32mpeg(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for byte in data {
            crc ^= UInt32(byte) << 24
            for _ in 0..<8 {
                if crc & 0x80000000 != 0 {
                    crc = (crc << 1) ^ 0x04C11DB7
                } else {
                    crc <<= 1
                }
            }
        }
        return crc
    }

    // MARK: - Continuity Counters

    private func nextVideoCC() -> UInt8 {
        let cc = videoContinuityCounter
        videoContinuityCounter = (videoContinuityCounter + 1) & 0x0F
        return cc
    }

    private func nextAudioCC() -> UInt8 {
        let cc = audioContinuityCounter
        audioContinuityCounter = (audioContinuityCounter + 1) & 0x0F
        return cc
    }

    private func nextPATCC() -> UInt8 {
        let cc = patContinuityCounter
        patContinuityCounter = (patContinuityCounter + 1) & 0x0F
        return cc
    }

    private func nextPMTCC() -> UInt8 {
        let cc = pmtContinuityCounter
        pmtContinuityCounter = (pmtContinuityCounter + 1) & 0x0F
        return cc
    }

    // MARK: - UDP Send

    private func sendUDP(_ data: Data) {
        guard let connection = udpConnection, data.count > 0 else { return }

        // Split into UDP-friendly chunks (~7 TS packets = 1316 bytes < MTU)
        let maxPerDatagram = Self.tsPacketSize * 7
        var offset = 0

        while offset < data.count {
            let end = min(offset + maxPerDatagram, data.count)
            let chunk = data[offset..<end]
            connection.send(content: chunk, completion: .contentProcessed { _ in })
            offset = end
        }
    }
}
