"""
LiveCat Messenger - PC <-> MacBook Claude Code 통신용
Usage:
  PC에서 서버 실행:   python tests/messenger.py --serve
  MacBook에서 전송:   curl -X POST http://192.168.123.106:8888/msg -d "hello from macbook"
  MacBook에서 읽기:   curl http://192.168.123.106:8888/msg
"""
import sys
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

messages = []
lock = threading.Lock()

class MsgHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/msg":
            with lock:
                data = json.dumps(messages[-20:], ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(data.encode("utf-8"))
        elif self.path == "/new":
            # 새 메시지만 (last N초)
            with lock:
                data = json.dumps(messages[-5:], ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(data.encode("utf-8"))
        elif self.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"pong")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            help_text = (
                "LiveCat Messenger\n"
                "POST /msg  body=message  -> send message\n"
                "GET  /msg               -> read all messages\n"
                "GET  /new               -> read latest 5\n"
                "GET  /ping              -> health check\n"
            )
            self.wfile.write(help_text.encode("utf-8"))

    def do_POST(self):
        if self.path == "/msg":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", errors="replace")

            # JSON or plain text
            try:
                data = json.loads(body)
                sender = data.get("from", "unknown")
                text = data.get("text", body)
            except (json.JSONDecodeError, AttributeError):
                sender = "remote"
                text = body

            msg = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "from": sender,
                "text": text
            }
            with lock:
                messages.append(msg)

            print(f"[{msg['time']}] {msg['from']}: {msg['text']}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "id": len(messages)}, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress default logging

def send_message(host, port, sender, text):
    """Send a message to the messenger server"""
    import urllib.request
    data = json.dumps({"from": sender, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/msg",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Send failed: {e}")
        return None

def read_messages(host, port):
    """Read messages from the messenger server"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/msg", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Read failed: {e}")
        return []

if __name__ == "__main__":
    port = 8888

    if "--serve" in sys.argv or len(sys.argv) == 1:
        server = HTTPServer(("0.0.0.0", port), MsgHandler)
        print(f"Messenger server on port {port}")
        print(f"MacBook usage:")
        print(f"  Send: curl -X POST http://192.168.123.106:{port}/msg -H 'Content-Type: application/json' -d '{{\"from\":\"macbook\",\"text\":\"hello\"}}'")
        print(f"  Read: curl http://192.168.123.106:{port}/msg")
        print()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")

    elif "--send" in sys.argv:
        idx = sys.argv.index("--send")
        text = " ".join(sys.argv[idx+1:]) if idx+1 < len(sys.argv) else "ping"
        host = "127.0.0.1"
        for i, a in enumerate(sys.argv):
            if a == "--host" and i+1 < len(sys.argv):
                host = sys.argv[i+1]
        result = send_message(host, port, "pc-claude", text)
        print(f"Sent: {result}")

    elif "--read" in sys.argv:
        host = "127.0.0.1"
        for i, a in enumerate(sys.argv):
            if a == "--host" and i+1 < len(sys.argv):
                host = sys.argv[i+1]
        msgs = read_messages(host, port)
        for m in msgs:
            print(f"[{m['time']}] {m['from']}: {m['text']}")
