# LiveCat - 실시간 고양이 자동 추적 & 라이브 스트리밍 시스템

## 1. 시스템 개요

### 1.1 프로젝트 목표
마당에 사는 고양이 2마리를 iPhone 4대로 자동 추적하며, 24/7 실시간 라이브 스트리밍하는 무인 방송 시스템.

### 1.2 핵심 요구사항
| 항목 | 요구사항 |
|------|---------|
| 카메라 | iPhone 4대, DockKit 모터 스탠드로 자동 팬/틸트 |
| 추적 | Apple Animal Body Pose API로 고양이 실시간 추적 |
| 스위칭 | AI 기반 멀티캠 자동 전환 (가장 활동적인 장면 선택) |
| 블러 | 사냥 장면(쥐/새) 실시간 감지 및 블러 처리 |
| 스트리밍 | YouTube/Twitch 24/7 RTMP 라이브 |
| 환경 | 야외 마당, 전천후 운영 |

### 1.3 시스템 컨셉도

```
┌─────────────────────────────────────────────────────────────────┐
│                        야외 마당                                  │
│                                                                   │
│  📱 iPhone #1          📱 iPhone #2        📱 iPhone #3          │
│  [소나무/캣타워]        [마당 전경]          [둥지/쉼터]           │
│  DockKit Stand         DockKit Stand       DockKit Stand         │
│       │                     │                    │                │
│       └─────────┬───────────┴────────────┬───────┘                │
│                 │    Wi-Fi (로컬 네트워크)   │                     │
│                 ▼                          ▼                      │
│           📱 iPhone #4                                            │
│           [로밍/클로즈업]                                          │
│           DockKit Stand                                           │
│                 │                                                  │
└─────────────────┼──────────────────────────────────────────────────┘
                  │ Wi-Fi
                  ▼
    ┌──────────────────────────────┐
    │     🖥️ Mac Mini (서버)       │
    │                              │
    │  ┌────────────────────┐      │
    │  │ LiveCat Director   │      │
    │  │ (카메라 오케스트라) │      │
    │  │                    │      │
    │  │ • 영상 수신 (4ch)  │      │
    │  │ • AI 카메라 스위칭 │      │
    │  │ • 블러 프로세싱    │      │
    │  │ • OBS 연동         │      │
    │  └────────┬───────────┘      │
    │           │                  │
    │  ┌────────▼───────────┐      │
    │  │ OBS Studio         │      │
    │  │ • 장면 전환        │      │
    │  │ • 오버레이/자막    │      │
    │  │ • RTMP 송출        │      │
    │  └────────┬───────────┘      │
    │           │                  │
    └───────────┼──────────────────┘
                │ RTMP
                ▼
    ┌──────────────────────┐
    │  YouTube Live        │
    │  Twitch              │
    │  (24/7 스트리밍)     │
    └──────────────────────┘
```

---

## 2. 하드웨어 아키텍처

### 2.1 카메라 유닛 (x4)

각 카메라 유닛 구성:

| 컴포넌트 | 제품 | 용도 |
|----------|------|------|
| 카메라 | iPhone (SE 3세대 이상) | 영상 촬영 + AI 추적 |
| 모터 스탠드 | Belkin Auto-Tracking Stand Pro | DockKit 360° 팬 + 90° 틸트 |
| 방수 하우징 | IP67 방수 케이스 + 투명 렌즈창 | 야외 전천후 보호 |
| 전원 | 방수 Lightning/USB-C 케이블 + 야외 전원 | 24/7 상시 전원 |
| 거치 | 스테인리스 마운트 브라켓 | 벽/기둥/나무 고정 |

### 2.2 카메라 배치도

```
               [소나무/캣타워]
                    🌲
                   /|\
                  / | \
                 /  |  \
            📱#1   |
           (위쪽)  |
                   |
    ───────────────┼───────────────
    |              |              |
    |   [마당]     |    [화단]    |
    |         📱#4 |              |
    |      (로밍)  |              |
    |              |              |
    ───────────────┼───────────────
    |              |              |
    |  📱#2        |        📱#3 |
    | (전경)       |    (둥지)   |
    |              |              |
    ────────────[집 벽면]──────────
```

**카메라별 역할:**

