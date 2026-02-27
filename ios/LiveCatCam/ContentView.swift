import SwiftUI

/// Main UI: fullscreen camera preview with minimal overlay controls.
/// Tap to show/hide controls. Settings slide in from right.
struct ContentView: View {
    @State private var viewModel = StreamViewModel()
    @State private var livePulse = false
    @State private var pinchScale: CGFloat = 1.0

    var body: some View {
        ZStack {
            // Layer 1: Fullscreen camera preview
            CameraPreviewView(session: viewModel.cameraService.session)
                .ignoresSafeArea()
                .onTapGesture {
                    viewModel.toggleControls()
                }
                .gesture(pinchGesture)

            // Layer 2: Dim overlay when settings open
            if viewModel.showSettings {
                Color.black.opacity(0.5)
                    .ignoresSafeArea()
                    .onTapGesture {
                        viewModel.toggleSettings()
                    }
            }

            // Layer 3: Controls overlay
            if viewModel.showControls {
                controlsOverlay
                    .transition(.opacity)
            }

            // Layer 4: Thermal warning
            if viewModel.isThermalWarning {
                thermalWarningBadge
            }

            // Layer 5: Settings panel (slides from right)
            if viewModel.showSettings {
                HStack {
                    Spacer()
                    SettingsView(
                        isPresented: $viewModel.showSettings,
                        isStreaming: viewModel.isStreaming
                    )
                    .transition(.move(edge: .trailing))
                }
                .ignoresSafeArea()
            }
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear {
            livePulse = true
        }
    }

    // MARK: - Controls Overlay

    private var controlsOverlay: some View {
        VStack {
            // Top bar
            topBar
                .padding(.horizontal, 20)
                .padding(.top, 12)

            Spacer()

            // Bottom bar
            bottomBar
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
        }
    }

    // MARK: - Top Bar

    private var topBar: some View {
        HStack {
            // Status badge (LIVE / Idle)
            statusBadge

            // Elapsed time
            Text(viewModel.formattedTime)
                .font(.subheadline.monospacedDigit().weight(.medium))
                .foregroundColor(.white)

            Spacer()

            // Battery indicator
            batteryIndicator
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(Color.black.opacity(0.45))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var statusBadge: some View {
        HStack(spacing: 6) {
            if viewModel.isStreaming {
                Circle()
                    .fill(Color(hex: "FF3B30"))
                    .frame(width: 8, height: 8)
                    .scaleEffect(livePulse ? 1.0 : 0.5)
                    .opacity(livePulse ? 1.0 : 0.4)
                    .animation(
                        .easeInOut(duration: 0.8).repeatForever(autoreverses: true),
                        value: livePulse
                    )

                Text("LIVE")
                    .font(.caption.weight(.bold))
                    .foregroundColor(Color(hex: "FF3B30"))
            } else {
                Text(NSLocalizedString("idle", comment: ""))
                    .font(.caption.weight(.medium))
                    .foregroundColor(.white.opacity(0.45))
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(
            viewModel.isStreaming
            ? Color(hex: "FF3B30").opacity(0.2)
            : Color.white.opacity(0.1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private var batteryIndicator: some View {
        HStack(spacing: 4) {
            Image(systemName: viewModel.batteryIcon)
                .font(.caption)
                .foregroundColor(viewModel.batteryColor)
            Text("\(viewModel.batteryLevel)%")
                .font(.caption.monospacedDigit())
                .foregroundColor(viewModel.batteryColor)
        }
    }

    // MARK: - Bottom Bar

    private var bottomBar: some View {
        HStack {
            // Mic button
            micButton

            Spacer()

            // Start/Stop button
            startStopButton

            Spacer()

            // Zoom level
            zoomLabel

            // Settings button
            settingsButton
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 16)
        .background(Color.black.opacity(0.45))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var micButton: some View {
        Button {
            viewModel.toggleAudio()
        } label: {
            Image(systemName: viewModel.isAudioEnabled ? "mic.fill" : "mic.slash.fill")
                .font(.title3)
                .foregroundColor(viewModel.isAudioEnabled ? .white : Color(hex: "FF9500"))
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(ControlButtonStyle())
    }

    private var startStopButton: some View {
        Button {
            viewModel.toggleStreaming()
        } label: {
            VStack(spacing: 4) {
                ZStack {
                    Circle()
                        .stroke(Color.white.opacity(0.6), lineWidth: 3)
                        .frame(width: 56, height: 56)

                    if viewModel.isStreaming {
                        RoundedRectangle(cornerRadius: 4)
                            .fill(Color(hex: "FF3B30"))
                            .frame(width: 22, height: 22)
                    } else {
                        Circle()
                            .fill(Color(hex: "FF3B30"))
                            .frame(width: 46, height: 46)
                    }
                }

                Text(viewModel.isStreaming
                     ? NSLocalizedString("stop", comment: "")
                     : NSLocalizedString("start", comment: ""))
                    .font(.caption2.weight(.medium))
                    .foregroundColor(.white.opacity(0.7))
            }
        }
        .buttonStyle(ControlButtonStyle())
    }

    private var zoomLabel: some View {
        Text(viewModel.zoomText)
            .font(.subheadline.monospacedDigit().weight(.medium))
            .foregroundColor(.white)
            .frame(width: 50)
    }

    private var settingsButton: some View {
        Button {
            viewModel.toggleSettings()
        } label: {
            Image(systemName: "gearshape.fill")
                .font(.title3)
                .foregroundColor(.white.opacity(0.8))
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(ControlButtonStyle())
    }

    // MARK: - Thermal Warning

    private var thermalWarningBadge: some View {
        VStack {
            HStack {
                Spacer()
                HStack(spacing: 6) {
                    Image(systemName: "thermometer.sun.fill")
                        .foregroundColor(Color(hex: "FF9500"))
                    Text(NSLocalizedString("overheat_warning", comment: ""))
                        .font(.caption.weight(.semibold))
                        .foregroundColor(Color(hex: "FF9500"))
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Color(hex: "FF9500").opacity(0.2))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .padding(.trailing, 20)
            }
            .padding(.top, 60)
            Spacer()
        }
    }

    // MARK: - Pinch Gesture

    private var pinchGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                viewModel.handlePinchZoom(scale: value.magnification)
            }
    }
}

// MARK: - Button Style

struct ControlButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.92 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

// MARK: - WebSocket Status Indicator

struct WSStatusDot: View {
    let isConnected: Bool

    var body: some View {
        Circle()
            .fill(isConnected ? Color(hex: "34D449") : Color(hex: "FF3B30"))
            .frame(width: 6, height: 6)
    }
}
