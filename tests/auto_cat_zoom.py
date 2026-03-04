"""
Auto Cat Zoom + YouTube Live
- 아이폰 연결 감지 → 방송 시작 + 자동 줌
- 아이폰 연결 해제 → 방송 종료
"""
import sys
sys.stdout.reconfigure(line_buffering=True)

import obsws_python as obs
import requests
import anthropic
import base64
import time
import json
from dotenv import load_dotenv

load_dotenv()

cl = obs.ReqClient(host='localhost', port=4455)
api = anthropic.Anthropic()
META = 'http://localhost:8082'

current_zoom = 1.0
SCAN_INTERVAL = 5


def get_iphone_status():
    try:
        st = requests.get(f'{META}/status', timeout=2).json()
        return st.get('clients', 0) > 0
    except:
        return False


def take_screenshot():
    resp = cl.get_source_screenshot(
        name='iPhone_LiveCat', img_format='jpg',
        width=640, height=360, quality=80
    )
    return resp.image_data.split(',')[1]


def detect_cat(img_b64):
    try:
        resp = api.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        }
                    },
                    {
                        "type": "text",
                        "text": 'Cat in image? JSON only: {"cat":true/false,"size":"small"/"medium"/"large"}'
                    }
                ]
            }]
        )
        text = resp.content[0].text.strip()
        print(f"    AI: {text}")
        if '{' in text:
            json_str = text[text.index('{'):text.rindex('}') + 1]
            return json.loads(json_str)
    except Exception as e:
        print(f"    API error: {e}")
    return {"cat": False}


def smooth_zoom(from_z, to_z, duration=1.0, steps=30):
    try:
        resp = requests.post(f'{META}/smooth_zoom', json={
            'from': from_z, 'to': to_z,
            'duration': duration, 'steps': steps
        }, timeout=10)
        print(f"    zoom {from_z}→{to_z}: {resp.json()}")
    except Exception as e:
        print(f"    zoom error: {e}")


def do_zoom_logic(img_b64):
    global current_zoom
    result = detect_cat(img_b64)

    if result.get('cat'):
        size = result.get('size', 'medium')
        if size == 'small' and current_zoom < 2.5:
            target = 2.5
            print(f"  고양이! (멀리) → {target}x")
            smooth_zoom(current_zoom, target)
            current_zoom = target
        elif size == 'medium' and abs(current_zoom - 1.8) > 0.3:
            target = 1.8
            print(f"  고양이! (중간) → {target}x")
            smooth_zoom(current_zoom, target)
            current_zoom = target
        elif size == 'large' and current_zoom > 1.3:
            target = 1.0
            print(f"  고양이 클로즈업! → {target}x")
            smooth_zoom(current_zoom, target)
            current_zoom = target
        else:
            print(f"  고양이 ({size}) 줌 유지 {current_zoom}x")
    else:
        if current_zoom > 1.0:
            print(f"  고양이 없음 → 줌아웃")
            smooth_zoom(current_zoom, 1.0)
            current_zoom = 1.0
        else:
            print(f"  스캔 중...")


def main():
    global current_zoom

    print("=" * 50)
    print("  LiveCat Auto Zoom + Live")
    print("  아이폰 스트리밍 시작 → 방송 시작")
    print("  아이폰 스트리밍 종료 → 방송 종료")
    print("=" * 50)
    print()

    while True:
        # Phase 1: 아이폰 연결 대기
        print("아이폰 연결 대기 중...")
        while not get_iphone_status():
            time.sleep(2)

        print("아이폰 연결됨!")
        time.sleep(3)  # 스트림 안정화 대기

        # 영상 확인
        try:
            img = take_screenshot()
            print(f"영상 OK ({len(base64.b64decode(img))} bytes)")
        except Exception as e:
            print(f"영상 없음: {e}, 재대기...")
            time.sleep(5)
            continue

        # Phase 2: YouTube 방송 시작
        try:
            cl.start_stream()
            print("\n★ YouTube LIVE 시작! ★\n")
        except Exception as e:
            print(f"방송 시작 에러: {e}")

        # Phase 3: 자동 줌 루프 (아이폰 연결 중)
        current_zoom = 1.0
        scan_count = 0
        disconnect_count = 0

        while True:
            # 아이폰 연결 체크
            if not get_iphone_status():
                disconnect_count += 1
                if disconnect_count >= 3:  # 3회 연속 끊김 → 종료
                    print("\n아이폰 연결 해제 감지!")
                    break
                print(f"  연결 불안정... ({disconnect_count}/3)")
                time.sleep(2)
                continue
            else:
                disconnect_count = 0

            # 줌 로직
            try:
                img = take_screenshot()
                scan_count += 1
                do_zoom_logic(img)
            except Exception as e:
                print(f"  에러: {e}")

            time.sleep(SCAN_INTERVAL)

        # Phase 4: 방송 종료
        if current_zoom > 1.0:
            smooth_zoom(current_zoom, 1.0)
            current_zoom = 1.0

        try:
            cl.stop_stream()
            print(f"\n★ 방송 종료! (스캔 {scan_count}회) ★")
            print("※ YouTube Studio에서도 '스트림 종료' 클릭 필요!")
        except Exception as e:
            print(f"방송 종료 에러: {e}")

        print("\n다시 아이폰 연결 대기...\n")
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n수동 종료!")
