import Foundation
import VideoToolbox
import CoreMedia

/// Hardware H.264 encoder using VTCompressionSession.
final class VideoEncoder: @unchecked Sendable {
    private var session: VTCompressionSession?
    private let width: Int32
    private let height: Int32
    private let fps: Int32
    private let bitrate: Int32
    private let keyframeInterval: Int32

    /// Callback for encoded NAL units (SPS/PPS + frame data).
    var onEncodedData: ((Data, Bool) -> Void)?  // (data, isKeyframe)

    private var formatDescription: CMFormatDescription?
    private var spsData: Data?
    private var ppsData: Data?
    private var encodedFrameCount: UInt64 = 0
    private var keyframeCount: UInt64 = 0

    init(width: Int = 1280, height: Int = 720, fps: Int = 30,
         bitrate: Int = 4_000_000, keyframeIntervalSeconds: Int = 2) {
        self.width = Int32(width)
        self.height = Int32(height)
        self.fps = Int32(fps)
        self.bitrate = Int32(bitrate)
        self.keyframeInterval = Int32(keyframeIntervalSeconds * fps)
    }

    func start() throws {
        var session: VTCompressionSession?

        let outputCallback: VTCompressionOutputCallback = { refcon, _, status, _, sampleBuffer in
            guard status == noErr, let sampleBuffer, let refcon else { return }
            let encoder = Unmanaged<VideoEncoder>.fromOpaque(refcon).takeUnretainedValue()
            encoder.handleEncodedSample(sampleBuffer)
        }

        let selfPointer = Unmanaged.passUnretained(self).toOpaque()
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: width,
            height: height,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: nil,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: outputCallback,
            refcon: selfPointer,
            compressionSessionOut: &session
        )

        guard status == noErr, let session else {
            throw EncoderError.creationFailed(status)
        }

        self.session = session

