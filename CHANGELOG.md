# OliveCam Changelog

## v1.1.0 (2026-03-14)

### New Features
- **SRT Protocol** — Reliable streaming via libsrt (caller mode). Crystal-clear quality with ~200ms latency
- **Auto Discover** — Find OBS servers on your network automatically (Bonjour + subnet scan)
- **Protocol Selection** — Choose between UDP (fastest) and SRT (best quality) in Settings
- **Live Status Badge** — See current protocol (SRT/UDP) and server IP on screen during streaming
- **Settings Persistence** — All settings saved between app launches
- **Unsaved Changes Alert** — Warns before closing settings with unsaved changes
- **OBS Setup Guide** — Step-by-step instructions for both UDP and SRT modes (tap i button)
- **Network Guide** — How to stream over different networks (WiFi, Cellular, Hotspot, VPN)

### Improvements
- Server selection feedback — "Selected ✓" with green highlight on tap
- WiFi icon reflects actual server connection status (not just WiFi state)
- Keyboard types optimized per field (IP, port, camera ID)
- CRC32 lookup table — 8x faster MPEG-TS packet generation
- Frame processing guard — prevents Task pile-up at 30fps
- Video encoding moved to frame callback for smoother output

### Bug Fixes
- Fixed cold-start issue where streaming would not send video until IP was changed
- Fixed MPEG-TS adaptation field stuffing for 183-byte payloads
- Thread-safety fixes across all streamers (UDP, FEC, SRT) and AudioEncoder

## v1.0.1 (2026-03-13)

### Initial App Store Release
- Live video streaming from iPhone to OBS via MPEG-TS over UDP
- Real-time cat detection and tracking (Apple Vision)
- WebSocket metadata (10Hz) for server coordination
- Pinch-to-zoom with smooth interpolation
- Battery, FPS, thermal monitoring
- Landscape-only, screen-lock prevention

## v1.0.0 (2026-03-12)

### Internal Build
- Core streaming pipeline
- Camera capture + H.264 encoding
- MPEG-TS muxing + UDP transport
