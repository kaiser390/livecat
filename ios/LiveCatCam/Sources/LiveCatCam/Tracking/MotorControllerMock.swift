import Foundation

/// Mock motor controller for simulator and hardware-less testing.
actor MotorControllerMock: MotorControlling {
    private(set) var currentPan: Double = 180
    private(set) var currentTilt: Double = 0
    private(set) var isConnected: Bool = true

    private let panSpeed: Double = 30   // degrees/sec
    private let tiltSpeed: Double = 20  // degrees/sec

    struct TrackingLog: Sendable {
        let timestamp: TimeInterval
        let boundingBox: CGRect
        let targetPan: Double
        let targetTilt: Double
    }

    private(set) var trackingHistory: [TrackingLog] = []

    func connect() async {
        isConnected = true
        Log.motor.info("Mock motor: connected")
    }

    func track(boundingBox: CGRect, in frameSize: CGSize) async throws {
        try await trackWithSpeed(boundingBox: boundingBox, in: frameSize, objectSpeed: 0.02)
    }

    func trackWithSpeed(boundingBox: CGRect, in frameSize: CGSize, objectSpeed: Double) async throws {
        // Dead zone check
        if CoordinateMapper.isInDeadZone(bbox: boundingBox) {
            return
        }

        let center = CGPoint(x: boundingBox.midX, y: boundingBox.midY)
        let angles = CoordinateMapper.targetAngles(
            for: center,
            currentPan: currentPan,
            currentTilt: currentTilt
        )

        // Speed-adaptive motor simulation
        let duration = CoordinateMapper.adaptiveDuration(for: objectSpeed)
        let dt = 1.0 / 30.0
        let speedFactor = dt / duration  // Faster duration = bigger steps

        let panDiff = angles.pan - currentPan
        let tiltDiff = angles.tilt - currentTilt

        let maxPanStep = panSpeed * dt * speedFactor * 10
        let maxTiltStep = tiltSpeed * dt * speedFactor * 10

        currentPan += max(-maxPanStep, min(maxPanStep, panDiff))
        currentTilt += max(-maxTiltStep, min(maxTiltStep, tiltDiff))

        trackingHistory.append(TrackingLog(
            timestamp: Date().timeIntervalSince1970,
            boundingBox: boundingBox,
            targetPan: angles.pan,
            targetTilt: angles.tilt
        ))

        if trackingHistory.count > 1000 {
            trackingHistory.removeFirst(500)
        }

        Log.motor.debug("Mock motor: pan=\(String(format: "%.1f", self.currentPan)) tilt=\(String(format: "%.1f", self.currentTilt)) dur=\(String(format: "%.2f", duration))")
    }

    func searchInDirection(panDelta: Double, tiltDelta: Double, duration: TimeInterval) async throws {
        currentPan += panDelta
        currentTilt += tiltDelta
        currentPan = min(max(currentPan, CoordinateMapper.panRange.lowerBound), CoordinateMapper.panRange.upperBound)
        currentTilt = min(max(currentTilt, CoordinateMapper.tiltRange.lowerBound), CoordinateMapper.tiltRange.upperBound)
        Log.motor.info("Mock motor: search pan+=\(String(format: "%.1f", panDelta)) tilt+=\(String(format: "%.1f", tiltDelta))")
    }

    func stopMotor() async throws {
        Log.motor.info("Mock motor: stopped")
    }

    func setOrientation(pan: Double, tilt: Double) async throws {
        currentPan = pan
        currentTilt = tilt
        Log.motor.info("Mock motor: goto pan=\(pan) tilt=\(tilt)")
    }

    func returnToHome() async throws {
        try await setOrientation(pan: 180, tilt: 0)
        Log.motor.info("Mock motor: returned home")
    }

    func clearHistory() {
        trackingHistory.removeAll()
    }
}
