import Foundation
import Vision
import CoreImage

/// Detects cats in video frames using VNDetectAnimalBodyPoseRequest.
actor CatDetector {
    private let request = VNDetectAnimalBodyPoseRequest()
    private var frameCount: UInt64 = 0
    private var lastProcessingTime: TimeInterval = 0

    struct DetectionResult: Sendable {
        let poses: [CatPose]
        let boundingBoxes: [CGRect]
        let confidences: [Float]
        let processingTime: TimeInterval
    }

    /// Detect cats in a pixel buffer (called per frame from camera output).
    func detect(in pixelBuffer: CVPixelBuffer) async -> DetectionResult {
        frameCount += 1
        let startTime = CFAbsoluteTimeGetCurrent()

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .up)

        do {
            try handler.perform([request])
        } catch {
            Log.tracking.error("Vision request failed: \(error)")
            return DetectionResult(poses: [], boundingBoxes: [], confidences: [], processingTime: 0)
        }

        guard let observations = request.results, !observations.isEmpty else {
            return DetectionResult(poses: [], boundingBoxes: [], confidences: [], processingTime: 0)
        }

        var poses: [CatPose] = []
        var bboxes: [CGRect] = []
        var confidences: [Float] = []

        for observation in observations {
            if let pose = CatPose.from(observation: observation) {
                poses.append(pose)
                bboxes.append(pose.boundingBox)
                // Use average joint confidence as detection confidence
                let avgConf = pose.joints.reduce(Float(0)) { $0 + $1.confidence } /
                              Float(max(1, pose.joints.count))
                confidences.append(avgConf)
            }
        }

        let elapsed = CFAbsoluteTimeGetCurrent() - startTime
        lastProcessingTime = elapsed

        if frameCount % 300 == 0 {
            Log.tracking.info("Detection: \(poses.count) cats, \(String(format: "%.1f", elapsed * 1000))ms")
        }

        return DetectionResult(
            poses: poses,
            boundingBoxes: bboxes,
            confidences: confidences,
            processingTime: elapsed
        )
    }

    var averageProcessingTime: TimeInterval { lastProcessingTime }
}
