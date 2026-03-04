"""Generate YouTube Thumbnail with real cat photos - Nana & Toto"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
img = Image.new('RGB', (W, H), '#1a1a2e')
draw = ImageDraw.Draw(img)

# Background gradient (dark navy)
for y in range(H):
    r = int(14 + (y / H) * 10)
    g = int(12 + (y / H) * 6)
    b = int(30 + (y / H) * 18)
    draw.line([(0, y), (W, y)], fill=(r, g, b))

# Load cat photos
nana = Image.open('D:/Nana.jpeg')
toto = Image.open('D:/Toto.jpeg')

# Circular crop helper
def circle_crop(photo, size):
    photo = photo.resize((size, size), Image.LANCZOS)
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([0, 0, size, size], fill=255)
    result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    result.paste(photo, (0, 0), mask)
    return result, mask

# Nana - crop to square (center crop)
nw, nh = nana.size
nana_sq = min(nw, nh)
nana_left = (nw - nana_sq) // 2
nana_top = (nh - nana_sq) // 2
nana = nana.crop((nana_left, nana_top, nana_left + nana_sq, nana_top + nana_sq))
nana_circle, nana_mask = circle_crop(nana, 340)

# Toto - crop to square
tw, th = toto.size
toto_sq = min(tw, th)
toto_left = (tw - toto_sq) // 2
toto_top = (th - toto_sq) // 2
toto = toto.crop((toto_left, toto_top, toto_left + toto_sq, toto_top + toto_sq))
toto_circle, toto_mask = circle_crop(toto, 260)

# Draw orange ring around photos
def draw_ring(img_draw, cx, cy, radius, ring_width=6):
    for i in range(ring_width):
        rv = min(255, int(255 - i * 2))
        gv = min(255, int(103 + i * 5))
        bv = int(0 + i * 3)
        img_draw.ellipse(
            [cx - radius - i, cy - radius - i, cx + radius + i, cy + radius + i],
            outline=(rv, gv, bv), width=2
        )

# Place Nana (left-center)
nana_x, nana_y = 60, 190
draw_ring(draw, nana_x + 170, nana_y + 170, 175, 8)
img.paste(nana_circle, (nana_x, nana_y), nana_mask)

# Place Toto (lower left, overlapping slightly)
toto_x, toto_y = 330, 370
draw_ring(draw, toto_x + 130, toto_y + 130, 135, 6)
img.paste(toto_circle, (toto_x, toto_y), toto_mask)

# Re-get draw after paste
draw = ImageDraw.Draw(img)

# Fonts
try:
    font_channel = ImageFont.truetype("arialbd.ttf", 110)
    font_sub = ImageFont.truetype("arialbd.ttf", 48)
    font_small = ImageFont.truetype("arial.ttf", 28)
    font_badge = ImageFont.truetype("arialbd.ttf", 40)
except:
    font_channel = ImageFont.load_default()
    font_sub = font_channel
    font_small = font_channel
    font_badge = font_channel

# Text shadow helper
def draw_text_shadow(pos, text, font, fill, shadow_color=(0,0,0), offset=4):
    x, y = pos
    for dx in range(-offset, offset+1):
        for dy in range(-offset, offset+1):
            if dx*dx + dy*dy <= offset*offset:
                draw.text((x + dx, y + dy), text, fill=shadow_color, font=font)
    draw.text((x, y), text, fill=fill, font=font)

# Channel name
draw_text_shadow((620, 140), "Nana", font_channel, fill='#FFFFFF')
draw_text_shadow((620, 265), "& Toto", font_channel, fill='#FF8C42')

# Orange accent line
draw.rectangle([625, 395, 1210, 398], fill='#FF6700')

# Subtitle
draw_text_shadow((630, 415), "Cat Live Stream", font_sub, fill='#FFFFFF')

# Tagline
draw.text((630, 480), "Outdoor Cats  |  Daily Life", fill=(160, 160, 170), font=font_small)

# LIVE badge
badge_x, badge_y = 1040, 50
draw.rounded_rectangle([badge_x, badge_y, badge_x + 190, badge_y + 60], radius=12, fill='#FF3B30')
draw.ellipse([badge_x + 16, badge_y + 20, badge_x + 36, badge_y + 40], fill='#ffffff')
draw.text((badge_x + 48, badge_y + 6), "LIVE", fill='#ffffff', font=font_badge)

# Bottom bar
draw.rectangle([0, H - 7, W, H], fill='#FF6700')

img.save('D:/livecat/appstore/thumbnail_live.png', 'PNG')
print(f"Thumbnail saved: D:/livecat/appstore/thumbnail_live.png ({W}x{H})")
