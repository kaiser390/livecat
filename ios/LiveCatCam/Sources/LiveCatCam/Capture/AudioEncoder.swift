import AudioToolbox
import CoreMedia

/// Real-time AAC encoder using AudioToolbox's AudioConverter.
/// Pipeline: PCM (from mic CMSampleBuffer) → AAC-LC → ADTS-wrapped frames
final class AudioEncoder: @unchecked Sendable {
    private var converter: AudioConverterRef?
    private var pcmBuffer = Data()
    private let aacFrameSize: UInt32 = 1024  // AAC-LC: 1024 samples per frame
    private var sampleRate: Double = 0
    private var channels: UInt32 = 0
    private var aacMaxOutputSize: UInt32 = 768
    private var inputBytesPerFrame: UInt32 = 0

    // Stable pointers for AudioConverter callback
    private var currentInputPtr: UnsafeMutableRawPointer?
    private var currentInputSize: UInt32 = 0

    var onEncodedAudio: ((Data) -> Void)?
    private var frameCount: UInt64 = 0

    func encode(sampleBuffer: CMSampleBuffer) {
        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer) else { return }

        // Lazy init converter from first buffer's audio format
        if converter == nil {
            guard let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else { return }
            setupConverter(inputFormat: asbd.pointee)
            guard converter != nil else { return }
        }

