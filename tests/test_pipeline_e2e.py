"""
LiveCat End-to-End Pipeline Test
================================

서버 파이프라인을 단계별로 검증하는 테스트 스크립트.

사용법:
  1. 영상 파일로 테스트:
     python tests/test_pipeline_e2e.py --input test_video.mp4

  2. NDI 소스로 테스트:
     python tests/test_pipeline_e2e.py --ndi "IPHONE1 (LiveCatCam)"

  3. SRT 소스로 테스트 (Larix Broadcaster):
     python tests/test_pipeline_e2e.py --srt 9000

  4. RTSP 소스로 테스트:
     python tests/test_pipeline_e2e.py --rtsp rtsp://192.168.1.10:8554/live

  4. 웹캠으로 테스트:
     python tests/test_pipeline_e2e.py --webcam 0

각 단계별 성공/실패를 리포트하고, 생성된 산출물을 확인할 수 있다.
"""

import argparse
import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows UTF-8
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import yaml


# ─── 유틸리티 ──────────────────────────────────────────────

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def ok(msg: str):
    print(f"  {Colors.GREEN}[OK]{Colors.END} {msg}")


def fail(msg: str):
    print(f"  {Colors.RED}[FAIL]{Colors.END} {msg}")


def info(msg: str):
    print(f"  {Colors.CYAN}[INFO]{Colors.END} {msg}")


def warn(msg: str):
    print(f"  {Colors.YELLOW}[WARN]{Colors.END} {msg}")


def section(title: str):
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{Colors.END}")


def check_command(cmd: str) -> bool:
    """명령어 존재 여부 체크."""
    return shutil.which(cmd) is not None


# ─── Step 0: 환경 체크 ────────────────────────────────────

def check_environment():
    section("Step 0: 환경 체크")
    all_ok = True

    # Python 버전
    v = sys.version_info
    if v.major == 3 and v.minor >= 11:
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        warn(f"Python {v.major}.{v.minor} (3.11+ 권장)")

    # ffmpeg
    if check_command("ffmpeg"):
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True
        )
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        ok(f"ffmpeg: {version_line[:60]}")
    else:
        fail("ffmpeg not found! 설치 필요: https://ffmpeg.org")
        all_ok = False

    # ffprobe
    if check_command("ffprobe"):
        ok("ffprobe: available")
    else:
        fail("ffprobe not found!")
        all_ok = False

    # Python 패키지
    packages = {
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "yaml": "pyyaml",
        "numpy": "numpy",
    }
    optional_packages = {
        "ultralytics": "ultralytics (YOLOv8)",
        "anthropic": "anthropic (Claude API)",
        "obsws": "obsws-python (OBS WebSocket)",
        "NDIlib": "ndi-python (NDI)",
    }

    for module, name in packages.items():
        try:
            __import__(module)
            ok(f"{name}")
        except ImportError:
            fail(f"{name} -pip install {name}")
            all_ok = False

    for module, name in optional_packages.items():
        try:
            __import__(module)
            ok(f"{name}")
        except ImportError:
            warn(f"{name} (선택사항, 일부 기능 제한)")

    # config.yaml
    config_path = ROOT_DIR / "server" / "config.yaml"
    if config_path.exists():
        ok(f"config.yaml: {config_path}")
    else:
        fail(f"config.yaml not found: {config_path}")
        all_ok = False

    return all_ok


# ─── Step 1: 영상 소스 수신 테스트 ──────────────────────

