# LiveCat 개발 사양서 (Development Specification)

> **Version**: 1.0.0
> **Date**: 2026-02-25
> **Status**: Draft
> **관련 문서**: [ARCHITECTURE.md](./ARCHITECTURE.md) (시스템 아키텍처)

---

## 1. 프로젝트 개요 & 하드웨어 현황

### 1.1 프로젝트 목표

마당 고양이 2마리(나나, 토토)를 iPhone 2대 + DockKit 스탠드 2대로 자동 추적하며,
**6대 자동화**를 구현하는 무인 고양이 방송 + 콘텐츠 자동생산 시스템.

### 1.2 6대 자동화 요구사항

| # | 자동화 항목 | 모듈 | 동작 |
|:-:|:-----------|:-----|:-----|
| 1 | 라이브 스트리밍 | 스트리밍 엔진 | 카메라 영상 → PC 서버 자동 편집 → YouTube/Twitch 실시간 송출 |
| 2 | 하이라이트 Shorts | 하이라이트 클리퍼 + 숏폼 프로듀서 | 액기스 추출 → YouTube Shorts 자동 제작 & 업로드 |
| 3 | 썸네일 자동 생성 | 썸네일 생성기 | AI 프레임 선택 + 텍스트 오버레이 |
| 4 | 타이틀/설명 생성 | 콘텐츠 매니저 | LLM(Claude) 기반 타이틀·설명·해시태그 자동 생성 |
| 5 | 영상/BGM 템플릿 | 숏폼 프로듀서 | 인트로/아웃로/오버레이 + 무드별 BGM 자동 적용 |
| 6 | TikTok 자동화 | 멀티플랫폼 업로더 | TikTok 영상 자동 제작 & 업로드 |

### 1.3 하드웨어 현황

| 장비 | 수량 | 상태 | 비고 |
|:-----|:----:|:----:|:-----|
| DockKit 스탠드 (Belkin Auto-Tracking Stand Pro) | 2대 | 3/7 도착 예정 | 360° 팬 + 90° 틸트 |
| iPhone (SE 3세대 이상) | 2대 | 보유 | 카메라 + 온디바이스 AI |
| Windows PC | 1대 | 보유 | 서버 (영상처리 + 스트리밍 + 배치 + Claude AI) |
| **총 비용** | | | **~25만원** (DockKit 스탠드 2대) |

> **서버 플랫폼 독립성**: 서버 파이프라인의 모든 기술 스택(NDI, OBS, ffmpeg, YOLOv8/PyTorch,
> OpenCV, Python asyncio, Claude API)은 **크로스 플랫폼**이다.
> Windows PC, Mac, Linux 어디서든 동작하며, 현재 운영 환경은 **Windows 11 PC**이다.
>
> | 컴포넌트 | Windows | Mac | Linux |
> |:---------|:-------:|:---:|:-----:|
> | NDI 수신 (ndi-python) | O | O | O |
> | OBS Studio + WebSocket | O | O | O |
> | ffmpeg | O | O | O |
> | YOLOv8 (PyTorch) | O | O | O |
> | OpenCV, Pillow | O | O | O |
> | Claude API (anthropic SDK) | O | O | O |
> | YouTube/TikTok API | O | O | O |
>
> **참고**: ARCHITECTURE.md의 CoreML 모델(`.mlmodel`)은 macOS 전용이므로,
> 본 사양에서는 PyTorch 모델(`.pt`)로 통일하여 OS 의존성을 제거했다.

### 1.4 고양이 프로필

| 이름 | 영문 | 무늬 | Cat-ID 특징 |
|:----:|:----:|:----:|:-----------|
| **나나** | Nana | 호랑이 (Tabby) | 줄무늬 패턴, 갈색/검정 |
| **토토** | Toto | 턱시도 (Tuxedo) | 흑백 대비, 가슴 흰색 |

### 1.5 아키텍처 참조

본 문서는 [ARCHITECTURE.md](./ARCHITECTURE.md)의 시스템 설계를 기반으로 하되,
**2캠 체제**와 **콘텐츠 자동화 파이프라인**에 맞춰 구체화한 개발 사양이다.

주요 차이점:
- ARCHITECTURE.md: 4캠 + Mac Mini (macOS 전용 CoreML) → 라이브 스트리밍 중심
- **DEVSPEC.md: 2캠 + Windows PC (크로스 플랫폼 PyTorch) → 라이브 + 숏폼 + 멀티플랫폼 자동화**

---

## 2. 시스템 파이프라인 전체도

### 2.1 전체 데이터 흐름

```
 📱 iPhone #1 (나나 추적)     📱 iPhone #2 (토토 추적/전경)
  DockKit Stand                DockKit Stand
       │                            │
       │   NDI HX (~100ms)          │   NDI HX (~100ms)
       │   + WebSocket (메타데이터)   │   + WebSocket (메타데이터)
       │                            │
       └────────────┬───────────────┘
                    │  Wi-Fi (로컬 네트워크)
                    ▼
    ┌─────────────────────────────────────────────────────┐
    │              🖥️ Windows PC (서버)                      │
    │                                                     │
    │  ┌─────────────────────────────────────────────┐    │
    │  │           Video Receiver (2ch NDI)           │    │
    │  │           + Rolling Buffer (RAM)             │    │
    │  └──────────┬──────────┬───────────┬───────────┘    │
    │             │          │           │                 │
    │    ┌────────▼───┐  ┌──▼────────┐  │                 │
    │    │ ① 라이브    │  │ ② 하이라  │  │                 │
    │    │  스트리밍   │  │  이트     │  │                 │
    │    │  엔진      │  │  클리퍼   │  │                 │
    │    │            │  │          │  │                 │
    │    │ AI 스위칭  │  │ 이벤트   │  │                 │
    │    │ 사냥 블러  │  │ 감지     │  │                 │
    │    │ OBS 제어   │  │ 클립저장 │  │                 │
    │    └─────┬──────┘  └───┬──────┘  │                 │
    │          │             │         │                 │
    │          │      ┌──────▼──────┐  │                 │
    │          │      │ ③ 숏폼      │  │                 │
    │          │      │  프로듀서   │  │                 │
    │          │      │            │  │                 │
    │          │      │ 세로변환   │  │                 │
    │          │      │ 템플릿적용 │  │                 │
    │          │      │ BGM믹싱    │  │                 │
    │          │      └──────┬─────┘  │                 │
    │          │             │        │                 │
    │          │      ┌──────▼──────────▼─────────┐     │
    │          │      │ ④ 콘텐츠 매니저            │     │
    │          │      │                           │     │
    │          │      │ 썸네일 생성 (⑤)            │     │
    │          │      │ 타이틀/설명 생성 (⑥ Claude) │     │
    │          │      │ 해시태그/SEO               │     │
    │          │      └──────────┬────────────────┘     │
    │          │                 │                       │
    │          │      ┌──────────▼────────────────┐     │
    │          │      │ ⑦ 멀티플랫폼 업로더        │     │
    │          │      │                           │     │
    │          │      │ YouTube Shorts 업로드      │     │
    │          │      │ TikTok 업로드              │     │
    │          │      │ 스케줄러 (최적 시간 배포)   │     │
    │          │      └───────────────────────────┘     │
    │          │                                         │
    └──────────┼─────────────────────────────────────────┘
               │ RTMP (6Mbps, 1080p30)
               ▼
    ┌───────────────────────┐
    │  YouTube Live / Twitch │
    │  (24/7 라이브)         │
    └───────────────────────┘
```

### 2.2 파이프라인 유형별 분류

| 파이프라인 | 유형 | 지연 요구 | 실행 주기 |
|:----------|:----:|:--------:|:---------|
| ① 라이브 스트리밍 엔진 | **실시간** | <200ms | 상시 (30fps) |
| ② 하이라이트 클리퍼 | **준실시간** | <5s | 이벤트 트리거 |
| ③ 숏폼 프로듀서 | **배치** | 분 단위 | 클립 생성 후 |
| ④ 콘텐츠 매니저 | **배치** | 분 단위 | 숏폼 완성 후 |
| ⑤ 썸네일 생성 | **배치** | 초 단위 | 숏폼 완성 후 |
| ⑥ 타이틀/설명 생성 | **배치** | 초 단위 | 숏폼 완성 후 |
| ⑦ 멀티플랫폼 업로더 | **스케줄** | 시간 단위 | 스케줄러 |

---

## 3. 모듈 1: 라이브 스트리밍 엔진

### 3.1 개요

2대의 iPhone에서 NDI로 수신한 영상을 AI 기반으로 자동 스위칭하고,
사냥 장면 블러 처리 후 OBS를 통해 YouTube/Twitch로 실시간 송출한다.

