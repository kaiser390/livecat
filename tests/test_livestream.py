"""ffmpeg 직접 RTMP 스트리밍 테스트.

cat_sample.mp4를 무한 루프로 YouTube Live에 송출한다.
640x360 → 1280x720 업스케일, libx264 veryfast 2500kbps.

Usage:
    python tests/test_livestream.py --key YOUR_STREAM_KEY
    python tests/test_livestream.py --env          # .env에서 키 로드
    python tests/test_livestream.py --key KEY --dry-run  # 명령만 출력
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIDEO_PATH = Path(__file__).resolve().parent / "cat_sample.mp4"

RTMP_URL = "rtmp://a.rtmp.youtube.com/live2"


def load_stream_key_from_env() -> str | None:
    """프로젝트 .env에서 YOUTUBE_STREAM_KEY를 읽는다."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "YOUTUBE_STREAM_KEY":
            return value.strip()
    return None


def build_ffmpeg_cmd(stream_key: str) -> list[str]:
    """ffmpeg RTMP 송출 명령을 생성한다."""
    return [
        "ffmpeg",
        # 입력: 실시간 속도로 읽기 + 무한 루프
        "-re",
        "-stream_loop", "-1",
        "-i", str(VIDEO_PATH),
        # 비디오: 720p 업스케일
        "-vf", "scale=1280:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", "2500k",
        "-maxrate", "2500k",
        "-bufsize", "5000k",
        "-pix_fmt", "yuv420p",
        "-g", "60",
        "-keyint_min", "60",
        # 오디오: AAC 128k
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        # 출력: RTMP FLV
        "-f", "flv",
        f"{RTMP_URL}/{stream_key}",
    ]


def run_stream(stream_key: str, dry_run: bool = False):
    """ffmpeg 스트리밍을 실행한다."""
    # 영상 파일 확인
    if not VIDEO_PATH.exists():
        print(f"[ERROR] 영상 파일 없음: {VIDEO_PATH}")
        sys.exit(1)

    cmd = build_ffmpeg_cmd(stream_key)

    if dry_run:
        # 스트림 키를 마스킹하여 출력
        display_cmd = cmd.copy()
        display_cmd[-1] = f"{RTMP_URL}/****"
        print("[DRY-RUN] 실행할 명령:")
        print(" \\\n  ".join(display_cmd))
        return

    print("=" * 60)
    print("  LiveCat - ffmpeg Direct RTMP Streaming")
    print("=" * 60)
    print(f"  영상: {VIDEO_PATH.name}")
    print(f"  해상도: 640x360 → 1280x720 (업스케일)")
    print(f"  인코딩: libx264 veryfast, 2500kbps")
    print(f"  오디오: AAC 128kbps / 44100Hz")
    print(f"  송출: YouTube RTMP (무한 루프)")
    print("=" * 60)
    print("  Ctrl+C로 종료")
    print()

    start_time = time.time()
    proc = None

    def shutdown(signum, frame):
        nonlocal proc
        print("\n[INFO] 스트리밍 종료 중...")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        elapsed = time.time() - start_time
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        print(f"[INFO] 총 송출 시간: {h:02d}:{m:02d}:{s:02d}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # ffmpeg 출력을 실시간으로 표시
        for line in proc.stdout:
            line = line.rstrip()
            # 진행 상태 라인 (frame=, fps=, bitrate= 등)
            if line.startswith("frame=") or "bitrate=" in line:
                elapsed = time.time() - start_time
                m, s = divmod(int(elapsed), 60)
                h, m = divmod(m, 60)
                print(f"\r  [{h:02d}:{m:02d}:{s:02d}] {line}", end="", flush=True)
            elif "error" in line.lower() or "warning" in line.lower():
                print(f"\n  [WARN] {line}")
            # 초기 설정 정보는 표시
            elif "Stream #" in line or "Output #" in line:
                print(f"  {line}")

        proc.wait()
        if proc.returncode != 0:
            print(f"\n[ERROR] ffmpeg 종료 코드: {proc.returncode}")
            sys.exit(proc.returncode)

    except FileNotFoundError:
        print("[ERROR] ffmpeg을 찾을 수 없습니다. PATH에 ffmpeg이 있는지 확인하세요.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="LiveCat - ffmpeg direct RTMP streaming test"
    )
    parser.add_argument(
        "--key", type=str, default=None,
        help="YouTube 스트림 키",
    )
    parser.add_argument(
        "--env", action="store_true",
        help=".env 파일에서 YOUTUBE_STREAM_KEY 로드",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="실제 실행 없이 ffmpeg 명령만 출력",
    )
    args = parser.parse_args()

    # 스트림 키 결정
    stream_key = args.key
    if not stream_key and args.env:
        stream_key = load_stream_key_from_env()
        if stream_key:
            print(f"[INFO] .env에서 스트림 키 로드 (****{stream_key[-4:]})")
    if not stream_key:
        stream_key = os.environ.get("YOUTUBE_STREAM_KEY")
    if not stream_key:
        print("[ERROR] 스트림 키가 필요합니다.")
        print("  --key YOUR_KEY  또는  --env (.env 파일)")
        sys.exit(1)

    run_stream(stream_key, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
