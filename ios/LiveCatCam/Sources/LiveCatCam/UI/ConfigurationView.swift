import SwiftUI

struct ConfigurationView: View {
    @Environment(AppState.self) private var appState
    @State private var serverIP: String = ""
    @State private var srtPort: String = ""
    @State private var camID: String = ""
    @State private var selectedResolution: CameraConfig.Resolution = .hd1080p

    var body: some View {
        HStack(spacing: 0) {
            // Tap outside to close
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        appState.showSettings = false
                    }
                }

            // Settings panel
            VStack(alignment: .leading, spacing: 0) {
                // Header
                HStack {
                    Text("Settings")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(.white)
                    Spacer()
                    Button {
                        withAnimation(.easeInOut(duration: 0.3)) {
                            appState.showSettings = false
                        }
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 20))
                            .foregroundStyle(.white.opacity(0.5))
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)

                Divider().background(.white.opacity(0.15))

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        // Server section
                        settingsSection("SERVER") {
                            settingsField("IP Address", text: $serverIP, placeholder: "192.168.123.106")
                            settingsField("SRT Port", text: $srtPort, placeholder: "9000")
                        }

                        // Camera section
                        settingsSection("CAMERA") {
                            settingsField("Camera ID", text: $camID, placeholder: "CAM-1")
                            HStack {
                                Text("Resolution")
                                    .font(.system(size: 13))
                                    .foregroundStyle(.white.opacity(0.6))
                                Spacer()
                                Picker("", selection: $selectedResolution) {
                                    ForEach(CameraConfig.Resolution.allCases, id: \.self) { res in
                                        Text(res.rawValue).tag(res)
                                    }
                                }
                                .tint(.white)
                            }
                        }

                        // Status section
                        settingsSection("STATUS") {
                            statusRow("Connection", value: appState.isConnected ? "Connected" : "Off",
                                      color: appState.isConnected ? .green : .white.opacity(0.4))
                            statusRow("Streaming", value: appState.isStreaming ? "Active" : "Off",
                                      color: appState.isStreaming ? .green : .white.opacity(0.4))
                            statusRow("FPS", value: String(format: "%.0f", appState.currentFPS),
                                      color: .white)
                            statusRow("Thermal", value: thermalLabel, color: thermalColor)
                        }

                        // Presets
                        settingsSection("PRESETS") {
                            HStack(spacing: 10) {
                                presetButton("CAM-1") { applyPreset(.cam1) }
                                presetButton("CAM-2") { applyPreset(.cam2) }
                            }
                        }

                        // Save
                        Button {
                            saveConfig()
                            withAnimation(.easeInOut(duration: 0.3)) {
                                appState.showSettings = false
                            }
                            #if os(iOS)
                            UINotificationFeedbackGenerator().notificationOccurred(.success)
                            #endif
                        } label: {
                            Text("Save")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(.white)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 10)
                                .background(Color(red: 0.2, green: 0.5, blue: 1.0), in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                    .padding(16)
                }
            }
            .frame(width: 280)
            .background(.ultraThinMaterial)
        }
        .ignoresSafeArea()
        .onAppear { loadConfig() }
    }

    // MARK: - Components

    private func settingsSection<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.white.opacity(0.4))
            content()
        }
    }

    private func settingsField(_ label: String, text: Binding<String>, placeholder: String) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 13))
                .foregroundStyle(.white.opacity(0.6))
            Spacer()
            TextField(placeholder, text: text)
                .font(.system(size: 13, design: .monospaced))
                .foregroundStyle(.white)
                .multilineTextAlignment(.trailing)
                .frame(width: 130)
                #if os(iOS)
                .keyboardType(.decimalPad)
                .toolbar {
                    ToolbarItemGroup(placement: .keyboard) {
                        Spacer()
                        Button("Done") {
                            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                        }
                    }
                }
                #endif
        }
    }

    private func statusRow(_ label: String, value: String, color: Color) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 13))
                .foregroundStyle(.white.opacity(0.6))
            Spacer()
            Text(value)
                .font(.system(size: 13, weight: .medium, design: .monospaced))
                .foregroundStyle(color)
        }
    }

    private func presetButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 7)
                .background(.white.opacity(0.15), in: RoundedRectangle(cornerRadius: 6))
        }
    }

    // MARK: - Config

    private func loadConfig() {
        serverIP = appState.config.serverIP
        camID = appState.config.camID
        srtPort = "\(appState.config.srtPort)"
        selectedResolution = appState.config.resolution
    }

    private func saveConfig() {
        appState.config.serverIP = serverIP
        appState.config.camID = camID
        appState.config.srtPort = Int(srtPort) ?? 9000
        appState.config.resolution = selectedResolution
    }

    private func applyPreset(_ preset: CameraConfig) {
        serverIP = preset.serverIP
        camID = preset.camID
        srtPort = "\(preset.srtPort)"
        selectedResolution = preset.resolution
    }

    // MARK: - Thermal

    private var thermalLabel: String {
        switch appState.thermalState {
        case .nominal: return "OK"
        case .fair: return "Warm"
        case .serious: return "Hot"
        case .critical: return "Critical"
        @unknown default: return "?"
        }
    }

    private var thermalColor: Color {
        switch appState.thermalState {
        case .nominal: return .green
        case .fair: return .yellow
        case .serious: return .orange
        case .critical: return .red
        @unknown default: return .gray
        }
    }
}
