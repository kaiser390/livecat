import Foundation
import Network
import os

/// Discovers servers on local network via two methods:
/// 1. Bonjour (_livecat._tcp) — finds live_auto.py server
/// 2. OBS subnet scan — TCP probe port 4455 (OBS WebSocket) across local subnet
@Observable
final class ServiceDiscoveryManager: @unchecked Sendable {

    struct DiscoveredServer: Identifiable, Sendable {
        let id = UUID()
        let name: String
        let host: String
        let port: UInt16
        let httpPort: UInt16?
        let platform: String?
        let type: ServerType

        enum ServerType: Sendable {
            case liveCat   // live_auto.py via Bonjour
            case obs       // OBS Direct via subnet scan
        }
    }

    // MARK: - Published state

    private(set) var servers: [DiscoveredServer] = []
    private(set) var isSearching = false

    // MARK: - Private

    private var browser: NWBrowser?
    private let queue = DispatchQueue(label: "com.livecat.discovery", attributes: .concurrent)
    private var scanTask: Task<Void, Never>?

    // MARK: - Public API

    /// Start both Bonjour browsing and OBS subnet scan simultaneously.
    func startBrowsing() {
        stopBrowsing()
        servers = []
        isSearching = true

        startBonjourBrowsing()
        startOBSScan()

        // Auto-stop after 10 seconds
        scanTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 10_000_000_000)
            await MainActor.run { self?.isSearching = false }
        }
    }

    /// Stop all discovery.
    func stopBrowsing() {
        browser?.cancel()
        browser = nil
        scanTask?.cancel()
        scanTask = nil
        isSearching = false
    }

    // MARK: - Bonjour (live_auto.py)

    private func startBonjourBrowsing() {
        let params = NWParameters()
        params.includePeerToPeer = true

        let descriptor = NWBrowser.Descriptor.bonjour(type: "_livecat._tcp", domain: nil)
        let browser = NWBrowser(for: descriptor, using: params)

        browser.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed(let error):
                Log.network.error("[Discovery] Bonjour failed: \(error)")
                DispatchQueue.main.async { self?.isSearching = false }
            default:
                break
            }
        }

        browser.browseResultsChangedHandler = { [weak self] results, _ in
            self?.handleBonjourResults(results)
        }

        browser.start(queue: queue)
        self.browser = browser
    }

    private func handleBonjourResults(_ results: Set<NWBrowser.Result>) {
        for result in results {
            if case .service(let name, _, _, _) = result.endpoint {
                Log.network.info("[Discovery] Bonjour found: \(name)")
                resolveBonjourEndpoint(result.endpoint, name: name)
            }
        }
    }

    private func resolveBonjourEndpoint(_ endpoint: NWEndpoint, name: String) {
        let connection = NWConnection(to: endpoint, using: .tcp)
        connection.stateUpdateHandler = { [weak self] state in
            if case .ready = state {
                if let innerEndpoint = connection.currentPath?.remoteEndpoint,
                   case .hostPort(let host, let port) = innerEndpoint {
                    let hostStr = Self.hostString(from: host)
                    self?.addServer(DiscoveredServer(
                        name: name,
                        host: hostStr,
                        port: port.rawValue,
                        httpPort: nil,
                        platform: nil,
                        type: .liveCat
                    ))
                    Log.network.info("[Discovery] Bonjour resolved: \(hostStr):\(port.rawValue)")
                }
                connection.cancel()
            }
        }
        connection.start(queue: queue)
    }

    // MARK: - OBS Subnet Scan (port 4455)

    private func startOBSScan() {
        guard let subnet = localSubnet() else {
            Log.network.warning("[Discovery] Could not determine local subnet")
            return
        }
        Log.network.info("[Discovery] Scanning subnet \(subnet).1-254 for OBS (port 4455)...")

        // Scan concurrently in batches
        scanTask = Task { [weak self] in
            await withTaskGroup(of: Void.self) { group in
                for i in 1...254 {
                    let ip = "\(subnet).\(i)"
                    group.addTask {
                        await self?.probeOBS(ip: ip)
                    }
                }
            }
        }
    }

    private func probeOBS(ip: String) async {
        // TCP connect to OBS WebSocket port 4455
        let connected = await tcpProbe(host: ip, port: 4455, timeout: 0.8)
        guard connected else { return }

        Log.network.info("[Discovery] OBS found at \(ip):4455")
        addServer(DiscoveredServer(
            name: "OBS Studio",
            host: ip,
            port: 9000,   // streaming port for the app
            httpPort: 4455,
            platform: nil,
            type: .obs
        ))
    }

    private func tcpProbe(host: String, port: UInt16, timeout: TimeInterval) async -> Bool {
        await withCheckedContinuation { continuation in
            let conn = NWConnection(
                host: NWEndpoint.Host(host),
                port: NWEndpoint.Port(integerLiteral: port),
                using: .tcp
            )
            var resolved = false
            let timer = DispatchWorkItem {
                if !resolved { resolved = true; conn.cancel(); continuation.resume(returning: false) }
            }
            conn.stateUpdateHandler = { state in
                guard !resolved else { return }
                switch state {
                case .ready:
                    resolved = true
                    timer.cancel()
                    conn.cancel()
                    continuation.resume(returning: true)
                case .failed, .cancelled:
                    resolved = true
                    timer.cancel()
                    continuation.resume(returning: false)
                default:
                    break
                }
            }
            conn.start(queue: queue)
            queue.asyncAfter(deadline: .now() + timeout, execute: timer)
        }
    }

    // MARK: - Helpers

    private func addServer(_ server: DiscoveredServer) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let duplicate = self.servers.contains { $0.host == server.host && $0.type == server.type }
            if !duplicate {
                self.servers.append(server)
            }
        }
    }

    private func localSubnet() -> String? {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0 else { return nil }
        defer { freeifaddrs(ifaddr) }

        var ptr = ifaddr
        while let current = ptr {
            let interface = current.pointee
            if interface.ifa_addr.pointee.sa_family == UInt8(AF_INET) {
                let name = String(cString: interface.ifa_name)
                if name.hasPrefix("en") {
                    var addr = interface.ifa_addr.pointee
                    var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                    getnameinfo(&addr, socklen_t(interface.ifa_addr.pointee.sa_len),
                                &hostname, socklen_t(NI_MAXHOST), nil, 0, NI_NUMERICHOST)
                    let ip = String(cString: hostname)
                    // Return first 3 octets as subnet prefix
                    let parts = ip.split(separator: ".")
                    if parts.count == 4 && !ip.hasPrefix("169.254") {
                        return parts.prefix(3).joined(separator: ".")
                    }
                }
            }
            ptr = current.pointee.ifa_next
        }
        return nil
    }

    private static func hostString(from host: NWEndpoint.Host) -> String {
        switch host {
        case .ipv4(let addr): return "\(addr)"
        case .ipv6(let addr): return "\(addr)"
        case .name(let hostname, _): return hostname
        @unknown default: return "\(host)"
        }
    }
}
