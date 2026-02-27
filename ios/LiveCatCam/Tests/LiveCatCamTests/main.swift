import Foundation
@testable import LiveCatCam

// Simple test runner
var passed = 0
var failed = 0
var errors: [String] = []

func test(_ name: String, _ body: () throws -> Void) {
    do {
        try body()
        passed += 1
        print("  PASS  \(name)")
    } catch {
        failed += 1
        errors.append("\(name): \(error)")
        print("  FAIL  \(name) - \(error)")
    }
}

func testAsync(_ name: String, _ body: @Sendable () async throws -> Void) async {
    do {
        try await body()
        passed += 1
        print("  PASS  \(name)")
    } catch {
        failed += 1
        errors.append("\(name): \(error)")
        print("  FAIL  \(name) - \(error)")
    }
}

struct AssertionError: Error, CustomStringConvertible {
    let description: String
}

func assertEqual<T: Equatable>(_ a: T, _ b: T, accuracy: Double? = nil, file: String = #file, line: Int = #line) throws {
    guard a == b else {
        throw AssertionError(description: "Expected \(a) == \(b) at \(file):\(line)")
    }
}

func assertApprox(_ a: Double, _ b: Double, accuracy: Double = 0.01, file: String = #file, line: Int = #line) throws {
    guard abs(a - b) < accuracy else {
        throw AssertionError(description: "Expected \(a) ≈ \(b) (±\(accuracy)) at \(file):\(line)")
    }
}

func assertTrue(_ condition: Bool, _ msg: String = "", file: String = #file, line: Int = #line) throws {
    guard condition else {
        throw AssertionError(description: "Assertion failed: \(msg) at \(file):\(line)")
    }
}

// ============================================================
print("\n=== KalmanFilter Tests ===")

test("initialUpdateSetsPosition") {
    let filter = KalmanFilter()
    filter.update(measurement: CGPoint(x: 0.5, y: 0.5))
    try assertApprox(filter.position.x, 0.5, accuracy: 0.001)
    try assertApprox(filter.position.y, 0.5, accuracy: 0.001)
}

test("predictMovesPosition") {
    let filter = KalmanFilter(dt: 1.0)
    // Feed enough points to build velocity estimate
    for i in 0..<10 {
        filter.predict()
        filter.update(measurement: CGPoint(x: Double(i), y: 0))
    }
    let posBeforePredict = filter.position.x
    filter.predict()
    try assertTrue(filter.position.x > posBeforePredict,
                   "Position should advance after predict (was \(posBeforePredict), now \(filter.position.x))")
}

test("convergesToStationaryTarget") {
    let filter = KalmanFilter()
    let target = CGPoint(x: 0.42, y: 0.35)
    for _ in 0..<100 {
        filter.predict()
        filter.update(measurement: target)
    }
    try assertApprox(filter.position.x, Double(target.x), accuracy: 0.01)
    try assertApprox(filter.position.y, Double(target.y), accuracy: 0.01)
    try assertTrue(filter.speed < 0.1, "Speed should converge near zero")
}

test("tracksMovingTarget") {
    let filter = KalmanFilter(dt: 1.0 / 30.0)
    for i in 0..<60 {
        let x = Double(i) / 60.0
        filter.predict()
        filter.update(measurement: CGPoint(x: x, y: 0.5))
    }
    try assertApprox(filter.position.x, 59.0 / 60.0, accuracy: 0.1)
    try assertTrue(filter.velocity.x > 0, "Should have positive x velocity")
}

test("resetClearsState") {
    let filter = KalmanFilter()
    filter.update(measurement: CGPoint(x: 0.5, y: 0.5))
    filter.reset()
    try assertApprox(filter.position.x, 0, accuracy: 0.001)
    try assertApprox(filter.position.y, 0, accuracy: 0.001)
    try assertTrue(filter.speed < 0.001, "Speed should be zero after reset")
}

// ============================================================
print("\n=== MetadataMessage Tests ===")

