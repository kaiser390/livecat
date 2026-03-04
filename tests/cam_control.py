"""
iPhone Camera Remote Controller
Sends zoom/focus/exposure commands to iPhone via TCP WebSocket (port 8081)

Usage:
  python tests/cam_control.py --zoom 2.0
  python tests/cam_control.py --focus 0.5 0.5
  python tests/cam_control.py --reset
  python tests/cam_control.py              # Interactive mode
"""
import json
import sys
import asyncio
import websockets

IPHONE_IP = "192.168.123.100"
WS_PORT = 8081
WS_URL = f"ws://{IPHONE_IP}:{WS_PORT}"


async def send_command(cmd: dict):
    """Send a single command to iPhone"""
    try:
        async with websockets.connect(WS_URL, close_timeout=3) as ws:
            msg = json.dumps(cmd)
            await ws.send(msg)
            print(f"Sent: {msg}")
            # Wait for response
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=3)
                print(f"Response: {resp}")
            except asyncio.TimeoutError:
                print("No response (timeout)")
    except Exception as e:
        print(f"Connection failed: {e}")


def cmd_zoom(factor: float):
    return {"cmd": "zoom", "factor": factor}


def cmd_focus(x: float, y: float):
    return {"cmd": "focus", "x": x, "y": y}


def cmd_exposure(x: float, y: float):
    return {"cmd": "exposure", "x": x, "y": y}


def cmd_reset():
    return {"cmd": "reset"}


async def interactive():
    """Interactive camera control"""
    print("=== iPhone Camera Controller ===")
    print(f"Target: {WS_URL}")
    print()
    print("Commands:")
    print("  z <factor>      - Zoom (e.g. 'z 2.0', range 0.5~15)")
    print("  f <x> <y>       - Focus at point (e.g. 'f 0.5 0.5')")
    print("  e <x> <y>       - Exposure at point")
    print("  r               - Reset (zoom 1x, auto focus)")
    print("  q               - Quit")
    print()

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        parts = line.split()
        action = parts[0].lower()

        if action == 'q':
            break
        elif action == 'r':
            await send_command(cmd_reset())
        elif action == 'z':
            factor = float(parts[1]) if len(parts) > 1 else 2.0
            await send_command(cmd_zoom(factor))
        elif action == 'f':
            x = float(parts[1]) if len(parts) > 1 else 0.5
            y = float(parts[2]) if len(parts) > 2 else 0.5
            await send_command(cmd_focus(x, y))
        elif action == 'e':
            x = float(parts[1]) if len(parts) > 1 else 0.5
            y = float(parts[2]) if len(parts) > 2 else 0.5
            await send_command(cmd_exposure(x, y))
        else:
            print("Unknown. Use z/f/e/r/q")


if __name__ == "__main__":
    if "--zoom" in sys.argv:
        idx = sys.argv.index("--zoom")
        factor = float(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 2.0
        asyncio.run(send_command(cmd_zoom(factor)))
    elif "--focus" in sys.argv:
        idx = sys.argv.index("--focus")
        x = float(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 0.5
        y = float(sys.argv[idx + 2]) if idx + 2 < len(sys.argv) else 0.5
        asyncio.run(send_command(cmd_focus(x, y)))
    elif "--reset" in sys.argv:
        asyncio.run(send_command(cmd_reset()))
    else:
        asyncio.run(interactive())
