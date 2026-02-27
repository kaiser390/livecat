import Foundation
import Network

/// Monitors Wi-Fi connectivity and triggers reconnection.
final class ConnectionMonitor: @unchecked Sendable {
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "com.livecat.connectionMonitor")

    private(set) var isConnected = false
    private(set) var isWiFi = false
    var onConnectionChanged: ((Bool) -> Void)?

    func start() {
        monitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let wasConnected = self.isConnected
            self.isConnected = path.status == .satisfied
            self.isWiFi = path.usesInterfaceType(.wifi)

            if self.isConnected {
                Log.network.info("Network: connected (WiFi: \(self.isWiFi))")
            } else {
                Log.network.warning("Network: disconnected")
            }

            if wasConnected != self.isConnected {
                self.onConnectionChanged?(self.isConnected)
            }
        }
        monitor.start(queue: queue)
        Log.network.info("ConnectionMonitor started")
    }

    func stop() {
        monitor.cancel()
        Log.network.info("ConnectionMonitor stopped")
    }
}
