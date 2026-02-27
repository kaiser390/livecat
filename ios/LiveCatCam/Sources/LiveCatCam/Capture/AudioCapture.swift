import Foundation
import AVFoundation

/// Optional ambient audio capture for stream mixing.
final class AudioCapture: NSObject, @unchecked Sendable {
    private var audioOutput: AVCaptureAudioDataOutput?
    private let processingQueue = DispatchQueue(label: "com.livecat.audio", qos: .userInteractive)

    var onAudioBuffer: ((CMSampleBuffer) -> Void)?
    private(set) var isCapturing = false

    /// Add audio input/output to an existing capture session.
    func attach(to session: AVCaptureSession) throws {
        guard let audioDevice = AVCaptureDevice.default(for: .audio) else {
            Log.camera.warning("No audio device available")
            return
        }

        let audioInput = try AVCaptureDeviceInput(device: audioDevice)
        guard session.canAddInput(audioInput) else { return }

        let output = AVCaptureAudioDataOutput()
        output.setSampleBufferDelegate(self, queue: processingQueue)
        guard session.canAddOutput(output) else { return }

        session.beginConfiguration()
        session.addInput(audioInput)
        session.addOutput(output)
        session.commitConfiguration()

        self.audioOutput = output
        isCapturing = true
        Log.camera.info("Audio capture attached")
    }

    func detach(from session: AVCaptureSession) {
        if let output = audioOutput {
            session.removeOutput(output)
        }
        audioOutput = nil
        isCapturing = false
        Log.camera.info("Audio capture detached")
    }
}

extension AudioCapture: AVCaptureAudioDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        onAudioBuffer?(sampleBuffer)
    }
}
