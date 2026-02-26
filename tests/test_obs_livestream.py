"""OBS 경유 YouTube 라이브 스트리밍 테스트.

OBS WebSocket으로 장면 생성 → 미디어 소스 추가 → 스트리밍 시작을 자동화한다.

사전 조건:
    1. OBS Studio 실행 + WebSocket 서버 활성화 (포트 4455)
    2. OBS → 설정 → 방송 → YouTube RTMP 서버 + 스트림 키 설정 완료
       (또는 --key 옵션으로 자동 설정)
    3. pip install obsws-python

Usage:
    python tests/test_obs_livestream.py                    # OBS에 이미 설정된 키 사용
    python tests/test_obs_livestream.py --key STREAM_KEY   # 키 자동 설정
    python tests/test_obs_livestream.py --stop             # 스트리밍 중지
    python tests/test_obs_livestream.py --cleanup          # 테스트 장면 삭제
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIDEO_PATH = Path(__file__).resolve().parent / "cat_sample.mp4"

SCENE_NAME = "LiveCat_Test"
SOURCE_NAME = "CatVideo_Loop"


def get_obs_client(host: str, port: int, password: str | None = None):
    """OBS WebSocket 클라이언트를 생성한다."""
    try:
        import obsws_python as obsws
    except ImportError:
        print("[ERROR] obsws-python 미설치")
        print("  pip install obsws-python")
        sys.exit(1)

    try:
        kwargs = {"host": host, "port": port}
        if password:
            kwargs["password"] = password
        return obsws.ReqClient(**kwargs)
    except Exception as e:
        print(f"[ERROR] OBS 연결 실패: {e}")
        print("  OBS Studio가 실행 중이고 WebSocket 서버가 활성화되어 있는지 확인하세요.")
        sys.exit(1)


def scene_exists(ws, scene_name: str) -> bool:
    """장면이 존재하는지 확인한다."""
    try:
        scenes = ws.get_scene_list().scenes
        return any(s["sceneName"] == scene_name for s in scenes)
    except Exception:
        return False


def source_exists_in_scene(ws, scene_name: str, source_name: str) -> bool:
    """장면에 특정 소스가 있는지 확인한다."""
    try:
        items = ws.get_scene_item_list(scene_name).scene_items
        return any(item["sourceName"] == source_name for item in items)
    except Exception:
        return False


def setup_scene(ws):
    """LiveCat_Test 장면과 미디어 소스를 생성한다."""
    if not VIDEO_PATH.exists():
        print(f"[ERROR] 영상 파일 없음: {VIDEO_PATH}")
        sys.exit(1)

    # 1. 장면 생성
    if scene_exists(ws, SCENE_NAME):
        print(f"  [SCENE] '{SCENE_NAME}' 이미 존재 — 재사용")
    else:
        print(f"  [SCENE] '{SCENE_NAME}' 생성 중...", end=" ")
        try:
            ws.create_scene(SCENE_NAME)
            print("OK")
        except Exception as e:
            print(f"FAIL — {e}")
            sys.exit(1)

    # 2. 미디어 소스 추가 (VLC Video Source 또는 Media Source)
    if source_exists_in_scene(ws, SCENE_NAME, SOURCE_NAME):
        print(f"  [SOURCE] '{SOURCE_NAME}' 이미 존재 — 재사용")
    else:
        print(f"  [SOURCE] '{SOURCE_NAME}' 추가 중...", end=" ")
        try:
            # Windows 경로를 슬래시로 변환하지 않고 그대로 사용
            video_path_str = str(VIDEO_PATH)

            # ffmpeg_source = Media Source (OBS 내장)
            ws.create_input(
                scene_name=SCENE_NAME,
                input_name=SOURCE_NAME,
                input_kind="ffmpeg_source",
                input_settings={
                    "local_file": video_path_str,
                    "looping": True,
                    "restart_on_activate": True,
                    "hw_decode": True,
                },
                scene_item_enabled=True,
            )
            print("OK")
        except Exception as e:
            print(f"FAIL — {e}")
            print("  수동으로 OBS에서 Media Source를 추가해주세요.")
            sys.exit(1)

    # 3. 활성 장면으로 전환
    print(f"  [SWITCH] '{SCENE_NAME}'으로 전환...", end=" ")
    try:
        ws.set_current_program_scene(SCENE_NAME)
        print("OK")
    except Exception as e:
        print(f"FAIL — {e}")


def configure_stream_key(ws, stream_key: str):
    """OBS 스트리밍 설정에 YouTube RTMP + 스트림 키를 설정한다."""
    print("  [CONFIG] YouTube RTMP 스트리밍 설정...", end=" ")
    try:
        ws.set_stream_service_settings(
            ss_type="rtmp_custom",
            ss_settings={
                "server": "rtmp://a.rtmp.youtube.com/live2",
                "key": stream_key,
            },
        )
        print("OK")
    except Exception as e:
        print(f"FAIL — {e}")
        print("  OBS → 설정 → 방송에서 수동으로 설정해주세요.")


def start_streaming(ws):
    """OBS 스트리밍을 시작한다."""
    # 현재 상태 확인
    status = ws.get_stream_status()
    if status.output_active:
        print("  [STREAM] 이미 스트리밍 중!")
        return True

    print("  [STREAM] 스트리밍 시작...", end=" ")
    try:
        ws.start_stream()
        # 시작 확인 대기
        for _ in range(10):
            time.sleep(1)
            status = ws.get_stream_status()
            if status.output_active:
                print("OK")
                return True
        print("TIMEOUT — OBS에서 상태를 확인하세요.")
        return False
    except Exception as e:
        print(f"FAIL — {e}")
        return False


def stop_streaming(ws):
    """OBS 스트리밍을 중지한다."""
    status = ws.get_stream_status()
    if not status.output_active:
        print("  [STREAM] 스트리밍이 실행 중이 아닙니다.")
        return

    print("  [STREAM] 스트리밍 중지...", end=" ")
    try:
        ws.stop_stream()
        print("OK")
    except Exception as e:
        print(f"FAIL — {e}")


def cleanup_scene(ws):
    """테스트 장면을 삭제한다."""
    if not scene_exists(ws, SCENE_NAME):
        print(f"  [CLEANUP] '{SCENE_NAME}' 없음 — 건너뜀")
        return

    # 다른 장면으로 먼저 전환
    try:
        current = ws.get_current_program_scene().scene_name
        if current == SCENE_NAME:
            scenes = ws.get_scene_list().scenes
            other = [s for s in scenes if s["sceneName"] != SCENE_NAME]
            if other:
                ws.set_current_program_scene(other[0]["sceneName"])
    except Exception:
        pass

    print(f"  [CLEANUP] '{SCENE_NAME}' 삭제...", end=" ")
    try:
        ws.remove_scene(SCENE_NAME)
        print("OK")
    except Exception as e:
        print(f"FAIL — {e}")


def monitor_stream(ws):
    """스트리밍 상태를 모니터링한다."""
    print()
    print("  스트리밍 모니터링 중... (Ctrl+C로 종료, 스트리밍은 계속)")
    print()
    try:
        while True:
            status = ws.get_stream_status()
            if not status.output_active:
                print("\n  [INFO] 스트리밍이 종료되었습니다.")
                break

            duration = status.output_duration
            m, s = divmod(int(duration / 1000), 60)
            h, m = divmod(m, 60)

            # 가용 속성 안전하게 접근
            bytes_sent = getattr(status, "output_bytes", 0)
            mb_sent = bytes_sent / (1024 * 1024) if bytes_sent else 0
            skipped = getattr(status, "output_skipped_frames", 0)
            total = getattr(status, "output_total_frames", 0)

            parts = [f"[{h:02d}:{m:02d}:{s:02d}]"]
            if mb_sent > 0:
                parts.append(f"{mb_sent:.1f}MB")
            if total > 0:
                drop_pct = (skipped / total * 100) if total else 0
                parts.append(f"drop={drop_pct:.1f}%")

            print(f"\r  {' | '.join(parts)}", end="", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n\n  [INFO] 모니터링 종료 (스트리밍은 OBS에서 계속)")


def main():
    parser = argparse.ArgumentParser(
        description="LiveCat - OBS YouTube livestream"
    )
    parser.add_argument("--key", default=None, help="YouTube 스트림 키 (자동 설정)")
    parser.add_argument("--env", action="store_true", help=".env에서 스트림 키 로드")
    parser.add_argument("--host", default="localhost", help="OBS 호스트 (기본: localhost)")
    parser.add_argument("--port", type=int, default=4455, help="WebSocket 포트 (기본: 4455)")
    parser.add_argument("--password", default=None, help="WebSocket 비밀번호")
    parser.add_argument("--stop", action="store_true", help="스트리밍 중지")
    parser.add_argument("--cleanup", action="store_true", help="테스트 장면 삭제")
    parser.add_argument("--no-monitor", action="store_true", help="모니터링 없이 시작만")
    args = parser.parse_args()

    print("=" * 60)
    print("  LiveCat - OBS Automated Livestream")
    print("=" * 60)

    ws = get_obs_client(args.host, args.port, args.password)
    print(f"  [OBS] 연결 성공 ({args.host}:{args.port})")
    print()

    try:
        if args.cleanup:
            cleanup_scene(ws)
            return

        if args.stop:
            stop_streaming(ws)
            return

        # 스트림 키 결정
        stream_key = args.key
        if not stream_key and args.env:
            # .env에서 로드
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("YOUTUBE_STREAM_KEY="):
                        stream_key = line.split("=", 1)[1].strip()
                        break
        if not stream_key:
            stream_key = os.environ.get("YOUTUBE_STREAM_KEY")

        # Step 1: 장면 + 소스 설정
        print("[Step 1] 장면 및 소스 설정")
        setup_scene(ws)
        print()

        # Step 2: 스트림 키 설정 (제공된 경우)
        if stream_key:
            print("[Step 2] 스트리밍 설정")
            configure_stream_key(ws, stream_key)
            print()
        else:
            print("[Step 2] 스트림 키 미제공 — OBS 기존 설정 사용")
            print("  (--key KEY 또는 --env 옵션으로 자동 설정 가능)")
            print()

        # Step 3: 스트리밍 시작
        print("[Step 3] 스트리밍 시작")
        success = start_streaming(ws)

        if success and not args.no_monitor:
            print()
            print("=" * 60)
            print("  YouTube Studio에서 라이브 방송을 확인하세요!")
            print("  https://studio.youtube.com")
            print("=" * 60)
            monitor_stream(ws)

    finally:
        try:
            ws.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