### 3.2 입출력 스펙

```
입력:
├─ NDI 영상 스트림 × 2 (1080p30, H.264, ~8Mbps 각)
├─ WebSocket 메타데이터 × 2 (10Hz)
│   ├─ tracking_state: idle | searching | tracking | lost
│   ├─ cat_positions: [{id, center, bbox, pose, confidence}]
│   ├─ activity_score: 0~150
│   └─ motor_position: {pan, tilt}
└─ 사냥 감지 결과 (blur 모듈)

출력:
├─ OBS WebSocket 명령 (장면 전환, 소스 전환, 필터 제어)
├─ RTMP 스트림 → YouTube Live / Twitch (1080p30, 6Mbps)
└─ 이벤트 로그 (camera_switch, blur_event, scene_change)
```

### 3.3 AI 카메라 스위칭 (2캠 최적화)

4캠 체제(ARCHITECTURE.md)에서 2캠 체제로 단순화.
핵심 변경: PIP 모드 활용도 증가, 전환 빈도 감소.

```
┌──────────────────────────────────────────────┐
│          Camera Selector (2-cam)              │
│                                              │
│  입력 (매 프레임):                            │
│  ├─ CAM-1: activity_score, tracking_state    │
│  └─ CAM-2: activity_score, tracking_state    │
│                                              │
│  스위칭 규칙:                                 │
│  1. 최소 유지 시간: 8초 (2캠이므로 더 길게)   │
│  2. 전환 조건:                                │
│     • 다른 카메라 점수 > 현재 × 1.5           │
│     • 현재 카메라 추적 실패 > 3초             │
│     • 특수 이벤트 (점프, 달리기) 즉시 전환    │
│  3. 2마리 동시 활동:                          │
│     • PIP 모드 전환 (메인 70% + 서브 30%)     │
│     • 메인 = 높은 activity_score 카메라       │
│  4. 양쪽 모두 비활동:                         │
│     • 5분 → 힐링/수면 모드                    │
│     • 교대 전환 (30초 간격 크로스페이드)       │
│                                              │
│  출력: active_camera_id, transition_type      │
└──────────────────────────────────────────────┘
```

**전환 모드 (2캠 버전):**

| 모드 | 조건 | 전환 효과 | 비고 |
|:----:|:-----|:---------|:-----|
| 일반 | 점수 차이 1.5x | 크로스페이드 (0.5초) | 기본 모드 |
| 긴급 | 특수 이벤트 감지 | 즉시 컷 (0초) | 점프, 달리기, 사냥 |
| PIP | 2마리 동시 활동 | 메인 70% + 서브 30% | 2캠 체제 핵심 |
| 수면 | 양쪽 activity < 10 (5분) | 30초 교대 크로스페이드 | 힐링 BGM 자동 재생 |
| 오프라인 | 양쪽 추적 실패 (10분) | "곧 돌아옵니다" 정적 화면 | 폴백 |

### 3.4 사냥 블러 처리

ARCHITECTURE.md §3.3.3과 동일. (YOLOv8-nano → 먹잇감 감지 → 가우시안 블러)

### 3.5 OBS WebSocket 제어

```python
# OBS WebSocket 5.x 연동
OBS_WS_URL = "ws://localhost:4455"
OBS_WS_PASSWORD = "${OBS_PASSWORD}"  # .env

# 주요 명령
commands = {
    "switch_camera": "SetCurrentProgramScene",      # 장면 전환
    "enable_blur": "SetSourceFilterEnabled",         # 블러 필터 ON/OFF
    "set_source": "SetInputSettings",                # 카메라 소스 URL 변경
    "start_stream": "StartStream",                   # 방송 시작
    "stop_stream": "StopStream",                     # 방송 중지
    "get_status": "GetStreamStatus",                 # 상태 확인
}

# OBS 장면 구성
scenes = {
    "MainView":   "단일 카메라 전체 화면 + 오버레이",
    "PIP_Mode":   "메인(70%) + 서브(30%) + 오버레이",
    "Sleeping":   "수면 카메라 + 힐링 오버레이 + 로파이 BGM",
    "Offline":    "곧 돌아옵니다 정적 화면",
}
```

### 3.6 기술 스택

| 컴포넌트 | 라이브러리 | 버전 |
|:---------|:----------|:-----|
| 비동기 엔진 | `asyncio` | Python 3.11+ 내장 |
| NDI 수신 | `ndi-python` | >=5.5 |
| OBS 제어 | `obsws-python` | >=1.7 |
| 영상 처리 | `ffmpeg` (subprocess) | >=6.0 |
| 블러 처리 | `opencv-python` | >=4.9 |
| 사냥 감지 | `ultralytics` (YOLOv8) | >=8.1 |
| WebSocket 서버 | `websockets` | >=12.0 |

---

## 4. 모듈 2: 하이라이트 클리퍼

### 4.1 개요

2캠 영상을 상시 롤링 버퍼에 저장하고, 이벤트 감지 시 전후 클립을 자동 추출한다.
일일 TOP 10 클립을 선별하여 숏폼 프로듀서에 전달한다.

### 4.2 입출력 스펙

```
입력:
├─ NDI 영상 스트림 × 2 (롤링 버퍼에 상시 저장)
├─ WebSocket 메타데이터 × 2 (activity_score, pose, cat_positions)
└─ 이벤트 감지 결과

출력:
├─ 클립 파일: clips/{date}/{event_id}.mp4 (20초, 1080p)
├─ 클립 메타데이터: clips/{date}/{event_id}.json
│   ├─ event_type: "climb" | "jump" | "run" | "interact" | "hunt"
│   ├─ score: 0~100 (클립 품질 점수)
│   ├─ camera_id: "CAM-1" | "CAM-2"
│   ├─ cats: ["nana"] | ["toto"] | ["nana", "toto"]
│   ├─ timestamp: ISO 8601
│   └─ duration_sec: 20
└─ 일일 리포트: clips/{date}/daily_top10.json
```

### 4.3 이벤트 감지 엔진

```
이벤트 감지 기준 (activity_score 기반 + 포즈 분석):

┌──────────────────────────────────────────────────────┐
│  메타데이터 스트림 (10Hz, 2채널)                       │
│        │                                              │
│        ▼                                              │
│  이벤트 분류기                                         │
│  ├─ 🌲 나무등반 (climbing)                             │
│  │   조건: pose == "climbing" AND duration > 2초       │
│  │   점수: base 80 + height_bonus (높이 비례)          │
│  │                                                    │
│  ├─ 🦘 점프 (jumping)                                  │
│  │   조건: pose == "jumping" OR vertical_speed > thr   │
│  │   점수: base 70 + height_bonus                     │
│  │                                                    │
│  ├─ 🏃 달리기 (running)                                │
│  │   조건: movement_speed > 50 (정규화) AND dur > 1초  │
│  │   점수: base 60 + speed_bonus                      │
│  │                                                    │
│  ├─ 🐱🐱 상호작용 (interaction)                        │
│  │   조건: 2마리 근접 (거리 < 0.3) AND 양쪽 활동 중    │
│  │   점수: base 90 (가장 희소한 이벤트)                │
│  │                                                    │
│  └─ 🎯 사냥시도 (hunt_attempt)                         │
│      조건: 사냥 감지 모델 trigger                      │
│      점수: base 85 (블러 처리 후 클립)                 │
└──────────────────────────────────────────────────────┘
```

### 4.4 롤링 버퍼

```python
# 롤링 버퍼 설정
ROLLING_BUFFER = {
    "storage": "RAM_DISK",          # /tmp/livecat_buffer/ (RAM 디스크)
    "duration_sec": 60,             # 최근 60초 항상 보관
    "cameras": 2,                   # 2캠 모두 버퍼링
    "format": "h264",               # 원본 코덱 유지 (재인코딩 없음)
    "segment_sec": 10,              # 10초 단위 세그먼트
    "total_ram_mb": 1200,           # ~600MB/채널 (1080p30, 60초)
}

# 클립 추출 프로세스
CLIP_EXTRACTION = {
    "pre_event_sec": 5,             # 이벤트 5초 전부터
    "post_event_sec": 15,           # 이벤트 15초 후까지
    "total_duration_sec": 20,       # 총 20초 클립
    "save_both_cameras": True,      # 2캠 모두 저장 (편집 옵션)
    "output_codec": "h264",         # 변환 없이 세그먼트 결합
    "output_dir": "clips/",
}
```

### 4.5 클립 스코어링 & 일일 TOP 10

