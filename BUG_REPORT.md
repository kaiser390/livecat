# Bug Report: Audio Helicopter Noise on SRT

**Date:** 2026-03-15
**Reported by:** Martin (via Maestro code review)
**Severity:** High
**Affects:** SRT protocol (UDP untested but likely OK)

## Symptom
- Audio has intermittent helicopter/buzzing noise during SRT streaming
- Noise appears mid-stream, not at start
- Video is clean — only audio affected

## Root Cause Analysis (Maestro)

### PTS Mismatch between Video and Audio

In the latest UDPStreamer refactor (commit `bb5fd57`), video PTS was changed from **wall-clock** to **frame-count** based:

```swift
// Video PTS (UDPStreamer.buildTSData) — frame-count based
let pts = frameCount * UInt64(90000 / max(config.fps, 1))

// Audio PTS (UDPStreamer.buildAudioTSData) — wall-clock based
let elapsed = CFAbsoluteTimeGetCurrent() - startTime
let pts = UInt64(elapsed * 90000)
```

Video and audio PTS are now on **different time bases**. This causes:
1. OBS decoder receives packets with mismatched timestamps
2. SRT's ARQ retransmission can reorder packets, amplifying the timing issue
3. Decoder produces noise when audio frames are placed at wrong positions

### Why SRT is worse than UDP
- SRT has a 200ms jitter buffer + ARQ retransmission
- Retransmitted packets arrive out of order → PTS mismatch amplified
- UDP sends in order, no retransmission → less visible

## Proposed Fix

**Option A:** Revert video PTS to wall-clock (match audio)
```swift
// Both use wall-clock
let elapsed = CFAbsoluteTimeGetCurrent() - startTime
let pts = UInt64(elapsed * 90000)
```

**Option B:** Change audio PTS to frame-count (match video)
```swift
// Audio: 1024 samples per AAC frame at 48kHz
let pts = audioFrameCount * UInt64(1024 * 90000 / 48000)
```

**Option C:** Both use wall-clock (safest, revert the change)

## Files to Review
- `UDPStreamer.swift` — `buildTSData()` line: PTS calculation
- `UDPStreamer.swift` — `buildAudioTSData()` line: PTS calculation
- `UDPStreamer.swift` — `write()` line: PTS calculation

## Verification
1. Fix PTS to use same time base
2. Test on SRT — verify no helicopter noise
3. Test on UDP — verify no regression
