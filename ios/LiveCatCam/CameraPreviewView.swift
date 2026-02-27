import SwiftUI
import AVFoundation

/// UIViewRepresentable wrapper for AVCaptureVideoPreviewLayer.
/// Displays the live camera feed fullscreen in landscape.
struct CameraPreviewView: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill

        if #available(iOS 17.0, *) {
            view.previewLayer.connection?.videoRotationAngle = 0
        } else {
            view.previewLayer.connection?.videoOrientation = .landscapeRight
        }

        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {
        // Session is already set; just ensure layer fills bounds
    }
}

/// Custom UIView that keeps the preview layer filling its bounds.
final class PreviewUIView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        layer as! AVCaptureVideoPreviewLayer
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        previewLayer.frame = bounds
    }
}
