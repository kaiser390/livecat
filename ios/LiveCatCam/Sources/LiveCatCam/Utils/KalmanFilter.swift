import Foundation

/// 2D Kalman filter for position + velocity estimation and smoothing.
final class KalmanFilter: @unchecked Sendable {
    // State: [x, y, vx, vy]
    private var state: [Double]
    // State covariance (4x4)
    private var P: [[Double]]
    // Process noise
    private let Q: Double
    // Measurement noise
    private let R: Double
    // Time step
    private let dt: Double

    private var initialized = false

    init(processNoise: Double = 0.01, measurementNoise: Double = 0.1, dt: Double = 1.0 / 30.0) {
        self.Q = processNoise
        self.R = measurementNoise
        self.dt = dt
        self.state = [0, 0, 0, 0]
        self.P = Self.identity(4, scale: 1.0)
    }

    /// Predict step: advance state by dt.
    func predict() {
        guard initialized else { return }
        // x = x + vx * dt
        state[0] += state[2] * dt
        // y = y + vy * dt
        state[1] += state[3] * dt

        // Update covariance: P = F * P * F^T + Q*I
        let F = transitionMatrix
        P = Self.add(Self.multiply(Self.multiply(F, P), Self.transpose(F)),
                     Self.identity(4, scale: Q))
    }

    /// Update step: correct state with measurement [x, y].
    func update(measurement: CGPoint) {
        if !initialized {
            state = [Double(measurement.x), Double(measurement.y), 0, 0]
            initialized = true
            return
        }

        // Innovation: z - H * x (H extracts position)
        let zx = Double(measurement.x) - state[0]
        let zy = Double(measurement.y) - state[1]

        // Innovation covariance: S = H * P * H^T + R
        let s00 = P[0][0] + R
        let s01 = P[0][1]
        let s10 = P[1][0]
        let s11 = P[1][1] + R

        // Kalman gain: K = P * H^T * S^-1
        let det = s00 * s11 - s01 * s10
        guard abs(det) > 1e-10 else { return }
        let sInv00 = s11 / det
        let sInv01 = -s01 / det
        let sInv10 = -s10 / det
        let sInv11 = s00 / det

        // K is 4x2
        var K = [[Double]](repeating: [0, 0], count: 4)
        for i in 0..<4 {
            K[i][0] = P[i][0] * sInv00 + P[i][1] * sInv10
            K[i][1] = P[i][0] * sInv01 + P[i][1] * sInv11
        }

        // State update: x = x + K * innovation
        for i in 0..<4 {
            state[i] += K[i][0] * zx + K[i][1] * zy
        }

        // Covariance update: P = (I - K*H) * P
        var KH = Self.identity(4, scale: 0)
        for i in 0..<4 {
            KH[i][0] = K[i][0]
            KH[i][1] = K[i][1]
        }
        let ImKH = Self.subtract(Self.identity(4, scale: 1), KH)
        P = Self.multiply(ImKH, P)
    }

    /// Current estimated position.
    var position: CGPoint {
        CGPoint(x: state[0], y: state[1])
    }

    /// Current estimated velocity.
    var velocity: CGPoint {
        CGPoint(x: state[2], y: state[3])
    }

    /// Speed in units per second.
    var speed: Double {
        sqrt(state[2] * state[2] + state[3] * state[3])
    }

    /// Reset filter state.
    func reset() {
        state = [0, 0, 0, 0]
        P = Self.identity(4, scale: 1.0)
        initialized = false
    }

    // MARK: - Matrix helpers

    private var transitionMatrix: [[Double]] {
        [
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1,  0],
            [0, 0, 0,  1]
        ]
    }

    private static func identity(_ n: Int, scale: Double) -> [[Double]] {
        var m = [[Double]](repeating: [Double](repeating: 0, count: n), count: n)
        for i in 0..<n { m[i][i] = scale }
        return m
    }

    private static func multiply(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        let n = a.count
        let m = b[0].count
        let p = b.count
        var result = [[Double]](repeating: [Double](repeating: 0, count: m), count: n)
        for i in 0..<n {
            for j in 0..<m {
                for k in 0..<p {
                    result[i][j] += a[i][k] * b[k][j]
                }
            }
        }
        return result
    }

    private static func transpose(_ a: [[Double]]) -> [[Double]] {
        let n = a.count
        let m = a[0].count
        var result = [[Double]](repeating: [Double](repeating: 0, count: n), count: m)
        for i in 0..<n {
            for j in 0..<m {
                result[j][i] = a[i][j]
            }
        }
        return result
    }

    private static func add(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        let n = a.count
        let m = a[0].count
        var result = a
        for i in 0..<n {
            for j in 0..<m {
                result[i][j] += b[i][j]
            }
        }
        return result
    }

    private static func subtract(_ a: [[Double]], _ b: [[Double]]) -> [[Double]] {
        let n = a.count
        let m = a[0].count
        var result = a
        for i in 0..<n {
            for j in 0..<m {
                result[i][j] -= b[i][j]
            }
        }
        return result
    }
}
