import Foundation
import Network

/// Sends real-time logs to a UDP endpoint.
/// Buffers messages and flushes in 100ms batches to reduce overhead.
/// Usage: RemoteLogger.shared.log("message")
final class RemoteLogger: @unchecked Sendable {
    static let shared = RemoteLogger()

    // UDP target — on simulator 127.0.0.1 works; on device use Mac's LAN IP
    private let host = "192.168.123.107"
    private let port: UInt16 = 9999

    private let queue = DispatchQueue(label: "RemoteLogger.udp")
    private var connection: NWConnection?
    private var buffer: [String] = []
    private var flushTimer: DispatchSourceTimer?

    private init() {
        NSLog("%@", "[RLOG] Init UDP -> \(host):\(port)")
        setupConnection()
        startFlushTimer()
    }

    private func setupConnection() {
        let endpoint = NWEndpoint.hostPort(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!
        )
        let conn = NWConnection(to: endpoint, using: .udp)
        conn.stateUpdateHandler = { state in
            NSLog("%@", "[RLOG] UDP state: \(state)")
        }
        conn.start(queue: queue)
        connection = conn
    }

    private func startFlushTimer() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + .milliseconds(100), repeating: .milliseconds(100))
        timer.setEventHandler { [weak self] in
            self?.flush()
        }
        timer.resume()
        flushTimer = timer
    }

    private func flush() {
        guard !buffer.isEmpty, let connection else { return }
        let batch = buffer.joined(separator: "\n") + "\n"
        buffer.removeAll()
        let data = Data(batch.utf8)
        connection.send(content: data, completion: .idempotent)
    }

    func log(_ msg: String) {
        let ts = String(format: "%.3f", CFAbsoluteTimeGetCurrent().truncatingRemainder(dividingBy: 100000))
        queue.async { [weak self] in
            self?.buffer.append("[\(ts)] \(msg)")
        }
    }
}