test("metadataMessageEncodesCorrectSnakeCaseKeys") {
    let message = MetadataMessage(
        camID: "CAM-1",
        trackingState: "tracking",
        activityScore: 72.5,
        catPositions: [
            MetadataMessage.CatPosition(x: 0.42, y: 0.35, w: 0.28, h: 0.32, confidence: 0.94)
        ],
        motorPosition: MetadataMessage.MotorPosition(pan: 180, tilt: -35),
        timestamp: 1700000000.123,
        cats: [
            MetadataMessage.CatInfo(
                id: "nana", bbox: [0.38, 0.30, 0.66, 0.62],
                pose: "climbing", speed: 48.5, center: [0.52, 0.46],
                airborneFrames: 0, frontLegAngle: 125
            )
        ],
        huntSignals: []
    )
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    let data = try encoder.encode(message)
    let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

    try assertEqual(json["cam_id"] as? String, "CAM-1")
    try assertEqual(json["tracking_state"] as? String, "tracking")
    try assertEqual(json["activity_score"] as? Double, 72.5)
    try assertTrue(json["cat_positions"] != nil, "cat_positions key must exist")
    try assertTrue(json["motor_position"] != nil, "motor_position key must exist")
    try assertTrue(json["hunt_signals"] != nil, "hunt_signals key must exist")

    let cats = json["cats"] as! [[String: Any]]
    try assertEqual(cats[0]["id"] as? String, "nana")
    try assertEqual(cats[0]["airborne_frames"] as? Int, 0)
    try assertEqual(cats[0]["front_leg_angle"] as? Double, 125)
}

test("registrationMessageEncodes") {
    let msg = RegistrationMessage.register(camID: "CAM-1")
    let data = try JSONEncoder().encode(msg)
    let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]
    try assertEqual(json["type"] as? String, "register")
    try assertEqual(json["cam_id"] as? String, "CAM-1")
}

test("registrationResponseDecodes") {
    let jsonString = #"{"type": "registered", "cam_id": "CAM-1"}"#
    let data = jsonString.data(using: .utf8)!
    let response = try JSONDecoder().decode(RegistrationResponse.self, from: data)
    try assertEqual(response.type, "registered")
    try assertEqual(response.camID, "CAM-1")
}

test("metadataMessageRoundTrips") {
    let message = MetadataMessage(
        camID: "CAM-2", trackingState: "idle", activityScore: 0,
        catPositions: [],
        motorPosition: MetadataMessage.MotorPosition(pan: 180, tilt: 0),
        timestamp: 1700000000.0, cats: [], huntSignals: []
    )
    let data = try JSONEncoder().encode(message)
    let decoded = try JSONDecoder().decode(MetadataMessage.self, from: data)
    try assertEqual(decoded.camID, message.camID)
    try assertEqual(decoded.trackingState, message.trackingState)
    try assertEqual(decoded.activityScore, message.activityScore)
    try assertEqual(decoded.motorPosition.pan, message.motorPosition.pan)
}

// ============================================================
print("\n=== TrackingStateMachine Tests ===")

await testAsync("initialStateIsIdle") {
    let sm = TrackingStateMachine()
    let state = await sm.state
    try assertEqual(state, .idle)
}

await testAsync("idleToTrackingOnDetection") {
    let sm = TrackingStateMachine()
    let state = await sm.update(catDetected: true)
    try assertEqual(state, .tracking)
}

await testAsync("trackingToLostOnNoDetection") {
    let sm = TrackingStateMachine()
    _ = await sm.update(catDetected: true)
    let state = await sm.update(catDetected: false)
    try assertEqual(state, .lost)
}

await testAsync("lostToTrackingOnRedetection") {
    let sm = TrackingStateMachine()
    _ = await sm.update(catDetected: true)
    _ = await sm.update(catDetected: false)
    let state = await sm.update(catDetected: true)
    try assertEqual(state, .tracking)
}

await testAsync("lostToSearchingAfterTimeout") {
    let sm = TrackingStateMachine()
    await sm.forceState(.lost)
    var state: TrackingState = .lost
    for _ in 0..<100 {
        state = await sm.update(catDetected: false)
        if state != .lost { break }
        try await Task.sleep(for: .milliseconds(50))
    }
    try assertEqual(state, .searching)
}

