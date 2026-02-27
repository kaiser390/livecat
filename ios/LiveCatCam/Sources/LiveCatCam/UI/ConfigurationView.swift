import SwiftUI

struct ConfigurationView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.dismiss) private var dismiss

    @State private var serverIP: String = ""
    @State private var camID: String = ""
    @State private var srtPort: String = ""
    @State private var selectedResolution: CameraConfig.Resolution = .hd720p

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    HStack {
                        Text("IP Address")
                        Spacer()
                        TextField("192.168.1.100", text: $serverIP)
                            .multilineTextAlignment(.trailing)
                            #if os(iOS)
                            .keyboardType(.decimalPad)
                            #endif
                    }
                    HStack {
                        Text("Metadata Port")
                        Spacer()
                        Text("8081")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Camera") {
                    HStack {
                        Text("Camera ID")
                        Spacer()
                        TextField("CAM-1", text: $camID)
                            .multilineTextAlignment(.trailing)
                    }
                    HStack {
                        Text("SRT Port")
                        Spacer()
                        TextField("9000", text: $srtPort)
                            .multilineTextAlignment(.trailing)
                            #if os(iOS)
                            .keyboardType(.numberPad)
                            #endif
                    }
                    Picker("Resolution", selection: $selectedResolution) {
                        ForEach(CameraConfig.Resolution.allCases, id: \.self) { res in
                            Text(res.rawValue).tag(res)
                        }
                    }
                }

                Section("Status") {
                    LabeledContent("Connection") {
                        Text(appState.isConnected ? "Connected" : "Disconnected")
                            .foregroundStyle(appState.isConnected ? .green : .red)
                    }
                    LabeledContent("Streaming") {
                        Text(appState.isStreaming ? "Active" : "Inactive")
                            .foregroundStyle(appState.isStreaming ? .green : .red)
                    }
                    LabeledContent("FPS") {
                        Text(String(format: "%.1f", appState.currentFPS))
                    }
                    LabeledContent("Thermal") {
                        Text(thermalLabel)
                            .foregroundStyle(thermalColor)
                    }
                }

                Section("Presets") {
                    Button("CAM-1 (Nana)") {
                        applyPreset(.cam1)
                    }
                    Button("CAM-2 (Toto)") {
                        applyPreset(.cam2)
                    }
                }
            }
            .navigationTitle("Configuration")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saveConfig()
                        dismiss()
                    }
                }
            }
            .onAppear {
                loadConfig()
            }
        }
    }

    // MARK: - Config loading/saving

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

    // MARK: - Thermal display

    private var thermalLabel: String {
        switch appState.thermalState {
        case .nominal: return "Normal"
        case .fair: return "Warm"
        case .serious: return "Hot"
        case .critical: return "Critical"
        @unknown default: return "Unknown"
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
