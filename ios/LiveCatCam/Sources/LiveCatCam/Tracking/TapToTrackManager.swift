import Foundation
import Vision
import CoreImage
import os

/// Manages tap-to-track lifecycle: tap selection → VNTrackObjectRequest → loss → search → timeout.
///
/// State flow:
/// ```
/// [idle] ──tap──→ [tracking] ──loss──→ [searching] ──found──→ [tracking]
///   ↑                  │                     │
///   └──────stop────────┘                     │
///   └──────────timeout───────────────────────┘
/// ```
@MainActor
final class TapToTrackManager {

    // MARK: - Types

    enum State: String, Sendable {
        case idle
        case tracking
        case searching
    }

    struct TrackResult: Sendable {
        let state: State
        let bbox: CGRect?
        let confidence: Float
        let objectSpeed: Double
        let lastVelocityX: Double
        let lastVelocityY: Double

        static let idle = TrackResult(
            state: .idle, bbox: nil, confidence: 0,
            objectSpeed: 0, lastVelocityX: 0, lastVelocityY: 0
        )
    }

    // MARK: - Configuration

    /// Minimum confidence to consider tracking valid
    var minConfidence: Float = 0.3
    /// Seconds to search before giving up
    var searchTimeout: TimeInterval = 5.0
    /// Initial bbox size around tap point (normalized, 0-1)
    var initialBBoxSize: CGFloat = 0.15

    // MARK: - State

    private(set) var state: State = .idle
    private var trackingRequest: VNTrackObjectRequest?
    private var lastObservation: VNDetectedObjectObservation?
    private var lastKnownBBox: CGRect?
    private var previousBBoxCenter: CGPoint?
    private var lastVelocityX: Double = 0
    private var lastVelocityY: Double = 0
    private var objectSpeed: Double = 0
    private var searchStartTime: TimeInterval = 0
    private var targetID: UUID = UUID()

    // Speed smoothing
    private var speedHistory: [Double] = []
    private let speedHistorySize = 5

    // MARK: - Public API

    /// Start tracking an object at the tapped normalized point.
    /// - Parameters:
    ///   - normalizedPoint: Tap location in Vision coordinates (0,0)=bottom-left, (1,1)=top-right.
    ///   - pixelBuffer: Current camera frame to initialize tracking from.
    func startTracking(at normalizedPoint: CGPoint, in pixelBuffer: CVPixelBuffer) {
        // Cancel any existing tracking
        stopTracking()

        // Create bbox centered on tap point
        let halfSize = initialBBoxSize / 2
        let bbox = CGRect(
            x: max(0, normalizedPoint.x - halfSize),
            y: max(0, normalizedPoint.y - halfSize),
            width: min(initialBBoxSize, 1.0 - max(0, normalizedPoint.x - halfSize)),
            height: min(initialBBoxSize, 1.0 - max(0, normalizedPoint.y - halfSize))
        )

        let observation = VNDetectedObjectObservation(boundingBox: bbox)
        setupTrackingRequest(with: observation)

        state = .tracking
        lastKnownBBox = bbox
        previousBBoxCenter = CGPoint(x: bbox.midX, y: bbox.midY)
        targetID = UUID()
        speedHistory.removeAll()

        Log.tracking.info("Tap-to-Track: started at (\(normalizedPoint.x), \(normalizedPoint.y))")
    }

    /// Start tracking a specific detected object (e.g., a cat that was tapped).
    func startTracking(bbox: CGRect) {
        stopTracking()

        let observation = VNDetectedObjectObservation(boundingBox: bbox)
        setupTrackingRequest(with: observation)

        state = .tracking
        lastKnownBBox = bbox
        previousBBoxCenter = CGPoint(x: bbox.midX, y: bbox.midY)
        targetID = UUID()
        speedHistory.removeAll()

        Log.tracking.info("Tap-to-Track: started on bbox \(String(describing: bbox))")
    }

    /// Stop all tracking and return to idle.
    func stopTracking() {
        state = .idle
        trackingRequest = nil
        lastObservation = nil
        lastKnownBBox = nil
        previousBBoxCenter = nil
        lastVelocityX = 0
        lastVelocityY = 0
        objectSpeed = 0
        speedHistory.removeAll()

        Log.tracking.info("Tap-to-Track: stopped")
    }

    /// Process a camera frame for tracking. Call this every frame.
    /// - Parameter pixelBuffer: Current camera frame.
    /// - Returns: Tracking result with bbox, speed, and state info.
    func processFrame(_ pixelBuffer: CVPixelBuffer) -> TrackResult {
        switch state {
        case .idle:
            return .idle

        case .tracking:
            return performTracking(pixelBuffer)

        case .searching:
            return performSearch(pixelBuffer)
        }
    }