```python
def score_clip(clip_metadata: dict) -> float:
    """
    클립 품질 종합 점수 (0~100)

    구성:
    - event_score (40%): 이벤트 유형별 기본 점수
    - clarity_score (20%): 영상 선명도 (Laplacian variance)
    - composition_score (15%): 고양이 위치 (프레임 중심 근접도)
    - novelty_score (15%): 오늘 동일 이벤트 반복 감소 페널티
    - cat_bonus (10%): 2마리 동시 등장 보너스
    """
    weights = {
        "event": 0.40,
        "clarity": 0.20,
        "composition": 0.15,
        "novelty": 0.15,
        "cat_bonus": 0.10,
    }
    # ...
    return weighted_sum  # 0~100
```

**일일 선별 프로세스:**

```
하루 전체 클립 (예: 30~80개)
       │
       ▼
  중복 제거 (같은 이벤트 연속 클립 → 최고 점수만)
       │
       ▼
  스코어 정렬 (내림차순)
       │
       ▼
  다양성 필터 (동일 이벤트 유형 최대 3개)
       │
       ▼
  TOP 10 선별 → daily_top10.json
       │
       ▼
  숏폼 프로듀서 큐에 전달
```

### 4.6 기술 스택

| 컴포넌트 | 라이브러리 | 용도 |
|:---------|:----------|:-----|
| 영상 세그먼트 | `ffmpeg` | 롤링 버퍼 세그먼트 저장/결합 |
| 선명도 분석 | `opencv-python` | Laplacian variance 계산 |
| 이벤트 감지 | Python 내장 로직 | 메타데이터 기반 규칙 엔진 |
| 스케줄링 | `asyncio` + `apscheduler` | 일일 TOP 10 배치 |

---

## 5. 모듈 3: 숏폼 프로듀서 (Shorts + TikTok)

### 5.1 개요

하이라이트 클립(16:9 가로)을 세로(9:16) 숏폼 콘텐츠로 변환하고,
영상 템플릿(인트로/아웃로/오버레이)과 BGM을 자동 적용하여 완성 영상을 생성한다.

### 5.2 입출력 스펙

```
입력:
├─ 클립 파일: clips/{date}/{event_id}.mp4 (20초, 1080p, 16:9)
├─ 클립 메타데이터: clips/{date}/{event_id}.json
├─ 영상 템플릿: templates/ (인트로, 아웃로, 오버레이)
└─ BGM 풀: bgm/ (카테고리별 로열티프리 음원)

출력:
├─ YouTube Shorts: output/shorts/{date}/{event_id}_shorts.mp4
│   (9:16, 1080x1920, 15~60초, H.264, AAC)
├─ TikTok: output/tiktok/{date}/{event_id}_tiktok.mp4
│   (9:16, 1080x1920, 15~60초, H.264, AAC)
└─ 제작 메타데이터: output/{platform}/{event_id}_meta.json
```

### 5.3 세로 변환 파이프라인 (16:9 → 9:16)

```
원본 클립 (1920x1080, 16:9)
       │
       ▼
  YOLOv8 고양이 감지 (프레임별)
  → bbox 중심점 추출
       │
       ▼
  스마트 크롭 영역 계산
  ├─ 크롭 사이즈: 608x1080 (원본 높이 유지, 9:16 비율)
  ├─ 크롭 중심: 고양이 bbox 중심 X좌표 추종
  ├─ 스무딩: 칼만 필터 (급격한 이동 방지)
  └─ 바운더리: 프레임 경계 클램핑
       │
       ▼
  ffmpeg crop + scale
  → 출력: 1080x1920 (9:16)
```

```python
# 스마트 크롭 설정
SMART_CROP = {
    "target_ratio": (9, 16),        # 세로 비율
    "output_size": (1080, 1920),    # 출력 해상도
    "cat_detector": "yolov8n",      # 고양이 감지 모델
    "smoothing_factor": 0.85,       # 칼만 필터 계수
    "padding_ratio": 1.3,           # 고양이 bbox 대비 여유 공간
    "fallback": "center_crop",      # 고양이 미감지 시 중앙 크롭
}
```

### 5.4 영상 템플릿 적용

```
완성 영상 구조 (총 ~25초):

┌─────────────────────────┐
│  INTRO (1.5초)           │  ← templates/intro/default.mp4
│  채널 로고 + 사운드      │     크로스페이드 인
├─────────────────────────┤
│                         │
│  본문 클립 (20초)        │  ← 세로 변환된 하이라이트
│                         │
│  [이벤트 텍스트]         │  ← 오버레이: "나나의 나무등반!"
│  [고양이 이름표]         │  ← 오버레이: "🐱 나나 (Nana)"
│                         │
├─────────────────────────┤
│  OUTRO (2초)             │  ← templates/outro/subscribe.mp4
│  "구독 & 좋아요!"        │     + 팔로우 CTA
│  채널 QR코드             │
└─────────────────────────┘
```

**오버레이 상세:**

| 오버레이 | 위치 | 크기 | 폰트/색상 | 지속 |
|:---------|:----:|:----:|:---------|:----:|
| 이벤트 텍스트 | 상단 중앙 | 48px Bold | 흰색 + 검정 외곽선 3px | 본문 전체 |
| 고양이 이름표 | 하단 좌측 | 36px Medium | 흰색 배경 반투명 | 본문 전체 |
| 채널 로고 워터마크 | 우측 하단 | 80x80px | 반투명 (opacity 0.7) | 전체 |
| 타임스탬프 | 좌측 상단 | 24px | 흰색 반투명 | 본문 전체 |

### 5.5 BGM 자동 선택 & 믹싱

```python
# 이벤트 → 무드 매핑 (bgm/config.yaml)
EVENT_MOOD_MAP = {
    "climb": "active",         # 🌲 나무등반 → 활동적
    "jump": "active",          # 🦘 점프 → 활동적
    "run": "active",           # 🏃 달리기 → 활동적
    "interact": "comic",       # 🐱🐱 상호작용 → 코믹
    "hunt_attempt": "tension", # 🎯 사냥시도 → 긴장
    "sleep": "healing",        # 💤 수면 → 힐링
    "groom": "healing",        # 🛁 그루밍 → 힐링
    "sunbathe": "healing",     # ☀️ 일광욕 → 힐링
    "fail": "comic",           # 😂 실패/놀람 → 코믹
}

# BGM 믹싱 설정
BGM_MIX = {
    "volume_bgm": 0.15,        # BGM 볼륨 (원본 대비)
    "volume_original": 0.85,   # 원본 오디오 볼륨
    "fade_in_sec": 1.0,        # BGM 페이드 인
    "fade_out_sec": 1.5,       # BGM 페이드 아웃
    "random_start": True,      # BGM 랜덤 시작 지점
}
```

**ffmpeg 믹싱 명령:**

```bash
ffmpeg -i clip.mp4 -i bgm.mp3 \
  -filter_complex "
    [1:a]atrim=start={random_offset}:duration={clip_duration},
    afade=t=in:d=1.0,
    afade=t=out:st={clip_duration-1.5}:d=1.5,
    volume=0.15[bgm];
    [0:a]volume=0.85[orig];
    [orig][bgm]amix=inputs=2:duration=first[aout]
  " \
  -map 0:v -map "[aout]" -c:v copy -c:a aac output.mp4
```

### 5.6 속도 조절

| 이벤트 | 속도 | 적용 구간 | 효과 |
|:-------|:----:|:---------|:-----|
| 점프/착지 | 0.5x (슬로우모션) | 점프 정점 ±1초 | 역동적 순간 강조 |
| 달리기 | 1.0x (원속) | 전체 | 원본 속도감 유지 |
| 이동/배회 | 2.0x (타임랩스) | 전체 | 지루한 구간 압축 |
| 수면 | 4.0x (타임랩스) | 전체 | 잠자는 모습 귀여움 압축 |

### 5.7 자막 자동 생성

```python
# 이벤트 기반 자막 (음성 인식 아님, 이벤트 메타데이터 기반)
SUBTITLE_TEMPLATES = {
    "climb": ["나나가 나무를 오른다! 🌲", "토토의 나무등반 도전!", "높이높이 올라가자!"],
    "jump": ["점프! 🦘", "대단한 점프력!", "착지 성공!"],
    "run": ["전력 질주! 🏃", "빠르다 빨라!", "어디로 가는 거야?"],
    "interact": ["나나 vs 토토! 🐱🐱", "같이 놀자!", "우리는 친구!"],
    "hunt_attempt": ["사냥 본능 발동! 🎯", "집중...!", "타겟 발견!"],
}
```

### 5.8 기술 스택

