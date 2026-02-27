import SwiftUI
import AVFoundation
import Combine

/// Main state manager — orchestrates Camera, Stream, and WebSocket services.
/// Provides all observable state for the UI.
@Observable
final class StreamViewModel {
    // MARK: - UI State

    var isStreaming = false
    var elapsedTime: TimeInterval = 0
    var formattedTime: String { formatTime(elapsedTime) }

    var zoomLevel: CGFloat = 1.0
    var zoomText: String { String(format: "%.1fx", zoomLevel) }

    var batteryLevel: Int = 100
    var isCharging = false
    var isThermalWarning = false

    var isWSConnected = false
    var isAudioEnabled = true

    var showControls = true
    var showSettings = false

    // MARK: - Services

    let cameraService = CameraService()
    private let streamService = StreamService()
    private let webSocketService = WebSocketService()
    private let settings = AppSettings.shared

    // MARK: - Private

    private var streamTimer: Timer?
    private var statusTimer: Timer?
    private var startTime: Date?
    private var batteryMonitor: Any?

    // MARK: - Init

    init() {
        setupCamera()
        setupWebSocketCallbacks()
        startBatteryMonitoring()
    }

    // MARK: - Camera Setup

    private func setupCamera() {
        cameraService.delegate = self
        cameraService.configure(quality: settings.videoQuality)
        cameraService.startCapture()
    }

    // MARK: - Streaming

    func startStreaming() {
        guard !isStreaming else { return }

        // Setup encoder
        let quality = settings.videoQuality
        streamService.setupCompressor(
            width: quality.width,
            height: quality.height,
            bitrate: quality.bitrate
        )

        // Connect UDP
        streamService.connect(
            host: settings.serverIP,
            port: UInt16(settings.udpPort)
        )

        // Connect WebSocket
        webSocketService.setAutoReconnect(settings.autoReconnect)
        webSocketService.connect(
            host: settings.serverIP,
            port: settings.wsPort
        )

        isStreaming = true
        isAudioEnabled = settings.audioEnabled
        startTime = Date()
        elapsedTime = 0

        // Elapsed time timer
        streamTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self, let start = self.startTime else { return }
            self.elapsedTime = Date().timeIntervalSince(start)
        }

        // Status reporting timer (every 10s)
        statusTimer = Timer.scheduledTimer(withTimeInterval: 10.0, repeats: true) { [weak self] _ in
            self?.sendStatusUpdate()
        }

        // Haptic — heavy impact
        let impact = UIImpactFeedbackGenerator(style: .heavy)
        impact.impactOccurred()
    }

    func stopStreaming() {
        guard isStreaming else { return }

        streamTimer?.invalidate()
        streamTimer = nil
        statusTimer?.invalidate()
        statusTimer = nil

        streamService.disconnect()
        webSocketService.disconnect()

        isStreaming = false
        isWSConnected = false
        startTime = nil

        // Haptic — double medium impact
        let impact = UIImpactFeedbackGenerator(style: .medium)
        impact.impactOccurred()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            impact.impactOccurred()
        }
    }

    func toggleStreaming() {
        if isStreaming {
            stopStreaming()
        } else {
            startStreaming()
        }
    }

    // MARK: - Audio Toggle

    func toggleAudio() {
        isAudioEnabled.toggle()
        settings.audioEnabled = isAudioEnabled
    }

    // MARK: - Zoom

    func setZoom(_ factor: CGFloat) {
        cameraService.setZoom(factor)
        zoomLevel = cameraService.currentZoom

        // Haptic
        let impact = UIImpactFeedbackGenerator(style: .light)
        impact.impactOccurred()
    }

    func handlePinchZoom(scale: CGFloat) {
        cameraService.handlePinch(scale: scale)
        zoomLevel = cameraService.currentZoom
    }

    // MARK: - Remote Command Handling

    func handleRemoteCommand(zoom factor: CGFloat) {
        setZoom(factor)
    }

    // MARK: - WebSocket Callbacks

    private func setupWebSocketCallbacks() {
        webSocketService.onZoomCommand = { [weak self] factor in
            self?.handleRemoteCommand(zoom: factor)
        }

        webSocketService.onConnected = { [weak self] in
            self?.isWSConnected = true
            let notification = UINotificationFeedbackGenerator()
            notification.notificationOccurred(.success)
        }

        webSocketService.onDisconnected = { [weak self] in
            self?.isWSConnected = false
            let notification = UINotificationFeedbackGenerator()
            notification.notificationOccurred(.error)
        }
    }

    // MARK: - Battery Monitoring

    private func startBatteryMonitoring() {
        UIDevice.current.isBatteryMonitoringEnabled = true
        updateBattery()

        // Observe battery changes
        NotificationCenter.default.addObserver(
            forName: UIDevice.batteryLevelDidChangeNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            self?.updateBattery()
        }
        NotificationCenter.default.addObserver(
            forName: UIDevice.batteryStateDidChangeNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            self?.updateBattery()
        }

        // Thermal state
        NotificationCenter.default.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            self?.updateThermalState()
        }
    }

    private func updateBattery() {
        let level = UIDevice.current.batteryLevel
        batteryLevel = level < 0 ? 100 : Int(level * 100)
        isCharging = UIDevice.current.batteryState == .charging || UIDevice.current.batteryState == .full
    }

    private func updateThermalState() {
        let state = ProcessInfo.processInfo.thermalState
        isThermalWarning = state == .serious || state == .critical
    }

    // MARK: - Status Update

    private func sendStatusUpdate() {
        webSocketService.sendStatus(
            battery: batteryLevel,
            zoom: zoomLevel,
            isStreaming: isStreaming,
            temperature: isThermalWarning ? "warning" : nil
        )
    }

    // MARK: - UI

    func toggleControls() {
        withAnimation(.easeInOut(duration: 0.3)) {
            showControls.toggle()
        }
    }

    func toggleSettings() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            showSettings.toggle()
        }
    }

    // MARK: - Helpers

    private func formatTime(_ seconds: TimeInterval) -> String {
        let h = Int(seconds) / 3600
        let m = (Int(seconds) % 3600) / 60
        let s = Int(seconds) % 60
        return String(format: "%02d:%02d:%02d", h, m, s)
    }

    var batteryIcon: String {
        if isCharging { return "battery.100.bolt" }
        switch batteryLevel {
        case 76...100: return "battery.100"
        case 51...75: return "battery.75"
        case 26...50: return "battery.50"
        default: return "battery.25"
        }
    }

    var batteryColor: Color {
        if batteryLevel <= 20 { return Color(hex: "FF3B30") }
        if batteryLevel <= 50 { return Color(hex: "FF9500") }
        return Color(hex: "34D449")
    }
}

// MARK: - CameraServiceDelegate

extension StreamViewModel: CameraServiceDelegate {
    func cameraService(_ service: CameraService, didOutputVideo sampleBuffer: CMSampleBuffer) {
        guard isStreaming else { return }
        streamService.encodeVideoFrame(sampleBuffer)
    }

    func cameraService(_ service: CameraService, didOutputAudio sampleBuffer: CMSampleBuffer) {
        guard isStreaming, isAudioEnabled else { return }
        streamService.sendAudioBuffer(sampleBuffer)
    }
}

// MARK: - Color Hex Extension

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let r = Double((int >> 16) & 0xFF) / 255.0
        let g = Double((int >> 8) & 0xFF) / 255.0
        let b = Double(int & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b)
    }
}
