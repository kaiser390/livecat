import Foundation

/// Classifies cat pose from joint positions and motion data.
enum PoseClassification: String, Sendable {
    case sitting
    case walking
    case running
    case jumping
    case climbing
    case sleeping
    case standing
    case crouching
    case stalking
    case pouncing
    case unknown
}

struct PoseClassifier: Sendable {
    /// Classify a cat's pose based on joint data, speed, and airborne status.
    static func classify(
        pose: CatPose,
        speed: Double,
        airborneFrames: Int,
        verticalVelocity: Double
    ) -> PoseClassification {
        let bbox = pose.boundingBox
        let aspectRatio = bbox.width / max(bbox.height, 0.001)
        let frontLegAngle = pose.frontLegAngle

        // Jumping: airborne or high vertical velocity with extended legs
        if airborneFrames >= 3 || (verticalVelocity > 50 && frontLegAngle > 100) {
            return .jumping
        }

        // Climbing: vertical movement + front legs above body center
        if let neck = pose.neck, let leftPaw = pose.leftFrontPaw {
            let isClimbing = leftPaw.location.y > neck.location.y &&
                             frontLegAngle >= 120 &&
                             abs(verticalVelocity) > 10
            if isClimbing {
                return .climbing
            }
        }

        // Running: high speed with extended stride
        if speed >= 50 {
            return .running
        }

        // Walking: moderate speed
        if speed >= 15 {
            return .walking
        }

        // Crouching/stalking: low profile, low speed
        if aspectRatio > 1.8 && speed < 10 && speed > 2 {
            return .stalking
        }

        if aspectRatio > 1.5 && speed < 5 {
            return .crouching
        }

        // Sleeping: minimal movement, compact shape
        if speed < 2 && bbox.height < 0.15 && bbox.width < 0.2 {
            return .sleeping
        }

        // Sitting: small vertical range, legs folded
        if speed < 5 && aspectRatio < 1.2 && bbox.height > bbox.width * 0.8 {
            return .sitting
        }

        // Standing: upright, not moving
        if speed < 5 {
            return .standing
        }

        return .unknown
    }
}