def test_video_source(args) -> Path | None:
    section("Step 1: 영상 소스 수신 테스트")

    test_clip_path = ROOT_DIR / "tests" / "_test_clip.mp4"

    if args.input:
        # 파일 입력
        src = Path(args.input)
        if not src.exists():
            fail(f"파일 없음: {src}")
            return None
        ok(f"입력 파일: {src}")

        # 20초 클립 추출 (테스트용)
        info("20초 테스트 클립 추출 중...")
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-t", "20", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-movflags", "+faststart",
            str(test_clip_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and test_clip_path.exists():
            ok(f"테스트 클립 생성: {test_clip_path}")
            return test_clip_path
        else:
            fail(f"클립 추출 실패: {result.stderr[:200]}")
            return None

    elif args.srt is not None:
        # SRT 소스 (Larix Broadcaster)
        port = args.srt
        info(f"SRT 수신 중: port={port} (20초 녹화)")
        info("iPhone Larix Broadcaster가 방송 중이어야 합니다")
        cmd = [
            "ffmpeg", "-y",
            "-i", f"srt://0.0.0.0:{port}?mode=listener&timeout=30000000",
            "-t", "20", "-c", "copy",
            str(test_clip_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if result.returncode == 0 and test_clip_path.exists():
            size_kb = test_clip_path.stat().st_size / 1024
            ok(f"SRT 클립 녹화 완료: {test_clip_path} ({size_kb:.0f}KB)")
            return test_clip_path
        else:
            fail(f"SRT 녹화 실패: {result.stderr[:200]}")
            return None

    elif args.rtsp:
        # RTSP 소스
        url = args.rtsp
        info(f"RTSP 수신 중: {url}")
        info("20초 녹화 후 테스트 진행...")
        cmd = [
            "ffmpeg", "-y", "-rtsp_transport", "tcp",
            "-i", url, "-t", "20",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", str(test_clip_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and test_clip_path.exists():
            ok(f"RTSP 클립 녹화 완료: {test_clip_path}")
            return test_clip_path
        else:
            fail(f"RTSP 녹화 실패: {result.stderr[:200]}")
            return None

    elif args.ndi:
        # NDI 소스
        source_name = args.ndi
        info(f"NDI 소스 탐색 중: {source_name}")
        try:
            import NDIlib as ndi

            if not ndi.initialize():
                fail("NDI 초기화 실패")
                return None

            finder = ndi.find_create_v2()
            if not finder:
                fail("NDI finder 생성 실패")
                return None

            info("NDI 소스 탐색 중 (5초)...")
            ndi.find_wait_for_sources(finder, 5000)
            sources = ndi.find_get_current_sources(finder)

            if sources:
                ok(f"발견된 NDI 소스: {[s.ndi_name for s in sources]}")
            else:
                fail("NDI 소스를 찾을 수 없습니다. iPhone에서 NDI 앱을 실행하세요.")
                ndi.find_destroy(finder)
                ndi.destroy()
                return None

            # ffmpeg으로 NDI 녹화
            info("NDI → ffmpeg 20초 녹화 중...")
            cmd = [
                "ffmpeg", "-y", "-f", "libndi_newtek",
                "-i", source_name, "-t", "20",
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", str(test_clip_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            ndi.find_destroy(finder)
            ndi.destroy()

            if result.returncode == 0 and test_clip_path.exists():
                ok(f"NDI 클립 녹화 완료: {test_clip_path}")
                return test_clip_path
            else:
                fail(f"NDI 녹화 실패: {result.stderr[:200]}")
                return None

        except ImportError:
            fail("ndi-python 미설치 -pip install ndi-python")
            return None

    elif args.webcam is not None:
        # 웹캠
        cam_id = args.webcam
        info(f"웹캠 {cam_id}에서 20초 녹화 중...")

        import cv2
        cap = cv2.VideoCapture(cam_id)
        if not cap.isOpened():
            fail(f"웹캠 {cam_id} 열기 실패")
            return None

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        ok(f"웹캠 열림: {width}x{height} @ {fps}fps")

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(test_clip_path), fourcc, fps, (width, height))

        start = time.time()
        frame_count = 0
        while time.time() - start < 20:
            ret, frame = cap.read()
            if not ret:
                break
            writer.write(frame)
            frame_count += 1

        cap.release()
        writer.release()

        if frame_count > 0:
            ok(f"웹캠 녹화 완료: {frame_count} frames → {test_clip_path}")
            return test_clip_path
        else:
            fail("웹캠 프레임 수신 실패")
            return None

    else:
        # 테스트용 더미 영상 생성
        warn("입력 소스 미지정 -테스트용 더미 영상 생성")
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            "testsrc=duration=20:size=1920x1080:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest",
            str(test_clip_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            ok(f"더미 영상 생성: {test_clip_path}")
            return test_clip_path
        else:
            fail(f"더미 영상 생성 실패: {result.stderr[:200]}")
            return None


# ─── Step 2: 영상 분석 (ffprobe) ────────────────────────

def test_video_info(clip_path: Path) -> dict:
    section("Step 2: 영상 정보 분석")

    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(clip_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        fail("ffprobe 실패")
        return {}

    probe = json.loads(result.stdout)

    # 비디오 스트림 정보
    video = next((s for s in probe.get("streams", []) if s["codec_type"] == "video"), None)
    audio = next((s for s in probe.get("streams", []) if s["codec_type"] == "audio"), None)

    info_dict = {}
    if video:
        info_dict["width"] = int(video.get("width", 0))
        info_dict["height"] = int(video.get("height", 0))
        info_dict["codec"] = video.get("codec_name", "unknown")
        info_dict["fps"] = eval(video.get("r_frame_rate", "30/1"))
        info_dict["duration"] = float(probe.get("format", {}).get("duration", 0))

        ok(f"해상도: {info_dict['width']}x{info_dict['height']}")
        ok(f"코덱: {info_dict['codec']}")
        ok(f"FPS: {info_dict['fps']:.1f}")
        ok(f"길이: {info_dict['duration']:.1f}초")
    else:
        fail("비디오 스트림 없음")

    if audio:
        ok(f"오디오: {audio.get('codec_name', 'N/A')} {audio.get('sample_rate', 'N/A')}Hz")
    else:
        warn("오디오 스트림 없음")

    return info_dict


# ─── Step 3: 이벤트 감지 시뮬레이션 ──────────────────────

def test_event_detection(clip_path: Path) -> dict:
    section("Step 3: 이벤트 감지 (시뮬레이션)")

    # 실제 YOLOv8로 고양이 감지 시도
    cat_detected = False
    cat_bbox = None

    try:
        from ultralytics import YOLO
        import cv2

        info("YOLOv8n으로 고양이 감지 중...")
        model = YOLO("yolov8n.pt")

        cap = cv2.VideoCapture(str(clip_path))
        frame_count = 0
        cat_frames = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frame_count += 1
            if frame_count % 30 != 0:  # 매 30프레임(1초)마다 체크
                continue

            results = model(frame, verbose=False)
            for r in results:
                for box in r.boxes:
                    cls = int(box.cls[0])
                    if cls == 15:  # cat
                        cat_detected = True
                        cat_frames += 1
                        cat_bbox = box.xyxy[0].tolist()

        cap.release()
        total_sec = frame_count / 30

        if cat_detected:
            ok(f"고양이 감지! {cat_frames}회 / {total_sec:.0f}초")
            ok(f"마지막 bbox: {[f'{x:.0f}' for x in cat_bbox]}")
        else:
            warn(f"고양이 미감지 ({total_sec:.0f}초 영상)")
            info("테스트용 이벤트를 시뮬레이션합니다")

    except ImportError:
        warn("ultralytics 미설치 -YOLOv8 감지 건너뜀")
        info("테스트용 이벤트를 시뮬레이션합니다")
    except Exception as e:
        warn(f"YOLOv8 오류: {e}")

    # 시뮬레이션 이벤트 생성
    event = {
        "event_id": datetime.now().strftime("%H%M%S000_climb"),
        "event_type": "climb",
        "camera_id": "CAM-1",
        "cats": ["nana"],
        "score": 80,
        "timestamp": datetime.now().isoformat(),
        "duration_sec": 20,
        "cat_detected_by_yolo": cat_detected,
    }

    ok(f"이벤트 생성: {event['event_type']} (score={event['score']})")
    return event


# ─── Step 4: 세로 변환 (16:9 → 9:16) ────────────────────

async def test_vertical_conversion(clip_path: Path, event: dict) -> Path | None:
    section("Step 4: 세로 변환 (16:9 → 9:16)")

    output_path = clip_path.with_name(clip_path.stem + "_vertical.mp4")

    # 고양이 중심 크롭 (또는 중앙 크롭)
    try:
        import cv2

        cap = cv2.VideoCapture(str(clip_path))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # 9:16 비율 크롭 계산
        crop_w = int(height * 9 / 16)  # 608 for 1080p
        crop_x = (width - crop_w) // 2  # 중앙 크롭

        info(f"원본: {width}x{height} → 크롭: {crop_w}x{height} @ x={crop_x}")

        cmd = [
            "ffmpeg", "-y", "-i", str(clip_path),
            "-vf", f"crop={crop_w}:{height}:{crop_x}:0,scale=1080:1920:flags=lanczos",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            ok(f"세로 변환 완료: {output_path.name} ({size_mb:.1f}MB)")
            return output_path
        else:
            fail(f"세로 변환 실패: {result.stderr[:200]}")
            return None

    except Exception as e:
        fail(f"세로 변환 오류: {e}")
        return None


# ─── Step 5: BGM 믹싱 ──────────────────────────────────

async def test_bgm_mixing(clip_path: Path, event: dict) -> Path | None:
    section("Step 5: BGM 믹싱")

    bgm_dir = ROOT_DIR / "bgm"

    # BGM 카테고리 매핑
    mood_map = {"climb": "active", "jump": "active", "run": "active",
                "interact": "comic", "hunt_attempt": "tension", "sleep": "healing"}
    mood = mood_map.get(event.get("event_type", ""), "active")
    mood_dir = bgm_dir / mood

    # BGM 파일 찾기
    bgm_files = list(mood_dir.glob("*.mp3")) + list(mood_dir.glob("*.wav"))

    if not bgm_files:
        warn(f"BGM 파일 없음: {mood_dir}")
        info("BGM 테스트를 위해 테스트 톤 생성 중...")

        # 테스트용 BGM 생성
        test_bgm = mood_dir / "test_bgm.mp3"
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=30",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(test_bgm),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            bgm_files = [test_bgm]
            ok(f"테스트 BGM 생성: {test_bgm}")
        else:
            fail("BGM 생성 실패")
            return clip_path

    bgm_file = bgm_files[0]
    output_path = clip_path.with_name(clip_path.stem + "_bgm.mp4")

    info(f"BGM: {bgm_file.name} (mood: {mood})")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-i", str(bgm_file),
        "-filter_complex",
        "[1:a]volume=0.15,afade=t=in:d=1.0,afade=t=out:st=18:d=1.5[bgm];"
        "[0:a]volume=0.85[orig];"
        "[orig][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0 and output_path.exists():
        ok(f"BGM 믹싱 완료: {output_path.name}")
        return output_path
    else:
        # 오디오 없는 영상일 경우 다른 방식
        warn(f"BGM 믹싱 실패 (원본에 오디오 없을 수 있음), 오디오 추가 시도...")
        cmd2 = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-i", str(bgm_file),
            "-filter_complex",
            "[1:a]volume=0.15,afade=t=in:d=1.0,afade=t=out:st=18:d=1.5[bgm]",
            "-map", "0:v", "-map", "[bgm]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(output_path),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if result2.returncode == 0 and output_path.exists():
            ok(f"BGM 추가 완료 (원본 무음): {output_path.name}")
            return output_path
        else:
            fail("BGM 믹싱 최종 실패")
            return clip_path


# ─── Step 6: 텍스트 오버레이 (자막 + 이벤트 텍스트) ─────

async def test_overlay(clip_path: Path, event: dict) -> Path | None:
    section("Step 6: 텍스트 오버레이")

    output_path = clip_path.with_name(clip_path.stem + "_overlay.mp4")

    cat_name = "나나" if "nana" in event.get("cats", []) else "토토"
    event_text = {
        "climb": "나무 등반 도전!",
        "jump": "대단한 점프!",
        "run": "전력 질주!",
        "interact": "나나 & 토토!",
        "hunt_attempt": "사냥 본능!",
    }.get(event.get("event_type", ""), "고양이 일상")

    info(f"이벤트 텍스트: {event_text}")
    info(f"고양이 이름: {cat_name}")

    # ffmpeg drawtext (한글 폰트 시도)
    font_candidates = [
        "NanumSquareRoundEB.ttf",
        "NanumGothicBold.ttf",
        "malgunbd.ttf",       # Windows 맑은 고딕 Bold
        "malgun.ttf",         # Windows 맑은 고딕
        "arial.ttf",          # 폴백
    ]

    font_path = None
    font_dirs = [
        Path("C:/Windows/Fonts"),
        Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    ]
    for fdir in font_dirs:
        for fname in font_candidates:
            p = fdir / fname
            if p.exists():
                font_path = str(p).replace("\\", "/").replace(":", "\\\\:")
                break
        if font_path:
            break

    if not font_path:
        warn("한글 폰트 미발견, 기본 폰트 사용")
        font_option = ""
    else:
        ok(f"폰트: {font_path}")
        font_option = f":fontfile='{font_path}'"

    # drawtext 필터 (이벤트 텍스트 + 고양이 이름)
    drawtext_event = (
        f"drawtext=text='{event_text}'"
        f"{font_option}"
        f":fontsize=48:fontcolor=white:borderw=3:bordercolor=black"
        f":x=(w-text_w)/2:y=80"
        f":enable='between(t,0.5,5)'"
    )
    drawtext_cat = (
        f"drawtext=text='{cat_name}'"
        f"{font_option}"
        f":fontsize=36:fontcolor=white"
        f":borderw=2:bordercolor=black"
        f":x=40:y=h-120"
    )
    drawtext_watermark = (
        f"drawtext=text='LiveCat'"
        f":fontsize=24:fontcolor=white@0.7"
        f":x=w-text_w-20:y=h-50"
    )

    vf = f"{drawtext_event},{drawtext_cat},{drawtext_watermark}"

    cmd = [
        "ffmpeg", "-y", "-i", str(clip_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0 and output_path.exists():
        ok(f"오버레이 적용 완료: {output_path.name}")
        return output_path
    else:
        warn(f"한글 오버레이 실패, 영어 폴백 시도...")
        # 영어 폴백
        vf_en = (
            f"drawtext=text='Tree Climbing!'"
            f":fontsize=48:fontcolor=white:borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=80:enable='between(t,0.5,5)',"
            f"drawtext=text='Nana'"
            f":fontsize=36:fontcolor=white:borderw=2:bordercolor=black"
            f":x=40:y=h-120,"
            f"drawtext=text='LiveCat'"
            f":fontsize=24:fontcolor=white@0.7:x=w-text_w-20:y=h-50"
        )
        cmd2 = [
            "ffmpeg", "-y", "-i", str(clip_path),
            "-vf", vf_en,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy", str(output_path),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if result2.returncode == 0:
            ok(f"영어 오버레이 폴백 완료: {output_path.name}")
            return output_path
        else:
            fail("오버레이 실패")
            return clip_path


# ─── Step 7: 썸네일 생성 ────────────────────────────────

def test_thumbnail(clip_path: Path, event: dict) -> Path | None:
    section("Step 7: 썸네일 생성")

    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        # 최적 프레임 선택 (선명도 기반)
        cap = cv2.VideoCapture(str(clip_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        best_frame = None
        best_clarity = 0
        best_idx = 0

        for i in range(0, total_frames, 10):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            clarity = cv2.Laplacian(gray, cv2.CV_64F).var()
            if clarity > best_clarity:
                best_clarity = clarity
                best_frame = frame
                best_idx = i

        cap.release()

        if best_frame is None:
            fail("프레임 추출 실패")
            return None

        ok(f"최적 프레임: #{best_idx} (선명도: {best_clarity:.1f})")

        # BGR → RGB → PIL
        rgb = cv2.cvtColor(best_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)

        # YouTube 썸네일 사이즈 (1280x720)
        img = img.resize((1280, 720), Image.Resampling.LANCZOS)

        # 배경 약간 어둡게
        darkened = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.2)

        draw = ImageDraw.Draw(darkened)

        # 폰트 로드
        font_large = None
        font_small = None
        font_paths = [
            "C:/Windows/Fonts/malgunbd.ttf",
            "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for fp in font_paths:
            if Path(fp).exists():
                try:
                    font_large = ImageFont.truetype(fp, 72)
                    font_small = ImageFont.truetype(fp, 36)
                    break
                except Exception:
                    continue

        if font_large is None:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
            warn("시스템 폰트 사용 (크기 제한)")

        # 이벤트 텍스트 (중앙)
        event_text = {
            "climb": "나무 등반!",
            "jump": "점프!",
            "run": "전력 질주!",
            "interact": "나나 vs 토토!",
            "hunt_attempt": "사냥 본능!",
        }.get(event.get("event_type", ""), "고양이 일상")

        # 텍스트 중앙 배치 (외곽선 효과)
        bbox = draw.textbbox((0, 0), event_text, font=font_large)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (1280 - tw) // 2
        ty = (720 - th) // 2 - 30

        # 외곽선 (검정)
        for dx in [-3, -2, 0, 2, 3]:
            for dy in [-3, -2, 0, 2, 3]:
                draw.text((tx + dx, ty + dy), event_text, fill="black", font=font_large)
        # 본문 (흰색)
        draw.text((tx, ty), event_text, fill="white", font=font_large)

        # 고양이 이름 (하단 좌측)
        cat_name = "나나 (Nana)" if "nana" in event.get("cats", []) else "토토 (Toto)"
        draw.text((40, 660), f"🐱 {cat_name}", fill="white", font=font_small)

        # 워터마크 (하단 우측)
        draw.text((1140, 680), "LiveCat", fill=(255, 255, 255, 180), font=font_small)

        # 저장
        thumb_dir = ROOT_DIR / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)
        thumb_path = thumb_dir / f"{event.get('event_id', 'test')}_yt.jpg"
        darkened.save(str(thumb_path), "JPEG", quality=95)

        size_kb = thumb_path.stat().st_size / 1024
        ok(f"썸네일 생성: {thumb_path.name} ({size_kb:.0f}KB)")
        return thumb_path

    except Exception as e:
        fail(f"썸네일 생성 오류: {e}")
        return None


# ─── Step 8: 타이틀/설명 생성 ────────────────────────────

async def test_title_generation(event: dict) -> dict:
    section("Step 8: 타이틀/설명 생성")

    content = {}

    # Claude API 시도
    try:
        import anthropic
        import os

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            warn("ANTHROPIC_API_KEY 미설정 -템플릿 폴백 사용")
            raise ValueError("No API key")

        client = anthropic.Anthropic(api_key=api_key)
        info("Claude Haiku로 타이틀 생성 중...")

        prompt = f"""당신은 고양이 유튜브 채널 타이틀 전문가입니다.
채널: LiveCat (고양이 나나 & 토토)
이벤트: {event.get('event_type', 'climb')}
고양이: {', '.join(event.get('cats', ['nana']))}

타이틀 5개를 한 줄에 하나씩 작성하세요. 최대 70자, 이모지 1-2개, 한국어."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        titles = [
            line.strip()
            for line in response.content[0].text.strip().split("\n")
            if line.strip() and len(line.strip()) > 5
        ][:5]

        content["titles"] = titles
        for i, t in enumerate(titles, 1):
            ok(f"타이틀 {i}: {t}")

    except Exception as e:
        warn(f"Claude API 사용 불가: {e}")
        info("템플릿 기반 폴백 타이틀 생성")

        cat = "나나" if "nana" in event.get("cats", []) else "토토"
        templates = {
            "climb": [
                f"🌲 {cat}의 나무 등반 도전! 과연 성공할까?",
                f"마당 고양이 {cat}, 오늘도 나무 위로! 🐱",
                f"{cat}의 놀라운 등반 실력 🌲✨",
            ],
            "jump": [f"🦘 {cat}의 놀라운 점프력!", f"뛰어! {cat}의 대점프 🐱"],
            "run": [f"🏃 {cat} 전력 질주!", f"마당을 달리는 {cat} 🐱💨"],
            "interact": ["🐱🐱 나나 vs 토토! 오늘의 승자는?", "나나와 토토의 귀여운 대결 😂"],
        }
        content["titles"] = templates.get(event.get("event_type", "climb"), [f"🐱 {cat}의 하루"])
        for i, t in enumerate(content["titles"], 1):
            ok(f"타이틀 {i}: {t}")

    # 해시태그 생성
    hashtags = [
        "#고양이", "#캣스타그램", "#고양이일상", "#냥스타그램",
        "#마당고양이", "#cat", "#catlife", "#나나", "#토토",
    ]
    event_tags = {
        "climb": ["#캣타워", "#나무등반", "#catclimbing"],
        "jump": ["#고양이점프", "#catjump"],
        "run": ["#고양이달리기", "#zoomies"],
        "interact": ["#고양이친구", "#catfriends"],
    }
    hashtags.extend(event_tags.get(event.get("event_type", ""), []))
    content["hashtags"] = hashtags
    ok(f"해시태그 {len(hashtags)}개 생성")

    return content


# ─── Step 9: 최종 결과 요약 ──────────────────────────────

def print_summary(results: dict):
    section("최종 결과 요약")

    steps = [
        ("환경 체크", results.get("env_ok", False)),
        ("영상 소스 수신", results.get("source") is not None),
        ("영상 정보 분석", bool(results.get("video_info"))),
        ("이벤트 감지", bool(results.get("event"))),
        ("세로 변환 (9:16)", results.get("vertical") is not None),
        ("BGM 믹싱", results.get("bgm") is not None),
        ("텍스트 오버레이", results.get("overlay") is not None),
        ("썸네일 생성", results.get("thumbnail") is not None),
        ("타이틀/설명 생성", bool(results.get("content"))),
    ]

    passed = sum(1 for _, ok in steps if ok)
    total = len(steps)

    for name, status in steps:
        icon = f"{Colors.GREEN}PASS{Colors.END}" if status else f"{Colors.RED}FAIL{Colors.END}"
        print(f"  [{icon}] {name}")

    print(f"\n  {Colors.BOLD}결과: {passed}/{total} 통과{Colors.END}")

    # 생성된 파일 목록
    print(f"\n  {Colors.BOLD}생성된 파일:{Colors.END}")
    files = [
        results.get("source"),
        results.get("vertical"),
        results.get("bgm"),
        results.get("overlay"),
        results.get("thumbnail"),
    ]
    for f in files:
        if f and Path(f).exists():
            size = Path(f).stat().st_size
            unit = "KB" if size < 1024 * 1024 else "MB"
            size_val = size / 1024 if unit == "KB" else size / (1024 * 1024)
            print(f"    {Path(f).name} ({size_val:.1f}{unit})")

    if passed == total:
        print(f"\n  {Colors.GREEN}{Colors.BOLD}모든 파이프라인 테스트 통과!{Colors.END}")
        print(f"  다음 단계: iPhone NDI 앱으로 실시간 수신 테스트")
    else:
        print(f"\n  {Colors.YELLOW}일부 단계 실패 -위 로그를 확인하세요{Colors.END}")


# ─── Main ─────────────────────────────────────────────────

async def run_test(args):
    results = {}

    # Step 0: 환경
    results["env_ok"] = check_environment()

    # Step 1: 영상 소스
    results["source"] = test_video_source(args)
    if not results["source"]:
        print_summary(results)
        return

    # Step 2: 영상 분석
    results["video_info"] = test_video_info(results["source"])

    # Step 3: 이벤트 감지
    results["event"] = test_event_detection(results["source"])

    # Step 4: 세로 변환
    results["vertical"] = await test_vertical_conversion(results["source"], results["event"])

    # Step 5: BGM 믹싱
    target = results["vertical"] or results["source"]
    results["bgm"] = await test_bgm_mixing(target, results["event"])

    # Step 6: 오버레이
    target = results["bgm"] or target
    results["overlay"] = await test_overlay(target, results["event"])

    # Step 7: 썸네일
    results["thumbnail"] = test_thumbnail(results["source"], results["event"])

    # Step 8: 타이틀
    results["content"] = await test_title_generation(results["event"])

    # 요약
    print_summary(results)


def main():
    parser = argparse.ArgumentParser(
        description="LiveCat E2E Pipeline Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python tests/test_pipeline_e2e.py                     # 더미 영상으로 테스트
  python tests/test_pipeline_e2e.py --input cat.mp4     # 파일 입력
  python tests/test_pipeline_e2e.py --webcam 0           # 웹캠
  python tests/test_pipeline_e2e.py --rtsp rtsp://...    # RTSP 스트림
  python tests/test_pipeline_e2e.py --ndi "iPhone"       # NDI 소스
        """,
    )
    parser.add_argument("--input", "-i", help="입력 영상 파일 경로")
    parser.add_argument("--srt", type=int, nargs="?", const=9000, help="SRT 리스너 포트 (기본: 9000)")
    parser.add_argument("--rtsp", help="RTSP 스트림 URL")
    parser.add_argument("--ndi", help="NDI 소스 이름")
    parser.add_argument("--webcam", type=int, nargs="?", const=0, help="웹캠 ID (기본: 0)")

    args = parser.parse_args()
    asyncio.run(run_test(args))


if __name__ == "__main__":
    main()
