"""
OBS Zoom Controller - iPhone LiveCat 영상 줌 제어

Usage:
  python tests/obs_zoom.py                    # Interactive mode
  python tests/obs_zoom.py --zoom 2.0         # Zoom 2x center
  python tests/obs_zoom.py --zoom 1.5 --x 0.3 --y 0.5   # Zoom to left-center
  python tests/obs_zoom.py --reset            # Reset to 1:1
"""
import obsws_python as obs
import sys
import time

CANVAS_W = 1920
CANVAS_H = 1080
SOURCE_NAME = 'iPhone_LiveCat'


def get_client():
    return obs.ReqClient(host='localhost', port=4455)


def get_source_item(cl):
    scenes = cl.get_scene_list()
    scene = scenes.current_program_scene_name
    items = cl.get_scene_item_list(name=scene)
    for item in items.scene_items:
        if item['sourceName'] == SOURCE_NAME:
            return scene, item['sceneItemId']
    raise RuntimeError(f"Source '{SOURCE_NAME}' not found")


def zoom_to(cl, zoom=1.0, fx=0.5, fy=0.5, smooth=False):
    """
    Zoom into a point on the source.

    Args:
        zoom: zoom factor (1.0 = normal, 2.0 = 2x zoom, etc.)
        fx: focus point X (0.0=left, 0.5=center, 1.0=right)
        fy: focus point Y (0.0=top, 0.5=center, 1.0=bottom)
        smooth: animate the zoom transition
    """
    scene, item_id = get_source_item(cl)

    # Source pixel coordinates for focus point
    src_x = fx * CANVAS_W
    src_y = fy * CANVAS_H

    # Position: offset so focus point is at canvas center
    pos_x = CANVAS_W / 2 - src_x * zoom
    pos_y = CANVAS_H / 2 - src_y * zoom

    # Clamp to prevent black edges
    min_x = CANVAS_W - CANVAS_W * zoom
    min_y = CANVAS_H - CANVAS_H * zoom
    pos_x = max(min_x, min(0, pos_x))
    pos_y = max(min_y, min(0, pos_y))

    if smooth:
        # Get current transform
        t = cl.get_scene_item_transform(scene_name=scene, item_id=item_id)
        tr = t.scene_item_transform
        cur_scale = tr['scaleX']
        cur_x = tr['positionX']
        cur_y = tr['positionY']

        steps = 15
        for i in range(1, steps + 1):
            t_val = i / steps
            # Ease-out curve
            t_ease = 1 - (1 - t_val) ** 2
            s = cur_scale + (zoom - cur_scale) * t_ease
            x = cur_x + (pos_x - cur_x) * t_ease
            y = cur_y + (pos_y - cur_y) * t_ease
            cl.set_scene_item_transform(scene_name=scene, item_id=item_id, transform={
                'scaleX': s, 'scaleY': s,
                'positionX': x, 'positionY': y,
            })
            time.sleep(0.03)
    else:
        cl.set_scene_item_transform(scene_name=scene, item_id=item_id, transform={
            'scaleX': zoom, 'scaleY': zoom,
            'positionX': pos_x, 'positionY': pos_y,
        })

    print(f"Zoom: {zoom:.1f}x @ ({fx:.2f}, {fy:.2f}) -> pos=({pos_x:.0f}, {pos_y:.0f})")


def zoom_reset(cl, smooth=False):
    """Reset to normal view (1:1)"""
    zoom_to(cl, zoom=1.0, fx=0.5, fy=0.5, smooth=smooth)
    print("Reset to 1:1")


def interactive(cl):
    """Interactive zoom control"""
    print("=== OBS Zoom Controller ===")
    print("Commands:")
    print("  z <factor>          - Zoom center (e.g. 'z 2.0')")
    print("  z <factor> <x> <y>  - Zoom to point (e.g. 'z 2.0 0.3 0.7')")
    print("  r                   - Reset")
    print("  s <factor>          - Smooth zoom center")
    print("  s <factor> <x> <y>  - Smooth zoom to point")
    print("  q                   - Quit")
    print()

    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        parts = cmd.split()
        action = parts[0].lower()

        if action == 'q':
            break
        elif action == 'r':
            zoom_reset(cl, smooth=True)
        elif action in ('z', 's'):
            smooth = (action == 's')
            try:
                factor = float(parts[1]) if len(parts) > 1 else 2.0
                fx = float(parts[2]) if len(parts) > 2 else 0.5
                fy = float(parts[3]) if len(parts) > 3 else 0.5
                factor = max(1.0, min(5.0, factor))
                fx = max(0.0, min(1.0, fx))
                fy = max(0.0, min(1.0, fy))
                zoom_to(cl, zoom=factor, fx=fx, fy=fy, smooth=smooth)
            except (ValueError, IndexError):
                print("Usage: z <factor> [<x> <y>]")
        else:
            print("Unknown command. Use z/s/r/q")


if __name__ == "__main__":
    cl = get_client()

    if "--reset" in sys.argv:
        zoom_reset(cl)
    elif "--zoom" in sys.argv:
        idx = sys.argv.index("--zoom")
        zoom = float(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 2.0
        fx = 0.5
        fy = 0.5
        for i, a in enumerate(sys.argv):
            if a == "--x" and i + 1 < len(sys.argv):
                fx = float(sys.argv[i + 1])
            if a == "--y" and i + 1 < len(sys.argv):
                fy = float(sys.argv[i + 1])
        zoom_to(cl, zoom=zoom, fx=fx, fy=fy)
    elif "--demo" in sys.argv:
        print("Demo: zoom sequence")
        zoom_to(cl, 1.0, smooth=False)
        time.sleep(1)
        print("-> Zoom 2x center")
        zoom_to(cl, 2.0, 0.5, 0.5, smooth=True)
        time.sleep(2)
        print("-> Pan to left")
        zoom_to(cl, 2.0, 0.3, 0.5, smooth=True)
        time.sleep(2)
        print("-> Zoom 3x top-right")
        zoom_to(cl, 3.0, 0.7, 0.3, smooth=True)
        time.sleep(2)
        print("-> Reset")
        zoom_reset(cl, smooth=True)
    else:
        interactive(cl)

    cl.disconnect()