| ID | 위치 | 화각 | 주요 역할 |
|----|------|------|----------|
| CAM-1 | 소나무 근처 (높이 2m) | 좁은 화각 (2x줌) | 나무 위 고양이 클로즈업, 점프/클라이밍 |
| CAM-2 | 집 벽면 좌측 (높이 2.5m) | 넓은 화각 (0.5x) | 마당 전경, 전체 동선 파악 |
| CAM-3 | 집 벽면 우측 (높이 1.5m) | 중간 화각 (1x) | 둥지/쉼터 영역, 수면/휴식 |
| CAM-4 | 마당 중앙 기둥 (높이 1.8m) | 좁은 화각 (2x줌) | 로밍 추적, 클로즈업 표정 |

### 2.3 메인 서버

| 컴포넌트 | 권장 사양 | 용도 |
|----------|----------|------|
| Mac Mini M2/M4 | 16GB RAM, 512GB SSD | 영상 처리 + 스트리밍 서버 |
| Wi-Fi Router | Wi-Fi 6E, 메시 지원 | iPhone↔서버 저지연 통신 |
| UPS | 1000VA 이상 | 정전 대비 무정전 전원 |

### 2.4 네트워크 토폴로지

```
인터넷 ← [공유기] ← Wi-Fi 6E ── Mac Mini (서버)
                         │
                    ┌────┼────┬────┐
                    │    │    │    │
                  📱#1 📱#2 📱#3 📱#4

        ※ 전용 VLAN 또는 5GHz 대역 분리 권장
        ※ 각 iPhone → 서버: ~8Mbps (1080p30)
        ※ 서버 → YouTube: ~6Mbps (1080p30 RTMP)
        ※ 총 다운로드: ~32Mbps, 업로드: ~6Mbps
```

---

## 3. 소프트웨어 아키텍처

### 3.1 전체 소프트웨어 스택

```
┌─────────────────────────────────────────────────────────┐
│                    iPhone App (Swift)                     │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐  │
│  │ Vision   │ │ DockKit  │ │ AVFounda- │ │ Network   │  │
│  │ Tracker  │ │ Motor    │ │ tion      │ │ Streamer  │  │
│  │          │ │ Control  │ │ Capture   │ │ (NDI/RTSP)│  │
│  └────┬─────┘ └────┬─────┘ └─────┬─────┘ └─────┬─────┘  │
│       │             │             │              │        │
│  ┌────▼─────────────▼─────────────▼──────────────▼────┐  │
│  │              CatTracker Engine                      │  │
│  │  • 고양이 감지 + 포즈 추정                          │  │
│  │  • 모터 제어 (팬/틸트 좌표 계산)                    │  │
│  │  • 영상 캡처 + 네트워크 전송                        │  │
│  │  • 메타데이터 전송 (추적 상태, 활동 점수)           │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                Mac Server (Python/Swift)                  │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐  │
│  │ Video    │ │ AI       │ │ Blur      │ │ OBS       │  │
│  │ Receiver │ │ Director │ │ Processor │ │ WebSocket │  │
│  │ (4ch)    │ │ (Switch) │ │ (Hunt Det)│ │ Control   │  │
│  └────┬─────┘ └────┬─────┘ └─────┬─────┘ └─────┬─────┘  │
│       │             │             │              │        │
│  ┌────▼─────────────▼─────────────▼──────────────▼────┐  │
│  │              LiveCat Director                       │  │
│  │  • 4채널 영상 동시 수신                             │  │
│  │  • 활동 점수 기반 카메라 자동 선택                  │  │
│  │  • 사냥 감지 → 블러 파이프라인                     │  │
│  │  • OBS Studio 원격 제어 (장면 전환)                │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 iPhone App — `LiveCatCam`

#### 3.2.1 앱 구조 (Swift + SwiftUI)

```
LiveCatCam/
├── App/
│   ├── LiveCatCamApp.swift          # 앱 엔트리포인트
│   └── ContentView.swift            # 메인 UI (상태 표시)
├── Tracking/
│   ├── CatDetector.swift            # Vision AnimalBodyPoseRequest
│   ├── CatTracker.swift             # 추적 로직 (칼만 필터)
│   ├── MotorController.swift        # DockKit 팬/틸트 제어
│   └── ActivityScorer.swift         # 고양이 활동 점수 계산
├── Capture/
│   ├── CameraManager.swift          # AVCaptureSession 관리
│   ├── VideoEncoder.swift           # H.264 하드웨어 인코딩
│   └── StreamSender.swift           # RTSP/NDI 네트워크 전송
├── Network/
│   ├── ServerConnection.swift       # 서버와 WebSocket 통신
│   ├── MetadataReporter.swift       # 추적 메타데이터 전송
│   └── CommandReceiver.swift        # 서버 명령 수신 (줌/모드)
├── Models/
│   ├── CatPose.swift                # 고양이 포즈 데이터 모델
│   ├── TrackingState.swift          # 추적 상태 (탐지/추적/분실)
│   └── ActivityEvent.swift          # 활동 이벤트 (점프/달리기 등)
└── Utils/
    ├── KalmanFilter.swift           # 부드러운 추적을 위한 필터
    └── CoordinateMapper.swift       # 화면좌표 → 모터각도 변환
