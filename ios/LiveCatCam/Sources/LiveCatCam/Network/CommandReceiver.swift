import Foundation

/// Receives and dispatches server commands from the WebSocket connection.
final class CommandReceiver: Sendable {
    typealias CommandHandler = @Sendable (ServerCommand) -> Void

    private let handlers: CommandHandlers

    final class CommandHandlers: @unchecked Sendable {
        var onSetMode: CommandHandler?
        var onSetZoom: CommandHandler?
        var onGotoPosition: CommandHandler?
        var onCameraControl: CommandHandler?
    }

    init() {
        self.handlers = CommandHandlers()
    }

    func setModeHandler(_ handler: @escaping CommandHandler) {
        handlers.onSetMode = handler
    }

    func setZoomHandler(_ handler: @escaping CommandHandler) {
        handlers.onSetZoom = handler
    }

    func setPositionHandler(_ handler: @escaping CommandHandler) {
        handlers.onGotoPosition = handler
    }

    func setCameraControlHandler(_ handler: @escaping CommandHandler) {
        handlers.onCameraControl = handler
    }

    func dispatch(_ command: ServerCommand) {
        switch command {
        case .setMode:
            Log.network.info("Command: set_mode")
            handlers.onSetMode?(command)
        case .setZoom:
            Log.network.info("Command: set_zoom")
            handlers.onSetZoom?(command)
        case .gotoPosition:
            Log.network.info("Command: goto_position")
            handlers.onGotoPosition?(command)
        case .cameraZoom, .cameraFocus, .cameraExposure, .cameraReset:
            Log.network.info("Command: camera_control")
            handlers.onCameraControl?(command)
        case .unknown(let type):
            Log.network.warning("Unknown command type: \(type)")
        }
    }
}
