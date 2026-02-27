import Foundation

/// State machine for tracking lifecycle: idle → searching → tracking → lost → idle.
actor TrackingStateMachine {
    private(set) var state: TrackingState = .idle
    private var stateEntryTime: TimeInterval = 0

    // Configurable timeouts
    var lostTimeout: TimeInterval = 3.0
    var searchTimeout: TimeInterval = 10.0
    var idleTimeout: TimeInterval = 30.0

    var onStateChange: ((TrackingState, TrackingState) -> Void)?

    /// Called each frame with detection results.
    func update(catDetected: Bool) -> TrackingState {
        let now = Date().timeIntervalSince1970
        let elapsed = now - stateEntryTime
        let oldState = state

        switch state {
        case .idle:
            if catDetected {
                transition(to: .tracking, at: now)
            } else if elapsed > idleTimeout {
                transition(to: .searching, at: now)
            }

        case .searching:
            if catDetected {
                transition(to: .tracking, at: now)
            } else if elapsed > searchTimeout {
                transition(to: .idle, at: now)
            }

        case .tracking:
            if !catDetected {
                transition(to: .lost, at: now)
            }

        case .lost:
            if catDetected {
                transition(to: .tracking, at: now)
            } else if elapsed > lostTimeout {
                transition(to: .searching, at: now)
            }
        }

        if state != oldState {
            onStateChange?(oldState, state)
        }

        return state
    }

    func forceState(_ newState: TrackingState) {
        let now = Date().timeIntervalSince1970
        transition(to: newState, at: now)
    }

    func reset() {
        state = .idle
        stateEntryTime = Date().timeIntervalSince1970
    }

    // MARK: - Private

    private func transition(to newState: TrackingState, at time: TimeInterval) {
        Log.tracking.info("State: \(self.state.rawValue) → \(newState.rawValue)")
        state = newState
        stateEntryTime = time
    }
}