```

#### 3.2.2 고양이 추적 파이프라인

```
AVCaptureSession (30fps, 1080p)
        │
        ▼
VNDetectAnimalBodyPoseRequest
        │
        ├─ 감지 성공 → CatPose (관절 17개)
        │                  │
        │                  ▼
        │          ActivityScorer
        │          • 속도 = Δ(중심점) / Δt
        │          • 포즈 변화율 (점프/달리기 감지)
        │          • 활동 점수 = f(속도, 포즈변화, 크기)
        │                  │
        │                  ▼
        │          MotorController (DockKit)
        │          • 목표: 고양이 중심을 프레임 1/3 지점에
        │          • 칼만 필터로 부드러운 추적
        │          • 예측 모드: 빠른 이동 시 선행 추적
        │                  │
        │                  ▼
        │          StreamSender → [서버로 영상 전송]
        │          MetadataReporter → [활동 점수 전송]
        │
        └─ 감지 실패 → 탐색 모드
                       • 마지막 위치 기반 느린 팬
                       • 10초 후 전체 스캔 (360° 회전)
                       • 30초 후 기본 포지션 복귀
```

#### 3.2.3 DockKit 모터 제어 상세

```swift
// 핵심 제어 로직 개념
enum TrackingMode {
    case idle           // 대기: 기본 포지션
    case searching      // 탐색: 천천히 회전하며 고양이 찾기
    case tracking       // 추적: 고양이 따라가기
    case fastTracking   // 고속추적: 달리기/점프 시
    case predictive     // 예측: 이동 방향으로 선행
}

