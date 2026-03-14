import SwiftUI

struct ConfigurationView: View {
    @Environment(AppState.self) private var appState
    @State private var serverIP: String = ""
    @State private var srtPort: String = ""
    @State private var camID: String = ""
    @State private var selectedResolution: CameraConfig.Resolution = .hd1080p
    @State private var selectedProtocol: CameraConfig.StreamProtocol = .udp
    @State private var discovery = ServiceDiscoveryManager()
    @State private var showUnsavedAlert = false
    @State private var showHelpSheet = false
    @State private var showObsHint = false

    var body: some View {
        HStack(spacing: 0) {
            // Tap outside to close (with unsaved check)
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture { dismissWithCheck() }

            // Settings panel
            VStack(alignment: .leading, spacing: 0) {
                // Header
                HStack {
                    Text("Settings")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(.white)
                    Spacer()
                    Button { showHelpSheet = true } label: {
                        Image(systemName: "info.circle")
                            .font(.system(size: 20))
                            .foregroundStyle(.white.opacity(0.6))
                    }
                    Button { dismissWithCheck() } label: {
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
                            // Auto-discovery
                            HStack {
                                Button {
                                    showObsHint = false
                                    discovery.startBrowsing()
                                } label: {
                                    HStack(spacing: 6) {
                                        if discovery.isSearching {
                                            ProgressView()
                                                .scaleEffect(0.7)
                                                .tint(.white)
                                        }
                                        Image(systemName: "antenna.radiowaves.left.and.right")
                                        Text(discovery.isSearching ? "Searching..." : "Auto Discover")
                                    }
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 7)
                                    .background(
                                        discovery.isSearching
                                            ? Color.orange.opacity(0.4)
                                            : Color(red: 0.2, green: 0.6, blue: 0.3),
                                        in: RoundedRectangle(cornerRadius: 6)
                                    )
                                }
                                .disabled(discovery.isSearching)
                                Spacer()
                            }

                            // OBS hint when search done with no results
                            if showObsHint && discovery.servers.isEmpty {
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack(spacing: 6) {
                                        Image(systemName: "exclamationmark.triangle.fill")
                                            .foregroundStyle(.orange)
                                            .font(.system(size: 12))
                                        Text("Server not found. Is live_auto.py running?")
                                            .font(.system(size: 12, weight: .semibold))
                                            .foregroundStyle(.orange)
                                    }
                                    Text("OBS setup (for direct connection):")
                                        .font(.system(size: 11))
                                        .foregroundStyle(.white.opacity(0.5))
                                    obsStep("1", "Sources → + → Media Source")
                                    obsStep("2", "Input: udp://@0.0.0.0:9000")
                                    obsStep("3", "Format: mpegts → OK")
                                    obsStep("4", "Enter Mac IP above & tap Start")
                                }
                                .padding(10)
                                .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(.orange.opacity(0.3), lineWidth: 1)
                                )
                            }

                            // Found servers
                            ForEach(discovery.servers) { server in
                                Button {
                                    serverIP = server.host
                                    #if os(iOS)
                                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                                    #endif
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: server.type == .obs ? "tv.fill" : "checkmark.circle.fill")
                                            .foregroundStyle(server.type == .obs ? .purple : .green)
                                            .font(.system(size: 14))
                                        VStack(alignment: .leading, spacing: 2) {
                                            HStack(spacing: 4) {
                                                Text(server.name)
                                                    .font(.system(size: 12, weight: .semibold))
                                                    .foregroundStyle(.white)
                                                Text(server.type == .obs ? "OBS" : "LiveCat")
                                                    .font(.system(size: 9, weight: .bold))
                                                    .foregroundStyle(server.type == .obs ? .purple : .green)
                                                    .padding(.horizontal, 4)
                                                    .padding(.vertical, 1)
                                                    .background(
                                                        (server.type == .obs ? Color.purple : Color.green).opacity(0.2),
                                                        in: RoundedRectangle(cornerRadius: 3)
                                                    )
                                            }
                                            Text("\(server.host):\(server.port)")
                                                .font(.system(size: 11, design: .monospaced))
                                                .foregroundStyle(.white.opacity(0.6))
                                        }
                                        Spacer()
                                        Text("Use")
                                            .font(.system(size: 11, weight: .medium))
                                            .foregroundStyle(.white.opacity(0.8))
                                            .padding(.horizontal, 8)
                                            .padding(.vertical, 4)
                                            .background(.white.opacity(0.15), in: RoundedRectangle(cornerRadius: 4))
                                    }
                                    .padding(8)
                                    .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                                }
                            }

                            settingsField("IP Address", text: $serverIP, placeholder: "192.168.123.xxx")
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

