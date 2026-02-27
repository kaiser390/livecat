import Foundation
import SwiftUI
import CoreMedia
#if os(iOS)
import UIKit
#endif

/// Central app state coordinating all modules.
@Observable @MainActor
final class AppState {
    // MARK: - Configuration
    var config = CameraConfig()

    // MARK: - Module instances
    let cameraManager = CameraManager()
    let catDetector = CatDetector()
    let catTracker = CatTracker()
    let activityScorer = ActivityScorer()
    let trackingStateMachine = TrackingStateMachine()
    let connectionMonitor = ConnectionMonitor()
    let commandReceiver = CommandReceiver()

    private(set) var serverConnection: ServerConnection?
    private(set) var metadataReporter: MetadataReporter?
    private(set) var videoEncoder: VideoEncoder?
    private(set) var srtStreamer: SRTStreamer?
    private(set) var motorController: (any MotorControlling)?
    private(set) var audioCapture = AudioCapture()
    private(set) var audioEncoder: AudioEncoder?

    // MARK: - Observable state
    var trackingState: TrackingState = .idle
    var activityScore: Double = 0
    var currentFPS: Double = 0
    var isConnected = false
    var isStreaming = false
    var catCount = 0
    var motorPan: Double = 180
    var motorTilt: Double = 0
    var thermalState: ProcessInfo.ThermalState = .nominal
    var debugLog: String = ""

    // MARK: - UI state
    var showControls = true
    var showSettings = false
    var currentZoom: Double = 1.0
    var isMuted = false
    private var streamStartTime: Date?
    private var elapsedTimer: Task<Void, Never>?
    var elapsedSeconds: Int = 0

    var formattedTime: String {
        let h = elapsedSeconds / 3600
        let m = (elapsedSeconds % 3600) / 60
        let s = elapsedSeconds % 60
        return String(format: "%02d:%02d:%02d", h, m, s)
    }

    #if os(iOS)
    var batteryLevel: Float { UIDevice.current.batteryLevel }
    var batteryIcon: String {
        if UIDevice.current.batteryState == .charging { return "battery.100.bolt" }
        let level = UIDevice.current.batteryLevel
        if level > 0.75 { return "battery.100" }
        if level > 0.50 { return "battery.75" }
        if level > 0.25 { return "battery.50" }
        return "battery.25" }
    var batteryColor: Color {
        let level = UIDevice.current.batteryLevel
        if UIDevice.current.batteryState == .charging { return .green }
        if level > 0.2 { return .white }
        return .red
    }
    #endif

    // MARK: - Watchdog
    private var lastFrameTime: TimeInterval = 0
    private var watchdogTask: Task<Void, Never>?

    // MARK: - Lifecycle

    /// Whether the streaming pipeline is actively running
    var isLive = false

    func start() async {
        setupModules()
        // Only start camera preview, not streaming
        do {
            try cameraManager.configure(resolution: config.resolution, fps: config.fps)
        } catch {
            Log.app.error("Camera configuration failed: \(error)")
            return
        }

        // Attach audio capture BEFORE session starts (safe, no crash)
        do {
            try audioCapture.attach(to: cameraManager.captureSession)
            addDebug("Audio attached")
        } catch {
            Log.app.warning("Audio attach failed: \(error)")
        }

        // Show camera diagnostic info after short delay (wait for first frame)
        Task {
            try? await Task.sleep(for: .seconds(2))
            addDebug("CAM: \(cameraManager.diagnosticInfo)")
        }

        cameraManager.onFrame = { [weak self] pixelBuffer, timestamp in
            guard let self else { return }
            self.lastFrameTime = Date().timeIntervalSince1970
            Task {
                await self.processFrame(pixelBuffer: pixelBuffer, timestamp: timestamp)
            }
        }
        cameraManager.start()
        #if os(iOS)
        UIDevice.current.isBatteryMonitoringEnabled = true
        #endif
        startThermalMonitoring()
    }

    func stop() async {
        if isLive {
            await stopStreaming()
        }
        cameraManager.stop()
    }

    private func addDebug(_ msg: String) {
        let time = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        debugLog = "[\(time)] \(msg)\n" + debugLog
        if debugLog.count > 500 { debugLog = String(debugLog.prefix(500)) }
        Log.app.info("\(msg)")
    }