// 모터 속도 프로파일
trackingSpeed:    20°/sec  (일반 추적)
fastSpeed:        60°/sec  (고속 추적)
searchSpeed:       5°/sec  (탐색 회전)
smoothingFactor:   0.85    (칼만 필터 계수)
```

### 3.3 Mac 서버 — `LiveCat Director`

#### 3.3.1 서버 구조

```
livecat/
├── server/
│   ├── main.py                      # 서버 엔트리포인트
│   ├── config.yaml                  # 설정 (카메라/스트리밍/블러)
│   │
│   ├── receiver/
│   │   ├── video_receiver.py        # 4채널 영상 수신 (RTSP/NDI)
│   │   ├── metadata_receiver.py     # iPhone 메타데이터 수신
│   │   └── stream_buffer.py         # 프레임 버퍼 관리
│   │
│   ├── director/
│   │   ├── camera_selector.py       # AI 카메라 선택 로직
│   │   ├── transition_engine.py     # 전환 효과 (크로스페이드 등)
│   │   ├── scene_analyzer.py        # 장면 분석 (활동 점수 집계)
│   │   └── rules_engine.py          # 전환 규칙 (최소 유지 시간 등)
│   │
│   ├── blur/
│   │   ├── hunt_detector.py         # 사냥 장면 감지 (CoreML/YOLO)
│   │   ├── prey_segmenter.py        # 먹잇감 영역 세그멘테이션
│   │   └── blur_processor.py        # 실시간 가우시안 블러 적용
│   │
│   ├── obs/
│   │   ├── obs_controller.py        # OBS WebSocket 제어
│   │   ├── scene_manager.py         # OBS 장면/소스 관리
│   │   └── overlay_manager.py       # 오버레이 (고양이 이름, 시계)
│   │
│   ├── web/
│   │   ├── dashboard.py             # 웹 대시보드 (Flask/FastAPI)
│   │   ├── api.py                   # REST API (상태 조회/수동 제어)
│   │   └── templates/
│   │       └── dashboard.html       # 4분할 모니터링 + 컨트롤
│   │
│   └── utils/
│       ├── logger.py                # 로깅 (활동 로그, 에러)
│       └── health_check.py          # iPhone/OBS 상태 체크
│
├── models/
│   └── hunt_detector.mlmodel        # 사냥 감지 CoreML 모델
│
├── overlays/
│   ├── cat_name_bar.png             # 고양이 이름 오버레이
│   ├── clock_widget.html            # 실시간 시계
│   └── viewer_count.html            # 시청자 수
│
├── tests/
│   ├── test_camera_selector.py
│   ├── test_hunt_detector.py
│   └── test_blur_processor.py
│
├── requirements.txt
├── Dockerfile
└── ARCHITECTURE.md                  # 이 문서
```

#### 3.3.2 AI 카메라 스위칭 로직

```
┌─────────────────────────────────────────────┐
│          Camera Selector Engine              │
│                                             │
│  입력 (매 프레임):                           │
│  ├─ CAM-1: activity_score, tracking_state   │
│  ├─ CAM-2: activity_score, tracking_state   │
│  ├─ CAM-3: activity_score, tracking_state   │
│  └─ CAM-4: activity_score, tracking_state   │
│                                             │
│  스위칭 규칙:                                │
│  1. 최소 유지 시간: 5초 (잦은 전환 방지)     │
│  2. 전환 조건:                               │
│     • 다른 카메라 점수 > 현재 × 1.5          │
│     • 현재 카메라 추적 실패 > 3초            │
│     • 특수 이벤트 (점프, 달리기) 즉시 전환   │
│  3. 우선순위:                                │
│     • 이벤트 발생 카메라 > 클로즈업 > 전경   │
│  4. 2마리 동시 활동:                         │
│     • PIP(Picture-in-Picture) 모드 전환      │
│                                             │
│  출력: active_camera_id, transition_type     │
└─────────────────────────────────────────────┘
```

**활동 점수 계산:**

```python
def calculate_activity_score(metadata):
    """
    각 iPhone에서 전송하는 메타데이터 기반 활동 점수

    score 구성:
    - movement_speed: 0~30점 (이동 속도)
    - pose_change:    0~30점 (포즈 변화량, 점프/스트레칭)
    - proximity:      0~20점 (카메라와의 거리, 가까울수록 높음)
    - event_bonus:    0~50점 (특수 이벤트: 나무오르기+50, 달리기+30)
    - novelty:        0~20점 (최근 5분 내 미노출 장면 보너스)

    Returns: 0 ~ 150
    """
```

**전환 모드:**

| 모드 | 조건 | 전환 효과 |
|------|------|----------|
| 일반 | 점수 차이 1.5x | 크로스페이드 (0.5초) |
| 긴급 | 특수 이벤트 감지 | 즉시 컷 |
| PIP | 2마리 동시 활동 | 메인+서브 분할 |
| 슬로우 | 고양이 수면 중 | 30초 간격 느린 전환 |
| 파노라마 | 활동 없음 (5분+) | 전경 카메라 고정 |

#### 3.3.3 사냥 블러 파이프라인

```
영상 프레임 (30fps)
      │
      ▼
  ┌──────────────────┐
  │ YOLO 물체 감지   │  ← hunt_detector.mlmodel
  │ • 쥐 (mouse)     │
  │ • 새 (bird)      │
  │ • 도마뱀 (lizard)│
  └────────┬─────────┘
           │
    감지 결과 분류
    ├─ 미감지 → 패스스루 (블러 없음)
    │
    ├─ 먹잇감 감지 → 블러 레벨 결정
    │   │
    │   ▼
    │  ┌──────────────────────────┐
    │  │ 블러 레벨 판정            │
    │  │                          │
    │  │ Level 0: 먹잇감만 보임   │ → 먹잇감 영역 가우시안 블러
    │  │ Level 1: 고양이가 물고 감│ → 고양이 입 주변 블러
    │  │ Level 2: 뜯는 장면       │ → 화면 전체 강한 블러
    │  │          + 컷 전환       │   + 다른 카메라로 전환
    │  └──────────────────────────┘
    │
    └─ 확신도 낮음 (0.3~0.7) → 가벼운 블러 + 경고 로그
```

**블러 처리 기술:**

```python
# 블러 영역 확장 (안전 마진)
bbox_expanded = expand_bbox(prey_bbox, margin=1.5)

