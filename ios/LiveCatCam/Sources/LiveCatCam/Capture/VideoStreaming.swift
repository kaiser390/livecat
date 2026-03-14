import Foundation

/// Common interface for UDP and UDP+FEC streamers.
protocol VideoStreaming: AnyObject, Sendable {
    func start() throws
    func write(encodedData: Data, isKeyframe: Bool)
    func writeAudio(aacData: Data)
    func stop()
}
