"""
LiveCat Real-time Listener & Responder
- Captures audio from iPhone MPEG-TS stream via UDP relay
- Transcribes with Whisper (small model)
- Responds with Claude API
- Speaks with TTS (pyttsx3)

Usage:
  python -u tests/live_listener.py
"""
import sys
# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import os
import sys
import time
import json
import socket
import subprocess
import threading
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import pyttsx3
import anthropic

# === Config ===
WHISPER_MODEL = "models/whisper/ggml-small.bin"
LISTEN_DURATION = 4       # seconds per chunk
SILENCE_THRESHOLD = -50   # dB
UDP_RECV_PORT = 9000      # iPhone sends here
UDP_OBS_PORT = 9001       # Forward to OBS
# Use project-local temp (avoids Windows path issues with ffmpeg filters)
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")

# Whisper hallucination phrases to REMOVE (not filter entire text)
HALLUCINATION_PHRASES = [
    "구독 / 좋아요", "구독과 좋아요", "구독", "좋아요",
    "MBC 뉴스 김성현입니다", "MBC 뉴스 김지경입니다", "MBC 뉴스 김상현입니다",
    "MBC 뉴스", "KBS 뉴스", "SBS 뉴스", "YTN",
    "시청해주셔서 감사합니다", "감사합니다",
    "자막", "번역", "기자입니다", "앵커", "리포트",
    "Please subscribe", "Thank you for watching",
]

# === Globals ===
tts_engine = None
claude_client = None
conversation = []
relay_running = True
ts_buffer = bytearray()
buffer_lock = threading.Lock()


def init_tts():
    global tts_engine
    tts_engine = pyttsx3.init()
    tts_engine.setProperty('rate', 170)
    for voice in tts_engine.getProperty('voices'):
        if 'Heami' in voice.name:
            tts_engine.setProperty('voice', voice.id)
            print(f"  TTS: {voice.name}")
            return
    print("  TTS: default")


def init_claude():
    global claude_client
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        print("  [ERROR] ANTHROPIC_API_KEY not set")
        return False
    claude_client = anthropic.Anthropic(api_key=api_key)
    print("  Claude API ready")
    return True


def udp_relay():
    """Receive UDP on 9000, forward to OBS on 9001, buffer for processing"""
    global relay_running, ts_buffer

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(('0.0.0.0', UDP_RECV_PORT))
    recv_sock.settimeout(1)

    fwd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"  UDP relay: :{UDP_RECV_PORT} -> :{UDP_OBS_PORT}")

    while relay_running:
        try:
            data, addr = recv_sock.recvfrom(65536)
            # Forward to OBS
            fwd_sock.sendto(data, ('127.0.0.1', UDP_OBS_PORT))
            # Buffer for audio processing
            with buffer_lock:
                ts_buffer.extend(data)
        except socket.timeout:
            continue
        except Exception as e:
            if relay_running:
                print(f"  Relay error: {e}")

    recv_sock.close()
    fwd_sock.close()


def grab_audio_chunk(duration):
    """Grab buffered TS data, extract audio with ffmpeg, return WAV path"""
    global ts_buffer

    # Wait for duration
    time.sleep(duration)

    # Grab buffer
    with buffer_lock:
        data = bytes(ts_buffer)
        ts_buffer.clear()

    print(f"  [buffer] {len(data)} bytes")
    if len(data) < 1000:
        print("  [skip] too little data")
        return None

    # Save TS chunk
    ts_path = os.path.join(TEMP_DIR, "chunk.ts")
    wav_path = os.path.join(TEMP_DIR, "chunk.wav")

    with open(ts_path, 'wb') as f:
        f.write(data)

    # Extract audio with ffmpeg
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", ts_path,
         "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
        capture_output=True, timeout=10
    )

    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
        return wav_path
    return None


def check_volume(wav_path):
    """Return max volume in dB"""
    result = subprocess.run(
        ["ffmpeg", "-i", wav_path, "-af", "volumedetect", "-f", "null", "NUL"],
        capture_output=True, text=True, timeout=10
    )
    for line in result.stderr.split('\n'):
        if 'max_volume' in line:
            try:
                return float(line.split('max_volume:')[1].split('dB')[0].strip())
            except (ValueError, IndexError):
                pass
    return -100.0


