"""
LiveCat NDI 수신 테스트
======================

iPhone NDI HX Camera 앱에서 보내는 영상을 PC에서 수신하는 테스트.

사전 준비:
  1. iPhone에 "NDI HX Camera" 앱 설치 (무료, iOS 17+)
  2. PC에 ndi-python 설치: pip install ndi-python
  3. iPhone과 PC가 같은 Wi-Fi에 연결

사용법:
  python tests/test_ndi_receiver.py              # NDI 소스 탐색
  python tests/test_ndi_receiver.py --record 20  # 20초 녹화
  python tests/test_ndi_receiver.py --preview     # OpenCV 미리보기 창
"""

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

try:
    import NDIlib as ndi
except ImportError:
    print("ndi-python 미설치!")
    print("설치: pip install ndi-python")
    print()
    print("대안: ffmpeg으로 NDI 수신 (NDI Tools 설치 필요)")
    print("  ffmpeg -f libndi_newtek -i \"iPhone (LiveCatCam)\" -t 20 test.mp4")
    sys.exit(1)

import numpy as np


def find_sources(timeout_sec: int = 10) -> list:
    """NDI 소스 탐색."""
    if not ndi.initialize():
        print("NDI 초기화 실패")
        return []

    finder = ndi.find_create_v2()
    if not finder:
        print("NDI finder 생성 실패")
        ndi.destroy()
        return []

    print(f"NDI 소스 탐색 중 ({timeout_sec}초)...")
    print("iPhone에서 NDI HX Camera 앱을 실행하세요.\n")

    sources = []
    start = time.time()
    while time.time() - start < timeout_sec:
        ndi.find_wait_for_sources(finder, 1000)
        sources = ndi.find_get_current_sources(finder)
        if sources:
            break
        remaining = timeout_sec - (time.time() - start)
        print(f"  탐색 중... ({remaining:.0f}초 남음)")

    ndi.find_destroy(finder)

    if sources:
        print(f"\n발견된 NDI 소스 ({len(sources)}개):")
        for i, s in enumerate(sources):
            print(f"  [{i}] {s.ndi_name}")
    else:
        print("\nNDI 소스를 찾을 수 없습니다.")
        print("확인사항:")
        print("  1. iPhone과 PC가 같은 Wi-Fi인지 확인")
        print("  2. iPhone에서 NDI HX Camera 앱이 실행 중인지 확인")
        print("  3. 방화벽에서 NDI 포트(5353, 5960-5969) 허용 확인")

    return sources


def receive_preview(source_name: str = None):
    """NDI 영상을 OpenCV 창으로 미리보기."""
    try:
        import cv2
    except ImportError:
        print("opencv-python 미설치: pip install opencv-python")
        return

    if not ndi.initialize():
        return

    finder = ndi.find_create_v2()
    print("NDI 소스 탐색 중...")
    ndi.find_wait_for_sources(finder, 5000)
    sources = ndi.find_get_current_sources(finder)

    if not sources:
        print("소스 없음")
        ndi.find_destroy(finder)
        ndi.destroy()
        return

    # 소스 선택
    target = sources[0]
    if source_name:
        for s in sources:
            if source_name.lower() in s.ndi_name.lower():
                target = s
                break

    print(f"연결: {target.ndi_name}")

    # NDI 수신기 생성
    recv_create = ndi.RecvCreateV3()
    recv_create.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
    recv = ndi.recv_create_v3(recv_create)

    if not recv:
        print("수신기 생성 실패")
        ndi.find_destroy(finder)
        ndi.destroy()
        return

    ndi.recv_connect(recv, target)
    ndi.find_destroy(finder)

    print("수신 시작... (ESC로 종료)")
    frame_count = 0
    start = time.time()

    while True:
        # 프레임 수신
        t, v, a, _ = ndi.recv_capture_v3(recv, 1000)

        if t == ndi.FRAME_TYPE_VIDEO:
            # BGRX → BGR numpy array
            frame = np.copy(v.data)
            h, w = v.yres, v.xres
            frame = frame.reshape(h, w, 4)[:, :, :3]  # BGRX → BGR

            frame_count += 1
            elapsed = time.time() - start
            fps = frame_count / elapsed if elapsed > 0 else 0

            # FPS 표시
            cv2.putText(
                frame, f"NDI: {target.ndi_name} | {w}x{h} | {fps:.1f}fps",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )

            cv2.imshow("LiveCat NDI Preview", frame)
            ndi.recv_free_video_v2(recv, v)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break

    cv2.destroyAllWindows()
    ndi.recv_destroy(recv)
    ndi.destroy()
    print(f"\n수신 종료: {frame_count} frames, {elapsed:.1f}초")


