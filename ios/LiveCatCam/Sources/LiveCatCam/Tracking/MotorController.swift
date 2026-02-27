import Foundation

/// Protocol abstracting motor control for real DockKit and mock implementations.
protocol MotorControlling: AnyObject, Sendable {
    var currentPan: Double { get async }
    var currentTilt: Double { get async }
    func track(boundingBox: CGRect, in frameSize: CGSize) async throws
    func setOrientation(pan: Double, tilt: Double) async throws
    func returnToHome() async throws
}

// DockKit real implementation is disabled until hardware is available.
// Enable by setting ENABLE_DOCKKIT=1 in build settings and updating
// the DockKit API calls to match the installed SDK version.
//
// When DockKit hardware arrives:
// 1. Add Active Compilation Condition: ENABLE_DOCKKIT
// 2. Update the DockKit API calls below to match your SDK version
// 3. Switch AppState.setupModules() to use MotorController()

#if ENABLE_DOCKKIT
import DockKit

/// Real DockKit motor controller for physical dock accessories.
actor MotorController: MotorControlling {
    private var accessory: DockAccessory?
    private(set) var currentPan: Double = 180
    private(set) var currentTilt: Double = 0

    func connect() async {
        Log.motor.info("Waiting for DockKit accessory...")
        // TODO: Update DockAccessory API for your SDK version
    }

    func track(boundingBox: CGRect, in frameSize: CGSize) async throws {
        guard let accessory else {
            Log.motor.warning("No DockKit accessory available")
            return
        }

        let center = CGPoint(x: boundingBox.midX, y: boundingBox.midY)
        let angles = CoordinateMapper.targetAngles(
            for: center,
            currentPan: currentPan,
            currentTilt: currentTilt
        )
        currentPan = angles.pan
        currentTilt = angles.tilt
    }

    func setOrientation(pan: Double, tilt: Double) async throws {
        currentPan = pan
        currentTilt = tilt
    }

    func returnToHome() async throws {
        try await setOrientation(pan: 180, tilt: 0)
    }
}
#endif
