import SwiftUI
import AVFoundation

/// Camera preview with pose skeleton overlay for debugging.
struct DebugCameraView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                #if os(iOS)
                // Live camera preview
                CameraPreviewLayer(session: appState.cameraManager.captureSession)
                    .ignoresSafeArea()
                #else
                Color.black
                    .overlay(Text("Camera Preview (iOS only)").foregroundStyle(.gray))
                #endif

                // Pose skeleton overlay (debug)
                Canvas { context, size in
                    drawDetections(context: context, size: size)
                }
                .allowsHitTesting(false)
            }
        }
    }

    private func drawDetections(context: GraphicsContext, size: CGSize) {
        // This would draw bounding boxes and skeleton connections
        // In a real implementation, this reads from catTracker's current state
        // For now, kept minimal to avoid blocking the camera preview
    }
}

#if os(iOS)
import UIKit

/// UIViewRepresentable for AVCaptureVideoPreviewLayer.
struct CameraPreviewLayer: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> CameraPreviewUIView {
        let view = CameraPreviewUIView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: CameraPreviewUIView, context: Context) {
        uiView.previewLayer.session = session
    }
}

final class CameraPreviewUIView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        layer as! AVCaptureVideoPreviewLayer
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        previewLayer.frame = bounds
        // Force landscape right for preview (separate from video data output connection)
        if let connection = previewLayer.connection,
           connection.isVideoOrientationSupported {
            connection.videoOrientation = .landscapeRight
        }
    }
}
#endif