                        // Protocol section
                        settingsSection("PROTOCOL") {
                            VStack(alignment: .leading, spacing: 6) {
                                ForEach(CameraConfig.StreamProtocol.allCases, id: \.self) { proto in
                                    Button {
                                        selectedProtocol = proto
                                    } label: {
                                        HStack(spacing: 8) {
                                            Image(systemName: selectedProtocol == proto ? "circle.fill" : "circle")
                                                .font(.system(size: 12))
                                                .foregroundStyle(selectedProtocol == proto ? .cyan : .white.opacity(0.4))
                                            VStack(alignment: .leading, spacing: 1) {
                                                Text(proto.rawValue)
                                                    .font(.system(size: 12, weight: .semibold))
                                                    .foregroundStyle(.white)
                                                Text(proto == .udp ? "OBS direct — lowest latency" : "live_auto.py — block-loss recovery")
                                                    .font(.system(size: 10))
                                                    .foregroundStyle(.white.opacity(0.45))
                                            }
                                            Spacer()
                                        }
                                    }
                                }
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

                        // Save (highlighted when changes detected)
                        Button {
                            let networkChanged = serverIP != appState.config.serverIP
                                || Int(srtPort) ?? 9000 != appState.config.srtPort
                            saveConfig()
                            withAnimation(.easeInOut(duration: 0.3)) {
                                appState.showSettings = false
                            }
                            #if os(iOS)
                            UINotificationFeedbackGenerator().notificationOccurred(.success)
                            #endif
                            if networkChanged {
                                Task { await appState.applyNetworkConfig() }
                            }
                        } label: {
                            HStack {
                                if hasChanges {
                                    Image(systemName: "circle.fill")
                                        .font(.system(size: 6))
                                        .foregroundStyle(.yellow)
                                }
                                Text(hasChanges ? "Save Changes" : "Save")
                                    .font(.system(size: 14, weight: .semibold))
                            }
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .background(
                                hasChanges
                                    ? Color.orange
                                    : Color(red: 0.2, green: 0.5, blue: 1.0),
                                in: RoundedRectangle(cornerRadius: 8)
                            )
                            .animation(.easeInOut(duration: 0.2), value: hasChanges)
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
        .onChange(of: discovery.isSearching) { _, searching in
            if !searching && discovery.servers.isEmpty {
                showObsHint = true
            }
        }
        .sheet(isPresented: $showHelpSheet) {
            HelpGuideView()
        }
        .alert("Unsaved Changes", isPresented: $showUnsavedAlert) {
            Button("Save & Close") {
                let networkChanged = serverIP != appState.config.serverIP
                    || Int(srtPort) ?? 9000 != appState.config.srtPort
                saveConfig()
                withAnimation(.easeInOut(duration: 0.3)) {
                    appState.showSettings = false
                }
                if networkChanged {
                    Task { await appState.applyNetworkConfig() }
                }
            }
            Button("Discard", role: .destructive) {
                withAnimation(.easeInOut(duration: 0.3)) {
                    appState.showSettings = false
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("You have unsaved changes. Save before closing?")
        }
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

    private func obsStep(_ number: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(number)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(.white.opacity(0.4))
                .frame(width: 14)
            Text(text)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(.white.opacity(0.75))
                .fixedSize(horizontal: false, vertical: true)
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

    // MARK: - Change Detection

    private var hasChanges: Bool {
        serverIP != appState.config.serverIP
        || camID != appState.config.camID
        || Int(srtPort) ?? 9000 != appState.config.srtPort
        || selectedResolution != appState.config.resolution
        || selectedProtocol != appState.config.streamProtocol
    }

    private func dismissWithCheck() {
        if hasChanges {
            showUnsavedAlert = true
        } else {
            withAnimation(.easeInOut(duration: 0.3)) {
                appState.showSettings = false
            }
        }
    }

    // MARK: - Config

    private func loadConfig() {
        serverIP = appState.config.serverIP
        camID = appState.config.camID
        srtPort = "\(appState.config.srtPort)"
        selectedResolution = appState.config.resolution
        selectedProtocol = appState.config.streamProtocol
    }

    private func saveConfig() {
        appState.config.serverIP = serverIP
        appState.config.camID = camID
        appState.config.srtPort = Int(srtPort) ?? 9000
        appState.config.resolution = selectedResolution
        appState.config.streamProtocol = selectedProtocol
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

// MARK: - Help Guide Sheet

struct HelpGuideView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {

                    helpSection(icon: "server.rack", title: "Server Setup (PC)") {
                        helpStep("1", "Install Python 3 on your PC")
                        helpStep("2", "Run: python live_auto.py")
                        helpStep("3", "Server registers on local network automatically")
                        helpStep("4", "Note your PC's IP address (e.g. 192.168.1.x)")
                    }

                    helpSection(icon: "iphone", title: "App Setup") {
                        helpStep("1", "Tap ⚙ to open Settings")
                        helpStep("2", "Tap Auto Discover — app finds the server")
                        helpStep("3", "Or enter PC's IP address manually")
                        helpStep("4", "Tap Start on main screen to begin streaming")
                    }

                    helpSection(icon: "video.fill", title: "OBS Setup (Without Server)") {
                        helpStep("1", "Open OBS Studio on your PC/Mac")
                        helpStep("2", "Sources panel → tap +")
                        helpStep("3", "Select Media Source → OK")
                        helpStep("4", "Uncheck Local File")
                        helpStep("5", "Input:  udp://@0.0.0.0:9000")
                        helpStep("6", "Input Format:  mpegts")
                        helpStep("7", "Click OK")
                        helpStep("8", "Enter Mac/PC IP in app → tap Start")
                        Text("💡 Make sure your iPhone and PC are on the same Wi-Fi network.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .padding(.top, 4)
                    }

                    helpSection(icon: "wifi", title: "Troubleshooting") {
                        helpStep("•", "No video in OBS? Check IP address matches your PC")
                        helpStep("•", "Auto Discover fails? Run live_auto.py on PC first")
                        helpStep("•", "Choppy video? Move closer to Wi-Fi router")
                        helpStep("•", "App disconnects? Check PC firewall (allow UDP 9000)")
                    }
                }
                .padding(20)
            }
            .navigationTitle("How to Use")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func helpSection<Content: View>(icon: String, title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .foregroundStyle(.blue)
                    .font(.system(size: 16, weight: .semibold))
                Text(title)
                    .font(.system(size: 16, weight: .semibold))
            }
            VStack(alignment: .leading, spacing: 6) {
                content()
            }
            .padding(12)
            .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 10))
        }
    }

    private func helpStep(_ number: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(number)
                .font(.system(size: 13, weight: .bold, design: .monospaced))
                .foregroundStyle(.blue)
                .frame(width: 18)
            Text(text)
                .font(.system(size: 13))
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
