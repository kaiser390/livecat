# OLiveCam - App Store 제출 가이드 (맥북 작업)

## 1. 프로젝트 이름 변경
- Display Name: `OLiveCam`
- Bundle Identifier: `com.kaiser390.OLiveCam`
- Xcode → Target → General → Display Name → `OLiveCam`

## 2. 앱 아이콘 등록
- `appstore/icon_1024.png` → Assets.xcassets → AppIcon
- 또는 Xcode 15+: 단일 1024x1024 아이콘만 등록하면 자동 리사이즈

## 3. 앱 설정
- Deployment Target: iOS 17.0
- Device: iPhone only
- Orientation: Landscape Right, Landscape Left
- Requires full screen: Yes
- Privacy descriptions (Info.plist):
  - NSCameraUsageDescription: "OLiveCam needs camera access to stream video to OBS"
  - NSMicrophoneUsageDescription: "OLiveCam needs microphone access to stream audio to OBS"
  - NSLocalNetworkUsageDescription: "OLiveCam needs local network access to send video to your computer"
  - NSBonjourServices: _olivecam._tcp

## 4. 유료 앱 설정 ($0.99)
- App Store Connect → 가격 → Tier 1 ($0.99)
- 구독/IAP 아님, 단순 유료 앱

## 5. Archive & Upload
```
Xcode → Product → Archive → Distribute App → App Store Connect
```

## 6. App Store Connect 설정
- 앱 이름: OLiveCam
- 부제: iPhone to OBS Wireless Camera (EN) / iPhone을 OBS 무선 카메라로 (KO)
- 카테고리: Photo & Video
- 가격: Tier 1 ($0.99)
- 프라이버시 URL: https://kaiser390.github.io/livecat/privacy.html
- 설명: appstore/app_description_en.md, app_description_ko.md 참조
- 키워드: obs,stream,camera,wireless,live,broadcast,webcam,udp,capture,wifi
- 스크린샷: 아이폰에서 앱 실행 상태 캡처 (6.7인치, 6.1인치)
- 연령 등급: 4+
- 저작권: 2026 kaiser390

## 7. 심사 노트 (App Review)
```
OLiveCam streams video from iPhone to OBS Studio over local Wi-Fi using standard UDP/MPEG-TS protocol.

To test:
1. Install OBS Studio on a computer on the same Wi-Fi network
2. Add Media Source → udp://@:9000
3. Enter the computer's IP in the app settings
4. Tap Start to begin streaming
5. Video appears in OBS

No server or account required. Local network only.
```

## 8. 제출 전 체크리스트
- [ ] Display Name → OLiveCam
- [ ] Bundle ID → com.kaiser390.OLiveCam
- [ ] 아이콘 등록
- [ ] Info.plist 권한 설명 (카메라/마이크/네트워크)
- [ ] WebSocket 연결 실패 시 크래시 없는지 확인
- [ ] Archive 성공
- [ ] App Store Connect 업로드
- [ ] 스크린샷 등록
- [ ] 설명/키워드 입력
- [ ] 프라이버시 URL 입력
- [ ] 가격 설정 ($0.99)
- [ ] 제출
