"""Generate YouTube Channel Profile Image (800x800) - Nana & Toto"""
from PIL import Image, ImageDraw, ImageFont

SIZE = 800
img = Image.new('RGB', (SIZE, SIZE), '#1a1a2e')
draw = ImageDraw.Draw(img)

# Background gradient (dark navy)
for y in range(SIZE):
    r = int(14 + (y / SIZE) * 12)
    g = int(12 + (y / SIZE) * 6)
    b = int(30 + (y / SIZE) * 18)
    draw.line([(0, y), (SIZE, y)], fill=(r, g, b))

# Load cat photos
nana = Image.open('D:/Nana.jpeg')
toto = Image.open('D:/Toto.jpeg')

# Circular crop helper
def circle_crop(photo, size):
    w, h = photo.size
    sq = min(w, h)
    left = (w - sq) // 2
    top = (h - sq) // 2
    photo = photo.crop((left, top, left + sq, top + sq))
    photo = photo.resize((size, size), Image.LANCZOS)
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([0, 0, size, size], fill=255)
    result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    result.paste(photo, (0, 0), mask)
    return result, mask

# Draw orange ring
def draw_ring(cx, cy, radius, width=6):
    for i in range(width):
        rv = min(255, int(255 - i * 2))
        gv = min(255, int(103 + i * 5))
        bv = int(0 + i * 3)
        draw.ellipse(
            [cx - radius - i, cy - radius - i, cx + radius + i, cy + radius + i],
            outline=(rv, gv, bv), width=2
        )

# Nana (top left, larger)
nana_size = 300
nana_circle, nana_mask = circle_crop(nana, nana_size)
nana_x, nana_y = 80, 140
draw_ring(nana_x + nana_size//2, nana_y + nana_size//2, nana_size//2 + 4, 8)
img.paste(nana_circle, (nana_x, nana_y), nana_mask)

# Toto (right, slightly lower)
toto_size = 260
toto_circle, toto_mask = circle_crop(toto, toto_size)
toto_x, toto_y = 410, 200
draw_ring(toto_x + toto_size//2, toto_y + toto_size//2, toto_size//2 + 4, 7)
img.paste(toto_circle, (toto_x, toto_y), toto_mask)

# Re-get draw
draw = ImageDraw.Draw(img)

# Fonts
try:
    font_name = ImageFont.truetype("arialbd.ttf", 80)
    font_sub = ImageFont.truetype("arial.ttf", 32)
except:
    font_name = ImageFont.load_default()
    font_sub = font_name

# Text shadow
def draw_text_shadow(pos, text, font, fill, offset=3):
    x, y = pos
    for dx in range(-offset, offset+1):
        for dy in range(-offset, offset+1):
            if dx*dx + dy*dy <= offset*offset:
                draw.text((x + dx, y + dy), text, fill=(0,0,0), font=font)
    draw.text((x, y), text, fill=fill, font=font)

# Channel name centered at bottom
name_text = "Nana & Toto"
bbox = draw.textbbox((0, 0), name_text, font=font_name)
tw = bbox[2] - bbox[0]
draw_text_shadow(((SIZE - tw) // 2, 530), name_text, font_name, fill='#FF8C42', offset=4)

# Subtitle
sub_text = "Cat Live Stream"
bbox2 = draw.textbbox((0, 0), sub_text, font=font_sub)
tw2 = bbox2[2] - bbox2[0]
draw.text(((SIZE - tw2) // 2, 630), sub_text, fill=(200, 200, 200), font=font_sub)

# Orange accent line
line_w = 300
draw.rectangle([(SIZE - line_w) // 2, 620, (SIZE + line_w) // 2, 623], fill='#FF6700')

# Bottom accent
draw.rectangle([0, SIZE - 5, SIZE, SIZE], fill='#FF6700')

img.save('D:/livecat/appstore/channel_profile.png', 'PNG')
print(f"Channel profile saved: D:/livecat/appstore/channel_profile.png ({SIZE}x{SIZE})")