        // Configure encoder properties
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ProfileLevel,
                             value: kVTProfileLevel_H264_Main_AutoLevel)
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AverageBitRate,
                             value: NSNumber(value: bitrate))
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameInterval,
                             value: NSNumber(value: keyframeInterval))
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_ExpectedFrameRate,
                             value: NSNumber(value: fps))
        VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AllowFrameReordering,
                             value: kCFBooleanFalse)

        VTCompressionSessionPrepareToEncodeFrames(session)
        Log.streaming.info("H.264 encoder started: \(self.width)x\(self.height) @ \(self.bitrate/1000)kbps")
    }

    func encode(pixelBuffer: CVPixelBuffer, presentationTime: CMTime) {
        guard let session else { return }
        VTCompressionSessionEncodeFrame(
            session,
            imageBuffer: pixelBuffer,
            presentationTimeStamp: presentationTime,
            duration: CMTime(value: 1, timescale: CMTimeScale(fps)),
            frameProperties: nil,
            sourceFrameRefcon: nil,
            infoFlagsOut: nil
        )
    }

    func stop() {
        guard let session else { return }
        VTCompressionSessionCompleteFrames(session, untilPresentationTimeStamp: .invalid)
        VTCompressionSessionInvalidate(session)
        self.session = nil
        Log.streaming.info("H.264 encoder stopped")
    }

    // MARK: - Handle encoded output

    private func handleEncodedSample(_ sampleBuffer: CMSampleBuffer) {
        guard let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

        let isKeyframe: Bool
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[CFString: Any]],
           let first = attachments.first {
            // kCMSampleAttachmentKey_NotSync: true = NOT sync (not keyframe), absent = IS sync (keyframe)
            let notSync = first[kCMSampleAttachmentKey_NotSync] as? Bool ?? false
            let dependsOnOthers = first[kCMSampleAttachmentKey_DependsOnOthers] as? Bool ?? false
            isKeyframe = !notSync && !dependsOnOthers
        } else {
            // No attachments = assume keyframe (conservative)
            isKeyframe = true
        }

        encodedFrameCount += 1

        // Extract SPS/PPS from keyframe
        if isKeyframe, let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer) {
            extractParameterSets(from: formatDesc)
        }

        // Get encoded data
        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        CMBlockBufferGetDataPointer(dataBuffer, atOffset: 0, lengthAtOffsetOut: nil,
                                    totalLengthOut: &length, dataPointerOut: &dataPointer)

        guard let dataPointer, length > 0 else { return }

        var outputData = Data()

        // Prepend SPS/PPS for keyframes
        if isKeyframe, let sps = spsData, let pps = ppsData {
            keyframeCount += 1
            let startCode = Data([0x00, 0x00, 0x00, 0x01])
            outputData.append(startCode)
            outputData.append(sps)
            outputData.append(startCode)
            outputData.append(pps)
            Log.streaming.info("[ENC] KEYFRAME #\(self.keyframeCount) SPS=\(sps.count)B PPS=\(pps.count)B frame#\(self.encodedFrameCount)")
        } else if isKeyframe {
            Log.streaming.warning("[ENC] KEYFRAME but SPS/PPS missing! sps=\(self.spsData == nil ? "nil" : "ok") pps=\(self.ppsData == nil ? "nil" : "ok")")
        }

        // Convert AVCC (length-prefixed) to Annex-B (start code prefixed)
        var offset = 0
        var nalTypes: [UInt8] = []
        while offset < length - 4 {
            var nalLength: UInt32 = 0
            memcpy(&nalLength, dataPointer + offset, 4)
            nalLength = nalLength.bigEndian
            offset += 4

            if nalLength > 0 {
                let nalType = UInt8(dataPointer[offset]) & 0x1F
                nalTypes.append(nalType)
            }

            let startCode = Data([0x00, 0x00, 0x00, 0x01])
            outputData.append(startCode)
            outputData.append(Data(bytes: dataPointer + offset, count: Int(nalLength)))
            offset += Int(nalLength)
        }

        // Debug: log NAL types every 30 frames or on keyframe
        if isKeyframe || encodedFrameCount % 30 == 0 {
            let nalTypeNames = nalTypes.map { type -> String in
                switch type {
                case 1: return "P"
                case 5: return "IDR"
                case 6: return "SEI"
                case 7: return "SPS"
                case 8: return "PPS"
                default: return "\(type)"
                }
            }
            Log.streaming.info("[ENC] frame#\(self.encodedFrameCount) key=\(isKeyframe) NALs=\(nalTypeNames) size=\(outputData.count)B")
        }

        onEncodedData?(outputData, isKeyframe)
    }

    private func extractParameterSets(from formatDescription: CMFormatDescription) {
        var spsSize = 0, spsCount = 0
        var spsPointer: UnsafePointer<UInt8>?
        let spsStatus = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            formatDescription, parameterSetIndex: 0,
            parameterSetPointerOut: &spsPointer, parameterSetSizeOut: &spsSize,
            parameterSetCountOut: &spsCount, nalUnitHeaderLengthOut: nil
        )
        if spsStatus == noErr, let spsPointer, spsSize > 0 {
            spsData = Data(bytes: spsPointer, count: spsSize)
            Log.streaming.info("[ENC] SPS extracted: \(spsSize)B (paramSets=\(spsCount))")
        } else {
            Log.streaming.error("[ENC] SPS extraction FAILED: status=\(spsStatus)")
        }

        var ppsSize = 0
        var ppsPointer: UnsafePointer<UInt8>?
        let ppsStatus = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            formatDescription, parameterSetIndex: 1,
            parameterSetPointerOut: &ppsPointer, parameterSetSizeOut: &ppsSize,
            parameterSetCountOut: nil, nalUnitHeaderLengthOut: nil
        )
        if ppsStatus == noErr, let ppsPointer, ppsSize > 0 {
            ppsData = Data(bytes: ppsPointer, count: ppsSize)
            Log.streaming.info("[ENC] PPS extracted: \(ppsSize)B")
        } else {
            Log.streaming.error("[ENC] PPS extraction FAILED: status=\(ppsStatus)")
        }
    }

    enum EncoderError: Error {
        case creationFailed(OSStatus)
    }
}
