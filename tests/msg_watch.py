"""Watch for new messages and print them"""
import urllib.request, json, time, sys

last_count = 0
server = "http://127.0.0.1:8888/msg"

while True:
    try:
        with urllib.request.urlopen(server, timeout=5) as resp:
            msgs = json.loads(resp.read().decode("utf-8"))
        if len(msgs) > last_count:
            for m in msgs[last_count:]:
                if m["from"] != "pc-claude":
                    print(f"[{m['time']}] {m['from']}: {m['text']}", flush=True)
            last_count = len(msgs)
    except Exception as e:
        print(f"Poll error: {e}", flush=True)
    time.sleep(15)
