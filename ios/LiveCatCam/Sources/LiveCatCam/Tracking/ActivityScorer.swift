import Foundation

/// Calculates activity score (0-150) from cat tracking data.
actor ActivityScorer {
    private let smoother = MovingAverage(alpha: 0.3)
    private var lastEventTimes: [ActivityEventType: TimeInterval] = [:]
    private var lastPoseClassifications: [String: PoseClassification] = [:]
    private var poseChangeCounter: Double = 0

    struct ScoreResult: Sendable {
        let rawScore: Double
        let smoothedScore: Double
        let events: [ActivityEvent]
    }

    /// Calculate score from current tracked cats.
    func score(
        cats: [CatTracker.TrackedCat],
        cameraID: String
    ) -> ScoreResult {
        let now = Date().timeIntervalSince1970
        var rawScore: Double = 0
        var events: [ActivityEvent] = []

        guard !cats.isEmpty else {
            let smoothed = smoother.update(0)
            return ScoreResult(rawScore: 0, smoothedScore: smoothed, events: [])
        }

        // 1. Movement Speed (0-30): max speed among all cats
        let maxSpeed = cats.map(\.speed).max() ?? 0
        let speedScore = min(30, maxSpeed / 100 * 30)
        rawScore += speedScore

        // 2. Pose Change (0-30): track pose transitions
        var poseChanges: Double = 0
        for cat in cats {
            if let lastPose = lastPoseClassifications[cat.id],
               lastPose != cat.classification {
                poseChanges += 1
            }
            lastPoseClassifications[cat.id] = cat.classification
        }
        poseChangeCounter = poseChangeCounter * 0.9 + poseChanges * 10
        rawScore += min(30, poseChangeCounter)

        // 3. Proximity (0-20): largest bbox area
        let maxArea = cats.map { Double($0.bbox.width * $0.bbox.height) }.max() ?? 0
        rawScore += min(20, maxArea * 200)

        // 4. Event Bonus (0-50)
        for cat in cats {
            let eventType = detectEvent(cat: cat)
            if let eventType,
               !isOnCooldown(eventType: eventType, now: now) {
                rawScore += min(50, eventType.baseScore * 0.625)  // Scale to 0-50
                lastEventTimes[eventType] = now
                events.append(ActivityEvent(
                    type: eventType,
                    cameraID: cameraID,
                    catIDs: [cat.id],
                    score: eventType.baseScore,
                    timestamp: now,
                    duration: eventType.minimumDuration
                ))
            }
        }

        // 5. Novelty (0-20): reduce score for recent repeated events
        let recentEventCount = lastEventTimes.values.filter { now - $0 < 60 }.count
        let noveltyScore = max(0, 20 - Double(recentEventCount) * 5)
        rawScore += noveltyScore

        // Two-cat interaction bonus
        if cats.count >= 2 {
            let c0 = cats[0].pose.center
            let c1 = cats[1].pose.center
            let dist = hypot(Double(c0.x - c1.x), Double(c0.y - c1.y))
            if dist <= 0.3 {
                rawScore += 30
                if !isOnCooldown(eventType: .interact, now: now) {
                    lastEventTimes[.interact] = now
                    events.append(ActivityEvent(
                        type: .interact,
                        cameraID: cameraID,
                        catIDs: cats.map(\.id),
                        score: ActivityEventType.interact.baseScore,
                        timestamp: now,
                        duration: 3
                    ))
                }
            }
        }

        rawScore = min(150, max(0, rawScore))
        let smoothed = smoother.update(rawScore)

        return ScoreResult(rawScore: rawScore, smoothedScore: smoothed, events: events)
    }

    /// Server expects 0-100, so normalize.
    func serverNormalizedScore(_ score: Double) -> Double {
        min(100, max(0, score / 150 * 100))
    }

    func reset() {
        smoother.reset()
        lastEventTimes.removeAll()
        lastPoseClassifications.removeAll()
        poseChangeCounter = 0
    }

    // MARK: - Event detection

    private func detectEvent(cat: CatTracker.TrackedCat) -> ActivityEventType? {
        switch cat.classification {
        case .climbing where cat.pose.frontLegAngle >= 120:
            return .climb
        case .jumping where cat.airborneFrames >= 3:
            return .jump
        case .running where cat.speed >= 50:
            return .run
        case .stalking, .pouncing:
            return .hunt
        default:
            return nil
        }
    }

    private func isOnCooldown(eventType: ActivityEventType, now: TimeInterval) -> Bool {
        guard let lastTime = lastEventTimes[eventType] else { return false }
        return now - lastTime < eventType.cooldownSeconds
    }
}
