import SwiftUI

/// Slide-in settings panel from the right side.
struct SettingsView: View {
    @ObservedObject var settings = AppSettings.shared
    @Binding var isPresented: Bool
    let isStreaming: Bool

    @FocusState private var focusedField: Field?

    enum Field { case ip, udpPort, wsPort }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Text(NSLocalizedString("settings", comment: ""))
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
                Button {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                        isPresented = false
                    }
                } label: {
                    Image(systemName: "xmark")
                        .font(.body.weight(.semibold))
                        .foregroundColor(.white.opacity(0.7))
                        .frame(width: 32, height: 32)
                        .background(Color.white.opacity(0.15))
                        .clipShape(Circle())
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 12)

            Divider()
                .background(Color.white.opacity(0.2))

            ScrollView(.vertical, showsIndicators: false) {
                VStack(alignment: .leading, spacing: 20) {
                    // Server IP
                    settingsField(
                        title: NSLocalizedString("server_ip", comment: ""),
                        text: $settings.serverIP,
                        placeholder: "192.168.123.xxx",
                        keyboard: .decimalPad,
                        field: .ip
                    )

                    // UDP Port
                    settingsField(
                        title: NSLocalizedString("udp_port", comment: ""),
                        text: Binding(
                            get: { String(settings.udpPort) },
                            set: { settings.udpPort = Int($0) ?? 9000 }
                        ),
                        placeholder: "9000",
                        keyboard: .numberPad,
                        field: .udpPort
                    )

                    // Video Quality
                    VStack(alignment: .leading, spacing: 8) {
                        Text(NSLocalizedString("quality", comment: ""))
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.6))

                        HStack(spacing: 8) {
                            ForEach(VideoQuality.allCases, id: \.self) { quality in
                                Button {
                                    settings.videoQuality = quality
                                } label: {
                                    Text(quality.rawValue)
                                        .font(.subheadline.weight(.medium))
                                        .foregroundColor(settings.videoQuality == quality ? .black : .white)
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 8)
                                        .background(
                                            settings.videoQuality == quality
                                            ? Color.white
                                            : Color.white.opacity(0.15)
                                        )
                                        .cornerRadius(8)
                                }
                                .disabled(isStreaming)
                            }
                        }
                    }

                    // Audio
                    VStack(alignment: .leading, spacing: 8) {
                        Text(NSLocalizedString("audio", comment: ""))
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.6))

                        HStack(spacing: 8) {
                            toggleButton("ON", isSelected: settings.audioEnabled) {
                                settings.audioEnabled = true
                            }
                            toggleButton("OFF", isSelected: !settings.audioEnabled) {
                                settings.audioEnabled = false
                            }
                        }
                    }

                    // Auto Reconnect
                    HStack {
                        Text(NSLocalizedString("auto_reconnect", comment: ""))
                            .font(.subheadline)
                            .foregroundColor(.white)
                        Spacer()
                        Toggle("", isOn: $settings.autoReconnect)
                            .labelsHidden()
                            .tint(Color(hex: "34D449"))
                    }

                    // WebSocket Port
                    settingsField(
                        title: NSLocalizedString("ws_port", comment: ""),
                        text: Binding(
                            get: { String(settings.wsPort) },
                            set: { settings.wsPort = Int($0) ?? 8081 }
                        ),
                        placeholder: "8081",
                        keyboard: .numberPad,
                        field: .wsPort
                    )

                    Spacer(minLength: 20)

                    // Version footer
                    HStack {
                        Spacer()
                        Text("v1.0.0  LiveCatCam")
                            .font(.caption2)
                            .foregroundColor(.white.opacity(0.3))
                        Spacer()
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 16)
            }
        }
        .frame(width: 280)
        .background(.ultraThinMaterial)
        .environment(\.colorScheme, .dark)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: .black.opacity(0.5), radius: 20, x: -5, y: 0)
        .onTapGesture {
            focusedField = nil
        }
    }

    // MARK: - Components

    @ViewBuilder
    private func settingsField(
        title: String,
        text: Binding<String>,
        placeholder: String,
        keyboard: UIKeyboardType,
        field: Field
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundColor(.white.opacity(0.6))
            TextField(placeholder, text: text)
                .font(.subheadline.monospaced())
                .foregroundColor(.white)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(Color.white.opacity(0.1))
                .cornerRadius(8)
                .keyboardType(keyboard)
                .focused($focusedField, equals: field)
                .disabled(isStreaming)
        }
    }

    @ViewBuilder
    private func toggleButton(_ label: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.subheadline.weight(.medium))
                .foregroundColor(isSelected ? .black : .white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .background(isSelected ? Color.white : Color.white.opacity(0.15))
                .cornerRadius(8)
        }
    }
}