def transcribe(wav_path):
    """Run whisper on WAV file"""
    # Use relative paths to avoid Windows drive letter ':' breaking ffmpeg filter parsing
    wav_rel = os.path.relpath(wav_path).replace("\\", "/")
    txt_rel = "tests/temp/chunk.txt"
    txt_abs = os.path.abspath(txt_rel)

    if os.path.exists(txt_abs):
        os.remove(txt_abs)

    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_rel,
         "-af", f"whisper=model={WHISPER_MODEL}:language=ko:destination={txt_rel}",
         "-f", "null", "NUL"],
        capture_output=True, timeout=30
    )

    if os.path.exists(txt_abs):
        with open(txt_abs, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""


def clean_hallucinations(text):
    """Remove hallucination phrases and return cleaned text"""
    import re
    cleaned = text
    # Remove bracketed content like [구독 / 좋아요] [감사합니다]
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    # Remove known hallucination phrases (longest first)
    for phrase in sorted(HALLUCINATION_PHRASES, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, '')
    # Clean up punctuation mess
    cleaned = re.sub(r'[-—.~,]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip(' -.,~')
    return cleaned


def is_meaningful(text):
    if not text or len(text) < 2:
        return False, ""
    cleaned = clean_hallucinations(text)
    if len(cleaned) < 2:
        return False, ""
    return True, cleaned


def get_response(text):
    global conversation
    conversation.append({"role": "user", "content": text})
    if len(conversation) > 20:
        conversation = conversation[-20:]

    response = claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=(
            "너는 고양이 나나와 토토를 지켜보는 AI 어시스턴트 '클로드'야. "
            "아이폰 카메라로 실시간 영상을 보고 있어. "
            "한국어로 자연스럽고 따뜻하게 대답해. "
            "짧게 1~2문장으로 답해. 이모티콘 쓰지 마."
        ),
        messages=conversation
    )
    reply = response.content[0].text
    conversation.append({"role": "assistant", "content": reply})
    return reply


def speak(text):
    tts_engine.say(text)
    tts_engine.runAndWait()


def main():
    global relay_running

    print("=" * 50)
    print("  LiveCat Real-time Listener")
    print("=" * 50)
    print()
    print("[Init]")

    os.makedirs(TEMP_DIR, exist_ok=True)
    init_tts()

    if not init_claude():
        return

    # NOTE: Before running, change OBS iPhone_LiveCat source to port 9001
    print()
    print(f"  iPhone UDP -> :{UDP_RECV_PORT} -> relay -> :{UDP_OBS_PORT} (OBS)")
    print()
    print("  ** OBS iPhone_LiveCat source must use port 9001 **")
    print()

    # Start UDP relay
    relay_thread = threading.Thread(target=udp_relay, daemon=True)
    relay_thread.start()
    print(f"Whisper: {WHISPER_MODEL}")
    print(f"Chunk: {LISTEN_DURATION}s | Silence: {SILENCE_THRESHOLD}dB")
    print()
    print("Listening... (Ctrl+C to stop)")
    print("-" * 50)

    try:
        while True:
            # Grab audio chunk
            wav_path = grab_audio_chunk(LISTEN_DURATION)
            if not wav_path:
                continue

            # Check volume
            max_vol = check_volume(wav_path)
            print(f"  [volume] max={max_vol:.1f}dB")
            if max_vol < SILENCE_THRESHOLD:
                continue

            # Transcribe
            text = transcribe(wav_path)
            if not text:
                continue

            ts = time.strftime('%H:%M:%S')
            print(f"[{ts}] Raw: {text}")

            meaningful, cleaned = is_meaningful(text)
            if not meaningful:
                print(f"         (filtered)")
                continue

            print(f"         Heard: {cleaned}")

            # Claude response
            reply = get_response(cleaned)
            print(f"         Reply: {reply}")

            # Speak
            speak(reply)

    except KeyboardInterrupt:
        pass
    finally:
        relay_running = False
        print("\nStopped.")


if __name__ == "__main__":
    main()
