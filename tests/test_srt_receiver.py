"""SRT VideoReceiver 통합 테스트.

iPhone Larix에서 srt://192.168.123.106:9000 으로 전송 중일 때 실행.
15초간 프레임을 수신하고 첫 프레임을 이미지로 저장한다.
"""
import asyncio
import time
import cv2
import numpy as np
from loguru import logger

# Minimal StreamBuffer mock
class MockStreamBuffer:
    def __init__(self):
        self.frame_count = 0
        self.first_frame = None
        self.last_frame = None

    async def push_frame(self, cam_id, frame):
        self.frame_count += 1
        self.last_frame = frame
        if self.first_frame is None:
            self.first_frame = frame.copy()
        if self.frame_count % 30 == 0:
            fps = self.frame_count / (time.time() - self.start)
            print(f"  [{cam_id}] frames={self.frame_count} fps={fps:.1f}", flush=True)


async def main():
    # Inline import to avoid package issues
    import sys, os
    sys.path.insert(0, "D:/livecat")

    from server.receiver.video_receiver import VideoReceiver

    config = {
        "camera": {
            "count": 1,
            "resolution": "720p",
            "fps": 30,
            "protocol": "srt",
            "cameras": [
                {"id": "CAM-1", "srt_port": 9000, "role": "test"},
            ],
        }
    }

    buf = MockStreamBuffer()
    buf.start = time.time()
    recv = VideoReceiver(config, buf)

    print("=" * 50)
    print("SRT VideoReceiver Test")
    print("=" * 50)
    print("Listening on SRT port 9000...")
    print("Start Larix Broadcaster on iPhone")
    print()

    # Run for 15 seconds
    task = asyncio.create_task(recv.run())
    await asyncio.sleep(15)
    await recv.stop()

    print()
    print(f"Total frames: {buf.frame_count}")
    if buf.frame_count > 0:
        elapsed = time.time() - buf.start
        print(f"FPS: {buf.frame_count / elapsed:.1f}")
        print(f"Frame shape: {buf.last_frame.shape}")

        # Save first frame
        out = "D:/livecat/tests/srt_receiver_frame.jpg"
        cv2.imwrite(out, buf.first_frame)
        print(f"Saved: {out}")
        print("SUCCESS!")
    else:
        print("No frames received.")


if __name__ == "__main__":
    asyncio.run(main())
