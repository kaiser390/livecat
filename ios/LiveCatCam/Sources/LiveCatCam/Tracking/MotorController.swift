import Foundation

/// Protocol abstracting motor control for real DockKit and mock implementations.
protocol MotorControlling: AnyObject, Sendable {
    var currentPan: Double { get async }
    var currentTilt: Double { get async }
    var isConnected: Bool { get async }
    func connect() async
    func track(boundingBox: CGRect, in frameSize: CGSize) async throws
    func trackWithSpeed(boundingBox: CGRect, in frameSize: CGSize, objectSpeed: Double) async throws
    func searchInDirection(panDelta: Double, tiltDelta: Double, duration: TimeInterval) async throws
    func stopMotor() async throws
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

/// Real DockKit motor controller for Belkin Auto-Tracking Stand Pro.
///
/// Uses DockKit APIs:
/// - `track(_:cameraInformation:)` for bbox-driven auto tracking
/// - `setOrientation(_:duration:relative:)` for direct motor control (search mode)
/// - `setSystemTrackingEnabled(_:)` for system-level tracking toggle
actor MotorController: MotorControlling {
    private var accessory: DockAccessory?
    private(set) var currentPan: Double = 180
    private(set) var currentTilt: Double = 0
    private(set) var isConnected: Bool = false

    /// Frame size for DockKit camera information
    private var cameraFOV: Float = 67.0  // iPhone wide camera HFOV

    func connect() async {
        Log.motor.info("Waiting for DockKit accessory...")
        do {
            // Listen for DockKit accessories
            for try await event in try DockAccessoryManager.shared.accessoryStateChanges {
                switch event {
                case .docked(let acc):
                    accessory = acc
                    isConnected = true
                    // Disable system face tracking — we do custom object tracking
                    try await acc.setSystemTrackingEnabled(false)
                    Log.motor.info("DockKit connected: \(acc.name)")
                case .undocked:
                    accessory = nil
                    isConnected = false
                    Log.motor.info("DockKit disconnected")
                @unknown default:
                    break
                }
            }
        } catch {
            Log.motor.error("DockKit accessory monitoring failed: \(error)")
        }
    }

    func track(boundingBox: CGRect, in frameSize: CGSize) async throws {
        try await trackWithSpeed(boundingBox: boundingBox, in: frameSize, objectSpeed: 0.02)
    }

    func trackWithSpeed(boundingBox: CGRect, in frameSize: CGSize, objectSpeed: Double) async throws {
        guard let accessory else {
            Log.motor.warning("No DockKit accessory available")
            return
        }

        // Dead zone check — don't move if object is near center
        if CoordinateMapper.isInDeadZone(bbox: boundingBox) {
            return
        }

        // Create DockKit observation from bounding box
        let observation = DockAccessory.Observation(
            identifier: 0,
            type: .object,
            rect: boundingBox
        )

        // Camera information for DockKit
        let cameraInfo = DockAccessory.CameraInformation(
            captureDevice: .builtInWideAngleCamera,
            cameraOrientation: .landscapeRight,
            cameraPosition: .front,
            fieldOfView: cameraFOV,
            frameSize: frameSize
        )

        // Feed observation to DockKit — it handles motor control automatically
        try accessory.track([observation], cameraInformation: cameraInfo)

        // Update local angle estimates
        let center = CGPoint(x: boundingBox.midX, y: boundingBox.midY)
        let angles = CoordinateMapper.targetAngles(
            for: center,
            currentPan: currentPan,
            currentTilt: currentTilt
        )
        currentPan = angles.pan
        currentTilt = angles.tilt
    }

    func searchInDirection(panDelta: Double, tiltDelta: Double, duration: TimeInterval) async throws {
        guard let accessory else { return }

        // Use relative orientation for search: move in the last known direction
        let orientation = DockAccessory.Orientation(
            pan: Measurement(value: panDelta, unit: .degrees),
            tilt: Measurement(value: tiltDelta, unit: .degrees)
        )
        try await accessory.setOrientation(orientation, duration: duration, relative: true)

        currentPan += panDelta
        currentTilt += tiltDelta
        // Clamp
        currentPan = min(max(currentPan, CoordinateMapper.panRange.lowerBound), CoordinateMapper.panRange.upperBound)
        currentTilt = min(max(currentTilt, CoordinateMapper.tiltRange.lowerBound), CoordinateMapper.tiltRange.upperBound)
    }

    func stopMotor() async throws {
        // Set orientation to current position (effectively stops movement)
        guard let accessory else { return }
        let orientation = DockAccessory.Orientation(
            pan: Measurement(value: 0, unit: .degrees),
            tilt: Measurement(value: 0, unit: .degrees)
        )
        try await accessory.setOrientation(orientation, duration: 0.1, relative: true)
    }

    func setOrientation(pan: Double, tilt: Double) async throws {
        guard let accessory else { return }
        let orientation = DockAccessory.Orientation(
            pan: Measurement(value: pan, unit: .degrees),
            tilt: Measurement(value: tilt, unit: .degrees)
        )
        try await accessory.setOrientation(orientation, duration: 0.5, relative: false)
        currentPan = pan
        currentTilt = tilt
    }

    func returnToHome() async throws {
        try await setOrientation(pan: 180, tilt: 0)
    }
}
#endif
