# Code Review Notes

## 2026-03-15 — Audio Sample Rate Fix (commit f6c262e)

### 검토 결과: 전체 구조 OK, 버그 1건 발견

---

### ✅ 잘 된 부분

- `AudioEncoder` → `onSampleRateDetected` 콜백 → `AppState` → `streamer.setAudioSampleRate()` 전달 체인 깔끔함
- `VideoStreaming` 프로토콜에 `setAudioSampleRate()` 추가 → UDPStreamer / SRTStreamer / FECStreamer 모두 구현
- `UDPStreamer.setAudioSampleRate()` 에서 `queue.sync` 사용 — 데드락 없음, 정상
- `StatusOverlayView` 샘플레이트 표시 (`44k` / `48k`) — 디버그 확인용으로 유용

---

### ❌ 버그: UDP 모드에서 샘플레이트 전달 안 됨

**파일**: `ios/LiveCatCam/Sources/LiveCatCam/App/AppState.swift`

**현재 코드**:
```swift
encoder.onSampleRateDetected = { [weak self] rate in
    self?.srtStreamer?.setAudioSampleRate(rate)   // SRT만 전달
    Task { @MainActor in self?.audioSampleRate = rate }
    self?.addDebug("Audio: \(rate)Hz")
}
```

**문제**: `srtStreamer`에만 샘플레이트를 전달하고 `udpStreamer`에는 전달하지 않음.
UDP 모드로 스트리밍 시 `audioSampleRate`가 기본값 48000으로 유지되어 PTS 오차 발생 가능.

**수정 방법**: `VideoStreaming` 프로토콜 타입의 공통 streamer 참조를 사용하거나,
두 스트리머에 모두 전달:

```swift
encoder.onSampleRateDetected = { [weak self] rate in
    self?.srtStreamer?.setAudioSampleRate(rate)
    self?.udpStreamer?.setAudioSampleRate(rate)
    Task { @MainActor in self?.audioSampleRate = rate }
    self?.addDebug("Audio: \(rate)Hz")
}
```

또는 더 깔끔하게 `VideoStreaming` 프로토콜 참조 변수가 있다면:
```swift
self?.activeStreamer?.setAudioSampleRate(rate)
```

---

### 수정 우선순위

| 항목 | 심각도 | 파일 |
|------|--------|------|
| UDP 모드 샘플레이트 미전달 | HIGH | AppState.swift |
