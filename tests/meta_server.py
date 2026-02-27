"""
LiveCat Metadata + Camera Control Server (WebSocket)
- Receives metadata from iPhone
- Sends camera control commands TO iPhone
- Port 8081

Usage:
  python tests/meta_server.py
"""
import asyncio
import json
import websockets
import sys
from datetime import datetime

# Connected iPhone clients
clients = set()
# Command queue (PC -> iPhone)
cmd_queue = asyncio.Queue()


async def handle_client(websocket):
    """Handle iPhone WebSocket connection"""
    addr = websocket.remote_address
    clients.add(websocket)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] iPhone connected: {addr}")

    try:
        async for message in websocket:
            # Metadata from iPhone
            ts = datetime.now().strftime('%H:%M:%S')
            try:
                data = json.loads(message)
                if data.get('type') == 'response':
                    print(f"[{ts}] Response: {data}")
                else:
                    # Print metadata compactly
                    print(f"[{ts}] Meta: {message[:100]}")
            except json.JSONDecodeError:
                print(f"[{ts}] Raw: {message[:100]}")
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.discard(websocket)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] iPhone disconnected: {addr}")


async def send_to_iphone(cmd: dict):
    """Send command to all connected iPhones"""
    if not clients:
        print("No iPhone connected!")
        return False

    msg = json.dumps(cmd)
    for ws in clients.copy():
        try:
            await ws.send(msg)
            print(f"Sent to {ws.remote_address}: {msg}")
            return True
        except Exception as e:
            print(f"Send error: {e}")
            clients.discard(ws)
    return False


async def command_processor():
    """Process commands from the queue"""
    while True:
        cmd = await cmd_queue.get()
        await send_to_iphone(cmd)


async def smooth_zoom(start, end, duration, steps):
    """Send smooth zoom commands via WebSocket (no HTTP round-trip per step)"""
    step_time = duration / steps
    for i in range(steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # ease in-out
        factor = start + (end - start) * t
        await send_to_iphone({"cmd": "zoom", "factor": round(factor, 3)})
        if i < steps:
            await asyncio.sleep(step_time)


async def http_command_handler(reader, writer):
    """HTTP endpoint for receiving commands from other scripts (port 8082)"""
    try:
        data = await asyncio.wait_for(reader.read(4096), timeout=5)
        request = data.decode('utf-8', errors='replace')

        if 'POST /smooth_zoom' in request:
            body = request.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in request else ''
            try:
                params = json.loads(body)
                start = float(params.get('from', 1.0))
                end = float(params.get('to', 3.0))
                duration = float(params.get('duration', 1.0))
                steps = int(params.get('steps', 30))
                await smooth_zoom(start, end, duration, steps)
                response_body = json.dumps({"ok": True, "steps": steps, "duration": duration})
            except Exception as e:
                response_body = json.dumps({"ok": False, "error": str(e)})
            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                f"\r\n{response_body}"
            )
        elif 'POST /cmd' in request:
            # Extract body
            body = request.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in request else ''
            try:
                cmd = json.loads(body)
                success = await send_to_iphone(cmd)
                response_body = json.dumps({"ok": success})
            except json.JSONDecodeError:
                response_body = json.dumps({"ok": False, "error": "invalid json"})

            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                f"\r\n{response_body}"
            )
        elif 'GET /status' in request:
            status = {
                "clients": len(clients),
                "addresses": [str(ws.remote_address) for ws in clients],
            }
            response_body = json.dumps(status)
            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                f"\r\n{response_body}"
            )
        else:
            help_text = "POST /cmd {json} - send command\nGET /status - check connections\n"
            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/plain\r\n"
                f"Content-Length: {len(help_text)}\r\n"
                f"\r\n{help_text}"
            )

        writer.write(response.encode())
        await writer.drain()
    except Exception as e:
        pass
    finally:
        writer.close()


async def main():
    # WebSocket server for iPhone (port 8081)
    ws_server = await websockets.serve(handle_client, "0.0.0.0", 8081)
    print(f"WebSocket server on port 8081 (iPhone connects here)")

    # HTTP command endpoint (port 8082)
    http_server = await asyncio.start_server(http_command_handler, "0.0.0.0", 8082)
    print(f"HTTP command endpoint on port 8082")
    print(f"  Send command: curl -X POST http://localhost:8082/cmd -d '{{\"cmd\":\"zoom\",\"factor\":2.0}}'")
    print(f"  Check status: curl http://localhost:8082/status")
    print()

    await asyncio.gather(
        ws_server.serve_forever(),
        http_server.serve_forever(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