# 가우시안 블러 (강도별)
BLUR_KERNELS = {
    0: (31, 31),    # 먹잇감만 → 가벼운 블러
    1: (61, 61),    # 입 주변 → 중간 블러
    2: (101, 101),  # 전체 장면 → 강한 블러 + 장면 전환
}

# 엣지 페더링 (자연스러운 블러 경계)
feather_radius = 20  # 블러 경계 부드럽게
```

### 3.4 OBS Studio 연동

#### 3.4.1 OBS 장면 구성

```
OBS Studio Scenes:
│
├── [Scene] MainView
│   ├── Source: ActiveCamera (동적 전환)
│   ├── Source: CatNameOverlay (하단 바)
│   ├── Source: ClockWidget (우측 상단)
│   └── Source: ViewerCount (좌측 상단)
│
├── [Scene] PIP_Mode
│   ├── Source: MainCamera (전체 화면)
│   ├── Source: SubCamera (우측 하단 PIP, 25%)
│   ├── Source: CatNameOverlay
│   └── Source: ClockWidget
│
├── [Scene] Sleeping
│   ├── Source: SleepCamera (고양이 수면 장면)
│   ├── Source: SleepOverlay ("😴 낮잠 중...")
│   ├── Source: LofiMusic (배경 음악)
│   └── Source: ClockWidget
│
├── [Scene] Panorama
│   ├── Source: WideCamera (전경)
│   ├── Source: TimelapseFilter (2배속)
│   └── Source: AmbientSound
│
└── [Scene] Offline
    ├── Source: OfflineImage ("곧 돌아옵니다")
    └── Source: ScheduleInfo
```

#### 3.4.2 OBS WebSocket 제어

```python
# OBS WebSocket 5.x 프로토콜
obs_ws_url = "ws://localhost:4455"

# 주요 명령:
# - SetCurrentProgramScene: 장면 전환
# - SetSourceFilterEnabled: 블러 필터 ON/OFF
# - SetInputSettings: 카메라 소스 URL 변경
# - GetStreamStatus: 스트리밍 상태 확인
# - StartStream / StopStream: 방송 시작/중지
```

---

## 4. 통신 프로토콜

### 4.1 iPhone → 서버: 영상 전송

**옵션 비교:**

| 프로토콜 | 지연 | 품질 | 구현 난이도 | 채택 |
|----------|------|------|-----------|------|
| NDI (HX) | ~100ms | 우수 | 중 | **1순위** |
| RTSP | ~200ms | 우수 | 중 | 2순위 |
| AirPlay | ~500ms | 양호 | 하 | 백업 |
| 직접 소켓 | ~50ms | 가변 | 상 | 고급 옵션 |

**채택: NDI HX** (Network Device Interface)
- iOS NDI SDK 지원
- Mac에서 OBS NDI 플러그인으로 직접 수신 가능
- 하드웨어 H.264 인코딩 → 저지연 + 저CPU

### 4.2 iPhone ↔ 서버: 제어/메타데이터

**WebSocket 프로토콜:**

```json
// iPhone → 서버: 메타데이터 (10Hz)
{
    "type": "metadata",
    "camera_id": "CAM-1",
    "timestamp": 1708900000.123,
    "tracking": {
        "state": "tracking",          // idle/searching/tracking/lost
        "cat_count": 1,
        "cat_positions": [
            {
                "id": "cat_mimi",
                "center": [0.45, 0.62],    // 정규화 좌표
                "bbox": [0.2, 0.4, 0.7, 0.85],
                "pose": "sitting",          // sitting/walking/running/jumping/climbing/sleeping
                "confidence": 0.94
            }
        ],
        "activity_score": 72,
        "motor_position": {"pan": 45.2, "tilt": -12.0}
    }
}

