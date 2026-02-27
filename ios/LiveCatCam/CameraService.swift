import AVFoundation
import UIKit

/// Manages AVCaptureSession, H.264 hardware encoding, and zoom control.
/// Delivers encoded video (CMSampleBuffer) and audio via delegate callbacks.
protocol CameraServiceDelegate: AnyObject {
    func cameraService(_ service: CameraService, didOutputVideo sampleBuffer: CMSampleBuffer)
    func cameraService(_ service: CameraService, didOutputAudio sampleBuffer: CMSampleBuffer)
}

final class CameraService: NSObject {
    weak var delegate: CameraServiceDelegate?

    let session = AVCaptureSession()
    private var videoDevice: AVCaptureDevice?
    private let sessionQueue = DispatchQueue(label: "com.livecatcam.camera")

    private(set) var currentZoom: CGFloat = 1.0
    private(set) var maxZoom: CGFloat = 5.0

    var isRunning: Bool { session.isRunning }

    // MARK: - Setup

    func configure(quality: VideoQuality) {
        sessionQueue.async { [weak self] in
            self?.setupSession(quality: quality)
        }
    }

    private func setupSession(quality: VideoQuality) {
        session.beginConfiguration()
        session.sessionPreset = AVCaptureSession.Preset(quality: quality)

        // Video input — back wide camera
        if let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) {
            videoDevice = device
            maxZoom = min(device.activeFormat.videoMaxZoomFactor, 10.0)

            if let input = try? AVCaptureDeviceInput(device: device) {
                if session.canAddInput(input) {
                    session.addInput(input)
                }
            }

            // Configure device for streaming
            try? device.lockForConfiguration()
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
            if device.isExposureModeSupported(.continuousAutoExposure) {
                device.exposureMode = .continuousAutoExposure
            }
            device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 30)
            device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 30)
            device.unlockForConfiguration()
        }

        // Audio input
        if let audioDevice = AVCaptureDevice.default(for: .audio),
           let audioInput = try? AVCaptureDeviceInput(device: audioDevice) {
            if session.canAddInput(audioInput) {
                session.addInput(audioInput)
            }
        }

        // Video output
        let videoOutput = AVCaptureVideoDataOutput()
        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        ]
        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.setSampleBufferDelegate(self, queue: DispatchQueue(label: "com.livecatcam.video"))
        if session.canAddOutput(videoOutput) {
            session.addOutput(videoOutput)
        }

        // Force landscape right orientation
        if let connection = videoOutput.connection(with: .video) {
            if #available(iOS 17.0, *) {
                connection.videoRotationAngle = 0
            } else {
                connection.videoOrientation = .landscapeRight
            }
        }

        // Audio output
        let audioOutput = AVCaptureAudioDataOutput()
        audioOutput.setSampleBufferDelegate(self, queue: DispatchQueue(label: "com.livecatcam.audio"))
        if session.canAddOutput(audioOutput) {
            session.addOutput(audioOutput)
        }

        session.commitConfiguration()
    }

    // MARK: - Start / Stop

    func startCapture() {
        sessionQueue.async { [weak self] in
            guard let self, !self.session.isRunning else { return }
            self.session.startRunning()
        }
    }

    func stopCapture() {
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
        }
    }

    // MARK: - Zoom

    func setZoom(_ factor: CGFloat, animated: Bool = true) {
        guard let device = videoDevice else { return }
        let clamped = min(max(factor, 1.0), maxZoom)

        try? device.lockForConfiguration()
        if animated {
            device.ramp(toVideoZoomFactor: clamped, withRate: 8.0)
        } else {
            device.videoZoomFactor = clamped
        }
        device.unlockForConfiguration()
        currentZoom = clamped
    }

    /// Handle pinch gesture zoom
    func handlePinch(scale: CGFloat) {
        let newZoom = currentZoom * scale
        setZoom(newZoom, animated: false)
    }

    // MARK: - SPS/PPS Extraction

    /// Extract SPS and PPS NAL units from a video format description.
    /// These must be prepended before each IDR frame in the MPEG-TS stream.
    static func extractSPSandPPS(from formatDescription: CMFormatDescription) -> (sps: Data, pps: Data)? {
        var spsSize: Int = 0
        var spsCount: Int = 0
        var ppsSize: Int = 0
        var ppsCount: Int = 0

        var spsPtr: UnsafePointer<UInt8>?
        var ppsPtr: UnsafePointer<UInt8>?

        // Get SPS
        var status = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            formatDescription, parameterSetIndex: 0,
            parameterSetPointerOut: &spsPtr, parameterSetSizeOut: &spsSize,
            parameterSetCountOut: &spsCount, nalUnitHeaderLengthOut: nil
        )
        guard status == noErr, let sps = spsPtr else { return nil }

        // Get PPS
        status = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            formatDescription, parameterSetIndex: 1,
            parameterSetPointerOut: &ppsPtr, parameterSetSizeOut: &ppsSize,
            parameterSetCountOut: &ppsCount, nalUnitHeaderLengthOut: nil
        )
        guard status == noErr, let pps = ppsPtr else { return nil }

        let spsData = Data(bytes: sps, count: spsSize)
        let ppsData = Data(bytes: pps, count: ppsSize)
        return (spsData, ppsData)
    }

    /// Convert AVCC (length-prefixed) H.264 to Annex B (start-code prefixed).
    /// Optionally prepends SPS/PPS before IDR frames.
    static func convertToAnnexB(
        sampleBuffer: CMSampleBuffer,
        prependParameterSets: Bool = false
    ) -> Data? {
        guard let dataBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return nil }

        var totalLength: Int = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        let status = CMBlockBufferGetDataPointer(
            dataBuffer, atOffset: 0, lengthAtOffsetOut: nil,
            totalLengthOut: &totalLength, dataPointerOut: &dataPointer
        )
        guard status == kCMBlockBufferNoErr, let ptr = dataPointer else { return nil }

        var result = Data()
        let startCode: [UInt8] = [0x00, 0x00, 0x00, 0x01]

        // Optionally prepend SPS/PPS
        if prependParameterSets,
           let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
           let params = extractSPSandPPS(from: formatDesc) {
            result.append(contentsOf: startCode)
            result.append(params.sps)
            result.append(contentsOf: startCode)
            result.append(params.pps)
        }

        // Convert AVCC NAL units to Annex B
        var offset = 0
        while offset < totalLength - 4 {
            // Read 4-byte NAL length (big endian)
            var nalLength: UInt32 = 0
            memcpy(&nalLength, ptr.advanced(by: offset), 4)
            nalLength = nalLength.bigEndian
            offset += 4

            guard nalLength > 0, offset + Int(nalLength) <= totalLength else { break }

            result.append(contentsOf: startCode)
            result.append(Data(bytes: ptr.advanced(by: offset), count: Int(nalLength)))
            offset += Int(nalLength)
        }

        return result.isEmpty ? nil : result
    }
}

// MARK: - AVCaptureVideoDataOutputSampleBufferDelegate

extension CameraService: AVCaptureVideoDataOutputSampleBufferDelegate, AVCaptureAudioDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        if output is AVCaptureVideoDataOutput {
            delegate?.cameraService(self, didOutputVideo: sampleBuffer)
        } else if output is AVCaptureAudioDataOutput {
            delegate?.cameraService(self, didOutputAudio: sampleBuffer)
        }
    }
}