| 컴포넌트 | 라이브러리 | 용도 |
|:---------|:----------|:-----|
| 세로 변환 | `ffmpeg` + `ultralytics` (YOLOv8) | 고양이 중심 스마트 크롭 |
| 영상 합성 | `ffmpeg` | 인트로/본문/아웃로 결합 |
| 텍스트 오버레이 | `Pillow` (>=10.0) | 이벤트 텍스트, 이름표, 자막 |
| BGM 믹싱 | `ffmpeg` (afade, amix) | BGM 자동 선택 & 볼륨 조절 |
| 속도 조절 | `ffmpeg` (setpts, atempo) | 슬로우모션, 타임랩스 |
| 파이프라인 | `moviepy` (>=2.0) | 복잡한 편집 시 폴백 |

---

## 6. 모듈 4: 썸네일 자동 생성

### 6.1 개요

클립 내 최적 프레임을 AI로 선택하고, 텍스트 오버레이를 적용하여
플랫폼별 썸네일을 자동 생성한다.

### 6.2 입출력 스펙

```
입력:
├─ 클립 파일: clips/{date}/{event_id}.mp4
├─ 클립 메타데이터: {event_id}.json (이벤트 유형, 고양이 정보)
└─ 썸네일 템플릿: templates/thumbnails/

출력:
├─ YouTube 썸네일: thumbnails/{event_id}_yt.jpg (1280x720, JPEG)
├─ TikTok 커버: thumbnails/{event_id}_tt.jpg (1080x1920, JPEG)
└─ 선택 메타데이터: thumbnails/{event_id}_frame.json
    ├─ frame_index: 선택된 프레임 번호
    ├─ scores: {clarity, pose, composition, total}
    └─ template_id: 적용된 템플릿 ID
```

### 6.3 프레임 선택 알고리즘

```
클립 전체 프레임 (20초 × 30fps = 600 프레임)
       │
       ▼
  1단계: 후보 추출 (매 10프레임 = 60장)
       │
       ▼
  2단계: 선명도 점수 (Laplacian Variance)
  ├─ cv2.Laplacian(gray, cv2.CV_64F).var()
  ├─ 임계값 이하 (블러 프레임) 제거
  └─ 정규화: 0~100
       │
       ▼
  3단계: 고양이 포즈 매력도
  ├─ YOLOv8 고양이 감지 → bbox 추출
  ├─ 정면/측면 선호 (얼굴 각도 추정)
  ├─ 눈 뜬 상태 선호 (eye landmark 기반)
  ├─ 전신 보이는 프레임 선호
  └─ 정규화: 0~100
       │
       ▼
  4단계: 구도 점수 (삼분할 법칙)
  ├─ 고양이 중심이 삼분할 교차점 근접 → 고점수
  ├─ 적절한 여백 (고양이가 프레임 20~80% 차지)
  └─ 정규화: 0~100
       │
       ▼
  5단계: 종합 점수
  ├─ total = clarity×0.3 + pose×0.4 + composition×0.3
  └─ 최고 점수 프레임 선택
```

```python
# 프레임 선택 설정
FRAME_SELECTOR = {
    "sample_interval": 10,          # 매 10프레임마다 후보
    "clarity_threshold": 50.0,      # Laplacian variance 최소값
    "weights": {
        "clarity": 0.30,
        "pose_attractiveness": 0.40,
        "composition": 0.30,
    },
    "prefer_both_cats": True,       # 2마리 동시 프레임 보너스 (+20)
}
```

### 6.4 텍스트 오버레이 & 템플릿

**플랫폼별 사이즈:**

| 플랫폼 | 사이즈 | 비율 | 포맷 |
|:-------|:------:|:----:|:----:|
| YouTube | 1280×720 | 16:9 | JPEG (quality 95) |
| TikTok | 1080×1920 | 9:16 | JPEG (quality 95) |

**텍스트 오버레이 구성:**

```
YouTube 썸네일 레이아웃:
┌─────────────────────────────────┐
│                                 │
│  [고양이 프레임 - 배경]          │
│                                 │
│        ┌─────────────────┐      │
│        │ 이벤트 키워드    │      │  ← 72px Bold, 흰색
│        │ (큰 글씨)       │      │     검정 외곽선 4px
│        └─────────────────┘      │     그림자 효과
│                                 │
│  🐱 나나 & 토토                  │  ← 36px, 좌측 하단
│                     [로고] 🔴   │  ← 채널 로고, 우측 하단
└─────────────────────────────────┘
```

**썸네일 템플릿 3종 (A/B 테스트용):**

| ID | 이름 | 스타일 | 특징 |
|:--:|:----:|:------|:-----|
| A | Bold | 큰 텍스트 중앙, 강한 대비 | 밝은 배경 + 큰 글씨 |
| B | Minimal | 작은 텍스트 하단, 이미지 중심 | 고양이 풀샷 강조 |
| C | Frame | 컬러 프레임 테두리, 이모지 장식 | 눈에 띄는 테두리 + 이모지 |

```python
# 썸네일 템플릿 설정
THUMBNAIL_TEMPLATES = {
    "A": {
        "name": "Bold",
        "text_position": "center",
        "text_size": 72,
        "text_stroke": 4,
        "background_darken": 0.3,
        "logo_position": "bottom_right",
    },
    "B": {
        "name": "Minimal",
        "text_position": "bottom_left",
        "text_size": 48,
        "text_stroke": 2,
        "background_darken": 0.0,
        "logo_position": "bottom_right",
    },
    "C": {
        "name": "Frame",
        "text_position": "top_center",
        "text_size": 56,
        "text_stroke": 3,
        "frame_color": "#FF6B35",
        "frame_width": 12,
        "logo_position": "bottom_right",
    },
}
```

### 6.5 기술 스택

| 컴포넌트 | 라이브러리 | 용도 |
|:---------|:----------|:-----|
| 프레임 추출 | `opencv-python` | 클립에서 프레임 샘플링 |
| 선명도 분석 | `opencv-python` | Laplacian variance |
| 고양이 감지 | `ultralytics` (YOLOv8) | bbox + 포즈 추정 |
| 텍스트 렌더링 | `Pillow` (>=10.0) | 한글 폰트 + 외곽선 + 그림자 |
| 이미지 리사이즈 | `Pillow` | 플랫폼별 사이즈 조정 |

---

## 7. 모듈 5: 타이틀/설명 자동 생성

### 7.1 개요

Claude API를 활용하여 이벤트 메타데이터 기반으로
플랫폼별 최적화된 타이틀, 설명, 해시태그를 자동 생성한다.

### 7.2 입출력 스펙

```
입력:
├─ 클립 메타데이터: {event_id}.json
│   ├─ event_type, score, cats, timestamp
│   └─ duration_sec, camera_id
├─ 프롬프트 템플릿: config/prompts/*.md
└─ 이전 업로드 히스토리 (중복 방지)

출력:
├─ YouTube 메타데이터:
│   ├─ title: str (최대 70자)
│   ├─ description: str (최대 5000자)
│   ├─ tags: list[str] (최대 500자)
│   └─ category_id: int (YouTube 카테고리)
├─ TikTok 메타데이터:
│   ├─ title: str (최대 150자, 해시태그 포함)
│   └─ hashtags: list[str]
└─ 후보 목록: 타이틀 5개 (자동 선택 또는 수동 선택)
```

### 7.3 Claude API 연동

```python
import anthropic

client = anthropic.Anthropic(api_key="${ANTHROPIC_API_KEY}")  # .env

def generate_title_candidates(event_meta: dict, platform: str) -> list[str]:
    """이벤트 메타데이터 → 타이틀 후보 5개 생성"""

    prompt_template = load_prompt(f"config/prompts/title_{platform}.md")
    prompt = prompt_template.format(
        event_type=event_meta["event_type"],
        cats=", ".join(event_meta["cats"]),
        score=event_meta["score"],
        time_of_day=get_time_period(event_meta["timestamp"]),
        # ...
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  # 빠르고 저렴한 모델
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    return parse_title_candidates(response.content[0].text)
```

### 7.4 프롬프트 템플릿

**`config/prompts/title_youtube.md`:**

```markdown
당신은 고양이 유튜브 채널의 타이틀 작성 전문가입니다.

## 채널 정보
- 채널명: LiveCat (고양이 나나 & 토토)
- 컨셉: 마당 고양이 2마리의 자연스러운 일상

## 고양이 정보
- 나나 (Nana): 호랑이 무늬 (Tabby)
- 토토 (Toto): 턱시도 (Tuxedo, 흑백)

## 이벤트 정보
- 이벤트: {event_type}
- 등장 고양이: {cats}
- 시간대: {time_of_day}

## 규칙
1. 최대 70자 (한글 기준)
2. 클릭을 유도하되 낚시성은 금지
3. 고양이 이름을 자연스럽게 포함
4. 이모지 1~2개 사용
5. 한국어로 작성

## 출력
타이틀 후보 5개를 한 줄에 하나씩 출력하세요.
```

