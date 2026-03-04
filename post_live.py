"""
Post-Live Pipeline — 라이브 종료 후 자동 업로드 오케스트레이터.

라이브 녹화 파일(.mp4)을 입력받아:
  1) 롱폼 썸네일 + 제목/설명 생성 → YouTube 업로드
  2) 쇼츠 3개 구간 자동 선택 → 세로 변환 → 썸네일/제목 생성 → YouTube 업로드
  3) 결과 pipeline_result.json 저장

Usage:
  python post_live.py "C:/Users/Computer/Videos/2026-03-02 10-06-06.mp4"
  python post_live.py "..." --dry-run
  python post_live.py --auth-only
  python post_live.py "..." --privacy unlisted
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

# ── Project root & sys.path ──────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

import yaml

from server.thumbnail.frame_selector import FrameSelector
from server.titler.title_generator import TitleGenerator
from server.titler.description_generator import DescriptionGenerator
from server.titler.hashtag_generator import HashtagGenerator
from server.producer.vertical_converter import VerticalConverter
from server.uploader.youtube_uploader import YouTubeUploader


# ── Logging ──────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="INFO",
)


def load_config() -> dict:
    """server/config.yaml 로드 + _root_dir 주입."""
    config_path = ROOT_DIR / "server" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["_root_dir"] = str(ROOT_DIR)
    return config


# ══════════════════════════════════════════════════════════════════════
# Activity Segment Selector (with cat verification)
# ══════════════════════════════════════════════════════════════════════

_CAT_CLASS_ID = 15  # COCO class ID for cat

_yolo_model = None


def _get_yolo():
    """YOLO 모델 싱글턴 (FrameSelector/VerticalConverter와 공유 가능)."""
    global _yolo_model
    if _yolo_model is None:
        try:
            from ultralytics import YOLO
            _yolo_model = YOLO("yolov8n.pt")
            logger.info("YOLO model loaded for cat verification")
        except Exception as e:
            logger.warning(f"YOLO load failed: {e} — cat verification disabled")
    return _yolo_model


def _check_cat_in_frame(model, frame: np.ndarray, conf: float = 0.3) -> bool:
    """프레임에서 고양이(COCO 15) 감지 여부를 반환한다."""
    try:
        results = model(frame, verbose=False, conf=conf)
        for result in results:
            if result.boxes is None:
                continue
            for i in range(len(result.boxes)):
                if int(result.boxes.cls[i].item()) == _CAT_CLASS_ID:
                    return True
    except Exception:
        pass
    return False


def verify_cat_presence(
    video_path: Path,
    start_sec: float,
    duration: float,
    num_samples: int = 5,
    min_detections: int = 1,
) -> bool:
    """구간 내 num_samples 프레임을 샘플링하여 고양이 존재를 확인한다.

    min_detections 이상 감지되면 True.
    """
    model = _get_yolo()
    if model is None:
        return True  # YOLO 없으면 통과시킴

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return False

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    detections = 0

    for i in range(num_samples):
        sample_sec = start_sec + (duration / (num_samples + 1)) * (i + 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(sample_sec * fps))
        ret, frame = cap.read()
        if not ret:
            continue
        if _check_cat_in_frame(model, frame):
            detections += 1
            if detections >= min_detections:
                cap.release()
                return True

    cap.release()
    return detections >= min_detections


def select_shorts_segments(
    video_path: Path,
    num: int = 3,
    duration: int = 55,
    sample_fps: float = 2.0,
    candidates_per_zone: int = 10,
) -> list[dict]:
    """영상을 num등분하여 각 구간에서 고양이가 있는 가장 활발한 구간을 선택한다.

    1단계: cv2.absdiff activity score로 후보 윈도우 선정
    2단계: YOLO로 고양이 존재 확인 → 고양이 있는 첫 번째 후보 선택

    Returns:
        [{"zone": 0, "start_sec": 12.5, "duration": 55, "score": 1234.5}, ...]
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_sec = total_frames / fps

    if total_sec < duration:
        logger.warning(
            f"Video too short ({total_sec:.0f}s) for {duration}s segments"
        )
        cap.release()
        return []

    # 프레임 샘플링 간격 (sample_fps에 맞춰)
    sample_interval = max(1, int(fps / sample_fps))

    logger.info(
        f"Activity scan: {total_sec:.0f}s video, "
        f"fps={fps:.1f}, sample_interval={sample_interval}"
    )

    # 전체 영상의 activity score를 샘플 포인트마다 계산
    scores: list[tuple[float, float]] = []  # (timestamp_sec, activity_score)
    prev_gray: Optional[np.ndarray] = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (320, 180))  # 다운스케일로 속도 향상

            if prev_gray is not None:
                diff = cv2.absdiff(prev_gray, gray)
                activity = float(np.mean(diff))
                timestamp = frame_idx / fps
                scores.append((timestamp, activity))

            prev_gray = gray

        frame_idx += 1

    cap.release()

    if not scores:
        logger.warning("No activity scores computed")
        return []

    # 영상을 num 등분 (zone)
    zone_duration = total_sec / num
    segments: list[dict] = []

    for zone_idx in range(num):
        zone_start = zone_idx * zone_duration
        zone_end = zone_start + zone_duration

        # 이 zone 내의 activity scores
        zone_scores = [
            (ts, score) for ts, score in scores
            if zone_start <= ts < zone_end
        ]

        if not zone_scores:
            continue

        # 슬라이딩 윈도우로 activity 합 기준 상위 후보들 수집
        candidates: list[tuple[float, float]] = []  # (start_sec, total_score)
        window_step = 1.0 / sample_fps
        candidate_start = zone_start

        while candidate_start + duration <= zone_end + 0.01:
            window_end = candidate_start + duration
            window_total = sum(
                score for ts, score in zone_scores
                if candidate_start <= ts < window_end
            )
            candidates.append((candidate_start, window_total))
            candidate_start += window_step

        # activity score 내림차순 정렬 → 간격 필터링
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 최소 duration/2초 간격으로 후보 다양화 (겹치는 윈도우 제거)
        min_gap = duration / 2
        diverse: list[tuple[float, float]] = []
        for cand_start, cand_score in candidates:
            if all(abs(cand_start - d[0]) >= min_gap for d in diverse):
                diverse.append((cand_start, cand_score))
                if len(diverse) >= candidates_per_zone:
                    break

        # 상위 후보 중 고양이가 있는 첫 번째 구간 선택
        selected_start = None
        selected_score = 0.0

        for rank, (cand_start, cand_score) in enumerate(diverse):
            cand_start = max(0.0, min(cand_start, total_sec - duration))
            has_cat = verify_cat_presence(video_path, cand_start, duration)
            logger.debug(
                f"  zone{zone_idx} candidate#{rank}: "
                f"{cand_start:.1f}s score={cand_score:.0f} cat={has_cat}"
            )
            if has_cat:
                selected_start = cand_start
                selected_score = cand_score
                break

        if selected_start is None:
            # 모든 후보에 고양이 없으면 이 zone 스킵
            logger.warning(
                f"  zone{zone_idx}: no cat found in top {candidates_per_zone} "
                f"candidates — skipping zone"
            )
            continue

        segments.append({
            "zone": zone_idx,
            "start_sec": round(selected_start, 2),
            "duration": duration,
            "score": round(selected_score, 2),
        })

    logger.info(
        f"Selected {len(segments)} segments: "
        + ", ".join(
            f"zone{s['zone']}@{s['start_sec']:.1f}s(score={s['score']:.0f})"
            for s in segments
        )
    )
    return segments