// 서버 → iPhone: 제어 명령
{
    "type": "command",
    "camera_id": "CAM-1",
    "action": "set_mode",              // set_mode/set_zoom/goto_position
    "params": {
        "mode": "tracking",
        "zoom_level": 2.0,
        "target_cat": "cat_mimi"
    }
}
```

### 4.3 서버 → OBS: 제어

OBS WebSocket 5.x 프로토콜 사용 (기존 표준).

---

## 5. AI/ML 모델 스택

### 5.1 온디바이스 (iPhone)

| 모델 | 프레임워크 | 용도 | 성능 |
|------|-----------|------|------|
| AnimalBodyPose | Apple Vision | 고양이 관절 17점 추적 | 30fps, ~5ms |
| AnimalDetector | Apple Vision | 고양이/개 감지 (바운딩 박스) | 30fps, ~3ms |
| PersonSegmentation | Apple Vision | 사람 영역 제외 (프라이버시) | 30fps, ~8ms |

### 5.2 서버사이드 (Mac)

| 모델 | 프레임워크 | 용도 | 성능 |
|------|-----------|------|------|
| YOLOv8-nano | CoreML/PyTorch | 먹잇감(쥐/새) 감지 | 30fps, ~15ms |
| Cat-ID | Custom CNN | 고양이 개체 식별 (2마리 구분) | 10fps, ~30ms |
| Scene Classifier | MobileNetV3 | 장면 분류 (활동/수면/부재) | 5fps, ~20ms |

### 5.3 모델 학습 데이터

```
학습 데이터 확보 전략:
1. 초기: 사전 학습 모델 (COCO, ImageNet)
2. 2주차~: 실제 촬영 영상으로 파인튜닝
   - 사냥 장면 수동 라벨링 (쥐/새 바운딩 박스)
   - 고양이 개체 라벨링 (고양이A vs 고양이B)
3. 지속: Active Learning 파이프라인
   - 확신도 낮은 프레임 자동 수집
   - 주 1회 라벨링 → 재학습
```

---

## 6. 핵심 기능 상세

### 6.1 고양이 개체 식별 (Cat-ID)

2마리 고양이를 구분하여 이름표 오버레이 표시.

```
방법: 외형 기반 분류 (간단 CNN)
├─ 학습 데이터: 각 고양이 200~500장
├─ 특징: 무늬 패턴, 체형, 얼굴 형태
├─ 출력: cat_mimi (0.95) / cat_nabi (0.87) / unknown
└─ 업데이트: 주 1회 신규 이미지로 재학습
```

### 6.2 수면 감지 & 로파이 모드

고양이가 장시간 수면 시 자동 "힐링 모드" 전환.

```
조건: 모든 카메라 activity_score < 10 (5분 지속)
동작:
├─ 수면 중인 고양이 카메라 고정
├─ 오버레이: "😴 낮잠 중..."
├─ BGM: 로파이 힙합 자동 재생
├─ 화면 전환: 30초 간격 느린 크로스페이드
└─ 해제: activity_score > 30 → 즉시 일반 모드
```

### 6.3 하이라이트 자동 클립

시청자 참여 & 숏폼 콘텐츠 자동 생성.

```
트리거 조건:
├─ 나무 등반 시작 (climbing 포즈 감지)
├─ 고속 달리기 (speed > threshold)
├─ 점프 (jumping 포즈)
├─ 두 고양이 상호작용 (2마리 근접 + 활동)
└─ 사냥 시도 (사냥 감지 + 빠른 이동)

클립 저장:
├─ 트리거 5초 전 ~ 15초 후 (20초 클립)
├─ 4개 카메라 모두 저장 (편집용)
├─ 메타데이터: 이벤트 종류, 점수, 카메라
└─ 자동 Shorts/Reels 업로드 파이프라인 (선택)
```

### 6.4 야간 모드

```
조건: 일몰 후 자동 전환 (위치 기반 일몰 시간)
동작:
├─ iPhone 카메라 야간 모드 활성화
├─ IR 보조등 점등 (별도 설치 시)
├─ 오버레이: "🌙 야간 모드"
├─ 감도 조정: 움직임 감지 임계값 하향
└─ 고양이 미감지 1시간 → 대기 모드 (전력 절약)
```

---

## 7. 야외 설치 & 운영

### 7.1 방수/방진 대책

```
┌─ iPhone 하우징 ─────────────────────┐
│  ┌─────────────────────────────┐    │
│  │   IP67 방수 케이스           │    │
│  │   + 광학 유리 렌즈창         │    │  ← 김서림 방지 코팅
│  │   + 방수 충전 포트           │    │  ← USB-C 방수 케이블
│  │   + 환기 홀 (고어텍스 멤브레인)│   │  ← 결로 방지
│  └─────────────────────────────┘    │
│  DockKit Stand                      │
│  + 스테인리스 브라켓 (나무/벽 고정)  │  ← 방수 아닌 제품은 캐노피 설치
│  + 방수 전원 케이블 (매립 배선)      │
└─────────────────────────────────────┘
```

### 7.2 전원 구성

```
분전반 → 야외 방수 콘센트 (IP65)
           │
      ┌────┼────┬────┐
      │    │    │    │
     📱#1 📱#2 📱#3 📱#4

