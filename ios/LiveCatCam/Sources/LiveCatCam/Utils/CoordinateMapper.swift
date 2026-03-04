import Foundation
import CoreGraphics

/// Maps Vision normalized coordinates (0-1) to DockKit motor angles.
enum CoordinateMapper {
    /// DockKit pan range (degrees). Typical range: 0-360.
    static let panRange: ClosedRange<Double> = 0...360
    /// DockKit tilt range (degrees). Typical range: -90 to 90.
    static let tiltRange: ClosedRange<Double> = -90...90

    /// Camera horizontal field of view in degrees.
    static let cameraHFOV: Double = 67.0
    /// Camera vertical field of view in degrees.
    static let cameraVFOV: Double = 41.0

    /// Convert a normalized Vision coordinate (0-1, origin bottom-left)
    /// to a relative pan/tilt offset from the current motor position.
    ///
    /// - Parameters:
    ///   - point: Normalized (x, y) where (0,0) is bottom-left, (1,1) is top-right.
    ///   - currentPan: Current motor pan angle.
    ///   - currentTilt: Current motor tilt angle.
    /// - Returns: Target (pan, tilt) in degrees.
    static func targetAngles(
        for point: CGPoint,
        currentPan: Double,
        currentTilt: Double
    ) -> (pan: Double, tilt: Double) {
        // Offset from frame center (0.5, 0.5)
        let dx = Double(point.x) - 0.5
        let dy = Double(point.y) - 0.5

        // Convert offset to angle delta
        let panDelta = dx * cameraHFOV
        let tiltDelta = dy * cameraVFOV

        let targetPan = (currentPan + panDelta).clamped(to: panRange)
        let targetTilt = (currentTilt + tiltDelta).clamped(to: tiltRange)

        return (pan: targetPan, tilt: targetTilt)
    }

    /// Convert a bounding box center to motor angles.
    static func targetAngles(
        for bbox: CGRect,
        currentPan: Double,
        currentTilt: Double
    ) -> (pan: Double, tilt: Double) {
        let center = CGPoint(x: bbox.midX, y: bbox.midY)
        return targetAngles(for: center, currentPan: currentPan, currentTilt: currentTilt)
    }

    // MARK: - Dead Zone

    /// Dead zone: normalized center region where motor commands are suppressed.
    /// Object within this region is "close enough" to center — no motor movement needed.
    static let deadZone = CGRect(x: 0.35, y: 0.35, width: 0.30, height: 0.30)

    /// Check if a normalized point is inside the dead zone (center of frame).
    static func isInDeadZone(_ point: CGPoint) -> Bool {
        deadZone.contains(point)
    }

    /// Check if a bbox center is inside the dead zone.
    static func isInDeadZone(bbox: CGRect) -> Bool {
        let center = CGPoint(x: bbox.midX, y: bbox.midY)
        return isInDeadZone(center)
    }

    // MARK: - Speed-Adaptive Duration

    /// Convert object speed (normalized units/frame) to motor duration parameter.
    /// Faster objects → shorter duration (faster motor response).
    /// - Parameter speed: Object movement speed in normalized coords per frame.
    /// - Returns: Duration in seconds for motor movement.
    static func adaptiveDuration(for speed: Double) -> TimeInterval {
        switch speed {
        case ..<0.005:  return 1.0    // Stationary — slow, smooth correction
        case ..<0.02:   return 0.5    // Slow movement
        case ..<0.05:   return 0.3    // Normal movement
        case ..<0.10:   return 0.15   // Fast movement
        default:        return 0.08   // Very fast (thrown object, running cat)
        }
    }

    // MARK: - Search Direction

    /// Calculate search orientation delta from last known velocity direction.
    /// Returns small angle deltas for slow search movement.
    static func searchDelta(
        lastVelocityX: Double,
        lastVelocityY: Double
    ) -> (panDelta: Double, tiltDelta: Double) {
        // Normalize direction, apply small search step (5 degrees)
        let magnitude = sqrt(lastVelocityX * lastVelocityX + lastVelocityY * lastVelocityY)
        guard magnitude > 0.001 else {
            return (panDelta: 0, tiltDelta: 0)
        }
        let searchStep = 5.0  // degrees per search step
        let normX = lastVelocityX / magnitude
        let normY = lastVelocityY / magnitude
        return (panDelta: normX * searchStep, tiltDelta: normY * searchStep)
    }

    /// Convert Vision bbox to server cat_positions format.
    static func toCatPosition(bbox: CGRect, confidence: Double) -> MetadataMessage.CatPosition {
        MetadataMessage.CatPosition(
            x: Double(bbox.origin.x),
            y: Double(bbox.origin.y),
            w: Double(bbox.width),
            h: Double(bbox.height),
            confidence: confidence
        )
    }
}

private extension Double {
    func clamped(to range: ClosedRange<Double>) -> Double {
        min(max(self, range.lowerBound), range.upperBound)
    }
}
