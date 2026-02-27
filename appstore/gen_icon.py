"""Generate OLiveCam app icon (1024x1024)"""
from PIL import Image, ImageDraw, ImageFont
import math

SIZE = 1024
img = Image.new('RGB', (SIZE, SIZE), '#1a1a2e')
draw = ImageDraw.Draw(img)

# Background gradient effect (dark blue to dark purple)
for y in range(SIZE):
    r = int(26 + (y / SIZE) * 10)
    g = int(26 - (y / SIZE) * 10)
    b = int(46 + (y / SIZE) * 20)
    draw.line([(0, y), (SIZE, y)], fill=(r, g, b))

cx, cy = SIZE // 2, SIZE // 2 - 30

# Outer lens ring (olive/gold gradient)
for i in range(40):
    radius = 340 - i
    # Olive to gold gradient
    r = int(160 + i * 1.5)
    g = int(180 + i * 0.8)
    b = int(60 - i * 0.5)
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=(r, g, b), width=2
    )

# Dark inner circle (lens body)
draw.ellipse(
    [cx - 280, cy - 280, cx + 280, cy + 280],
    fill='#0d0d1a'
)

# Lens glass rings
for ring_r in [240, 200, 160]:
    # Subtle ring
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=(40, 40, 70), width=2
    )

# Inner lens (dark with blue tint)
draw.ellipse(
    [cx - 150, cy - 150, cx + 150, cy + 150],
    fill='#0a0a20'
)

# Lens flare / highlight (olive green glow)
for i in range(80):
    alpha = int(120 - i * 1.5)
    if alpha <= 0:
        break
    r = int(180 + i * 0.5)
    g = int(200 - i * 0.3)
    b = int(80 - i * 0.5)
    radius = 60 + i
    flare_x = cx - 60
    flare_y = cy - 60
    draw.ellipse(
        [flare_x - radius // 3, flare_y - radius // 3,
         flare_x + radius // 3, flare_y + radius // 3],
        outline=(min(255, r), min(255, g), max(0, b)), width=1
    )

# Small bright dot (lens reflection)
draw.ellipse(
    [cx - 100, cy - 100, cx - 60, cy - 60],
    fill='#e8e8ff'
)
draw.ellipse(
    [cx - 90, cy - 90, cx - 70, cy - 70],
    fill='#ffffff'
)

# Second smaller reflection
draw.ellipse(
    [cx + 40, cy + 50, cx + 60, cy + 70],
    fill=(200, 200, 240)
)

# REC dot (red, top-left area)
rec_x, rec_y = 180, 180
draw.ellipse(
    [rec_x - 22, rec_y - 22, rec_x + 22, rec_y + 22],
    fill='#ff3b30'
)
# Glow around REC dot
for i in range(15):
    r = 22 + i * 2
    draw.ellipse(
        [rec_x - r, rec_y - r, rec_x + r, rec_y + r],
        outline=(255, 59, 48, max(0, 60 - i * 4)), width=1
    )

# "OLiveCam" text at bottom
try:
    font = ImageFont.truetype("arial.ttf", 72)
    font_small = ImageFont.truetype("arial.ttf", 48)
except:
    font = ImageFont.load_default()
    font_small = font

# App name
text = "OLiveCam"
bbox = draw.textbbox((0, 0), text, font=font)
tw = bbox[2] - bbox[0]
draw.text(
    (cx - tw // 2, SIZE - 160),
    text, fill='#c8d8a0', font=font
)

img.save('D:/livecat/appstore/icon_1024.png', 'PNG')
print(f"Icon saved: D:/livecat/appstore/icon_1024.png ({SIZE}x{SIZE})")

# Also generate smaller sizes for Xcode
for size in [180, 167, 152, 120, 87, 80, 76, 60, 58, 40, 29, 20]:
    small = img.resize((size, size), Image.LANCZOS)
    small.save(f'D:/livecat/appstore/icon_{size}.png', 'PNG')
    print(f"  icon_{size}.png")

print("Done!")
