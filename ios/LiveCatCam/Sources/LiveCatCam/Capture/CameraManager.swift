import Foundation
import AVFoundation

/// Manages AVCaptureSession for camera input, providing frames to Vision and video encoder.
final class CameraManager: NSObject, @unchecked Sendable {
    private let session = AVCaptureSession()
    private let videoOutput = AVCaptureVideoDataOutput()
    private let processingQueue = DispatchQueue(label: "com.livecat.camera", qos: .userInteractive)
    private var captureDevice: AVCaptureDevice?

    var onFrame: ((CVPixelBuffer, CMTime) -> Void)?
    var diagnosticInfo: String = ""

    private(set) var isRunning = false
    private(set) var currentFPS: Double = 0
    private var frameTimestamps: [CFTimeInterval] = []
    private var frameCount: UInt64 = 0

    func configure(resolution: CameraConfig.Resolution = .hd720p, fps: Int = 30) throws {
        session.beginConfiguration()
        defer { session.commitConfiguration() }

        session.sessionPreset = resolution == .hd1080p ? .hd1920x1080 : .hd1280x720

        // Find rear wide-angle camera
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw CameraError.noCameraAvailable
        }

        self.captureDevice = device

        // Configure frame rate
        try device.lockForConfiguration()
        let targetDuration = CMTime(value: 1, timescale: CMTimeScale(fps))
        device.activeVideoMinFrameDuration = targetDuration
        device.activeVideoMaxFrameDuration = targetDuration
        device.unlockForConfiguration()

        // Add input
        let input = try AVCaptureDeviceInput(device: device)
        guard session.canAddInput(input) else {
            throw CameraError.cannotAddInput
        }
        session.addInput(input)

        // Configure video output for Vision processing
        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.setSampleBufferDelegate(self, queue: processingQueue)

        guard session.canAddOutput(videoOutput) else {
            throw CameraError.cannotAddOutput
        }
        session.addOutput(videoOutput)

        // Rotate actual pixel data to landscape right (deprecated but physically rotates CVPixelBuffer)
        if let connection = videoOutput.connection(with: .video) {
            if connection.isVideoOrientationSupported {
                connection.videoOrientation = .landscapeRight
                diagnosticInfo = "videoOrientation=landscapeRight"
                Log.camera.info("Video orientation set to landscapeRight (pixel rotation)")
            }
        }

        Log.camera.info("Camera configured: \(resolution.rawValue) @ \(fps)fps")
    }

    func start() {
        guard !session.isRunning else { return }
        processingQueue.async { [weak self] in
            self?.session.startRunning()
        }
        isRunning = true
        Log.camera.info("Camera started")

        // Monitor for session interruptions
        NotificationCenter.default.addObserver(
            self, selector: #selector(handleInterruption),
            name: .AVCaptureSessionWasInterrupted, object: session
        )
        NotificationCenter.default.addObserver(
            self, selector: #selector(handleInterruptionEnded),
            name: .AVCaptureSessionInterruptionEnded, object: session
        )
    }

    func stop() {
        guard session.isRunning else { return }
        session.stopRunning()
        isRunning = false
        NotificationCenter.default.removeObserver(self)
        Log.camera.info("Camera stopped")
    }

    func restart() {
        stop()
        start()
    }

    var captureSession: AVCaptureSession { session }

    // MARK: - Remote Camera Control

    func setZoom(factor: Double) {
        #if os(iOS)
        guard let device = captureDevice else { return }
        do {
            try device.lockForConfiguration()
            let clamped = min(max(factor, 1.0), min(device.activeFormat.videoMaxZoomFactor, 15.0))
            device.videoZoomFactor = clamped
            device.unlockForConfiguration()
            Log.camera.info("Zoom set to \(clamped)x")
        } catch {
            Log.camera.error("Zoom failed: \(error)")
        }
        #endif
    }

    func setFocus(x: Double, y: Double) {
        guard let device = captureDevice else { return }
        let point = CGPoint(x: min(max(x, 0), 1), y: min(max(y, 0), 1))
        do {
            try device.lockForConfiguration()
            if device.isFocusPointOfInterestSupported {
                device.focusPointOfInterest = point
                device.focusMode = .autoFocus
            }
            device.unlockForConfiguration()
            Log.camera.info("Focus set to (\(point.x), \(point.y))")
        } catch {
            Log.camera.error("Focus failed: \(error)")
        }
    }

    func setExposure(x: Double, y: Double) {
        guard let device = captureDevice else { return }
        let point = CGPoint(x: min(max(x, 0), 1), y: min(max(y, 0), 1))
        do {
            try device.lockForConfiguration()
            if device.isExposurePointOfInterestSupported {
                device.exposurePointOfInterest = point
                device.exposureMode = .autoExpose
            }
            device.unlockForConfiguration()
            Log.camera.info("Exposure set to (\(point.x), \(point.y))")
        } catch {
            Log.camera.error("Exposure failed: \(error)")
        }
    }

    func resetCamera() {
        guard let device = captureDevice else { return }
        do {
            try device.lockForConfiguration()
            #if os(iOS)
            device.videoZoomFactor = 1.0
            #endif
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
            if device.isExposureModeSupported(.continuousAutoExposure) {
                device.exposureMode = .continuousAutoExposure
            }
            device.unlockForConfiguration()
            Log.camera.info("Camera reset: zoom=1.0, autoFocus, autoExposure")
        } catch {
            Log.camera.error("Camera reset failed: \(error)")
        }
    }

    // MARK: - Interruption handling

    @objc private func handleInterruption(_ notification: Notification) {
        #if os(iOS)
        guard let reason = notification.userInfo?[AVCaptureSessionInterruptionReasonKey] as? Int else { return }
        Log.camera.warning("Camera interrupted: \(reason)")
        #else
        Log.camera.warning("Camera interrupted")
        #endif
    }

    @objc private func handleInterruptionEnded(_ notification: Notification) {
        Log.camera.info("Camera interruption ended, restarting")
        start()
    }

    // MARK: - FPS tracking

    private func updateFPS() {
        let now = CFAbsoluteTimeGetCurrent()
        frameTimestamps.append(now)
        frameTimestamps.removeAll { now - $0 > 1.0 }
        currentFPS = Double(frameTimestamps.count)
    }
}

// MARK: - AVCaptureVideoDataOutputSampleBufferDelegate

extension CameraManager: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        updateFPS()
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        // Log first frame dimensions
        frameCount += 1
        if frameCount == 1 {
            let w = CVPixelBufferGetWidth(pixelBuffer)
            let h = CVPixelBufferGetHeight(pixelBuffer)
            let angle = connection.videoRotationAngle
            let info = "frame=\(w)x\(h) angle=\(Int(angle))"
            diagnosticInfo += " | \(info)"
            Log.camera.info("First frame: \(w)x\(h), connection.videoRotationAngle=\(angle)")
        }

        let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        onFrame?(pixelBuffer, timestamp)
    }
}

// MARK: - Errors

enum CameraError: Error, LocalizedError {
    case noCameraAvailable
    case cannotAddInput
    case cannotAddOutput

    var errorDescription: String? {
        switch self {
        case .noCameraAvailable: return "No rear camera available"
        case .cannotAddInput: return "Cannot add camera input to session"
        case .cannotAddOutput: return "Cannot add video output to session"
        }
    }
}