        // Extract PCM data
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil,
                                    totalLengthOut: &length, dataPointerOut: &dataPointer)
        guard let dataPointer, length > 0 else { return }

        pcmBuffer.append(Data(bytes: dataPointer, count: length))

        // Encode when we have enough samples for one AAC frame (1024 samples)
        let bytesNeeded = Int(aacFrameSize) * Int(inputBytesPerFrame)
        guard bytesNeeded > 0 else { return }

        while pcmBuffer.count >= bytesNeeded {
            let frameData = Data(pcmBuffer.prefix(bytesNeeded))
            pcmBuffer.removeFirst(bytesNeeded)

            if let aacFrame = encodeOneFrame(frameData) {
                let adts = buildADTSHeader(aacFrameLength: aacFrame.count)
                var output = adts
                output.append(aacFrame)
                frameCount += 1
                if frameCount <= 3 || frameCount % 200 == 0 {
                    Log.streaming.info("[AUDIO] AAC #\(self.frameCount) \(output.count)B")
                }
                onEncodedAudio?(output)
            }
        }
    }

    func stop() {
        let count = frameCount
        if let converter {
            AudioConverterDispose(converter)
        }
        converter = nil
        pcmBuffer.removeAll()
        frameCount = 0
        Log.streaming.info("[AUDIO] Encoder stopped after \(count) frames")
    }

    // MARK: - Setup

    private func setupConverter(inputFormat: AudioStreamBasicDescription) {
        sampleRate = inputFormat.mSampleRate
        channels = inputFormat.mChannelsPerFrame
        inputBytesPerFrame = inputFormat.mBytesPerFrame

        Log.streaming.info("[AUDIO] Input: \(self.sampleRate)Hz \(self.channels)ch \(inputFormat.mBitsPerChannel)bit bpf=\(self.inputBytesPerFrame) flags=\(inputFormat.mFormatFlags)")

        var inputDesc = inputFormat
        var outputDesc = AudioStreamBasicDescription(
            mSampleRate: sampleRate,
            mFormatID: kAudioFormatMPEG4AAC,
            mFormatFlags: 0,
            mBytesPerPacket: 0,
            mFramesPerPacket: 1024,
            mBytesPerFrame: 0,
            mChannelsPerFrame: channels,
            mBitsPerChannel: 0,
            mReserved: 0
        )

        var conv: AudioConverterRef?
        let status = AudioConverterNew(&inputDesc, &outputDesc, &conv)
        guard status == noErr, let conv else {
            Log.streaming.error("[AUDIO] AudioConverter create failed: \(status)")
            return
        }
        converter = conv

        var bitrate: UInt32 = channels == 1 ? 64000 : 128000
        AudioConverterSetProperty(conv, kAudioConverterEncodeBitRate,
                                  UInt32(MemoryLayout<UInt32>.size), &bitrate)

        var propSize = UInt32(MemoryLayout<UInt32>.size)
        AudioConverterGetProperty(conv, kAudioConverterPropertyMaximumOutputPacketSize,
                                  &propSize, &aacMaxOutputSize)

        Log.streaming.info("[AUDIO] Encoder ready: → AAC-LC \(bitrate/1000)kbps maxOut=\(self.aacMaxOutputSize)B")
    }

    // MARK: - Encode one AAC frame

    private func encodeOneFrame(_ pcmData: Data) -> Data? {
        guard let converter else { return nil }

        // Copy PCM to stable buffer for C callback
        let inputPtr = UnsafeMutableRawPointer.allocate(byteCount: pcmData.count, alignment: 1)
        pcmData.copyBytes(to: inputPtr.assumingMemoryBound(to: UInt8.self), count: pcmData.count)
        currentInputPtr = inputPtr
        currentInputSize = UInt32(pcmData.count)
        defer {
            inputPtr.deallocate()
            currentInputPtr = nil
            currentInputSize = 0
        }

        let outputSize = Int(aacMaxOutputSize)
        let outputPtr = UnsafeMutableRawPointer.allocate(byteCount: outputSize, alignment: 1)
        defer { outputPtr.deallocate() }

        var outputBufferList = AudioBufferList(
            mNumberBuffers: 1,
            mBuffers: AudioBuffer(
                mNumberChannels: channels,
                mDataByteSize: UInt32(outputSize),
                mData: outputPtr
            )
        )

        var outputPacketCount: UInt32 = 1
        var packetDesc = AudioStreamPacketDescription()
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()

        let result = AudioConverterFillComplexBuffer(
            converter,
            { (_, ioNumberDataPackets, ioData, _, inUserData) -> OSStatus in
                guard let inUserData else {
                    ioNumberDataPackets.pointee = 0
                    return -1
                }
                let enc = Unmanaged<AudioEncoder>.fromOpaque(inUserData).takeUnretainedValue()
                guard let ptr = enc.currentInputPtr, enc.currentInputSize > 0 else {
                    ioNumberDataPackets.pointee = 0
                    return -1
                }

                ioData.pointee.mNumberBuffers = 1
                ioData.pointee.mBuffers.mData = ptr
                ioData.pointee.mBuffers.mDataByteSize = enc.currentInputSize
                ioData.pointee.mBuffers.mNumberChannels = enc.channels
                ioNumberDataPackets.pointee = enc.aacFrameSize

                // Only provide data once per call
                enc.currentInputPtr = nil
                enc.currentInputSize = 0
                return noErr
            },
            selfPtr,
            &outputPacketCount,
            &outputBufferList,
            &packetDesc
        )

        guard result == noErr, outputPacketCount > 0 else { return nil }

        let actualSize = Int(outputBufferList.mBuffers.mDataByteSize)
        return Data(bytes: outputPtr, count: actualSize)
    }

    // MARK: - ADTS Header (7 bytes, no CRC)

    private func buildADTSHeader(aacFrameLength: Int) -> Data {
        let fullLength = aacFrameLength + 7
        let profile: UInt8 = 1   // AAC-LC (AudioObjectType 2 - 1)
        let freqIdx = sampleRateIndex(sampleRate)
        let chanCfg = UInt8(min(channels, 7))

        var h = Data(count: 7)
        h[0] = 0xFF                                                           // syncword high
        h[1] = 0xF1                                                           // syncword low + MPEG-4 + no CRC
        h[2] = (profile << 6) | (freqIdx << 2) | ((chanCfg >> 2) & 0x01)     // profile + freq + chan high bit
        h[3] = ((chanCfg & 0x03) << 6) | UInt8((fullLength >> 11) & 0x03)    // chan low + frame len high
        h[4] = UInt8((fullLength >> 3) & 0xFF)                                // frame len mid
        h[5] = UInt8((fullLength & 0x07) << 5) | 0x1F                         // frame len low + buffer fullness high (VBR=0x7FF)
        h[6] = 0xFC                                                            // buffer fullness low + 0 raw blocks
        return h
    }

    private func sampleRateIndex(_ rate: Double) -> UInt8 {
        let rates: [Double] = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350]
        for (i, r) in rates.enumerated() {
            if abs(rate - r) < 1 { return UInt8(i) }
        }
        return 4  // Default 44100
    }
}