def record_clip(source_name: str = None, duration_sec: int = 20):
    """NDI → MP4 녹화."""
    try:
        import cv2
    except ImportError:
        print("opencv-python 미설치: pip install opencv-python")
        return

    if not ndi.initialize():
        return

    finder = ndi.find_create_v2()
    print("NDI 소스 탐색 중...")
    ndi.find_wait_for_sources(finder, 5000)
    sources = ndi.find_get_current_sources(finder)

    if not sources:
        print("소스 없음")
        ndi.find_destroy(finder)
        ndi.destroy()
        return

    target = sources[0]
    if source_name:
        for s in sources:
            if source_name.lower() in s.ndi_name.lower():
                target = s
                break

    print(f"연결: {target.ndi_name}")
    print(f"녹화: {duration_sec}초")

    recv_create = ndi.RecvCreateV3()
    recv_create.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
    recv = ndi.recv_create_v3(recv_create)
    ndi.recv_connect(recv, target)
    ndi.find_destroy(finder)

    # 첫 프레임으로 해상도 확인
    print("첫 프레임 대기 중...")
    w, h, fps_actual = 1920, 1080, 30
    for _ in range(100):
        t, v, a, _ = ndi.recv_capture_v3(recv, 1000)
        if t == ndi.FRAME_TYPE_VIDEO:
            w, h = v.xres, v.yres
            ndi.recv_free_video_v2(recv, v)
            break

    print(f"해상도: {w}x{h}")

    # 저장 설정
    output_path = ROOT_DIR / "tests" / f"ndi_record_{int(time.time())}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, 30, (w, h))

    print(f"녹화 시작...")
    frame_count = 0
    start = time.time()

    while time.time() - start < duration_sec:
        t, v, a, _ = ndi.recv_capture_v3(recv, 1000)
        if t == ndi.FRAME_TYPE_VIDEO:
            frame = np.copy(v.data).reshape(v.yres, v.xres, 4)[:, :, :3]
            writer.write(frame)
            frame_count += 1
            ndi.recv_free_video_v2(recv, v)

            elapsed = time.time() - start
            if frame_count % 30 == 0:
                print(f"  {elapsed:.0f}/{duration_sec}초 ({frame_count} frames)")

    writer.release()
    ndi.recv_destroy(recv)
    ndi.destroy()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\n녹화 완료: {output_path}")
    print(f"  {frame_count} frames, {size_mb:.1f}MB")
    print(f"\n다음 단계: python tests/test_pipeline_e2e.py --input {output_path}")


def main():
    parser = argparse.ArgumentParser(description="LiveCat NDI 수신 테스트")
    parser.add_argument("--source", "-s", help="NDI 소스 이름 (부분 매칭)")
    parser.add_argument("--preview", "-p", action="store_true", help="OpenCV 미리보기")
    parser.add_argument("--record", "-r", type=int, metavar="SEC", help="N초 녹화")

    args = parser.parse_args()

    if args.preview:
        receive_preview(args.source)
    elif args.record:
        record_clip(args.source, args.record)
    else:
        # 소스 탐색만
        sources = find_sources()
        if sources:
            print(f"\n다음 단계:")
            print(f"  미리보기: python tests/test_ndi_receiver.py --preview")
            print(f"  녹화:     python tests/test_ndi_receiver.py --record 20")


if __name__ == "__main__":
    main()