    /// Start streaming + server connection (user taps Start)
    func startStreaming() async {
        guard !isLive else { return }
        addDebug("START tapped")

        // Wire up video encoding → UDP (thread-safe: capture local ref)
        addDebug("Wiring encoder → UDP...")
        let streamer = srtStreamer
        var callbackCount: UInt64 = 0
        videoEncoder?.onEncodedData = { [weak self] data, isKeyframe in
            callbackCount += 1
            streamer?.write(encodedData: data, isKeyframe: isKeyframe)
            // Show first few callbacks + keyframes on debug overlay
            if callbackCount <= 5 || isKeyframe {
                let msg = isKeyframe ? "KF#\(callbackCount) \(data.count)B" : "F#\(callbackCount) \(data.count)B"
                Task { @MainActor in
                    self?.addDebug(msg)
                }
            }
        }

        // Start video encoder
        addDebug("Starting encoder...")
        do {
            try videoEncoder?.start()
            addDebug("Encoder OK")
        } catch {
            addDebug("Encoder FAIL: \(error)")
        }

        // Start UDP streamer
        addDebug("Starting UDP...")
        do {
            try srtStreamer?.start()
            isStreaming = true
            addDebug("UDP OK → \(config.serverIP):\(config.srtPort)")
        } catch {
            addDebug("UDP FAIL: \(error)")
        }

        // Wire up audio encoding → UDP
        addDebug("Wiring audio...")
        let encoder = AudioEncoder()
        audioEncoder = encoder
        encoder.onEncodedAudio = { aacData in
            streamer?.writeAudio(aacData: aacData)
        }
        audioCapture.onAudioBuffer = { sampleBuffer in
            encoder.encode(sampleBuffer: sampleBuffer)
        }
        addDebug("Audio wired")

        // Set live BEFORE async network calls (so encoding starts immediately)
        isLive = true
        streamStartTime = Date()
        elapsedSeconds = 0
        startElapsedTimer()
        startWatchdog()
        addDebug("LIVE! Streaming started")

        // Connect to server (WebSocket) - fire and forget, don't block
        addDebug("Connecting WebSocket...")
        connectionMonitor.start()
        Task {
            await serverConnection?.connect()
        }
        await metadataReporter?.start()
        addDebug("WebSocket connecting in background")
    }

    /// Stop streaming + server connection (user taps Stop)
    func stopStreaming() async {
        elapsedTimer?.cancel()
        watchdogTask?.cancel()
        videoEncoder?.stop()
        audioEncoder?.stop()
        audioCapture.onAudioBuffer = nil
        audioEncoder = nil
        srtStreamer?.stop()
        isStreaming = false
        await metadataReporter?.stop()
        await serverConnection?.disconnect()
        connectionMonitor.stop()
        isConnected = false
        isLive = false
    }

    // MARK: - Setup

    private func setupModules() {
        // Use mock motor controller (switch to real MotorController when hardware is available)
        #if targetEnvironment(simulator)
        motorController = MotorControllerMock()
        #else
        motorController = MotorControllerMock()  // TODO: Switch to MotorController() with real DockKit
        #endif

        // Network
        let connection = ServerConnection(config: config)
        serverConnection = connection
        metadataReporter = MetadataReporter(connection: connection, config: config)

        // Wire server commands → command receiver
        let receiver = commandReceiver
        Task {
            await connection.setCommandHandler { command in
                receiver.dispatch(command)
            }
        }

        // Video
        videoEncoder = VideoEncoder(
            width: config.resolution.width,
            height: config.resolution.height,
            fps: config.fps,
            bitrate: config.bitrate
        )
        srtStreamer = SRTStreamer(config: config)

        // Connection state handling
        connectionMonitor.onConnectionChanged = { [weak self] connected in
            Task { @MainActor in
                self?.isConnected = connected
                if connected {
                    await self?.serverConnection?.connect()
                }
            }
        }

        // Command handling
        commandReceiver.setModeHandler { [weak self] command in
            guard case .setMode(let mode) = command else { return }
            Log.app.info("Server set mode: \(mode)")
            _ = self
        }
        commandReceiver.setZoomHandler { _ in
            Log.app.info("Zoom command received (not implemented)")
        }
        commandReceiver.setPositionHandler { [weak self] command in
            guard case .gotoPosition(let pan, let tilt) = command else { return }
            Task {
                try? await self?.motorController?.setOrientation(pan: pan, tilt: tilt)
            }
        }

        // PC remote camera control
        commandReceiver.setCameraControlHandler { [weak self] command in
            guard let self else { return }
            switch command {
            case .cameraZoom(let factor):
                self.cameraManager.setZoom(factor: factor)
                Task { @MainActor in self.addDebug("ZOOM \(factor)x") }
            case .cameraFocus(let x, let y):
                self.cameraManager.setFocus(x: x, y: y)
                Task { @MainActor in self.addDebug("FOCUS (\(String(format:"%.1f",x)),\(String(format:"%.1f",y)))") }
            case .cameraExposure(let x, let y):
                self.cameraManager.setExposure(x: x, y: y)
                Task { @MainActor in self.addDebug("EXPOSURE (\(String(format:"%.1f",x)),\(String(format:"%.1f",y)))") }
            case .cameraReset:
                self.cameraManager.resetCamera()
                Task { @MainActor in self.addDebug("CAMERA RESET") }
            default:
                break
            }
        }
    }

