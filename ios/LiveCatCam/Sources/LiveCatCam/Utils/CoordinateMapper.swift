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