await testAsync("forceStateWorks") {
    let sm = TrackingStateMachine()
    await sm.forceState(.searching)
    let state = await sm.state
    try assertEqual(state, .searching)
}

await testAsync("resetGoesToIdle") {
    let sm = TrackingStateMachine()
    _ = await sm.update(catDetected: true)
    await sm.reset()
    let state = await sm.state
    try assertEqual(state, .idle)
}

await testAsync("searchingToTrackingOnDetection") {
    let sm = TrackingStateMachine()
    await sm.forceState(.searching)
    let state = await sm.update(catDetected: true)
    try assertEqual(state, .tracking)
}

// ============================================================
print("\n=== ActivityScorer Tests ===")

await testAsync("scoreRangeWithNoCats") {
    let scorer = ActivityScorer()
    let result = await scorer.score(cats: [], cameraID: "CAM-1")
    try assertEqual(result.rawScore, 0)
    try assertTrue(result.smoothedScore >= 0 && result.smoothedScore <= 150,
                   "Smoothed score should be in range [0, 150]")
}

await testAsync("serverNormalizedScore") {
    let scorer = ActivityScorer()
    let zero = await scorer.serverNormalizedScore(0)
    try assertApprox(zero, 0, accuracy: 0.001)
    let max = await scorer.serverNormalizedScore(150)
    try assertApprox(max, 100, accuracy: 0.001)
    let mid = await scorer.serverNormalizedScore(75)
    try assertApprox(mid, 50, accuracy: 0.001)
}

// ============================================================
print("\n=== CatPose Tests ===")

test("catPoseCenter") {
    let pose = CatPose(joints: [
        CatPose.Joint(name: "nose", location: CGPoint(x: 0.4, y: 0.6), confidence: 0.9),
        CatPose.Joint(name: "neck", location: CGPoint(x: 0.6, y: 0.4), confidence: 0.9),
    ], timestamp: 0)
    let center = pose.center
    try assertApprox(Double(center.x), 0.5, accuracy: 0.001)
    try assertApprox(Double(center.y), 0.5, accuracy: 0.001)
}

test("catPoseBoundingBox") {
    let pose = CatPose(joints: [
        CatPose.Joint(name: "nose", location: CGPoint(x: 0.3, y: 0.3), confidence: 0.9),
        CatPose.Joint(name: "tail", location: CGPoint(x: 0.7, y: 0.7), confidence: 0.9),
    ], timestamp: 0)
    let bbox = pose.boundingBox
    try assertTrue(bbox.minX >= 0 && bbox.minY >= 0, "bbox origin should be >= 0")
    try assertTrue(bbox.maxX <= 1 && bbox.maxY <= 1, "bbox max should be <= 1")
    try assertTrue(bbox.width > 0 && bbox.height > 0, "bbox should have positive dimensions")
}

test("catPoseLowConfidenceFiltering") {
    let pose = CatPose(joints: [
        CatPose.Joint(name: "nose", location: CGPoint(x: 0.5, y: 0.5), confidence: 0.9),
        CatPose.Joint(name: "junk", location: CGPoint(x: 0.0, y: 0.0), confidence: 0.1),
    ], timestamp: 0)
    let center = pose.center
    try assertApprox(Double(center.x), 0.5, accuracy: 0.001)
    try assertApprox(Double(center.y), 0.5, accuracy: 0.001)
}

// ============================================================
print("\n=== MovingAverage Tests ===")

test("movingAverageInitialValue") {
    let ma = MovingAverage(alpha: 0.3)
    let v = ma.update(100)
    try assertApprox(v, 100, accuracy: 0.001)
}

test("movingAverageSmoothing") {
    let ma = MovingAverage(alpha: 0.3)
    _ = ma.update(100)
    let v = ma.update(0)
    try assertApprox(v, 70, accuracy: 0.001)  // 0.3*0 + 0.7*100 = 70
}

// ============================================================
// Summary
print("\n===================================")
print("  Results: \(passed) passed, \(failed) failed")
print("===================================")

if !errors.isEmpty {
    print("\nFailures:")
    for e in errors {
        print("  - \(e)")
    }
}

if failed > 0 {
    exit(1)
}
