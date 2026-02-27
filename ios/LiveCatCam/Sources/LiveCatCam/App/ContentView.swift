import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var appState
    @State private var pinchScale: CGFloat = 1.0
    @State private var lastZoom: Double = 1.0

    var body: some View {
        ZStack {
            // Fullscreen camera preview
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
                .onTapGesture {
                    withAnimation(.easeInOut(duration: 0.25)) {
                        appState.showControls.toggle()
                    }
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

            // Debug log overlay (visible when controls hidden)
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
        }
        .preferredColorScheme(.dark)
        #if os(iOS)
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        #endif
    }
}
