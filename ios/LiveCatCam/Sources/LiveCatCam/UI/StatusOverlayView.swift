import SwiftUI

struct StatusOverlayView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        VStack {
            // MARK: - Top bar
            topBar
                .padding(.horizontal, 20)
                .padding(.top, 8)

            Spacer()

            // MARK: - Bottom bar
            bottomBar
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
        }
    }

    // MARK: - Top Bar

    private var topBar: some View {
        HStack(spacing: 12) {
            // LIVE badge
            liveBadge

            // Elapsed time
            if appState.isLive {
                Text(appState.formattedTime)
                    .font(.system(size: 14, weight: .medium, design: .monospaced))
                    .foregroundStyle(.white)
            }

            Spacer()

            // Cat count
            if appState.catCount > 0 {
                HStack(spacing: 3) {
                    Image(systemName: "cat.fill")
                        .font(.system(size: 11))
                    Text("\(appState.catCount)")
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                }
                .foregroundStyle(.green)
            }

            // FPS
            Text("\(Int(appState.currentFPS))fps")
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(appState.currentFPS >= 25 ? .white.opacity(0.6) : .yellow)

            // Battery
            #if os(iOS)
            HStack(spacing: 3) {
                Image(systemName: appState.batteryIcon)
                    .font(.system(size: 11))
                Text("\(Int(appState.batteryLevel * 100))%")
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(appState.batteryColor)
            #endif
        }
    }

    // MARK: - LIVE Badge

    private var liveBadge: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(appState.isLive ? Color(red: 1, green: 0.23, blue: 0.19) : .white.opacity(0.45))
                .frame(width: 8, height: 8)
                .modifier(PulseModifier(isActive: appState.isLive))

            Text(appState.isLive ? "LIVE" : "IDLE")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(appState.isLive ? .white : .white.opacity(0.45))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule()
                .fill(appState.isLive ? Color(red: 1, green: 0.23, blue: 0.19).opacity(0.85) : .white.opacity(0.15))
        )
    }

    // MARK: - Bottom Bar

    private var bottomBar: some View {
        HStack(spacing: 0) {
            // Mic button
            OverlayButton(icon: appState.isMuted ? "mic.slash.fill" : "mic.fill",
                          color: appState.isMuted ? .red : .white) {
                appState.isMuted.toggle()
                #if os(iOS)
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
                #endif
            }

            Spacer()

            // Connection status + protocol + server
            HStack(spacing: 4) {
                Image(systemName: appState.isConnected ? "wifi" : "wifi.slash")
                    .font(.system(size: 13))
                    .foregroundStyle(appState.isConnected ? .green : .white.opacity(0.35))
                if appState.isLive {
                    Text(appState.config.streamProtocol.rawValue)
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 4)
                        .padding(.vertical, 1)
                        .background(
                            appState.config.streamProtocol == .srt ? Color.cyan : Color.orange,
                            in: RoundedRectangle(cornerRadius: 3)
                        )
                    Text(appState.config.serverIP)
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(.white.opacity(0.5))
                }
            }

            Spacer()

            // Start/Stop button (center)
            startStopButton

            Spacer()

            // Zoom indicator
            Text(String(format: "%.1fx", appState.currentZoom))
                .font(.system(size: 13, weight: .medium, design: .monospaced))
                .foregroundStyle(.white.opacity(0.7))

            Spacer()

            // Settings gear
            OverlayButton(icon: "gearshape.fill", color: .white) {
                withAnimation(.easeInOut(duration: 0.3)) {
                    appState.showSettings.toggle()
                }
                #if os(iOS)
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
                #endif
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(.black.opacity(0.45))
        )
    }

    // MARK: - Start/Stop Button

    private var startStopButton: some View {
        Button {
            Task {
                if appState.isLive {
                    await appState.stopStreaming()
                    #if os(iOS)
                    let gen = UIImpactFeedbackGenerator(style: .medium)
                    gen.impactOccurred()
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { gen.impactOccurred() }
                    #endif
                } else {
                    await appState.startStreaming()
                    #if os(iOS)
                    UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
                    #endif
                }
            }
        } label: {
            ZStack {
                Circle()
                    .stroke(.white.opacity(0.5), lineWidth: 3)
                    .frame(width: 56, height: 56)

                if appState.isLive {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color(red: 1, green: 0.23, blue: 0.19))
                        .frame(width: 22, height: 22)
                } else {
                    Circle()
                        .fill(Color(red: 1, green: 0.23, blue: 0.19))
                        .frame(width: 44, height: 44)
                }
            }
        }
        .buttonStyle(ScaleButtonStyle())
    }
}

// MARK: - Overlay Button

struct OverlayButton: View {
    let icon: String
    var color: Color = .white
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 18))
                .foregroundStyle(color)
                .frame(width: 44, height: 44)
        }
        .buttonStyle(ScaleButtonStyle())
    }
}

// MARK: - Scale Button Style

struct ScaleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.92 : 1.0)
            .animation(.easeInOut(duration: 0.1), value: configuration.isPressed)
    }
}

// MARK: - Pulse Animation

struct PulseModifier: ViewModifier {
    let isActive: Bool
    @State private var pulsing = false

    func body(content: Content) -> some View {
        content
            .opacity(isActive ? (pulsing ? 0.3 : 1.0) : 1.0)
            .onAppear {
                if isActive { pulsing = true }
            }
            .onChange(of: isActive) { _, active in
                pulsing = active
            }
            .animation(
                isActive ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true) : .default,
                value: pulsing
            )
    }
}