    /// Current target ID (changes when a new object is tapped).
    var currentTargetID: UUID { targetID }

    // MARK: - Private: Tracking

    private func performTracking(_ pixelBuffer: CVPixelBuffer) -> TrackResult {
        guard let request = trackingRequest else {
            state = .idle
            return .idle
        }

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .up)
        do {
            try handler.perform([request])
        } catch {
            Log.tracking.error("VNTrackObjectRequest failed: \(error)")
            enterSearchMode()
            return makeSearchResult()
        }

        guard let result = request.results?.first as? VNDetectedObjectObservation else {
            Log.tracking.info("Tap-to-Track: no observation result, entering search")
            enterSearchMode()
            return makeSearchResult()
        }

        // Check confidence
        if result.confidence < minConfidence {
            Log.tracking.info("Tap-to-Track: low confidence \(result.confidence), entering search")
            enterSearchMode()
            return makeSearchResult()
        }

        // Update velocity from bbox movement
        let currentCenter = CGPoint(x: result.boundingBox.midX, y: result.boundingBox.midY)
        if let prev = previousBBoxCenter {
            lastVelocityX = Double(currentCenter.x - prev.x)
            lastVelocityY = Double(currentCenter.y - prev.y)
            let frameSpeed = sqrt(lastVelocityX * lastVelocityX + lastVelocityY * lastVelocityY)
            updateSpeedHistory(frameSpeed)
        }
        previousBBoxCenter = currentCenter
        lastKnownBBox = result.boundingBox

        // Prepare next frame's tracking request
        setupTrackingRequest(with: result)

        return TrackResult(
            state: .tracking,
            bbox: result.boundingBox,
            confidence: result.confidence,
            objectSpeed: objectSpeed,
            lastVelocityX: lastVelocityX,
            lastVelocityY: lastVelocityY
        )
    }

    // MARK: - Private: Search Mode

    private func enterSearchMode() {
        state = .searching
        searchStartTime = Date().timeIntervalSince1970
        Log.tracking.info("Tap-to-Track: search mode (dir: vx=\(self.lastVelocityX), vy=\(self.lastVelocityY))")
    }

    private func performSearch(_ pixelBuffer: CVPixelBuffer) -> TrackResult {
        let now = Date().timeIntervalSince1970

        // Timeout check
        if now - searchStartTime > searchTimeout {
            Log.tracking.info("Tap-to-Track: search timeout, going idle")
            stopTracking()
            return .idle
        }

        // Try to re-detect the object using the last known observation
        if let lastObs = lastObservation {
            let request = VNTrackObjectRequest(detectedObjectObservation: lastObs)
            request.trackingLevel = .accurate
            let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .up)
            do {
                try handler.perform([request])
                if let result = request.results?.first as? VNDetectedObjectObservation,
                   result.confidence >= minConfidence {
                    // Re-acquired!
                    Log.tracking.info("Tap-to-Track: re-acquired (confidence: \(result.confidence))")
                    state = .tracking
                    setupTrackingRequest(with: result)
                    lastKnownBBox = result.boundingBox
                    previousBBoxCenter = CGPoint(x: result.boundingBox.midX, y: result.boundingBox.midY)
                    return TrackResult(
                        state: .tracking,
                        bbox: result.boundingBox,
                        confidence: result.confidence,
                        objectSpeed: objectSpeed,
                        lastVelocityX: lastVelocityX,
                        lastVelocityY: lastVelocityY
                    )
                }
            } catch {
                // Continue searching
            }
        }

        return makeSearchResult()
    }

    private func makeSearchResult() -> TrackResult {
        TrackResult(
            state: .searching,
            bbox: lastKnownBBox,
            confidence: 0,
            objectSpeed: objectSpeed,
            lastVelocityX: lastVelocityX,
            lastVelocityY: lastVelocityY
        )
    }

    // MARK: - Helpers

    private func setupTrackingRequest(with observation: VNDetectedObjectObservation) {
        lastObservation = observation
        let request = VNTrackObjectRequest(detectedObjectObservation: observation)
        request.trackingLevel = .accurate
        trackingRequest = request
    }

    private func updateSpeedHistory(_ speed: Double) {
        speedHistory.append(speed)
        if speedHistory.count > speedHistorySize {
            speedHistory.removeFirst()
        }
        objectSpeed = speedHistory.reduce(0, +) / Double(speedHistory.count)
    }
}