**`config/prompts/title_tiktok.md`:**

```markdown
당신은 고양이 틱톡 콘텐츠의 캡션 작성 전문가입니다.

## 채널 정보
- 계정: @livecat_nana_toto
- 컨셉: 마당 고양이의 귀여운 일상 (숏폼)

## 고양이 정보
- 나나 (Nana): 호랑이 무늬
- 토토 (Toto): 턱시도 (흑백)

## 이벤트 정보
- 이벤트: {event_type}
- 등장 고양이: {cats}
- 시간대: {time_of_day}

## 규칙
1. 최대 120자 (해시태그 제외)
2. 캐주얼하고 재미있는 톤
3. 해시태그 5~8개 추가
4. 한국어 + 영어 해시태그 혼용
5. 트렌딩 해시태그 활용

## 출력
캡션 후보 5개, 각각 해시태그 포함하여 출력하세요.
```

**`config/prompts/description.md`:**

```markdown
당신은 고양이 유튜브 영상의 설명(description) 작성 전문가입니다.

## 이벤트 정보
- 이벤트: {event_type}
- 등장 고양이: {cats}
- 시간대: {time_of_day}
- 영상 길이: {duration}초

## 규칙
1. 첫 2줄이 가장 중요 (미리보기에 노출)
2. 고양이 소개 포함
3. SEO 키워드 자연스럽게 포함
4. 구독/좋아요 유도 문구 하단에
5. 200~500자

## 출력
설명문 1개를 출력하세요.
```

### 7.5 해시태그 자동 생성

```python
# 기본 해시태그 풀
BASE_HASHTAGS = {
    "ko": ["#고양이", "#캣스타그램", "#고양이일상", "#냥스타그램", "#마당고양이"],
    "en": ["#cat", "#catsofinstagram", "#catlife", "#outdoorcat", "#catvideo"],
}

# 이벤트별 추가 해시태그
EVENT_HASHTAGS = {
    "climb": ["#캣타워", "#나무등반", "#고양이운동", "#catclimbing"],
    "jump": ["#고양이점프", "#catjump", "#슈퍼캣"],
    "run": ["#고양이달리기", "#zoomies", "#catrun"],
    "interact": ["#고양이친구", "#멀티캣", "#catfriends"],
    "hunt_attempt": ["#사냥본능", "#고양이사냥", "#cathunting"],
    "sleep": ["#고양이낮잠", "#힐링", "#catsleeping", "#lofi"],
}

# 고양이별 해시태그
CAT_HASHTAGS = {
    "nana": ["#나나", "#호랑이고양이", "#태비", "#tabbycat"],
    "toto": ["#토토", "#턱시도고양이", "#tuxedocat"],
}
```

### 7.6 SEO 키워드 최적화

```python
# YouTube SEO 전략
SEO_CONFIG = {
    "title_keywords": [
        "고양이", "cat", "마당고양이", "outdoor cat",
        "귀여운", "cute", "일상", "daily",
    ],
    "description_keywords": [
        "고양이 일상", "마당고양이 일상", "고양이 라이브",
        "cat daily life", "outdoor cat life",
    ],
    "tags_max_length": 500,     # YouTube 태그 최대 500자
    "tags_max_count": 30,       # 최대 30개 권장
}
```

### 7.7 기술 스택

