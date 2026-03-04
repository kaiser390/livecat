"""
LiveCat Auto Live - iPhone WebSocket → OBS Stream → YouTube Live

Detects streaming state by metadata messages (10Hz from iPhone).
  - Metadata arriving → iPhone is streaming → Start OBS
  - No metadata for 5s → iPhone stopped → Stop OBS

Usage:
  python tests/live_auto.py
"""
import asyncio
import json
import locale
import os
import subprocess
import sys
import time
from datetime import datetime

# Fix OBS WebSocket locale issue on Windows
os.environ['LANG'] = 'en_US.UTF-8'
os.environ['LC_ALL'] = 'en_US.UTF-8'

try:
    import websockets
except ImportError:
    print("[ERROR] pip install websockets")
    sys.exit(1)

try:
    import obsws_python as obsws
except ImportError:
    print("[ERROR] pip install obsws-python")
    sys.exit(1)

# Config
WS_PORT = 8081
HTTP_PORT = 8082
OBS_HOST = "localhost"
OBS_PORT = 4455
IDLE_TIMEOUT = 5  # seconds without metadata → stop OBS

# State
clients = set()
is_obs_streaming = False
stream_start_time = None
last_metadata_time = 0  # last time we received metadata


def ts():
    return datetime.now().strftime('%H:%M:%S')


def obs_start():
    """Start OBS streaming + recording"""
    global is_obs_streaming, stream_start_time
    if is_obs_streaming:
        return True

    try:
        ws = obsws.ReqClient(host=OBS_HOST, port=OBS_PORT)
        status = ws.get_stream_status()
        already_streaming = status.output_active
        if not already_streaming:
            ws.start_stream()
            print(f"  [{ts()}] OBS STREAM STARTED")
        else:
            print(f"  [{ts()}] OBS already streaming")
        # Always start recording if not already recording
        try:
            rec_status = ws.get_record_status()
            if not rec_status.output_active:
                ws.start_record()
                print(f"  [{ts()}] OBS RECORDING STARTED (local)")
            else:
                print(f"  [{ts()}] OBS already recording")
        except Exception as e:
            print(f"  [{ts()}] Recording start skipped: {e}")
        ws.disconnect()
        is_obs_streaming = True
        stream_start_time = time.time()
        return True
    except Exception as e:
        print(f"  [{ts()}] OBS start failed: {e}")
        return False


def obs_stop():
    """Stop OBS streaming + recording"""
    global is_obs_streaming, stream_start_time
    if not is_obs_streaming:
        return

    try:
        ws = obsws.ReqClient(host=OBS_HOST, port=OBS_PORT)
        status = ws.get_stream_status()
        if status.output_active:
            duration = status.output_duration // 1000
            m, s = divmod(duration, 60)
            print(f"  [{ts()}] Stream duration: {m:.0f}m {s:.0f}s")
            ws.stop_stream()
        # Stop local recording
        try:
            rec_status = ws.get_record_status()
            if rec_status.output_active:
                result = ws.stop_record()
                path = getattr(result, 'output_path', '')
                print(f"  [{ts()}] OBS RECORDING SAVED: {path}")
                if path:
                    subprocess.Popen(
                        [sys.executable, "-u", "D:/livecat/post_live.py", path, "--num-shorts", "2", "--dry-run"],
                        creationflags=0x00000008,  # DETACHED_PROCESS
                    )
                    print(f"  [{ts()}] Post-live pipeline launched")
        except Exception:
            pass
        ws.disconnect()
    except Exception as e:
        print(f"  [{ts()}] OBS stop failed: {e}")

    is_obs_streaming = False
    stream_start_time = None
    print(f"  [{ts()}] OBS STREAM STOPPED")


async def idle_monitor():
    """Monitor metadata flow. No metadata for IDLE_TIMEOUT → stop OBS."""
    global last_metadata_time
    while True:
        await asyncio.sleep(1)
        if not is_obs_streaming:
            continue
        if last_metadata_time == 0:
            continue
        elapsed = time.time() - last_metadata_time
        if elapsed > IDLE_TIMEOUT:
            print(f"  [{ts()}] No metadata for {IDLE_TIMEOUT}s → iPhone stopped")
            obs_stop()
            print()
            print(f"  [{ts()}] Waiting for iPhone START...")


