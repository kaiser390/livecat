# OliveCam Changelog

## v1.1.1 (2026-03-15)

### Improvements
- **OBS Live Monitor** — WiFi icon shows real-time OBS connection status (1s heartbeat)
- **OBS Pre-check** — Start button verifies OBS is running before streaming
- **Auto Discover fix** — OBS subnet scan was not working; now correctly finds OBS on local network
- **UI Restore Button** — Long-press hides controls; tap center button to restore
- **OBS WebSocket Guide** — Help section explains how to enable WebSocket Server in OBS
- **Network Guide** — Setup instructions for WiFi, Cellular, Hotspot, VPN environments
- **Quick Start Guide** — OBS Direct mode (no server software needed)

### Bug Fixes
- Fixed WiFi icon showing green without actual OBS connection (UX bug)
- Fixed accidental UI hide — long-press duration increased to 1 second
- Fixed OBS subnet scan (scanTask was overwritten by stop timer)
- Removed internal server references from Help guide

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
