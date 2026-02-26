"""SRT receive test - receive video from iPhone via SRT protocol.

Setup:
1. Install "Larix Broadcaster" on iPhone (free from App Store)
2. In Larix: Settings > Connections > New Connection
   - URL: srt://192.168.123.106:9000
   - Mode: Caller
3. Run this script on PC
4. Start streaming in Larix
"""
import subprocess
import sys
import time
import os

# PC's WiFi IP (the USB WiFi adapter)
LISTEN_PORT = 9000
OUTPUT_FILE = "D:/livecat/tests/srt_test_output.mp4"
PREVIEW_FILE = "D:/livecat/tests/srt_frame_%04d.jpg"


def test_srt_listen():
    """Start SRT listener and save incoming stream."""
    print("=" * 50)
    print("SRT Receive Test")
    print("=" * 50)
    print()
    print(f"Listening on SRT port {LISTEN_PORT}...")
    print(f"Output: {OUTPUT_FILE}")
    print()
    print("iPhone Setup (Larix Broadcaster):")
    print(f"  URL: srt://192.168.123.106:{LISTEN_PORT}")
    print("  Mode: Caller")
    print()
    print("Waiting for connection... (Ctrl+C to stop)")
    print()

    # SRT listener mode: ffmpeg listens, iPhone connects
    cmd = [
        "ffmpeg", "-y",
        "-i", f"srt://0.0.0.0:{LISTEN_PORT}?mode=listener&timeout=30000000",
        "-c", "copy",  # Don't re-encode, just copy
        "-t", "15",    # Record 15 seconds
        "-f", "mp4",
        OUTPUT_FILE,
    ]

    print(f"CMD: {' '.join(cmd)}")
    print()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for completion or timeout
        try:
            stdout, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()

        output = stderr.decode("utf-8", errors="replace")
        print("--- ffmpeg output ---")
        # Print last 30 lines
        lines = output.strip().split("\n")
        for line in lines[-30:]:
            print(f"  {line}")
        print("---")

        if os.path.exists(OUTPUT_FILE):
            size = os.path.getsize(OUTPUT_FILE)
            print(f"\nOutput file: {OUTPUT_FILE} ({size:,} bytes)")
            if size > 10000:
                print("SUCCESS! Video received via SRT!")

                # Extract a frame for verification
                subprocess.run([
                    "ffmpeg", "-y", "-i", OUTPUT_FILE,
                    "-vframes", "1", "-q:v", "2",
                    "D:/livecat/tests/srt_frame.jpg"
                ], capture_output=True)

                if os.path.exists("D:/livecat/tests/srt_frame.jpg"):
                    fsize = os.path.getsize("D:/livecat/tests/srt_frame.jpg")
                    print(f"Frame extracted: srt_frame.jpg ({fsize:,} bytes)")
            else:
                print("File too small - may not have received video data.")
        else:
            print("\nNo output file created.")

    except KeyboardInterrupt:
        print("\nStopped by user.")
        proc.kill()
    except Exception as e:
        print(f"\nError: {e}")


def test_srt_preview():
    """SRT listener with live console output showing frame info."""
    print("=" * 50)
    print("SRT Live Preview (console stats)")
    print("=" * 50)
    print()
    print(f"Listening on SRT port {LISTEN_PORT}...")
    print("Waiting for iPhone to connect...")
    print()

    cmd = [
        "ffmpeg",
        "-i", f"srt://0.0.0.0:{LISTEN_PORT}?mode=listener&timeout=30000000",
        "-t", "10",
        "-vf", "fps=1",  # 1 frame per second
        "-q:v", "5",
        PREVIEW_FILE,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout, stderr = proc.communicate(timeout=45)
        output = stderr.decode("utf-8", errors="replace")

        # Show stream info
        for line in output.split("\n"):
            if any(k in line.lower() for k in ["stream", "video:", "audio:", "input", "output", "frame"]):
                print(f"  {line.strip()}")

        # Check extracted frames
        import glob
        frames = glob.glob("D:/livecat/tests/srt_frame_*.jpg")
        print(f"\nExtracted {len(frames)} frames")
        for f in frames[:3]:
            print(f"  {f} ({os.path.getsize(f):,} bytes)")

    except subprocess.TimeoutExpired:
        proc.kill()
        print("Timeout - no connection received.")
    except KeyboardInterrupt:
        proc.kill()
        print("Stopped.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        test_srt_preview()
    else:
        test_srt_listen()
