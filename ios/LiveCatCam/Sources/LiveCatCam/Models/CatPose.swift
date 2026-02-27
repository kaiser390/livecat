import Foundation
import Vision

struct CatPose: Sendable {
    struct Joint: Sendable {
        let name: String
        let location: CGPoint
        let confidence: Float
    }

    let joints: [Joint]
    let timestamp: TimeInterval

    // MARK: - Named joint accessors (VNAnimalBodyPoseObservation.JointName)

    var leftEar: Joint? { joint(named: "left_earTip") }
    var rightEar: Joint? { joint(named: "right_earTip") }
    var nose: Joint? { joint(named: "nose") }
    var neck: Joint? { joint(named: "neck") }
    var leftFrontElbow: Joint? { joint(named: "leftFrontElbow") }
    var rightFrontElbow: Joint? { joint(named: "rightFrontElbow") }
    var leftFrontPaw: Joint? { joint(named: "leftFrontPaw") }
    var rightFrontPaw: Joint? { joint(named: "rightFrontPaw") }
    var leftBackElbow: Joint? { joint(named: "leftBackElbow") }
    var rightBackElbow: Joint? { joint(named: "rightBackElbow") }
    var leftBackPaw: Joint? { joint(named: "leftBackPaw") }
    var rightBackPaw: Joint? { joint(named: "rightBackPaw") }
    var tailBase: Joint? { joint(named: "tailBase") }
    var tailMiddle: Joint? { joint(named: "tailMiddle") }
    var tailTip: Joint? { joint(named: "tailTip") }

    // MARK: - Computed properties

    var center: CGPoint {
        let validJoints = joints.filter { $0.confidence > 0.3 }
        guard !validJoints.isEmpty else { return .zero }
        let sumX = validJoints.reduce(0.0) { $0 + $1.location.x }
        let sumY = validJoints.reduce(0.0) { $0 + $1.location.y }
        return CGPoint(x: sumX / CGFloat(validJoints.count),
                       y: sumY / CGFloat(validJoints.count))
    }

    var boundingBox: CGRect {
        let validJoints = joints.filter { $0.confidence > 0.3 }
        guard !validJoints.isEmpty else { return .zero }
        let xs = validJoints.map(\.location.x)
        let ys = validJoints.map(\.location.y)
        let minX = xs.min()!
        let maxX = xs.max()!
        let minY = ys.min()!
        let maxY = ys.max()!
        let padding: CGFloat = 0.05
        return CGRect(x: max(0, minX - padding),
                      y: max(0, minY - padding),
                      width: min(1, maxX - minX + padding * 2),
                      height: min(1, maxY - minY + padding * 2))
    }

    var frontLegAngle: Double {
        guard let neck = neck,
              let leftElbow = leftFrontElbow,
              let leftPaw = leftFrontPaw else { return 0 }
        let v1 = CGVector(dx: leftElbow.location.x - neck.location.x,
                          dy: leftElbow.location.y - neck.location.y)
        let v2 = CGVector(dx: leftPaw.location.x - leftElbow.location.x,
                          dy: leftPaw.location.y - leftElbow.location.y)
        let dot = v1.dx * v2.dx + v1.dy * v2.dy
        let mag1 = sqrt(v1.dx * v1.dx + v1.dy * v1.dy)
        let mag2 = sqrt(v2.dx * v2.dx + v2.dy * v2.dy)
        guard mag1 > 0, mag2 > 0 else { return 0 }
        let cosAngle = max(-1, min(1, dot / (mag1 * mag2)))
        return acos(cosAngle) * 180.0 / .pi
    }

    // MARK: - Helpers

    private func joint(named name: String) -> Joint? {
        joints.first { $0.name == name }
    }

    static func from(observation: VNAnimalBodyPoseObservation) -> CatPose? {
        guard let points = try? observation.recognizedPoints(.all) else { return nil }
        let joints = points.compactMap { key, point -> Joint? in
            guard point.confidence > 0.1 else { return nil }
            return Joint(name: key.rawValue.rawValue,
                         location: point.location,
                         confidence: point.confidence)
        }
        guard !joints.isEmpty else { return nil }
        return CatPose(joints: joints, timestamp: Date().timeIntervalSince1970)
    }
}
