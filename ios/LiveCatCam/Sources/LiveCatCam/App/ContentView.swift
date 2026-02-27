import SwiftUI

struct ContentView: View {
    @Environment(AppState.self) private var appState
    @State private var showConfig = false

    var body: some View {
        ZStack {
            // Camera preview layer
            DebugCameraView()
                .ignoresSafeArea()

            // HUD overlay
            StatusOverlayView()

            // Debug log overlay
            if !appState.debugLog.isEmpty {
                VStack {
                    Spacer()
                    Text(appState.debugLog)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.green)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.black.opacity(0.7))
                        .padding(.bottom, 80)
                }
            }

            // Top bar: settings + start/stop
            VStack {
                HStack {
                    // Start/Stop button
                    Button {
                        Task {
                            if appState.isLive {
                                await appState.stopStreaming()
                            } else {
                                await appState.startStreaming()
                            }
                        }
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: appState.isLive ? "stop.circle.fill" : "play.circle.fill")
                                .font(.title2)
                            Text(appState.isLive ? "STOP" : "START")
                                .font(.caption.bold())
                        }
                        .foregroundStyle(appState.isLive ? .red : .green)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(.ultraThinMaterial, in: Capsule())
                    }

                    Spacer()

                    // Settings button
                    Button {
                        showConfig = true
                    } label: {
                        Image(systemName: "gear")
                            .font(.title2)
                            .foregroundStyle(.white)
                            .padding(12)
                            .background(.ultraThinMaterial, in: Circle())
                    }
                }
                .padding()
                Spacer()
            }
        }
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showConfig) {
            ConfigurationView()
        }
    }
}
