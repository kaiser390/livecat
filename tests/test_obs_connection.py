"""OBS WebSocket 연결 테스트.

OBS Studio의 WebSocket 서버에 연결하여 기본 상태를 확인한다.

사전 조건:
    1. OBS Studio 실행 중
    2. 도구 → WebSocket Server Settings → "Enable WebSocket server" 체크
    3. 포트: 4455 (기본값)
    4. pip install obsws-python

Usage:
    python tests/test_obs_connection.py
    python tests/test_obs_connection.py --host localhost --port 4455
    python tests/test_obs_connection.py --password YOUR_PASSWORD
"""

from __future__ import annotations

import argparse
import sys


def test_connection(host: str, port: int, password: str | None = None):
    """OBS WebSocket 연결을 테스트한다."""
    try:
        import obsws_python as obsws
    except ImportError:
        print("[ERROR] obsws-python 미설치")
        print("  pip install obsws-python")
        sys.exit(1)

    print("=" * 60)
    print("  LiveCat - OBS WebSocket Connection Test")
    print("=" * 60)
    print(f"  Host: {host}:{port}")
    print(f"  Auth: {'enabled' if password else 'disabled'}")
    print()

    # 1. 연결
    print("[1/4] OBS WebSocket 연결 중...", end=" ")
    try:
        kwargs = {"host": host, "port": port}
        if password:
            kwargs["password"] = password
        ws = obsws.ReqClient(**kwargs)
        print("OK")
    except Exception as e:
        print("FAIL")
        print(f"  Error: {e}")
        print()
        print("  확인 사항:")
        print("  - OBS Studio가 실행 중인가?")
        print("  - 도구 → WebSocket Server Settings에서 서버 활성화했는가?")
        print(f"  - 포트가 {port}인가?")
        if not password:
            print("  - 인증이 활성화되어 있다면 --password 옵션 사용")
        sys.exit(1)

    # 2. 버전 정보
    print("[2/4] OBS 버전 정보...", end=" ")
    try:
        version = ws.get_version()
        print("OK")
        print(f"  OBS Studio: v{version.obs_version}")
        print(f"  WebSocket:  v{version.obs_web_socket_version}")
        print(f"  Platform:   {version.platform_description}")
    except Exception as e:
        print(f"WARN — {e}")

    # 3. 장면 목록
    print("[3/4] 장면 목록 조회...", end=" ")
    try:
        scenes_resp = ws.get_scene_list()
        current_scene = scenes_resp.current_program_scene_name
        scenes = scenes_resp.scenes
        print("OK")
        print(f"  현재 활성 장면: {current_scene}")
        print(f"  전체 장면 ({len(scenes)}개):")
        for scene in reversed(scenes):  # OBS는 역순으로 반환
            marker = " <-- ACTIVE" if scene["sceneName"] == current_scene else ""
            print(f"    - {scene['sceneName']}{marker}")
    except Exception as e:
        print(f"WARN — {e}")

    # 4. 스트리밍 상태
    print("[4/4] 스트리밍 상태 확인...", end=" ")
    try:
        stream_status = ws.get_stream_status()
        active = stream_status.output_active
        print("OK")
        if active:
            duration = stream_status.output_duration
            m, s = divmod(int(duration / 1000), 60)
            h, m = divmod(m, 60)
            bytes_sent = getattr(stream_status, "output_bytes", 0)
            mb_sent = bytes_sent / (1024 * 1024) if bytes_sent else 0
            print(f"  스트리밍: ON (송출 중)")
            print(f"  송출 시간: {h:02d}:{m:02d}:{s:02d}")
            if mb_sent > 0:
                print(f"  전송량: {mb_sent:.1f} MB")
        else:
            print(f"  스트리밍: OFF (대기 중)")
    except Exception as e:
        print(f"WARN — {e}")

    # 정리
    try:
        ws.disconnect()
    except Exception:
        pass

    print()
    print("=" * 60)
    print("  연결 테스트 완료!")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="LiveCat - OBS WebSocket connection test"
    )
    parser.add_argument("--host", default="localhost", help="OBS 호스트 (기본: localhost)")
    parser.add_argument("--port", type=int, default=4455, help="WebSocket 포트 (기본: 4455)")
    parser.add_argument("--password", default=None, help="WebSocket 비밀번호 (인증 활성화 시)")
    args = parser.parse_args()

    test_connection(args.host, args.port, args.password)


if __name__ == "__main__":
    main()
