import Foundation

/// WebSocket client connecting to PC's meta_server.py (port 8081).
/// Receives camera control commands (zoom) and sends metadata.
/// Auto-reconnects on disconnect.
final class WebSocketService {
    // MARK: - Callbacks

    var onZoomCommand: ((CGFloat) -> Void)?
    var onConnected: (() -> Void)?
    var onDisconnected: (() -> Void)?

    // MARK: - State

    private(set) var isConnected = false
    private var webSocketTask: URLSessionWebSocketTask?
    private var session: URLSession?
    private var serverURL: URL?
    private var autoReconnect = true
    private var reconnectTimer: Timer?
    private let reconnectInterval: TimeInterval = 3.0
    private var intentionalDisconnect = false

    // MARK: - Connect

    func connect(host: String, port: Int) {
        intentionalDisconnect = false
        guard let url = URL(string: "ws://\(host):\(port)") else { return }
        serverURL = url

        session = URLSession(configuration: .default)
        let task = session!.webSocketTask(with: url)
        webSocketTask = task
        task.resume()

        // Start listening
        receiveMessage()

        // Treat as connected (URLSessionWebSocketTask doesn't have a "connected" callback)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.isConnected = true
            self?.onConnected?()
        }
    }

    func disconnect() {
        intentionalDisconnect = true
        autoReconnect = false
        stopReconnectTimer()
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        onDisconnected?()
    }

    func setAutoReconnect(_ enabled: Bool) {
        autoReconnect = enabled
    }

    // MARK: - Send Metadata

    func sendMetadata(_ metadata: [String: Any]) {
        guard isConnected, let task = webSocketTask else { return }

        guard let data = try? JSONSerialization.data(withJSONObject: metadata),
              let text = String(data: data, encoding: .utf8) else { return }

        task.send(.string(text)) { error in
            if error != nil {
                // Will trigger reconnect
            }
        }
    }

    /// Send current status (battery, zoom, etc.) periodically
    func sendStatus(battery: Int, zoom: CGFloat, isStreaming: Bool, temperature: String?) {
        var meta: [String: Any] = [
            "type": "status",
            "battery": battery,
            "zoom": zoom,
            "streaming": isStreaming,
            "timestamp": Date().timeIntervalSince1970
        ]
        if let temp = temperature {
            meta["temperature"] = temp
        }
        sendMetadata(meta)
    }

    // MARK: - Receive Messages

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            switch result {
            case .success(let message):
                self?.handleMessage(message)
                self?.receiveMessage() // Continue listening
            case .failure:
                self?.handleDisconnect()
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .string(let text):
            parseCommand(text)
        case .data(let data):
            if let text = String(data: data, encoding: .utf8) {
                parseCommand(text)
            }
        @unknown default:
            break
        }
    }

    private func parseCommand(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

        guard let cmd = json["cmd"] as? String else { return }

        switch cmd {
        case "zoom":
            if let factor = json["factor"] as? Double {
                DispatchQueue.main.async { [weak self] in
                    self?.onZoomCommand?(CGFloat(factor))
                }
            }
        default:
            break
        }
    }

    // MARK: - Reconnect

    private func handleDisconnect() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let wasConnected = self.isConnected
            self.isConnected = false
            self.webSocketTask = nil

            if wasConnected {
                self.onDisconnected?()
            }

            if self.autoReconnect && !self.intentionalDisconnect {
                self.scheduleReconnect()
            }
        }
    }

    private func scheduleReconnect() {
        stopReconnectTimer()
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: reconnectInterval, repeats: false) { [weak self] _ in
            guard let self, let url = self.serverURL else { return }
            let host = url.host ?? ""
            let port = url.port ?? 8081
            self.connect(host: host, port: port)
        }
    }

    private func stopReconnectTimer() {
        reconnectTimer?.invalidate()
        reconnectTimer = nil
    }
}
