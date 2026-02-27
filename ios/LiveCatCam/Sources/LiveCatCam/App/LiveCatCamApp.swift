import SwiftUI

@main
struct LiveCatCamApp: App {
    @State private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(appState)
                .onAppear {
                    // Prevent screen dimming for 24/7 operation
                    #if os(iOS)
                    UIApplication.shared.isIdleTimerDisabled = true
                    #endif
                    Task {
                        await appState.start()
                    }
                }
        }
    }
}
