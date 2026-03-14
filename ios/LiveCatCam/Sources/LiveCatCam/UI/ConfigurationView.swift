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
    @State private var selectedServerHost: String? = nil

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
                                    Text("OBS setup — UDP mode:")
                                        .font(.system(size: 11))
                                        .foregroundStyle(.white.opacity(0.5))
                                    obsStep("1", "Sources → + → Media Source")
                                    obsStep("2", "Input: udp://@0.0.0.0:9000")
                                    obsStep("3", "Format: mpegts → OK")

                                    Text("OBS setup — SRT mode (recommended):")
                                        .font(.system(size: 11))
                                        .foregroundStyle(.white.opacity(0.5))
                                        .padding(.top, 6)
                                    obsStep("1", "Sources → + → Media Source")
                                    obsStep("2", "Input: srt://0.0.0.0:9000?mode=listener")
                                    obsStep("3", "Format: mpegts → OK")

                                    obsStep("→", "Enter OBS PC/Mac IP above & tap Start")
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
                                let isSelected = selectedServerHost == server.host
                                Button {
                                    serverIP = server.host
                                    selectedServerHost = server.host
                                    #if os(iOS)
                                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                                    #endif
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: isSelected ? "checkmark.circle.fill" : (server.type == .obs ? "tv.fill" : "antenna.radiowaves.left.and.right"))
                                            .foregroundStyle(isSelected ? .green : (server.type == .obs ? .purple : .cyan))
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
                                        Text(isSelected ? "Selected ✓" : "Use")
                                            .font(.system(size: 11, weight: .medium))
                                            .foregroundStyle(isSelected ? .green : .white.opacity(0.8))
                                            .padding(.horizontal, 8)
                                            .padding(.vertical, 4)
                                            .background(
                                                isSelected ? Color.green.opacity(0.2) : .white.opacity(0.15),
                                                in: RoundedRectangle(cornerRadius: 4)
                                            )
                                    }
                                    .padding(8)
                                    .background(
                                        isSelected ? Color.green.opacity(0.1) : .white.opacity(0.08),
                                        in: RoundedRectangle(cornerRadius: 8)
                                    )
                                    .overlay(
                                        isSelected ? RoundedRectangle(cornerRadius: 8).stroke(.green.opacity(0.4), lineWidth: 1) : nil
                                    )
                                    .animation(.easeInOut(duration: 0.2), value: isSelected)
                                }
                            }

                            settingsField("IP Address", text: $serverIP, placeholder: "192.168.123.xxx", keyboardType: .asciiCapable)
                            settingsField("SRT Port", text: $srtPort, placeholder: "9000", keyboardType: .numberPad)
                        }

                        // Camera section
                        settingsSection("CAMERA") {
                            settingsField("Camera ID", text: $camID, placeholder: "CAM-1", keyboardType: .asciiCapable)
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
                                                Text(proto == .udp ? "Fastest — may have rare glitches"
                                     : "Best quality — reliable, ~200ms delay")
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
                                || selectedProtocol != appState.config.streamProtocol
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
                    || selectedProtocol != appState.config.streamProtocol
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

    private func settingsField(_ label: String, text: Binding<String>, placeholder: String,
                               keyboardType: UIKeyboardType = .default) -> some View {
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
                .keyboardType(keyboardType)
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
        selectedServerHost = appState.config.serverIP
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

                    helpSection(icon: "tv.fill", title: "Quick Start — OBS Direct (No Server Needed)") {
                        helpStep("1", "Install OBS Studio on your PC/Mac")
                        helpStep("2", "Add Media Source in OBS (see SRT or UDP setup below)")
                        helpStep("3", "Find your PC/Mac IP address (Settings → WiFi → IP)")
                        helpStep("4", "Open OLiveCam → Settings → enter PC/Mac IP")
                        helpStep("5", "Choose protocol: SRT (recommended) or UDP")
                        helpStep("6", "Tap Save → Tap Start")
                        Text("That's it! No server software needed. OBS receives video directly from your iPhone.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .padding(.top, 4)
                    }

                    helpSection(icon: "shield.checkered", title: "OBS Setup — SRT (Recommended)") {
                        helpStep("1", "Open OBS Studio on your PC/Mac")
                        helpStep("2", "Sources panel → tap +")
                        helpStep("3", "Select Media Source → OK")
                        helpStep("4", "Uncheck Local File")
                        helpStep("5", "Input:  srt://0.0.0.0:9000?mode=listener")
                        helpStep("6", "Input Format:  mpegts")
                        helpStep("7", "Click OK")
                        helpStep("8", "Select SRT protocol in app Settings")
                        helpStep("9", "Enter OBS PC/Mac IP → tap Start")
                        Text("SRT provides reliable delivery with ~200ms latency. Best for stable streams.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .padding(.top, 4)
                    }

                    helpSection(icon: "video.fill", title: "OBS Setup — UDP (Low Latency)") {
                        helpStep("1", "Open OBS Studio on your PC/Mac")
                        helpStep("2", "Sources panel → tap +")
                        helpStep("3", "Select Media Source → OK")
                        helpStep("4", "Uncheck Local File")
                        helpStep("5", "Input:  udp://@0.0.0.0:9000")
                        helpStep("6", "Input Format:  mpegts")
                        helpStep("7", "Click OK")
                        helpStep("8", "Enter Mac/PC IP in app → tap Start")
                        Text("UDP has lowest latency but may occasionally glitch on packet loss.")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .padding(.top, 4)
                    }

                    helpSection(icon: "network", title: "Network Environments") {
                        helpStep("🏠", "Same Wi-Fi — Just enter PC/Mac IP. Works out of the box.")
                        helpStep("🌐", "Different Wi-Fi — Set up port forwarding on OBS router (port 9000 + 8081).")
                        helpStep("📱", "Cellular (LTE/5G) — Use Tailscale VPN on both iPhone and PC. Enter Tailscale IP (100.x.x.x).")
                        helpStep("📡", "Hotspot — Connect PC to iPhone hotspot. Enter PC IP shown in hotspot settings.")
                        Text("Tip: Install Tailscale (free) for the easiest remote streaming setup — no port forwarding needed!")
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
