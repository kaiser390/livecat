"""NDI receive test using FrameSync API."""
import os
import sys
import time

os.environ['NDILIB_EXTRA_IPS'] = '192.168.123.108'

from cyndilib import Finder, Receiver
from cyndilib.framesync import FrameSync
from cyndilib.video_frame import VideoRecvFrame, VideoFrameSync
from cyndilib.audio_frame import AudioRecvFrame, AudioFrameSync
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

    # Create FrameSync (wraps the receiver)
    fs = recv.frame_sync

    # Set frame buffers
    vf = VideoFrameSync()
    af = AudioFrameSync()
    fs.set_video_frame(vf)
    fs.set_audio_frame(af)

    # Connect
    recv.set_source(src)
    time.sleep(2)  # Wait for connection
    print(f"Connected: {recv.is_connected()}", flush=True)

    # Receive using FrameSync
    frame_count = 0
    start = time.time()
    max_time = 20

    while time.time() - start < max_time:
        elapsed = time.time() - start

        try:
            fs.capture_video()
            w, h = vf.xres, vf.yres
            if w > 0 and h > 0:
                frame_count += 1
                fps = frame_count / elapsed if elapsed > 0 else 0
                print(f"  VIDEO #{frame_count}: {w}x{h} {fps:.1f}fps", flush=True)

                if frame_count >= 5:
                    try:
                        arr = np.array(vf)
                        print(f"  -> shape={arr.shape} dtype={arr.dtype}", flush=True)
                        # Save a frame as test
                        if arr.ndim >= 2:
                            np.save("D:/livecat/tests/ndi_frame.npy", arr)
                            print(f"  -> Saved frame to ndi_frame.npy", flush=True)
                    except Exception as e:
                        print(f"  -> numpy error: {e}", flush=True)
                    break
            else:
                if int(elapsed) % 3 == 0:
                    connected = recv.is_connected()
                    print(f"  [{elapsed:.0f}s] No video yet. connected={connected}", flush=True)
                    time.sleep(1)
        except Exception as e:
            print(f"  Error: {type(e).__name__}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(0.5)

        time.sleep(0.033)  # ~30fps polling

    recv.disconnect()
    f.close()
    print(f"\nDone: {frame_count} frames in {time.time()-start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
