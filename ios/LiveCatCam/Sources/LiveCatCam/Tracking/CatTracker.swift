import Foundation

/// Tracks up to 2 cats across frames using Kalman filtering.
actor CatTracker {
    struct TrackedCat: Sendable {
        let id: String
        var pose: CatPose
        var classification: PoseClassification
        var speed: Double
        var airborneFrames: Int
        var lastSeen: TimeInterval
        var bbox: CGRect
        var confidence: Float
    }

    private var trackedCats: [TrackedCat] = []
    private var filters: [String: KalmanFilter] = [:]
    private let maxCats = 2
    private let lostTimeout: TimeInterval = 3.0
    private let associationThreshold: Double = 0.3

    // Assigned profiles for identification
    private let profiles: [CatProfile] = CatProfile.all

    /// Update tracking with new detections from CatDetector.
    func update(detections: CatDetector.DetectionResult) -> [TrackedCat] {
        let now = Date().timeIntervalSince1970

        // Remove stale tracks
        trackedCats.removeAll { now - $0.lastSeen > lostTimeout }

        // Associate detections with existing tracks (nearest neighbor)
        var usedDetections = Set<Int>()

        for i in 0..<trackedCats.count {
            var bestIdx = -1
            var bestDist = Double.infinity

            for (j, bbox) in detections.boundingBoxes.enumerated() {
                guard !usedDetections.contains(j) else { continue }
                let center = CGPoint(x: bbox.midX, y: bbox.midY)
                let trackCenter = trackedCats[i].pose.center
                let dist = hypot(Double(center.x - trackCenter.x),
                                 Double(center.y - trackCenter.y))
                if dist < bestDist && dist < associationThreshold {
                    bestDist = dist
                    bestIdx = j
                }
            }

            if bestIdx >= 0 {
                usedDetections.insert(bestIdx)
                let pose = detections.poses[bestIdx]
                let filter = getFilter(for: trackedCats[i].id)
                filter.predict()
                filter.update(measurement: pose.center)

                let speed = filter.speed * 30  // Convert from per-frame to per-second
                let verticalVelocity = Double(filter.velocity.y) * 30

                // Detect airborne: y position increasing (cat going up in Vision coords)
                var airborne = trackedCats[i].airborneFrames
                if verticalVelocity > 20 {
                    airborne += 1
                } else {
                    airborne = 0
                }

                let classification = PoseClassifier.classify(
                    pose: pose,
                    speed: speed,
                    airborneFrames: airborne,
                    verticalVelocity: verticalVelocity
                )

                trackedCats[i] = TrackedCat(
                    id: trackedCats[i].id,
                    pose: pose,
                    classification: classification,
                    speed: speed,
                    airborneFrames: airborne,
                    lastSeen: now,
                    bbox: detections.boundingBoxes[bestIdx],
                    confidence: detections.confidences[bestIdx]
                )
            }
        }

        // Create new tracks for unmatched detections
        for (j, pose) in detections.poses.enumerated() {
            guard !usedDetections.contains(j) else { continue }
            guard trackedCats.count < maxCats else { break }

            let id = profiles.indices.contains(trackedCats.count)
                ? profiles[trackedCats.count].id
                : "cat-\(trackedCats.count)"

            let filter = KalmanFilter()
            filter.update(measurement: pose.center)
            filters[id] = filter

            let classification = PoseClassifier.classify(
                pose: pose, speed: 0, airborneFrames: 0, verticalVelocity: 0
            )

            trackedCats.append(TrackedCat(
                id: id,
                pose: pose,
                classification: classification,
                speed: 0,
                airborneFrames: 0,
                lastSeen: now,
                bbox: detections.boundingBoxes[j],
                confidence: detections.confidences[j]
            ))
        }

        return trackedCats
    }

    var currentCats: [TrackedCat] { trackedCats }
    var isTracking: Bool { !trackedCats.isEmpty }
    var catCount: Int { trackedCats.count }

    func reset() {
        trackedCats.removeAll()
        filters.removeAll()
    }

    // MARK: - Helpers

    private func getFilter(for id: String) -> KalmanFilter {
        if let filter = filters[id] { return filter }
        let filter = KalmanFilter()
        filters[id] = filter
        return filter
    }

    /// Convert tracked cats to server metadata format.
    func toMetadataCats() -> [MetadataMessage.CatInfo] {
        trackedCats.map { cat in
            let bbox = cat.bbox
            return MetadataMessage.CatInfo(
                id: cat.id,
                bbox: [Double(bbox.minX), Double(bbox.minY),
                       Double(bbox.maxX), Double(bbox.maxY)],
                pose: cat.classification.rawValue,
                speed: cat.speed,
                center: [Double(cat.pose.center.x), Double(cat.pose.center.y)],
                airborneFrames: cat.airborneFrames,
                frontLegAngle: cat.pose.frontLegAngle
            )
        }
    }

    /// Convert to cat_positions format.
    func toCatPositions() -> [MetadataMessage.CatPosition] {
        trackedCats.map { cat in
            CoordinateMapper.toCatPosition(bbox: cat.bbox, confidence: Double(cat.confidence))
        }
    }
}
