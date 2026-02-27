import SwiftUI

/// LiveCatCam — Cat live streaming camera app.
/// Streams H.264 + MPEG-TS over UDP to PC, with WebSocket remote control.
@main
struct LiveCatCamApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
                .persistentSystemOverlays(.hidden)
        }
    }
}

// MARK: - AppDelegate

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // Prevent screen lock during streaming
        UIApplication.shared.isIdleTimerDisabled = true

        // Lock to landscape
        return true
    }

    func application(
        _ application: UIApplication,
        supportedInterfaceOrientationsFor window: UIWindow?
    ) -> UIInterfaceOrientationMask {
        .landscapeRight
    }
}