async def handle_client(websocket):
    """Handle iPhone WebSocket connection"""
    global last_metadata_time
    addr = websocket.remote_address
    clients.add(websocket)
    print(f"  [{ts()}] iPhone CONNECTED: {addr}")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', '')

                if msg_type == 'register':
                    cam_id = data.get('cam_id', 'unknown')
                    print(f"  [{ts()}] Registered: {cam_id}")
                    await websocket.send(json.dumps({
                        "type": "registered",
                        "status": "ok"
                    }))
                elif msg_type == 'response':
                    print(f"  [{ts()}] Response: {data}")
                else:
                    # Metadata message → iPhone is streaming
                    last_metadata_time = time.time()
                    if not is_obs_streaming:
                        print(f"  [{ts()}] Metadata received → Starting OBS...")
                        obs_start()

            except json.JSONDecodeError:
                pass
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.discard(websocket)
        print(f"  [{ts()}] iPhone DISCONNECTED: {addr}")


async def send_to_iphone(cmd: dict):
    """Send command to all connected iPhones"""
    if not clients:
        return False
    msg = json.dumps(cmd)
    for ws in clients.copy():
        try:
            await ws.send(msg)
            return True
        except:
            clients.discard(ws)
    return False


async def smooth_zoom(start, end, duration, steps):
    """Smooth zoom via WebSocket"""
    step_time = duration / steps
    for i in range(steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        factor = start + (end - start) * t
        await send_to_iphone({"cmd": "zoom", "factor": round(factor, 3)})
        if i < steps:
            await asyncio.sleep(step_time)


async def http_handler(reader, writer):
    """HTTP command endpoint (port 8082)"""
    try:
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        request = data.decode('utf-8', errors='replace')

        if 'POST /smooth_zoom' in request:
            body = request.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in request else ''
            try:
                params = json.loads(body)
                await smooth_zoom(
                    float(params.get('from', 1.0)),
                    float(params.get('to', 3.0)),
                    float(params.get('duration', 1.0)),
                    int(params.get('steps', 30))
                )
                resp_body = json.dumps({"ok": True})
            except Exception as e:
                resp_body = json.dumps({"ok": False, "error": str(e)})

        elif 'POST /cmd' in request:
            body = request.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in request else ''
            try:
                cmd = json.loads(body)
                success = await send_to_iphone(cmd)
                resp_body = json.dumps({"ok": success})
            except:
                resp_body = json.dumps({"ok": False})

        elif 'GET /status' in request:
            resp_body = json.dumps({
                "clients": len(clients),
                "obs_streaming": is_obs_streaming,
                "uptime": int(time.time() - stream_start_time) if stream_start_time else 0,
            })
        else:
            resp_body = "POST /cmd, POST /smooth_zoom, GET /status\n"

        response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(resp_body)}\r\n\r\n{resp_body}"
        writer.write(response.encode())
        await writer.drain()
    except:
        pass
    finally:
        writer.close()


async def main():
    print("=" * 50)
    print("  LiveCat Auto Live")
    print("=" * 50)
    print()
    print("  Metadata arriving  -> OBS ON  -> YouTube Live")
    print("  No metadata 5s     -> OBS OFF -> YouTube auto-ends")
    print()

    # Verify OBS connection (retry up to 60s for OBS to start)
    obs_connected = False
    print(f"  [OBS] Connecting to OBS...", end="", flush=True)
    for attempt in range(30):
        try:
            ws = obsws.ReqClient(host=OBS_HOST, port=OBS_PORT)
            status = ws.get_stream_status()
            streaming = status.output_active
            print(f" OK (currently {'LIVE' if streaming else 'OFF'})")
            if streaming:
                try:
                    ws.stop_stream()
                    print(f"  [OBS] Stopped existing stream for clean start")
                except Exception:
                    pass
            ws.disconnect()
            obs_connected = True
            break
        except Exception:
            print(".", end="", flush=True)
            await asyncio.sleep(2)
    if not obs_connected:
        print(" FAILED")
        print(f"  Make sure OBS is running with WebSocket enabled (port {OBS_PORT})")
        return

    # WebSocket server
    ws_server = await websockets.serve(handle_client, "0.0.0.0", WS_PORT)
    print(f"  [WS] Server on port {WS_PORT}")

    # HTTP command endpoint
    http_server = await asyncio.start_server(http_handler, "0.0.0.0", HTTP_PORT)
    print(f"  [HTTP] Command endpoint on port {HTTP_PORT}")
    print()
    print(f"  [{ts()}] Waiting for iPhone START...")
    print()

    await asyncio.gather(
        ws_server.serve_forever(),
        http_server.serve_forever(),
        idle_monitor(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if is_obs_streaming:
            obs_stop()
        print("\n  Stopped.")
