import Foundation
import Network

/// Discovers LiveCat server on local network via Bonjour (mDNS).
/// Server registers `_livecat._tcp` service; this class finds it.
@Observable
final class ServiceDiscoveryManager: @unchecked Sendable {

    struct DiscoveredServer: Identifiable, Sendable {
        let id = UUID()
        let name: String
        let host: String
        let port: UInt16
        let httpPort: UInt16?
        let platform: String?
    }

    // MARK: - Published state

    private(set) var servers: [DiscoveredServer] = []
    private(set) var isSearching = false

    // MARK: - Private

    private var browser: NWBrowser?
    private let queue = DispatchQueue(label: "com.livecat.discovery")

    // MARK: - Public API

    /// Start browsing for `_livecat._tcp` services.
    func startBrowsing() {
        stopBrowsing()
        servers = []
        isSearching = true

        let params = NWParameters()
        params.includePeerToPeer = true

        let descriptor = NWBrowser.Descriptor.bonjour(type: "_livecat._tcp", domain: nil)
        let browser = NWBrowser(for: descriptor, using: params)

        browser.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                Log.network.info("[Discovery] Browsing for _livecat._tcp...")
            case .failed(let error):
                Log.network.error("[Discovery] Browse failed: \(error)")
                DispatchQueue.main.async { self?.isSearching = false }
            case .cancelled:
                DispatchQueue.main.async { self?.isSearching = false }
            default:
                break
            }
        }

        browser.browseResultsChangedHandler = { [weak self] results, _ in
            self?.handleResults(results)
        }

        browser.start(queue: queue)
        self.browser = browser

        // Auto-stop after 10 seconds
        queue.asyncAfter(deadline: .now() + 10) { [weak self] in
            DispatchQueue.main.async {
                self?.isSearching = false
            }
        }
    }

    /// Stop browsing.
    func stopBrowsing() {
        browser?.cancel()
        browser = nil
        isSearching = false
    }

    // MARK: - Private

    private func handleResults(_ results: Set<NWBrowser.Result>) {
        for result in results {
            if case .service(let name, let type, _, _) = result.endpoint {
                Log.network.info("[Discovery] Found: \(name) (\(type))")
                resolveEndpoint(result.endpoint, name: name)
            }
        }
    }

    private func resolveEndpoint(_ endpoint: NWEndpoint, name: String) {
        let connection = NWConnection(to: endpoint, using: .tcp)
        connection.stateUpdateHandler = { [weak self] state in
            if case .ready = state {
                if let innerEndpoint = connection.currentPath?.remoteEndpoint,
                   case .hostPort(let host, let port) = innerEndpoint {
                    let hostStr: String
                    switch host {
                    case .ipv4(let addr):
                        hostStr = "\(addr)"
                    case .ipv6(let addr):
                        hostStr = "\(addr)"
                    case .name(let hostname, _):
                        hostStr = hostname
                    @unknown default:
                        hostStr = "\(host)"
                    }

                    let server = DiscoveredServer(
                        name: name,
                        host: hostStr,
                        port: port.rawValue,
                        httpPort: nil,
                        platform: nil
                    )
                    DispatchQueue.main.async {
                        // Avoid duplicates
                        if !(self?.servers.contains(where: { $0.host == hostStr && $0.port == port.rawValue }) ?? true) {
                            self?.servers.append(server)
                        }
                        Log.network.info("[Discovery] Resolved: \(hostStr):\(port.rawValue)")
                    }
                }
                connection.cancel()
            }
        }
        connection.start(queue: queue)
    }
}
