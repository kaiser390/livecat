import Foundation

/// Mock motor controller for simulator and hardware-less testing.
actor MotorControllerMock: MotorControlling {
    private(set) var currentPan: Double = 180
    private(set) var currentTilt: Double = 0

    private let panSpeed: Double = 30   // degrees/sec
    private let tiltSpeed: Double = 20  // degrees/sec

    struct TrackingLog: Sendable {
        let timestamp: TimeInterval
        let boundingBox: CGRect
        let targetPan: Double
        let targetTilt: Double
    }

    private(set) var trackingHistory: [TrackingLog] = []

    func track(boundingBox: CGRect, in frameSize: CGSize) async throws {
        let center = CGPoint(x: boundingBox.midX, y: boundingBox.midY)
        let angles = CoordinateMapper.targetAngles(
            for: center,
            currentPan: currentPan,
            currentTilt: currentTilt
        )

        // Simulate smooth motor movement
        let panDiff = angles.pan - currentPan
        let tiltDiff = angles.tilt - currentTilt
        let dt = 1.0 / 30.0  // Assume 30fps

        let maxPanStep = panSpeed * dt
        let maxTiltStep = tiltSpeed * dt

        currentPan += max(-maxPanStep, min(maxPanStep, panDiff))
        currentTilt += max(-maxTiltStep, min(maxTiltStep, tiltDiff))

        trackingHistory.append(TrackingLog(
            timestamp: Date().timeIntervalSince1970,
            boundingBox: boundingBox,
            targetPan: angles.pan,
            targetTilt: angles.tilt
        ))

        // Keep history bounded
        if trackingHistory.count > 1000 {
            trackingHistory.removeFirst(500)
        }

        Log.motor.debug("Mock motor: pan=\(String(format: "%.1f", self.currentPan)) tilt=\(String(format: "%.1f", self.currentTilt))")
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