각 유닛: 5V 3A USB 충전기 (방수 박스 내)
※ 아이폰은 충전하며 상시 구동 가능 (배터리 80% 충전 제한 설정)
※ 겨울철: 히팅 패드 (아이폰 동작온도 0~35°C)
※ 여름철: 차양막 (직사광선 방지, 과열 보호)
```

### 7.3 유지보수 체크리스트

| 주기 | 항목 |
|------|------|
| 매일 | 대시보드 확인 (4캠 모두 온라인) |
| 주 1회 | 렌즈 세척, 방수 씰 점검 |
| 월 1회 | 케이블 상태, 마운트 조임, 모터 동작 점검 |
| 분기 | 방수 케이스 교체, 전원 케이블 점검 |

---

## 8. 웹 대시보드

### 8.1 모니터링 화면

```
┌────────────────────────────────────────────────┐
│  LiveCat Dashboard                    [설정] ⚙️ │
├────────────────────┬───────────────────────────┤
│                    │                           │
│   CAM-1 (소나무)   │   CAM-2 (전경)            │
│   🟢 추적 중       │   🟡 탐색 중              │
│   Score: 72        │   Score: 15               │
│   [실시간 영상]     │   [실시간 영상]            │
│                    │                           │
├────────────────────┼───────────────────────────┤
│                    │                           │
│   CAM-3 (둥지)     │   CAM-4 (로밍)            │
│   🔴 오프라인      │   🟢 추적 중              │
│   Score: 0         │   Score: 89 ★ ACTIVE      │
│   [오프라인]        │   [실시간 영상]            │
│                    │                           │
├────────────────────┴───────────────────────────┤
│  현재 방송: CAM-4  │ 시청자: 142  │ 업타임: 12h │
│  블러 상태: OFF    │ 이벤트: 23건 │ 클립: 8개   │
├────────────────────────────────────────────────┤
│  최근 이벤트:                                   │
│  14:32 🐱 미미 - 나무 등반 (CAM-1, Score: 145) │
│  14:28 🐱 나비 - 달리기 (CAM-4, Score: 89)     │
│  14:15 ⚠️  사냥 감지 → 블러 적용 (CAM-2)       │
│  14:02 💤 수면 모드 해제                         │
└────────────────────────────────────────────────┘
```

### 8.2 수동 제어

```
대시보드에서 수동 제어 가능:
├─ 카메라 강제 전환 (클릭으로 메인 카메라 선택)
├─ 줌 제어 (슬라이더)
├─ 추적 모드 전환 (자동/수동/고정)
├─ 블러 강제 ON/OFF
├─ 장면 모드 전환 (일반/PIP/수면/파노라마)
├─ 스트리밍 시작/중지
└─ 하이라이트 수동 클립 저장
```

---

## 9. 기술 스택 요약

| 레이어 | 기술 | 비고 |
|--------|------|------|
| iPhone App | Swift, SwiftUI | iOS 17+ |
| 고양이 추적 | Apple Vision Framework | AnimalBodyPose |
| 모터 제어 | Apple DockKit | Belkin 스탠드 |
| 영상 전송 | NDI HX (1순위) / RTSP | 로컬 Wi-Fi |
| 서버 앱 | Python 3.11+ | FastAPI + asyncio |
| AI 모델 | CoreML (Mac) / YOLOv8 | 사냥 감지, Cat-ID |
| 영상 처리 | OpenCV + ffmpeg | 블러, 리사이즈 |
| 방송 소프트웨어 | OBS Studio | WebSocket 5.x |
| 스트리밍 | RTMP → YouTube/Twitch | 1080p30, 6Mbps |
| 대시보드 | FastAPI + HTML/JS | 실시간 모니터링 |
| 통신 | WebSocket | 제어 + 메타데이터 |

---

## 10. 개발 로드맵

### Phase 0: 프로토타입 (2주)
- [ ] iPhone 1대 + DockKit 스탠드로 고양이 추적 검증
- [ ] AnimalBodyPose API 정확도/성능 테스트
- [ ] NDI 영상 전송 Mac 수신 확인
- [ ] OBS에서 NDI 소스 표시 확인

### Phase 1: 단일 카메라 스트리밍 (2주)
- [ ] LiveCatCam iOS 앱 MVP (추적 + NDI 전송)
- [ ] 서버 영상 수신 + OBS 제어 기본
- [ ] YouTube RTMP 라이브 스트리밍 테스트
- [ ] 기본 오버레이 (고양이 이름, 시계)

### Phase 2: 멀티카메라 (3주)
- [ ] 4대 동시 수신 안정화
- [ ] AI 카메라 스위칭 로직
- [ ] PIP 모드
- [ ] 웹 대시보드 MVP

### Phase 3: 블러 & 고급 기능 (2주)
- [ ] 사냥 감지 모델 학습/배포
- [ ] 실시간 블러 파이프라인
- [ ] 수면 모드 / 야간 모드
- [ ] 하이라이트 자동 클립

### Phase 4: 안정화 & 야외 배포 (2주)
- [ ] 방수 하우징 설치
- [ ] 24/7 내구성 테스트
- [ ] 자동 복구 (앱 크래시, 네트워크 끊김)
- [ ] 모니터링 알림 (Slack/Telegram)

### Phase 5: 콘텐츠 확장 (지속)
- [ ] 자동 하이라이트 → YouTube Shorts 업로드
- [ ] 시청자 인터랙션 (채팅 명령 → 카메라 전환)
- [ ] Cat-ID 개체 인식 고도화
- [ ] 계절별 자동 설정 프로파일

---

## 11. 예상 비용

| 항목 | 수량 | 단가 | 소계 |
|------|------|------|------|
| iPhone SE 3 (중고) | 4대 | ~20만원 | 80만원 |
| Belkin Auto-Tracking Stand | 4개 | ~25만원 | 100만원 |
| 방수 케이스 | 4개 | ~5만원 | 20만원 |
| Mac Mini M2 (중고) | 1대 | ~80만원 | 80만원 |
| Wi-Fi 6E 라우터 | 1개 | ~15만원 | 15만원 |
| 야외 전원/배선 공사 | 1식 | ~30만원 | 30만원 |
| 방수 브라켓/마운트 | 4세트 | ~3만원 | 12만원 |
| UPS | 1개 | ~10만원 | 10만원 |
| **합계** | | | **~347만원** |

※ 이미 보유 중인 iPhone/Mac이 있으면 대폭 절감 가능
※ 월 운영비: 전기료 ~2만원, 인터넷 기존 사용

---

## 12. 리스크 & 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 비/눈 침투 | 장비 고장 | IP67 케이스 + 캐노피 + 고어텍스 환기 |
| 고양이 추적 실패 | 빈 화면 | 탐색 모드 + 전경 카메라 폴백 |
| 네트워크 끊김 | 스트리밍 중단 | 자동 재연결 + 로컬 버퍼 + UPS |
| 아이폰 과열 | 앱 종료 | 차양막 + 열감지 경보 + 앱 자동 재시작 |
| 사냥 블러 실패 | 잔인한 장면 노출 | 보수적 블러 (확신도 0.3부터) + 수동 컷 |
| DockKit 모터 고장 | 추적 불가 | 고정 화각 모드로 전환 + 예비 스탠드 |
| 아이폰 배터리 팽창 | 장기 충전 | 80% 제한 + 3개월 주기 점검 |

---

## 부록 A: Apple API 레퍼런스

### DockKit Framework
- `DockAccessory`: 모터 스탠드 연결/제어
- `DockAccessory.track()`: 바운딩 박스 기반 자동 추적
- `DockAccessory.setOrientation()`: 수동 팬/틸트 설정
- 지원 기기: iOS 17+, DockKit 인증 스탠드

### Vision Framework — Animal Body Pose
- `VNDetectAnimalBodyPoseRequest`: 고양이/개 관절 감지
- 관절 포인트: head, neck, tail, 4 legs (각 3 joints) = 17 points
- 성능: A15+ 칩에서 30fps 실시간
- iOS 17+ 필수

### AVFoundation
- `AVCaptureSession`: 카메라 입력 관리
- `AVCaptureVideoDataOutput`: 프레임별 접근
- `AVAssetWriter`: 로컬 녹화 (하이라이트 클립용)
