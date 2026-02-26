"""Quick NDI receive test with cyndilib."""
import os
import sys
import time

os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

from cyndilib import Finder, Receiver
from cyndilib.receiver import ReceiveFrameType
from cyndilib.video_frame import VideoRecvFrame
from cyndilib.audio_frame import AudioRecvFrame
import numpy as np

def main():
    # Find source
    f = Finder()
    f.open()
    print("Finding NDI source...", flush=True)
    f.wait_for_sources(8)
    names = f.get_source_names()
    print(f"Sources: {names}", flush=True)

    if not names:
        print("No sources found!")
        f.close()
        return

    src = f.get_source(names[0])
    print(f"Connecting to: {names[0]}", flush=True)

    # Create receiver
    recv = Receiver()

    # Set frame buffers
    vf = VideoRecvFrame()
    af = AudioRecvFrame()
    recv.set_video_frame(vf)
    recv.set_audio_frame(af)

    # Connect
    recv.set_source(src)
    time.sleep(1)
    print(f"Connected: {recv.is_connected()}", flush=True)
    print(f"Num connections: {recv.get_num_connections()}", flush=True)

    # Receive
    frame_count = 0
    audio_count = 0
    meta_count = 0
    start = time.time()
    max_time = 30  # 30 seconds max

    while time.time() - start < max_time:
        elapsed = time.time() - start

        # Try video
        try:
            result = recv.receive(ReceiveFrameType.recv_video, 500)
            if result == ReceiveFrameType.recv_video:
                frame_count += 1
                w, h = vf.xres, vf.yres
                fourcc = vf.fourcc if hasattr(vf, 'fourcc') else 'N/A'
                fps = frame_count / elapsed if elapsed > 0 else 0
                print(f"  VIDEO #{frame_count}: {w}x{h} fourcc={fourcc} {fps:.1f}fps", flush=True)
                if frame_count >= 5:
                    try:
                        arr = np.array(vf)
                        print(f"  -> numpy shape={arr.shape} dtype={arr.dtype}", flush=True)
                    except Exception as e:
                        print(f"  -> numpy error: {e}", flush=True)
                    break
        except Exception as e:
            print(f"  recv error: {type(e).__name__}: {e}", flush=True)

        # Try audio
        try:
            result = recv.receive(ReceiveFrameType.recv_audio, 100)
            if result == ReceiveFrameType.recv_audio:
                audio_count += 1
                if audio_count <= 3:
                    print(f"  AUDIO #{audio_count}", flush=True)
        except:
            pass

        # Try metadata
        try:
            result = recv.receive(ReceiveFrameType.recv_metadata, 100)
            if result == ReceiveFrameType.recv_metadata:
                meta_count += 1
                print(f"  METADATA #{meta_count}", flush=True)
        except:
            pass

        # Status
        if int(elapsed) % 5 == 0 and int(elapsed) > 0 and frame_count == 0:
            connected = recv.is_connected()
            n_conn = recv.get_num_connections()
            print(f"  [{elapsed:.0f}s] connected={connected} conns={n_conn} v={frame_count} a={audio_count}", flush=True)
            time.sleep(1)  # Avoid spam

    recv.disconnect()
    f.close()
    total = time.time() - start
    print(f"\nDone: {frame_count} video, {audio_count} audio, {meta_count} meta in {total:.1f}s", flush=True)


if __name__ == "__main__":
    main()
