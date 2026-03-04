"""Generate OLiveCam app icon (1024x1024) - Dutch Neon Orange"""
from PIL import Image, ImageDraw, ImageFont
import math

SIZE = 1024
img = Image.new('RGB', (SIZE, SIZE), '#1a1a2e')
draw = ImageDraw.Draw(img)

# Background gradient (dark navy)
for y in range(SIZE):
    r = int(20 + (y / SIZE) * 8)
    g = int(18 + (y / SIZE) * 5)
    b = int(38 + (y / SIZE) * 15)
    draw.line([(0, y), (SIZE, y)], fill=(r, g, b))

cx, cy = SIZE // 2, SIZE // 2 - 30

# Outer lens ring (Dutch neon orange gradient)
for i in range(40):
    radius = 340 - i
    r = min(255, int(255 - i * 0.5))
    g = min(255, int(103 + i * 1.2))
    b = int(0 + i * 0.8)
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=(r, g, b), width=2
    )

# Dark inner circle (lens body)
draw.ellipse(
    [cx - 280, cy - 280, cx + 280, cy + 280],
    fill='#0d0d1a'
)

# Lens glass rings (subtle orange tint)
for ring_r in [240, 200, 160]:
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=(50, 35, 30), width=2
    )

# Inner lens (dark)
draw.ellipse(
    [cx - 150, cy - 150, cx + 150, cy + 150],
    fill='#0a0a18'
)

# Lens flare (orange glow)
for i in range(80):
    if int(120 - i * 1.5) <= 0:
        break
    r = min(255, int(255 - i * 0.3))
    g = min(255, int(140 - i * 0.8))
    b = int(30 - i * 0.3)
    radius = 60 + i
    flare_x = cx - 60
    flare_y = cy - 60
    draw.ellipse(
        [flare_x - radius // 3, flare_y - radius // 3,
         flare_x + radius // 3, flare_y + radius // 3],
        outline=(r, max(0, g), max(0, b)), width=1
    )

# Bright lens reflection
draw.ellipse(
    [cx - 100, cy - 100, cx - 60, cy - 60],
    fill='#fff0e0'
)
draw.ellipse(
    [cx - 90, cy - 90, cx - 70, cy - 70],
    fill='#ffffff'
)

# Second smaller reflection
draw.ellipse(
    [cx + 40, cy + 50, cx + 60, cy + 70],
    fill=(255, 220, 200)
)

# REC dot (neon orange, not red)
rec_x, rec_y = 180, 180
draw.ellipse(
    [rec_x - 22, rec_y - 22, rec_x + 22, rec_y + 22],
    fill='#FF6700'
)
# Glow around REC dot
for i in range(15):
    r = 22 + i * 2
    draw.ellipse(
        [rec_x - r, rec_y - r, rec_x + r, rec_y + r],
        outline=(255, 103, 0), width=1
    )

# "OLiveCam" text at bottom (orange tint)
try:
    font = ImageFont.truetype("arial.ttf", 72)
except:
    font = ImageFont.load_default()

text = "OLiveCam"
bbox = draw.textbbox((0, 0), text, font=font)
tw = bbox[2] - bbox[0]
draw.text(
    (cx - tw // 2, SIZE - 160),
    text, fill='#FF8C42', font=font
)

img.save('D:/livecat/appstore/icon_1024.png', 'PNG')
print(f"Icon saved: D:/livecat/appstore/icon_1024.png ({SIZE}x{SIZE})")

# Smaller sizes for Xcode
for size in [180, 167, 152, 120, 87, 80, 76, 60, 58, 40, 29, 20]:
    small = img.resize((size, size), Image.LANCZOS)
    small.save(f'D:/livecat/appstore/icon_{size}.png', 'PNG')
    print(f"  icon_{size}.png")

print("Done!")
