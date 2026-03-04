"""
LiveCat Messenger MCP Server
- stdio transport로 Claude Code와 통신
- 기존 messenger.py (HTTP :8888)를 백엔드로 사용

환경변수:
  MESSENGER_HOST (기본: localhost)
  MESSENGER_PORT (기본: 8888)
"""
import os
import sys
import json
import urllib.request
import urllib.error
from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("MESSENGER_HOST", "localhost")
PORT = int(os.environ.get("MESSENGER_PORT", "8888"))
BASE = f"http://{HOST}:{PORT}"

mcp = FastMCP("messenger")


def _http_get(path: str) -> str:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as resp:
        return resp.read().decode("utf-8")


def _http_post_json(path: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8")


@mcp.tool()
def send_message(text: str, sender: str = "claude") -> str:
    """메신저 서버로 메시지를 전송합니다.

    Args:
        text: 전송할 메시지 내용
        sender: 발신자 이름 (기본: claude)
    """
    try:
        result = _http_post_json("/msg", {"from": sender, "text": text})
        return f"Sent OK: {result}"
    except Exception as e:
        return f"Send failed: {e}"


@mcp.tool()
def read_messages(count: int = 5) -> str:
    """메신저 서버에서 최근 메시지를 읽어옵니다.

    Args:
        count: 읽어올 메시지 수 (기본: 5)
    """
    try:
        raw = _http_get("/msg")
        msgs = json.loads(raw)
        recent = msgs[-count:] if count < len(msgs) else msgs
        if not recent:
            return "No messages."
        lines = []
        for m in recent:
            lines.append(f"[{m['time']}] {m['from']}: {m['text']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Read failed: {e}"


@mcp.tool()
def ping() -> str:
    """메신저 서버 상태를 확인합니다."""
    try:
        result = _http_get("/ping")
        return f"Server alive: {result}"
    except Exception as e:
        return f"Server unreachable: {e}"


if __name__ == "__main__":
    print(f"Connecting to messenger at {BASE}", file=sys.stderr)
    mcp.run(transport="stdio")
