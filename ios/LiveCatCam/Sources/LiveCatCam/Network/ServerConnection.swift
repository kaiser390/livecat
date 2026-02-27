import Foundation

/// Thread-safe WebSocket client for server communication.
actor ServerConnection {
    private var webSocketTask: URLSessionWebSocketTask?
    private let session: URLSession
    private var isRegistered = false
    private var reconnectAttempt = 0
    private let maxReconnectDelay: TimeInterval = 30
    private var config: CameraConfig

    enum ConnectionState: Sendable {
        case disconnected
        case connecting
        case connected
        case registered
    }

    private(set) var state: ConnectionState = .disconnected
    var onCommand: ((ServerCommand) -> Void)?
    var onStateChange: ((ConnectionState) -> Void)?

    init(config: CameraConfig) {
        self.config = config
        self.session = URLSession(configuration: .default)
    }

    // MARK: - Connection lifecycle

    func connect() async {
        guard state == .disconnected else { return }
        guard let url = config.webSocketURL else {
            Log.network.error("Invalid WebSocket URL")
            return
        }

        state = .connecting
        onStateChange?(.connecting)
        Log.network.info("Connecting to \(url.absoluteString)")

        let task = session.webSocketTask(with: url)
        task.maximumMessageSize = 65536
        self.webSocketTask = task
        task.resume()

        state = .connected
        onStateChange?(.connected)
        reconnectAttempt = 0

        await register()

        // Run receive loop in a separate task so connect() returns immediately
        Task { [weak self] in
            await self?.receiveLoop()
        }
    }

    func disconnect() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        state = .disconnected
        isRegistered = false
        onStateChange?(.disconnected)
        Log.network.info("Disconnected")
    }

    // MARK: - Registration

    private func register() async {
        let message = RegistrationMessage.register(camID: config.camID)
        guard let data = try? JSONEncoder().encode(message) else { return }
        guard let json = String(data: data, encoding: .utf8) else { return }

        do {
            try await webSocketTask?.send(.string(json))
            Log.network.info("Registration sent for \(self.config.camID)")
        } catch {
            Log.network.error("Registration send failed: \(error)")
            await handleDisconnect()
        }
    }

    // MARK: - Sending

    func send(_ message: MetadataMessage) async {
        guard state == .registered else { return }
        do {
            let data = try JSONEncoder().encode(message)
            guard let json = String(data: data, encoding: .utf8) else { return }
            try await webSocketTask?.send(.string(json))
        } catch {
            Log.network.error("Send failed: \(error)")
            await handleDisconnect()
        }
    }

    func sendRaw(_ string: String) async {
        do {
            try await webSocketTask?.send(.string(string))
        } catch {
            Log.network.error("Raw send failed: \(error)")
            await handleDisconnect()
        }
    }

    // MARK: - Receive loop

    private func receiveLoop() async {
        guard let task = webSocketTask else { return }

        while state == .connected || state == .registered {
            do {
                let message = try await task.receive()
                switch message {
                case .string(let text):
                    handleMessage(text)
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8) {
                        handleMessage(text)
                    }
                @unknown default:
                    break
                }
            } catch {
                Log.network.error("Receive error: \(error)")
                await handleDisconnect()
                return
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8) else { return }

        // Check registration response
        if let response = try? JSONDecoder().decode(RegistrationResponse.self, from: data),
           response.type == "registered" {
            isRegistered = true
            state = .registered
            onStateChange?(.registered)
            Log.network.info("Registered as \(self.config.camID)")
            return
        }

        // Parse server command
        if let command = ServerCommand.parse(from: data) {
            onCommand?(command)
        }
    }

    // MARK: - Reconnection

    private func handleDisconnect() async {
        disconnect()
        reconnectAttempt += 1

        let delay = min(pow(2.0, Double(reconnectAttempt)) * 0.5, maxReconnectDelay)
        Log.network.info("Reconnecting in \(delay)s (attempt \(self.reconnectAttempt))")

        try? await Task.sleep(for: .seconds(delay))

        guard state == .disconnected else { return }
        // Use a new Task to avoid recursive async call stack growth
        Task { [weak self] in
            await self?.connect()
        }
    }

    func updateConfig(_ newConfig: CameraConfig) {
        self.config = newConfig
    }

    func setCommandHandler(_ handler: @escaping (ServerCommand) -> Void) {
        self.onCommand = handler
    }
}