# ══════════════════════════════════════════════════════════════════════
# FFmpeg Segment Extraction
# ══════════════════════════════════════════════════════════════════════

async def extract_segment(
    source: Path,
    start_sec: float,
    duration_sec: float,
    output: Path,
) -> Path:
    """ffmpeg로 영상에서 특정 구간을 추출한다."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(output),
    ]

    logger.debug(f"Extracting segment: {start_sec:.1f}s + {duration_sec}s → {output.name}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg extract failed (rc={proc.returncode}): {error_msg}")

    logger.info(f"Segment extracted: {output.name}")
    return output


# ══════════════════════════════════════════════════════════════════════
# Thumbnail Save Helper
# ══════════════════════════════════════════════════════════════════════

def save_thumbnail(
    frame: np.ndarray,
    output_path: Path,
    size: tuple[int, int] = (1280, 720),
) -> Path:
    """프레임을 리사이즈하여 JPEG로 저장한다."""
    resized = cv2.resize(frame, size, interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(output_path), resized, [cv2.IMWRITE_JPEG_QUALITY, 95])
    logger.info(f"Thumbnail saved: {output_path.name} ({size[0]}x{size[1]})")
    return output_path


# ══════════════════════════════════════════════════════════════════════
# Main Pipeline
# ══════════════════════════════════════════════════════════════════════

async def run_pipeline(
    recording_path: Path,
    dry_run: bool = False,
    privacy_override: Optional[str] = None,
    num_shorts_override: Optional[int] = None,
) -> dict:
    """메인 파이프라인 — 롱폼 1개 + 쇼츠 3개 처리 및 업로드.

    Args:
        recording_path: OBS 녹화 파일 경로.
        dry_run: True이면 업로드 스킵.
        privacy_override: "public", "unlisted", "private" 오버라이드.

    Returns:
        파이프라인 결과 dict (pipeline_result.json에도 저장).
    """
    started_at = time.time()
    config = load_config()
    pl_cfg = config.get("post_live", {})

    # Privacy 오버라이드
    if privacy_override:
        config.setdefault("upload", {}).setdefault("youtube", {})["privacy_status"] = privacy_override

    # 출력 디렉토리
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    output_dir = Path(pl_cfg.get("output_dir", str(ROOT_DIR / "output"))) / timestamp_str
    output_dir.mkdir(parents=True, exist_ok=True)

    num_shorts = num_shorts_override if num_shorts_override is not None else pl_cfg.get("num_shorts", 3)
    short_duration = pl_cfg.get("short_duration_sec", 55)
    sample_fps = pl_cfg.get("activity_sample_fps", 2.0)

    result: dict = {
        "recording": str(recording_path),
        "output_dir": str(output_dir),
        "timestamp": timestamp_str,
        "dry_run": dry_run,
        "longform": {},
        "shorts": [],
        "errors": [],
    }

    # 모듈 초기화
    frame_selector = FrameSelector(config)
    title_gen = TitleGenerator(config)
    desc_gen = DescriptionGenerator(config)
    hashtag_gen = HashtagGenerator(config)
    vertical_conv = VerticalConverter(config)
    uploader = YouTubeUploader(config)

    # ── [1] 영상 분석 ─────────────────────────────────────────────
    logger.info(f"[1/10] Analyzing: {recording_path.name}")
    cap = cv2.VideoCapture(str(recording_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_sec = total_frames / fps
    cap.release()

    logger.info(f"  Video: {total_sec:.0f}s, {fps:.1f}fps, {total_frames} frames")

    # 메타데이터 (롱폼용 — 이벤트 없이 일상 전체)
    longform_meta = {
        "event_type": "interact",
        "cats": ["nana", "toto"],
        "timestamp": datetime.now().isoformat(),
        "duration_sec": int(total_sec),
    }

    # ── [2] 롱폼 썸네일 ──────────────────────────────────────────
    longform_thumb_path = output_dir / "longform_thumb.jpg"
    try:
        logger.info("[2/10] Generating longform thumbnail...")
        selected = frame_selector.select(recording_path)
        save_thumbnail(selected.frame, longform_thumb_path, size=(1280, 720))
        result["longform"]["thumbnail"] = str(longform_thumb_path)
        logger.info(f"  Score: {selected.scores.get('total', 0):.1f}")
    except Exception as e:
        logger.error(f"  Longform thumbnail failed: {e}")
        result["errors"].append(f"longform_thumbnail: {e}")
        longform_thumb_path = None

    # ── [3] 롱폼 제목/설명 ────────────────────────────────────────
    try:
        logger.info("[3/10] Generating longform title & description...")
        titles = await title_gen.generate(longform_meta, platform="youtube")
        longform_title = titles[0] if titles else "Nana & Toto's Day | Outdoor Cat Life"
        longform_desc = await desc_gen.generate(longform_meta, platform="youtube")
        longform_tags = hashtag_gen.generate(longform_meta, platform="youtube")

        result["longform"]["title"] = longform_title
        result["longform"]["description"] = longform_desc[:200] + "..."
        logger.info(f"  Title: {longform_title}")
    except Exception as e:
        logger.error(f"  Longform title/desc failed: {e}")
        result["errors"].append(f"longform_title: {e}")
        longform_title = "Nana & Toto's Day | Outdoor Cat Life"
        longform_desc = "Watch Nana and Toto's daily outdoor adventures!"
        longform_tags = ["#cat", "#outdoorcat", "#catlife"]

    # ── [4] 쇼츠 구간 선택 ────────────────────────────────────────
    logger.info(f"[4/10] Selecting {num_shorts} shorts segments ({short_duration}s each)...")
    try:
        segments = select_shorts_segments(
            recording_path,
            num=num_shorts,
            duration=short_duration,
            sample_fps=sample_fps,
        )
    except Exception as e:
        logger.error(f"  Segment selection failed: {e}")
        result["errors"].append(f"segment_selection: {e}")
        segments = []

    # ── [5-7] 쇼츠 처리 (구간 추출 → 세로 변환 → 썸네일 → 제목) ──
    shorts_data: list[dict] = []

    for i, seg in enumerate(segments, 1):
        short_info: dict = {"zone": seg["zone"], "start_sec": seg["start_sec"]}
        raw_path = output_dir / f"short_{i}_raw.mp4"
        vertical_path = output_dir / f"short_{i}_vertical.mp4"
        thumb_path = output_dir / f"short_{i}_thumb.jpg"

        # [5a] 구간 추출
        try:
            logger.info(
                f"[5/10] Short {i}: extracting {seg['start_sec']:.1f}s + {seg['duration']}s..."
            )
            await extract_segment(
                recording_path, seg["start_sec"], seg["duration"], raw_path,
            )
            short_info["raw_path"] = str(raw_path)
        except Exception as e:
            logger.error(f"  Short {i} extraction failed: {e}")
            result["errors"].append(f"short_{i}_extract: {e}")
            shorts_data.append(short_info)
            continue

        # [5b] 세로 변환
        try:
            logger.info(f"[5/10] Short {i}: converting to vertical...")
            short_meta = {
                "cat_id": "nana",
                "event_type": "interact",
            }
            converted = await vertical_conv.convert(raw_path, short_meta)
            # convert() returns path with _vertical suffix
            if converted.exists():
                # Rename to our naming convention if needed
                if converted != vertical_path:
                    converted.rename(vertical_path)
                short_info["vertical_path"] = str(vertical_path)
            else:
                short_info["vertical_path"] = str(converted)
        except Exception as e:
            logger.error(f"  Short {i} vertical conversion failed: {e}")
            result["errors"].append(f"short_{i}_vertical: {e}")

        # [6] 쇼츠 썸네일
        try:
            logger.info(f"[6/10] Short {i}: generating thumbnail...")
            sel = frame_selector.select(raw_path)
            save_thumbnail(sel.frame, thumb_path, size=(1280, 720))
            short_info["thumbnail_path"] = str(thumb_path)
        except Exception as e:
            logger.error(f"  Short {i} thumbnail failed: {e}")
            result["errors"].append(f"short_{i}_thumbnail: {e}")
            thumb_path = None

        # [7] 쇼츠 제목/설명
        try:
            logger.info(f"[7/10] Short {i}: generating title & description...")
            short_meta_full = {
                "event_type": "interact",
                "cats": ["nana", "toto"],
                "timestamp": datetime.now().isoformat(),
                "duration_sec": seg["duration"],
            }
            s_titles = await title_gen.generate(short_meta_full, platform="shorts")
            short_info["title"] = s_titles[0] if s_titles else f"Nana & Toto daily life #{i}"
            short_info["description"] = await desc_gen.generate(
                short_meta_full, platform="shorts"
            )
            short_info["tags"] = hashtag_gen.generate(short_meta_full, platform="shorts")
            logger.info(f"  Title: {short_info['title']}")
        except Exception as e:
            logger.error(f"  Short {i} title/desc failed: {e}")
            result["errors"].append(f"short_{i}_title: {e}")
            short_info.setdefault("title", f"Nana & Toto daily life #{i}")
            short_info.setdefault("description", "Nana & Toto living their best outdoor life")
            short_info.setdefault("tags", ["#cat", "#outdoorcat", "#catlife", "#shorts"])

        shorts_data.append(short_info)

    # ── [8] 롱폼 업로드 ──────────────────────────────────────────
    if dry_run:
        logger.info("[8/10] DRY RUN — skipping longform upload")
        result["longform"]["upload"] = "skipped (dry-run)"
    else:
        try:
            logger.info("[8/10] Uploading longform to YouTube...")
            # Strip # from tags for YouTube API
            clean_tags = [t.lstrip("#") for t in longform_tags]
            upload_result = await uploader.upload(
                video_path=recording_path,
                thumbnail_path=longform_thumb_path,
                title=longform_title,
                description=longform_desc,
                tags=clean_tags,
                is_short=False,
            )
            result["longform"]["upload"] = {
                "success": upload_result.success,
                "video_id": upload_result.video_id,
                "url": upload_result.url,
                "error": upload_result.error_message,
            }
            if upload_result.success:
                logger.info(f"  Longform uploaded: {upload_result.url}")
            else:
                logger.error(f"  Longform upload failed: {upload_result.error_message}")
        except Exception as e:
            logger.error(f"  Longform upload error: {e}")
            result["errors"].append(f"longform_upload: {e}")

    # ── [9] 쇼츠 업로드 ──────────────────────────────────────────
    for i, short_info in enumerate(shorts_data, 1):
        video_file = short_info.get("vertical_path", short_info.get("raw_path"))
        if not video_file or not Path(video_file).exists():
            logger.warning(f"[9/10] Short {i}: no video file — skipping upload")
            continue

        if dry_run:
            logger.info(f"[9/10] DRY RUN — skipping short {i} upload")
            short_info["upload"] = "skipped (dry-run)"
            continue

        try:
            logger.info(f"[9/10] Uploading short {i} to YouTube...")
            s_thumb = short_info.get("thumbnail_path")
            clean_tags = [t.lstrip("#") for t in short_info.get("tags", [])]
            upload_result = await uploader.upload(
                video_path=video_file,
                thumbnail_path=s_thumb,
                title=short_info.get("title", f"Nana & Toto #{i}"),
                description=short_info.get("description", ""),
                tags=clean_tags,
                is_short=True,
            )
            short_info["upload"] = {
                "success": upload_result.success,
                "video_id": upload_result.video_id,
                "url": upload_result.url,
                "error": upload_result.error_message,
            }
            if upload_result.success:
                logger.info(f"  Short {i} uploaded: {upload_result.url}")
            else:
                logger.error(f"  Short {i} upload failed: {upload_result.error_message}")
        except Exception as e:
            logger.error(f"  Short {i} upload error: {e}")
            result["errors"].append(f"short_{i}_upload: {e}")

    result["shorts"] = shorts_data

    # ── [10] 결과 저장 ────────────────────────────────────────────
    elapsed = time.time() - started_at
    result["elapsed_sec"] = round(elapsed, 1)
    result["quota_remaining"] = uploader.quota_remaining

    result_path = output_dir / "pipeline_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"[10/10] Pipeline complete in {elapsed:.0f}s → {result_path}")

    # 요약
    n_uploaded = sum(
        1 for s in shorts_data
        if isinstance(s.get("upload"), dict) and s["upload"].get("success")
    )
    longform_ok = (
        isinstance(result["longform"].get("upload"), dict)
        and result["longform"]["upload"].get("success")
    )
    logger.info(
        f"Summary: longform={'OK' if longform_ok else 'FAIL'}, "
        f"shorts={n_uploaded}/{len(shorts_data)} uploaded, "
        f"errors={len(result['errors'])}, "
        f"quota_remaining={result['quota_remaining']}"
    )

    return result


# ══════════════════════════════════════════════════════════════════════
# Auth-Only Mode
# ══════════════════════════════════════════════════════════════════════

async def auth_only():
    """YouTube OAuth 인증만 수행 (최초 1회)."""
    config = load_config()
    uploader = YouTubeUploader(config)
    # _get_service() 호출 시 토큰이 없으면 브라우저 OAuth 실행
    service = await uploader._get_service()
    if service:
        logger.info("YouTube OAuth authentication successful!")
        logger.info(f"Token saved to: {uploader._token_path}")
    else:
        logger.error("YouTube OAuth authentication failed.")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Post-Live Pipeline: longform + shorts auto upload",
    )
    parser.add_argument(
        "recording",
        nargs="?",
        help="Path to OBS recording (.mp4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run everything except YouTube upload",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Run YouTube OAuth authentication only (first-time setup)",
    )
    parser.add_argument(
        "--privacy",
        choices=["public", "unlisted", "private"],
        default=None,
        help="Override privacy status for all uploads",
    )
    parser.add_argument(
        "--num-shorts",
        type=int,
        default=None,
        help="Override number of shorts to generate (default: config value)",
    )

    args = parser.parse_args()

    if args.auth_only:
        asyncio.run(auth_only())
        return

    if not args.recording:
        parser.error("recording path is required (unless using --auth-only)")

    recording_path = Path(args.recording)
    if not recording_path.exists():
        logger.error(f"Recording not found: {recording_path}")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("  Post-Live Pipeline")
    logger.info("=" * 50)
    logger.info(f"  Recording: {recording_path}")
    logger.info(f"  Dry run:   {args.dry_run}")
    logger.info(f"  Privacy:   {args.privacy or 'config default'}")
    logger.info("")

    result = asyncio.run(
        run_pipeline(
            recording_path=recording_path,
            dry_run=args.dry_run,
            privacy_override=args.privacy,
            num_shorts_override=args.num_shorts,
        )
    )

    # 에러가 있으면 non-zero exit
    if result.get("errors"):
        sys.exit(1)


if __name__ == "__main__":
    main()
