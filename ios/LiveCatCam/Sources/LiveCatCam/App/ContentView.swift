import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var appState
    @State private var pinchScale: CGFloat = 1.0
    @State private var lastZoom: Double = 1.0

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Fullscreen camera preview with tracking overlay
                DebugCameraView()
                    .ignoresSafeArea()
                    .gesture(
                        MagnifyGesture()
                            .onChanged { value in
                                let newZoom = lastZoom * value.magnification
                                let clamped = min(max(newZoom, 1.0), 10.0)
                                appState.setZoomLevel(clamped)
                            }
                            .onEnded { value in
                                lastZoom = appState.currentZoom
                            }
                    )
                    .onTapGesture { location in
                        handleTap(at: location, in: geometry.size)
                    }
                    .onLongPressGesture(minimumDuration: 0.5) {
                        // Long press: toggle controls
                        withAnimation(.easeInOut(duration: 0.25)) {
                            appState.showControls.toggle()
                        }
                    }

                // Tap-to-Track indicator
                if appState.isTapTracking {
                    tapTrackIndicator
                }

                // Overlay controls
                if appState.showControls {
                    StatusOverlayView()
                        .transition(.opacity)
                }

                // Settings panel (slide from right)
                if appState.showSettings {
                    ConfigurationView()
                        .transition(.move(edge: .trailing))
                }

                // Debug log overlay (only in debug builds)
                #if DEBUG
                if !appState.debugLog.isEmpty {
                    VStack {
                        Spacer()
                        Text(appState.debugLog)
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(.green.opacity(0.7))
                            .padding(6)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.black.opacity(0.5))
                    }
                    .allowsHitTesting(false)
                }
                #endif
            }
        }
        .preferredColorScheme(.dark)
        #if os(iOS)
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        #endif
    }

    // MARK: - Tap-to-Track

    /// Convert screen tap location to Vision normalized coordinates and initiate tracking.
    private func handleTap(at screenLocation: CGPoint, in viewSize: CGSize) {
        // Convert screen coordinates to Vision normalized coordinates
        // Screen: (0,0) = top-left, Vision: (0,0) = bottom-left
        let normalizedX = screenLocation.x / viewSize.width
        let normalizedY = 1.0 - (screenLocation.y / viewSize.height)  // Flip Y axis
        let visionPoint = CGPoint(x: normalizedX, y: normalizedY)

        appState.handleTapToTrack(at: visionPoint)

        #if os(iOS)
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        #endif
    }

    // MARK: - Tap-to-Track Indicator

    private var tapTrackIndicator: some View {
        VStack {
            HStack {
                Spacer()
                HStack(spacing: 6) {
                    Circle()
                        .fill(tapTrackColor)
                        .frame(width: 8, height: 8)

                    Text(tapTrackLabel)
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundStyle(.white)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(
                    Capsule()
                        .fill(tapTrackColor.opacity(0.7))
                )

                Button {
                    appState.stopTapToTrack()
                    #if os(iOS)
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    #endif
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 20))
                        .foregroundStyle(.white.opacity(0.8))
                }
                .padding(.trailing, 8)
            }
            .padding(.top, 50)

            Spacer()
        }
        .allowsHitTesting(true)
    }

    private var tapTrackColor: Color {
        switch appState.tapTrackState {
        case .tracking: return .cyan
        case .searching: return .orange
        case .idle: return .gray
        }
    }

    private var tapTrackLabel: String {
        switch appState.tapTrackState {
        case .tracking: return "TRACKING"
        case .searching: return "SEARCHING"
        case .idle: return "IDLE"
        }
    }
}