    // startPipeline moved into startStreaming/stopStreaming

    // MARK: - Frame processing pipeline

    private func processFrame(pixelBuffer: CVPixelBuffer, timestamp: CMTime) async {
        // 1. Detect cats
        let detection = await catDetector.detect(in: pixelBuffer)

        // 2. Track cats
        let cats = await catTracker.update(detections: detection)
        let catDetected = !cats.isEmpty

        // 3. Update tracking state
        let state = await trackingStateMachine.update(catDetected: catDetected)

        // 4. Score activity
        let scoreResult = await activityScorer.score(cats: cats, cameraID: config.camID)

        // 5. Motor tracking (track first detected cat)
        if let primaryCat = cats.first {
            try? await motorController?.track(
                boundingBox: primaryCat.bbox,
                in: CGSize(width: config.resolution.width, height: config.resolution.height)
            )
        }

        // 6. Encode video frame (only when streaming)
        if isLive {
            videoEncoder?.encode(pixelBuffer: pixelBuffer, presentationTime: timestamp)
        }

        // 7. Update metadata reporter
        let catPositions = await catTracker.toCatPositions()
        let catInfos = await catTracker.toMetadataCats()
        let normalizedScore = await activityScorer.serverNormalizedScore(scoreResult.smoothedScore)
        let pan = await motorController?.currentPan ?? 180
        let tilt = await motorController?.currentTilt ?? 0

        // Detect hunt signals
        var huntSignals: [String] = []
        for cat in cats {
            switch cat.classification {
            case .crouching: huntSignals.append("crouch")
            case .stalking: huntSignals.append("stalk")
            case .pouncing: huntSignals.append("pounce")
            default: break
            }
        }

        await metadataReporter?.updateTracking(state: state, score: normalizedScore)
        await metadataReporter?.updateCatPositions(catPositions)
        await metadataReporter?.updateCats(catInfos)
        await metadataReporter?.updateMotorPosition(pan: pan, tilt: tilt)
        await metadataReporter?.updateHuntSignals(huntSignals)

        // 8. Update UI state (throttled to ~10Hz)
        await MainActor.run {
            self.trackingState = state
            self.activityScore = normalizedScore
            self.currentFPS = self.cameraManager.currentFPS
            self.catCount = cats.count
            self.motorPan = pan
            self.motorTilt = tilt
        }
    }

    // MARK: - Elapsed timer

    private func startElapsedTimer() {
        elapsedTimer = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self, let start = self.streamStartTime else { return }
                self.elapsedSeconds = Int(Date().timeIntervalSince(start))
            }
        }
    }

    // MARK: - Zoom control

    func setZoomLevel(_ factor: Double) {
        currentZoom = factor
        cameraManager.setZoom(factor: factor)
    }

    // MARK: - Watchdog (restart pipeline if no frames for 30s)

    private func startWatchdog() {
        watchdogTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                guard let self else { return }
                let elapsed = Date().timeIntervalSince1970 - self.lastFrameTime
                if self.lastFrameTime > 0 && elapsed > 30 {
                    Log.app.error("Watchdog: no frames for 30s, restarting pipeline")
                    self.cameraManager.restart()
                }
            }
        }
    }

    // MARK: - Thermal management

    private func startThermalMonitoring() {
        NotificationCenter.default.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            guard let self else { return }
            self.thermalState = ProcessInfo.processInfo.thermalState
            if self.thermalState == .critical {
                Log.app.warning("Thermal state CRITICAL: reducing to 15fps/480p")
                // In production: reconfigure camera to lower settings
            }
        }
    }
}
