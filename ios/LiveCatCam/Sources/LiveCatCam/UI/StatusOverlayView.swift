import SwiftUI

struct StatusOverlayView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        VStack {
            Spacer()
            HStack(spacing: 16) {
                // Tracking state
                StatusBadge(
                    icon: trackingIcon,
                    label: appState.trackingState.rawValue.uppercased(),
                    color: trackingColor
                )

                // Cat count
                StatusBadge(
                    icon: "cat.fill",
                    label: "\(appState.catCount)",
                    color: appState.catCount > 0 ? .green : .gray
                )

                // Activity score
                StatusBadge(
                    icon: "bolt.fill",
                    label: String(format: "%.0f", appState.activityScore),
                    color: scoreColor
                )

                Spacer()

                // FPS
                StatusBadge(
                    icon: "video.fill",
                    label: String(format: "%.0f", appState.currentFPS),
                    color: fpsColor
                )

                // Connection
                StatusBadge(
                    icon: appState.isConnected ? "wifi" : "wifi.slash",
                    label: appState.isConnected ? "ON" : "OFF",
                    color: appState.isConnected ? .green : .red
                )
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
            .background(.ultraThinMaterial)

            // Motor position bar
            HStack(spacing: 8) {
                Image(systemName: "arrow.left.and.right")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(String(format: "P:%.0f T:%.0f", appState.motorPan, appState.motorTilt))
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)

                Spacer()

                if appState.thermalState == .critical {
                    Label("HOT", systemImage: "thermometer.sun.fill")
                        .font(.caption2)
                        .foregroundStyle(.red)
                }

                if appState.isStreaming {
                    Label("SRT", systemImage: "dot.radiowaves.left.and.right")
                        .font(.caption2)
                        .foregroundStyle(.green)
                }
            }
            .padding(.horizontal)
            .padding(.bottom, 4)
        }
    }

    // MARK: - Computed styles

    private var trackingIcon: String {
        switch appState.trackingState {
        case .idle: return "pause.circle"
        case .searching: return "magnifyingglass"
        case .tracking: return "scope"
        case .lost: return "questionmark.circle"
        }
    }

    private var trackingColor: Color {
        switch appState.trackingState {
        case .idle: return .gray
        case .searching: return .yellow
        case .tracking: return .green
        case .lost: return .orange
        }
    }

    private var scoreColor: Color {
        if appState.activityScore >= 70 { return .red }
        if appState.activityScore >= 40 { return .orange }
        if appState.activityScore >= 10 { return .yellow }
        return .gray
    }

    private var fpsColor: Color {
        if appState.currentFPS >= 25 { return .green }
        if appState.currentFPS >= 15 { return .yellow }
        return .red
    }
}

// MARK: - Status Badge component

struct StatusBadge: View {
    let icon: String
    let label: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.caption)
            Text(label)
                .font(.caption.monospaced())
        }
        .foregroundStyle(color)
    }
}
