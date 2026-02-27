import Foundation

/// Collects and sends metadata to the server at 10Hz.
actor MetadataReporter {
    private let connection: ServerConnection
    private let config: CameraConfig
    private var timer: Task<Void, Never>?
    private let interval: TimeInterval = 0.1  // 10Hz

    // Latest state (updated by other modules)
    var trackingState: TrackingState = .idle
    var activityScore: Double = 0
    var catPositions: [MetadataMessage.CatPosition] = []
    var motorPan: Double = 180
    var motorTilt: Double = 0
    var cats: [MetadataMessage.CatInfo] = []
    var huntSignals: [String] = []

    init(connection: ServerConnection, config: CameraConfig) {
        self.connection = connection
        self.config = config
    }

    func start() {
        stop()
        timer = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(0.1))
                await self?.sendMetadata()
            }
        }
        Log.network.info("MetadataReporter started at 10Hz")
    }

    func stop() {
        timer?.cancel()
        timer = nil
    }

    private func sendMetadata() async {
        let message = MetadataMessage(
            camID: config.camID,
            trackingState: trackingState.serverValue,
            activityScore: activityScore,
            catPositions: catPositions,
            motorPosition: MetadataMessage.MotorPosition(
                pan: motorPan,
                tilt: motorTilt
            ),
            timestamp: Date().timeIntervalSince1970,
            cats: cats,
            huntSignals: huntSignals
        )
        await connection.send(message)
    }

    // MARK: - State update methods

    func updateTracking(state: TrackingState, score: Double) {
        self.trackingState = state
        self.activityScore = score
    }

    func updateCatPositions(_ positions: [MetadataMessage.CatPosition]) {
        self.catPositions = positions
    }

    func updateMotorPosition(pan: Double, tilt: Double) {
        self.motorPan = pan
        self.motorTilt = tilt
    }

    func updateCats(_ cats: [MetadataMessage.CatInfo]) {
        self.cats = cats
    }

    func updateHuntSignals(_ signals: [String]) {
        self.huntSignals = signals
    }
}
