import Foundation

/// Exponential moving average for score smoothing.
final class MovingAverage: @unchecked Sendable {
    private let alpha: Double
    private var value: Double?

    /// - Parameter alpha: Smoothing factor (0-1). Higher = more responsive. Server uses 0.3.
    init(alpha: Double = 0.3) {
        self.alpha = max(0, min(1, alpha))
    }

    /// Update with a new raw value and return the smoothed result.
    @discardableResult
    func update(_ newValue: Double) -> Double {
        guard let current = value else {
            value = newValue
            return newValue
        }
        let smoothed = alpha * newValue + (1 - alpha) * current
        value = smoothed
        return smoothed
    }

    /// Current smoothed value, or 0 if no data yet.
    var current: Double {
        value ?? 0
    }

    /// Reset the filter.
    func reset() {
        value = nil
    }
}