| 컴포넌트 | 라이브러리 | 용도 |
|:---------|:----------|:-----|
| LLM API | `anthropic` (>=0.40) | Claude API (타이틀/설명 생성) |
| 모델 | `claude-haiku-4-5-20251001` | 빠르고 저렴한 생성 (Haiku) |
| 프롬프트 관리 | 파일 시스템 (markdown) | config/prompts/*.md |
| 캐싱 | `diskcache` | 동일 이벤트 반복 생성 방지 |

---

## 8. 모듈 6: 멀티플랫폼 업로더

### 8.1 개요

완성된 숏폼 영상 + 썸네일 + 메타데이터를 YouTube Shorts와 TikTok에
자동으로 업로드하고, 최적 시간대에 배포하는 스케줄러를 운영한다.

### 8.2 입출력 스펙

```
입력:
├─ 영상 파일: output/{platform}/{event_id}_{platform}.mp4
├─ 썸네일: thumbnails/{event_id}_{platform}.jpg
├─ 메타데이터: {title, description, tags, hashtags, category}
└─ 업로드 스케줄: scheduler/queue.json

출력:
├─ 업로드 결과: uploads/{date}/{event_id}_result.json
│   ├─ platform: "youtube" | "tiktok"
│   ├─ video_id: 플랫폼별 영상 ID
│   ├─ url: 공개 URL
│   ├─ status: "published" | "processing" | "failed"
│   └─ uploaded_at: ISO 8601
└─ 업로드 로그: uploads/upload_history.jsonl
```

### 8.3 YouTube Shorts 업로드

```python
# YouTube Data API v3 설정
YOUTUBE_CONFIG = {
    "api_version": "v3",
    "scopes": [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    ],
    "credentials_file": "config/credentials/youtube_oauth.json",
    "token_file": "config/credentials/youtube_token.json",

    # Shorts 설정
    "shorts": {
        "category_id": 15,             # Pets & Animals
        "privacy_status": "public",     # public | private | unlisted
        "made_for_kids": False,
        "default_language": "ko",
        "embeddable": True,
    },

    # 할당량 관리
    "quota": {
        "daily_limit": 10000,           # YouTube API 일일 할당량
        "upload_cost": 1600,            # 영상 업로드 1건 = 1,600 units
        "thumbnail_cost": 50,           # 썸네일 설정 = 50 units
        "max_uploads_per_day": 6,       # 10000 / 1650 ≈ 6건
    },
}
```

**업로드 프로세스:**

```
1. OAuth 2.0 인증 (첫 실행 시 브라우저 인증, 이후 자동 갱신)
       │
       ▼
2. 영상 업로드 (resumable upload)
   ├─ POST /upload/youtube/v3/videos?part=snippet,status
   ├─ 청크 업로드 (256KB 단위)
   └─ 업로드 진행률 추적
       │
       ▼
3. 썸네일 설정
   └─ POST /youtube/v3/thumbnails/set?videoId={id}
       │
       ▼
4. 메타데이터 확인
   └─ GET /youtube/v3/videos?id={id}&part=status
       │
       ▼
5. 결과 저장 + 로그
```

### 8.4 TikTok 업로드

```python
# TikTok Content Posting API 설정
TIKTOK_CONFIG = {
    "api_base": "https://open.tiktokapis.com/v2",
    "scopes": ["video.publish", "video.upload"],
    "credentials_file": "config/credentials/tiktok_oauth.json",

    # 업로드 설정
    "upload": {
        "privacy_level": "PUBLIC_TO_EVERYONE",  # 공개
        "disable_duet": False,
        "disable_comment": False,
        "disable_stitch": False,
        "video_cover_timestamp_ms": 0,          # 커버 이미지 타임스탬프
    },

    # 제한
    "limits": {
        "max_video_size_mb": 287,
        "max_duration_sec": 600,
        "min_duration_sec": 3,
    },
}
```

**TikTok 업로드 프로세스:**

```
1. OAuth 2.0 인증 (Authorization Code Flow)
       │
       ▼
2. 업로드 초기화
   POST /v2/post/publish/inbox/video/init/
   → upload_url 수신
       │
       ▼
3. 파일 업로드
   PUT {upload_url}
   Content-Type: video/mp4
   Content-Range: bytes {start}-{end}/{total}
       │
       ▼
4. 게시 완료 확인
   POST /v2/post/publish/status/fetch/
   → publish_id로 상태 확인
       │
       ▼
5. 결과 저장 + 로그
```

### 8.5 업로드 스케줄러

```python
# 스케줄러 설정
SCHEDULER_CONFIG = {
    # 최적 업로드 시간대 (KST)
    "optimal_hours": {
        "youtube": [18, 19, 20, 21, 22],    # 오후 6시~10시
        "tiktok": [12, 18, 19, 20, 21],     # 점심 + 저녁
    },

    # 일일 업로드 할당
    "daily_quota": {
        "youtube_shorts": 3,     # 하루 Shorts 2~3개
        "tiktok": 3,             # 하루 TikTok 2~3개
    },

    # 업로드 간격
    "min_interval_hours": 2,     # 같은 플랫폼 최소 2시간 간격

    # 큐 우선순위
    "priority_order": [
        "interaction",           # 2마리 상호작용 최우선
        "climb",
        "jump",
        "hunt_attempt",
        "run",
        "sleep",
    ],
}
```

**스케줄러 동작 흐름:**

```
매시 정각 실행 (cron: 0 * * * *)
       │
       ▼
  큐 확인 (scheduler/queue.json)
  ├─ 대기 중인 영상 목록
  ├─ 우선순위 정렬
  └─ 일일 할당량 잔여 확인
       │
       ▼
  현재 시간이 최적 시간대인지 확인
  ├─ YES → 다음 영상 업로드 실행
  │         ├─ YouTube Shorts
  │         └─ TikTok (동일 클립, 다른 메타데이터)
  └─ NO  → 다음 최적 시간까지 대기
       │
       ▼
  업로드 결과 기록
  ├─ 성공 → 큐에서 제거, 히스토리 기록
  └─ 실패 → 재시도 카운터 증가 (최대 3회)
```

### 8.6 기술 스택

| 컴포넌트 | 라이브러리 | 용도 |
|:---------|:----------|:-----|
| YouTube API | `google-api-python-client` (>=2.100) | YouTube Data API v3 |
| YouTube 인증 | `google-auth-oauthlib` (>=1.2) | OAuth 2.0 |
| TikTok API | `requests` (>=2.31) | TikTok Content Posting API |
| 스케줄러 | `apscheduler` (>=3.10) | 업로드 스케줄링 |
| 큐 관리 | JSON 파일 (경량) | scheduler/queue.json |

---

## 9. 영상 템플릿 & BGM 템플릿 상세

### 9.1 영상 템플릿

#### 인트로 템플릿

| 파일 | 길이 | 해상도 | 설명 |
|:-----|:----:|:------:|:-----|
| `templates/intro/default.mp4` | 1.5초 | 1080×1920 | 채널 로고 줌인 + 고양이 발자국 효과 + 사운드 |
| `templates/intro/morning.mp4` | 1.5초 | 1080×1920 | 아침 햇살 + 새소리 + 로고 |
| `templates/intro/night.mp4` | 1.5초 | 1080×1920 | 달빛 + 귀뚜라미 소리 + 로고 |

#### 아웃로 템플릿

| 파일 | 길이 | 해상도 | 설명 |
|:-----|:----:|:------:|:-----|
| `templates/outro/subscribe.mp4` | 2초 | 1080×1920 | "구독 & 좋아요!" CTA + 구독 버튼 애니메이션 |
| `templates/outro/follow_tiktok.mp4` | 2초 | 1080×1920 | "팔로우!" CTA + TikTok 로고 |
| `templates/outro/next_video.mp4` | 2초 | 1080×1920 | "다음 영상도 기대해주세요!" |

#### 오버레이 설정

```yaml
# templates/overlays/event_text.yaml
event_text:
  position: "top_center"
  margin_top: 80
  font: "NanumSquareRoundEB.ttf"    # 한글 볼드 폰트
  size: 48
  color: "#FFFFFF"
  stroke_color: "#000000"
  stroke_width: 3
  shadow:
    offset: [2, 2]
    color: "#00000080"
  animation: "fade_in"               # 0.3초 페이드 인
  duration: "full"                    # 본문 전체

# templates/overlays/cat_name.yaml
cat_name:
  position: "bottom_left"
  margin_bottom: 120
  margin_left: 40
  font: "NanumSquareRoundB.ttf"
  size: 36
  color: "#FFFFFF"
  background:
    color: "#00000060"               # 반투명 검정
    padding: [8, 16]
    border_radius: 12
  icons:
    nana: "🐱"
    toto: "🐈‍⬛"

# templates/overlays/watermark.yaml
watermark:
  position: "bottom_right"
  margin: 20
  image: "templates/overlays/logo_80x80.png"
  opacity: 0.7
  size: [80, 80]
```

#### 전환 효과

```yaml
# templates/transitions/config.yaml
transitions:
  intro_to_main:
    type: "crossfade"
    duration_ms: 300

  main_to_outro:
    type: "crossfade"
    duration_ms: 500

  between_clips:                    # 멀티 클립 결합 시
    type: "swipe_left"
    duration_ms: 400
```

### 9.2 BGM 템플릿

#### 디렉토리 구조 & 음원

```
bgm/
├── active/                         # 🏃 활동적 (달리기, 점프, 나무등반)
│   ├── active_01_energetic.mp3     # 경쾌한 일렉트로닉
│   ├── active_02_playful.mp3       # 장난스러운 마림바
│   ├── active_03_adventure.mp3     # 모험 느낌 오케스트라
│   ├── active_04_bounce.mp3        # 바운시 팝
│   └── active_05_chase.mp3         # 추격전 느낌
│
├── healing/                        # 💤 힐링 (수면, 그루밍, 일광욕)
│   ├── healing_01_lofi.mp3         # 로파이 힙합
│   ├── healing_02_piano.mp3        # 잔잔한 피아노
│   ├── healing_03_nature.mp3       # 자연 사운드 + 기타
│   ├── healing_04_ambient.mp3      # 앰비언트
│   └── healing_05_musicbox.mp3     # 오르골
│
├── comic/                          # 😂 코믹 (실패, 놀람, 엉뚱한 행동)
│   ├── comic_01_pizzicato.mp3      # 피치카토 (톡톡톡)
│   ├── comic_02_cartoon.mp3        # 카툰 효과음
│   ├── comic_03_silly.mp3          # 실리 워킹
│   ├── comic_04_surprise.mp3       # 놀람 효과 + 멜로디
│   └── comic_05_clumsy.mp3         # 어리숙한 느낌
│
├── tension/                        # 😰 긴장 (사냥 직전, 대치)
│   ├── tension_01_suspense.mp3     # 서스펜스
│   ├── tension_02_stalking.mp3     # 스토킹/잠행
│   ├── tension_03_heartbeat.mp3    # 심장박동 + 긴장
│   ├── tension_04_predator.mp3     # 포식자 테마
│   └── tension_05_countdown.mp3    # 카운트다운
│
└── config.yaml                     # 이벤트 → 무드 매핑 + 설정
```

#### BGM 설정 파일

```yaml
# bgm/config.yaml

# 이벤트 → 무드 매핑
event_mood_map:
  climb: "active"
  jump: "active"
  run: "active"
  interact: "comic"
  hunt_attempt: "tension"
  sleep: "healing"
  groom: "healing"
  sunbathe: "healing"
  fail: "comic"
  surprise: "comic"
  standoff: "tension"

# 믹싱 설정
mixing:
  bgm_volume: 0.15
  original_volume: 0.85
  fade_in_sec: 1.0
  fade_out_sec: 1.5
  random_start: true             # BGM 시작 지점 랜덤
  crossfade_overlap_sec: 0.5     # 인트로/아웃로 전환 시

# 선택 규칙
selection:
  avoid_repeat_count: 3          # 최근 3개 영상에 사용된 BGM 회피
  prefer_shorter: true           # 클립보다 긴 BGM 선호 (루핑 방지)
```

#### 저작권 정보

| 소스 | URL | 라이선스 | 비고 |
|:-----|:----|:--------|:-----|
| YouTube Audio Library | YouTube Studio 내 | 무료/상업적 이용 가능 | 일부 크레딧 필요 |
| Pixabay Music | pixabay.com | Pixabay License (상업적 무료) | 크레딧 불필요 |
| Free Music Archive | freemusicarchive.org | CC BY / CC0 | 라이선스 확인 필수 |
| Uppbeat | uppbeat.io | 무료 플랜 (크레딧 표기) | 월 10곡 무료 |

---

## 10. 프로젝트 디렉토리 구조

```
D:\livecat/
├── ARCHITECTURE.md                 # 시스템 아키텍처 (4캠 원본 설계)
├── DEVSPEC.md                      # 개발 사양서 (이 문서, 2캠 체제)
│
├── ios/                            # iPhone 앱 (Swift)
│   └── LiveCatCam/
│       ├── App/
│       ├── Tracking/               # 고양이 추적 (Vision + DockKit)
│       ├── Capture/                # 영상 캡처 + NDI 전송
│       ├── Network/                # 서버 통신 (WebSocket)
│       ├── Models/                 # 데이터 모델
│       └── Utils/                  # 유틸리티 (칼만 필터 등)
│
├── server/                         # PC 서버 (Python, 크로스 플랫폼)
│   ├── main.py                     # 서버 엔트리포인트 (asyncio)
│   ├── config.yaml                 # 전역 설정
│   │
│   ├── receiver/                   # 모듈: 영상 수신
│   │   ├── __init__.py
│   │   ├── video_receiver.py       # NDI 2채널 수신
│   │   ├── metadata_receiver.py    # WebSocket 메타데이터 수신
│   │   └── stream_buffer.py        # 롤링 버퍼 (RAM 디스크)
│   │
│   ├── director/                   # 모듈: AI 카메라 스위칭
│   │   ├── __init__.py
│   │   ├── camera_selector.py      # 2캠 스위칭 로직
│   │   ├── transition_engine.py    # 전환 효과 (크로스페이드/컷/PIP)
│   │   ├── scene_analyzer.py       # 장면 분석 (활동 점수 집계)
│   │   └── rules_engine.py         # 전환 규칙 (최소 유지, 우선순위)
│   │
│   ├── blur/                       # 모듈: 사냥 블러
│   │   ├── __init__.py
│   │   ├── hunt_detector.py        # YOLOv8 먹잇감 감지
│   │   ├── prey_segmenter.py       # 먹잇감 영역 세그멘테이션
│   │   └── blur_processor.py       # 가우시안 블러 적용
│   │
│   ├── obs/                        # 모듈: OBS 제어
│   │   ├── __init__.py
│   │   ├── obs_controller.py       # OBS WebSocket 5.x 제어
│   │   ├── scene_manager.py        # 장면/소스 관리
│   │   └── overlay_manager.py      # 오버레이 (이름표, 시계)
│   │
│   ├── clipper/                    # 모듈: 하이라이트 클리퍼
│   │   ├── __init__.py
│   │   ├── event_detector.py       # 이벤트 감지 (규칙 엔진)
│   │   ├── clip_extractor.py       # 롤링 버퍼 → 클립 추출
│   │   ├── clip_scorer.py          # 클립 품질 점수 계산
│   │   └── daily_selector.py       # 일일 TOP 10 선별
│   │
│   ├── producer/                   # 모듈: 숏폼 프로듀서
│   │   ├── __init__.py
│   │   ├── vertical_converter.py   # 16:9 → 9:16 스마트 크롭
│   │   ├── template_applier.py     # 인트로/아웃로/오버레이 적용
│   │   ├── bgm_mixer.py            # BGM 선택 & 믹싱
│   │   ├── speed_adjuster.py       # 슬로우모션/타임랩스
│   │   └── subtitle_generator.py   # 자막 생성
│   │
│   ├── thumbnail/                  # 모듈: 썸네일 생성
│   │   ├── __init__.py
│   │   ├── frame_selector.py       # 최적 프레임 선택
│   │   ├── text_overlay.py         # 텍스트 + 로고 오버레이
│   │   └── template_renderer.py    # 썸네일 템플릿 A/B/C 렌더
│   │
│   ├── titler/                     # 모듈: 타이틀/설명 생성
│   │   ├── __init__.py
│   │   ├── title_generator.py      # Claude API → 타이틀 후보 생성
│   │   ├── description_generator.py # Claude API → 설명 생성
│   │   ├── hashtag_generator.py    # 해시태그 자동 생성
│   │   └── seo_optimizer.py        # SEO 키워드 최적화
│   │
│   ├── uploader/                   # 모듈: 멀티플랫폼 업로더
│   │   ├── __init__.py
│   │   ├── youtube_uploader.py     # YouTube Data API v3 업로드
│   │   ├── tiktok_uploader.py      # TikTok Content Posting API
│   │   └── upload_tracker.py       # 업로드 결과 추적 & 로그
│   │
│   ├── scheduler/                  # 모듈: 업로드 스케줄러
│   │   ├── __init__.py
│   │   ├── upload_scheduler.py     # 최적 시간대 배포 스케줄러
│   │   └── queue.json              # 업로드 대기 큐
│   │
│   ├── web/                        # 대시보드
│   │   ├── __init__.py
│   │   ├── dashboard.py            # FastAPI 대시보드 서버
│   │   ├── api.py                  # REST API (상태 조회/수동 제어)
│   │   └── templates/
│   │       └── dashboard.html      # 2분할 모니터링 + 컨트롤
│   │
│   └── utils/                      # 유틸리티
│       ├── __init__.py
│       ├── logger.py               # 로깅 (활동, 에러, 이벤트)
│       ├── health_check.py         # iPhone/OBS 상태 체크
│       └── cat_identifier.py       # 나나/토토 개체 식별 (Cat-ID)
│
├── templates/                      # 영상 템플릿
│   ├── intro/
│   │   ├── default.mp4
│   │   ├── morning.mp4
│   │   └── night.mp4
│   ├── outro/
│   │   ├── subscribe.mp4
│   │   ├── follow_tiktok.mp4
│   │   └── next_video.mp4
│   ├── overlays/
│   │   ├── event_text.yaml
│   │   ├── cat_name.yaml
│   │   ├── watermark.yaml
│   │   └── logo_80x80.png
│   ├── thumbnails/
│   │   ├── template_a_bold.json
│   │   ├── template_b_minimal.json
│   │   └── template_c_frame.json
│   └── transitions/
│       └── config.yaml
│
├── bgm/                            # BGM 템플릿
│   ├── active/                     # 활동적 (5~10곡)
│   ├── healing/                    # 힐링 (5~10곡)
│   ├── comic/                      # 코믹 (5~10곡)
│   ├── tension/                    # 긴장 (5~10곡)
│   └── config.yaml                 # 이벤트→무드 매핑 규칙
│
├── config/                         # 설정
│   ├── prompts/                    # LLM 프롬프트 템플릿
│   │   ├── title_youtube.md
│   │   ├── title_tiktok.md
│   │   └── description.md
│   └── credentials/                # API 키 (⚠️ .gitignore)
│       ├── youtube_oauth.json
│       ├── youtube_token.json
│       └── tiktok_oauth.json
│
├── clips/                          # 하이라이트 클립 저장
│   └── {YYYY-MM-DD}/
│       ├── {event_id}.mp4
│       ├── {event_id}.json
│       └── daily_top10.json
│
├── output/                         # 완성 영상 저장
│   ├── shorts/
│   │   └── {YYYY-MM-DD}/
│   └── tiktok/
│       └── {YYYY-MM-DD}/
│
├── thumbnails/                     # 생성된 썸네일
│   └── {event_id}_{platform}.jpg
│
├── uploads/                        # 업로드 결과
│   ├── {YYYY-MM-DD}/
│   │   └── {event_id}_result.json
│   └── upload_history.jsonl
│
├── models/                         # ML 모델
│   ├── yolov8n.pt                  # YOLOv8-nano (고양이/먹잇감)
│   ├── cat_id_nana_toto.pt         # 나나/토토 개체 식별
│   └── hunt_detector.pt            # 사냥 감지 (PyTorch, 크로스 플랫폼)
│
├── tests/
│   ├── test_camera_selector.py
│   ├── test_event_detector.py
│   ├── test_clip_scorer.py
│   ├── test_vertical_converter.py
│   ├── test_thumbnail_generator.py
│   ├── test_title_generator.py
│   ├── test_youtube_uploader.py
│   └── test_tiktok_uploader.py
│
├── requirements.txt                # Python 의존성
├── .env                            # 환경변수 (⚠️ .gitignore)
├── .env.example                    # 환경변수 예시
└── .gitignore
```

### `requirements.txt`

```
# Core
asyncio-extras>=1.3
fastapi>=0.109
uvicorn>=0.27
websockets>=12.0
pyyaml>=6.0

# Video Processing
opencv-python>=4.9
Pillow>=10.0
moviepy>=2.0

# AI/ML
ultralytics>=8.1           # YOLOv8
torch>=2.1                 # PyTorch (CPU)

# NDI
ndi-python>=5.5

# OBS
obsws-python>=1.7

# YouTube API
google-api-python-client>=2.100
google-auth-oauthlib>=1.2

# LLM
anthropic>=0.40

# Scheduling
apscheduler>=3.10

# HTTP
requests>=2.31
httpx>=0.26

# Utils
python-dotenv>=1.0
diskcache>=5.6
loguru>=0.7
```

### `.env.example`

```bash
# YouTube API
YOUTUBE_CLIENT_ID=your_client_id
YOUTUBE_CLIENT_SECRET=your_client_secret

# TikTok API
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret

# Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# OBS WebSocket
OBS_WS_URL=ws://localhost:4455
OBS_WS_PASSWORD=your_obs_password

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
DEBUG=false

# Paths
CLIPS_DIR=./clips
OUTPUT_DIR=./output
THUMBNAILS_DIR=./thumbnails
MODELS_DIR=./models
```

---

## 11. 개발 로드맵 (2캠 체제 기준)

### Phase 0: 서버 기본 골격 (3/7 이전)

> **목표**: DockKit 도착 전에 서버 인프라와 ffmpeg 파이프라인 완성

| 작업 | 산출물 | 의존성 |
|:-----|:-------|:-------|
| Python 프로젝트 초기화 | `server/main.py`, `requirements.txt` | 없음 |
| config 시스템 구축 | `config.yaml`, `.env` 로드 | 없음 |
| ffmpeg 파이프라인 테스트 | 영상 크롭/합성/BGM 믹싱 검증 | ffmpeg 설치 |
| OBS WebSocket 연동 테스트 | OBS 장면 전환 자동화 확인 | OBS 설치 |
| 롤링 버퍼 프로토타입 | RAM 디스크 세그먼트 저장 검증 | 없음 |
| 영상 템플릿 초안 제작 | 인트로/아웃로 MP4 | 없음 |
| BGM 수집 (로열티프리) | bgm/ 카테고리별 5곡씩 | 없음 |

### Phase 1: iPhone 앱 + 라이브 스트리밍 (3/7~)

> **목표**: 2캠 라이브 스트리밍 MVP 완성

| 작업 | 산출물 | 의존성 |
|:-----|:-------|:-------|
| LiveCatCam iOS 앱 MVP | 추적 + NDI 전송 | DockKit 스탠드 도착 |
| iPhone → PC NDI 수신 확인 | 2채널 안정 수신 | iOS 앱 |
| 활동 점수 전송 (WebSocket) | 메타데이터 10Hz | iOS 앱 |
| AI 카메라 스위칭 (2캠) | `camera_selector.py` | NDI 수신 |
| OBS 장면 자동 전환 | MainView / PIP / Sleeping | 카메라 스위칭 |
| YouTube RTMP 라이브 테스트 | 실시간 스트리밍 확인 | OBS 설정 |
| 사냥 블러 기본 구현 | YOLOv8 감지 + 블러 | 없음 |
| 나나/토토 개체 식별 (Cat-ID) | `cat_identifier.py` | 촬영 데이터 |

### Phase 2: 하이라이트 클리퍼 + 숏폼 프로듀서

> **목표**: 자동 클립 추출 → 숏폼 영상 완성까지

| 작업 | 산출물 | 의존성 |
|:-----|:-------|:-------|
| 이벤트 감지 엔진 | `event_detector.py` | 메타데이터 수신 |
| 롤링 버퍼 → 클립 추출 | `clip_extractor.py` | 롤링 버퍼 |
| 클립 스코어링 | `clip_scorer.py` | 클립 추출 |
| 일일 TOP 10 선별 | `daily_selector.py` | 스코어링 |
| 세로 변환 (스마트 크롭) | `vertical_converter.py` | YOLOv8 |
| 영상 템플릿 적용 | `template_applier.py` | 템플릿 파일 |
| BGM 자동 선택 & 믹싱 | `bgm_mixer.py` | BGM 파일 |
| 속도 조절 | `speed_adjuster.py` | 없음 |
| 자막 생성 | `subtitle_generator.py` | 이벤트 메타 |

### Phase 3: 썸네일 + 타이틀 + 업로더

> **목표**: 콘텐츠 자동 생성 → 자동 업로드 완성

| 작업 | 산출물 | 의존성 |
|:-----|:-------|:-------|
| 프레임 선택 알고리즘 | `frame_selector.py` | 클립 파일 |
| 썸네일 텍스트 오버레이 | `text_overlay.py` | Pillow |
| 썸네일 템플릿 3종 | A/B/C 렌더러 | 없음 |
| Claude API 연동 | `title_generator.py` | API 키 |
| 타이틀/설명 자동 생성 | 프롬프트 + 파싱 | Claude 연동 |
| 해시태그 생성 | `hashtag_generator.py` | 없음 |
| YouTube Shorts 업로드 | `youtube_uploader.py` | OAuth 인증 |
| 업로드 스케줄러 | `upload_scheduler.py` | 업로더 |

### Phase 4: TikTok + 템플릿 고도화 + 안정화

> **목표**: TikTok 자동화 + 전체 시스템 안정화

| 작업 | 산출물 | 의존성 |
|:-----|:-------|:-------|
| TikTok API 연동 | `tiktok_uploader.py` | TikTok 개발자 계정 |
| TikTok 업로드 자동화 | 스케줄러 통합 | 업로더 |
| 썸네일 A/B 테스트 시스템 | 성과 추적 | 업로드 이력 |
| 웹 대시보드 구축 | `dashboard.py` | FastAPI |
| 자동 복구 (앱 크래시, 네트워크) | health_check + restart | 전체 시스템 |
| 24/7 내구성 테스트 | 72시간 무중단 검증 | 전체 시스템 |
| 모니터링 알림 (Telegram) | 오류 알림 | 없음 |
| 성능 최적화 (CPU/메모리) | 프로파일링 + 튜닝 | 전체 시스템 |

### 마일스톤 타임라인

```
     3/7 이전          3/7~           3월 중순~        4월~           4월 중순~
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Phase 0  │  │ Phase 1  │  │ Phase 2  │  │ Phase 3  │  │ Phase 4  │
    │          │  │          │  │          │  │          │  │          │
    │ 서버골격 │→ │ 라이브   │→ │ 클리퍼   │→ │ 썸네일   │→ │ TikTok   │
    │ ffmpeg   │  │ 2캠MVP   │  │ 숏폼     │  │ 타이틀   │  │ 안정화   │
    │ 템플릿   │  │ 스트리밍 │  │ 프로듀서 │  │ 업로더   │  │ 대시보드 │
    └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
    DockKit 도착 전  DockKit 도착   자동클립 시작  자동업로드 시작  풀 자동화
```

---

## 부록 A: 6대 자동화 요구사항 → 모듈 매핑 검증

| # | 요구사항 | 담당 모듈 | 섹션 | 상태 |
|:-:|:---------|:---------|:----:|:----:|
| 1 | 카메라 → 자동 편집 → 라이브 스트리밍 | 라이브 스트리밍 엔진 | §3 | ✅ |
| 2 | 하이라이트 → YouTube Shorts 자동 제작/업로드 | 클리퍼 + 프로듀서 + 업로더 | §4, §5, §8 | ✅ |
| 3 | 썸네일 자동 생성 (AI 프레임 + 텍스트) | 썸네일 생성기 | §6 | ✅ |
| 4 | 타이틀/설명 자동 생성 (LLM) | 콘텐츠 매니저 (Claude) | §7 | ✅ |
| 5 | 영상 템플릿 + BGM 템플릿 | 프로듀서 + 템플릿/BGM | §5, §9 | ✅ |
| 6 | TikTok 영상 자동 제작 & 업로드 | 프로듀서 + 업로더 | §5, §8 | ✅ |

---

## 부록 B: 외부 API 요약

| API | 용도 | 인증 | 비용 |
|:----|:-----|:-----|:-----|
| YouTube Data API v3 | Shorts 업로드 | OAuth 2.0 | 무료 (일일 할당량 10,000 units) |
| TikTok Content Posting API | TikTok 업로드 | OAuth 2.0 | 무료 |
| Anthropic Claude API | 타이틀/설명 생성 | API Key | ~$0.001/요청 (Haiku) |
| NDI SDK | 영상 전송 | 라이선스 | 무료 (NDI Tools) |

## 부록 C: 주요 설정값 요약

```yaml
# 핵심 파라미터 (config.yaml에 통합)

camera:
  count: 2
  resolution: "1080p"
  fps: 30
  protocol: "ndi"

switching:
  min_hold_sec: 8
  score_threshold_multiplier: 1.5
  tracking_lost_timeout_sec: 3

clip:
  pre_event_sec: 5
  post_event_sec: 15
  total_duration_sec: 20
  rolling_buffer_sec: 60
  daily_top_n: 10

shortform:
  output_resolution: [1080, 1920]
  intro_duration_sec: 1.5
  outro_duration_sec: 2.0
  bgm_volume: 0.15

thumbnail:
  youtube_size: [1280, 720]
  tiktok_size: [1080, 1920]
  quality: 95

upload:
  youtube_shorts_per_day: 3
  tiktok_per_day: 3
  optimal_hours_kst: [18, 19, 20, 21, 22]
  min_interval_hours: 2

llm:
  model: "claude-haiku-4-5-20251001"
  max_tokens: 500
  title_candidates: 5
```
