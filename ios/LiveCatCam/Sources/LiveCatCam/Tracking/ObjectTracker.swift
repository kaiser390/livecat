import Foundation
import Vision

/// Tracks an arbitrary object across frames using VNTrackObjectRequest.
/// Used for tap-to-track: user taps any object on screen → tracked via Vision.
actor ObjectTracker {
    struct TrackingResult: Sendable {
        let bbox: CGRect
        let confidence: Float
        let isTracking: Bool
    }

    private var requestHandler: VNSequenceRequestHandler?
    private var trackRequest: VNTrackObjectRequest?
    private var lowConfidenceCount = 0
    private let maxLowConfidenceFrames = 150  // ~5 seconds at 30fps
    private let minConfidence: Float = 0.15
    private var initialBboxSize: CGFloat = 0
    private var lastCenter: CGPoint = .zero

    var isTracking: Bool { trackRequest != nil }

    /// Start tracking an object at the given bounding box (Vision normalized coordinates).
    func startTracking(at bbox: CGRect) {
        let observation = VNDetectedObjectObservation(boundingBox: bbox)
        let request = VNTrackObjectRequest(detectedObjectObservation: observation)
        request.trackingLevel = .accurate

        trackRequest = request
        requestHandler = VNSequenceRequestHandler()
        lowConfidenceCount = 0
        initialBboxSize = max(bbox.width, bbox.height)
        lastCenter = CGPoint(x: bbox.midX, y: bbox.midY)

        Log.tracking.info("ObjectTracker: started at (\(bbox.origin.x), \(bbox.origin.y), \(bbox.width), \(bbox.height))")
    }

    /// Track the object in the current frame. Returns nil if not tracking.
    func track(in pixelBuffer: CVPixelBuffer) -> TrackingResult? {
        guard let request = trackRequest, let handler = requestHandler else {
            return nil
        }

        do {
            try handler.perform([request], on: pixelBuffer, orientation: .up)
        } catch {
            Log.tracking.error("ObjectTracker: perform failed - \(error)")
            stopTracking()
            return TrackingResult(bbox: .zero, confidence: 0, isTracking: false)
        }

        guard let result = request.results?.first as? VNDetectedObjectObservation else {
            stopTracking()
            return TrackingResult(bbox: .zero, confidence: 0, isTracking: false)
        }

        // Prepare next frame's request with updated observation
        let nextRequest = VNTrackObjectRequest(detectedObjectObservation: result)
        nextRequest.trackingLevel = .accurate
        trackRequest = nextRequest

        // Detect tracker jump (e.g. latching onto a face)
        let currentSize = max(result.boundingBox.width, result.boundingBox.height)
        let currentCenter = CGPoint(x: result.boundingBox.midX, y: result.boundingBox.midY)
        let sizeRatio = initialBboxSize > 0 ? currentSize / initialBboxSize : 1.0
        let jumpDist = hypot(currentCenter.x - lastCenter.x, currentCenter.y - lastCenter.y)
        lastCenter = currentCenter

        // If bbox grew >3x or center jumped >0.25 in one frame → tracker lost original target
        if sizeRatio > 3.0 || jumpDist > 0.25 {
            Log.tracking.info("ObjectTracker: target jump detected (size=\(sizeRatio)x, jump=\(jumpDist))")
            stopTracking()
            return TrackingResult(bbox: result.boundingBox, confidence: 0, isTracking: false)
        }

        // Auto-release if confidence stays low
        let confidence = result.confidence
        if confidence < minConfidence {
            lowConfidenceCount += 1
            if lowConfidenceCount >= maxLowConfidenceFrames {
                Log.tracking.info("ObjectTracker: lost target (low confidence \(self.lowConfidenceCount) frames)")
                stopTracking()
                return TrackingResult(bbox: result.boundingBox, confidence: confidence, isTracking: false)
            }
        } else {
            lowConfidenceCount = 0
        }

        return TrackingResult(bbox: result.boundingBox, confidence: confidence, isTracking: true)
    }

    func stopTracking() {
        trackRequest = nil
        requestHandler = nil
        lowConfidenceCount = 0
        Log.tracking.info("ObjectTracker: stopped")
    }
}
