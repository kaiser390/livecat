import SwiftUI
import AVFoundation

/// Camera preview with tracking bounding box overlay.
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

                // Tap-to-Track bounding box overlay
                if appState.isTapTracking, let bbox = appState.tapTrackBBox {
                    trackingBBoxOverlay(bbox: bbox, viewSize: geometry.size)
                }
            }
        }
    }

    /// Draw bounding box in screen coordinates from Vision normalized bbox.
    private func trackingBBoxOverlay(bbox: CGRect, viewSize: CGSize) -> some View {
        // Convert Vision coords (0,0)=bottom-left to screen coords (0,0)=top-left
        let screenX = bbox.minX * viewSize.width
        let screenY = (1.0 - bbox.maxY) * viewSize.height  // Flip Y
        let screenW = bbox.width * viewSize.width
        let screenH = bbox.height * viewSize.height

        let color: Color = appState.tapTrackState == .tracking ? .cyan : .orange

        return ZStack {
            // Bounding box rectangle
            Rectangle()
                .stroke(color, lineWidth: 2)
                .frame(width: screenW, height: screenH)
                .position(x: screenX + screenW / 2, y: screenY + screenH / 2)

            // Corner brackets for better visibility
            cornerBrackets(
                x: screenX, y: screenY,
                width: screenW, height: screenH,
                color: color
            )

            // Center crosshair
            crosshair(
                x: screenX + screenW / 2,
                y: screenY + screenH / 2,
                color: color
            )
        }
        .allowsHitTesting(false)
    }

    private func cornerBrackets(x: CGFloat, y: CGFloat, width: CGFloat, height: CGFloat, color: Color) -> some View {
        let bracketLen: CGFloat = min(12, min(width, height) / 3)
        let lineWidth: CGFloat = 3

        return Canvas { context, _ in
            var path = Path()
            // Top-left
            path.move(to: CGPoint(x: x, y: y + bracketLen))
            path.addLine(to: CGPoint(x: x, y: y))
            path.addLine(to: CGPoint(x: x + bracketLen, y: y))
            // Top-right
            path.move(to: CGPoint(x: x + width - bracketLen, y: y))
            path.addLine(to: CGPoint(x: x + width, y: y))
            path.addLine(to: CGPoint(x: x + width, y: y + bracketLen))
            // Bottom-right
            path.move(to: CGPoint(x: x + width, y: y + height - bracketLen))
            path.addLine(to: CGPoint(x: x + width, y: y + height))
            path.addLine(to: CGPoint(x: x + width - bracketLen, y: y + height))
            // Bottom-left
            path.move(to: CGPoint(x: x + bracketLen, y: y + height))
            path.addLine(to: CGPoint(x: x, y: y + height))
            path.addLine(to: CGPoint(x: x, y: y + height - bracketLen))

            context.stroke(path, with: .color(color), lineWidth: lineWidth)
        }
        .allowsHitTesting(false)
    }

    private func crosshair(x: CGFloat, y: CGFloat, color: Color) -> some View {
        let size: CGFloat = 6
        return Canvas { context, _ in
            var path = Path()
            path.move(to: CGPoint(x: x - size, y: y))
            path.addLine(to: CGPoint(x: x + size, y: y))
            path.move(to: CGPoint(x: x, y: y - size))
            path.addLine(to: CGPoint(x: x, y: y + size))
            context.stroke(path, with: .color(color.opacity(0.7)), lineWidth: 1)
        }
        .allowsHitTesting(false)
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
