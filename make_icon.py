# -*- coding: utf-8 -*-
"""Generate the application icon (a Live Photo style concentric-ring mark)."""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT, exist_ok=True)
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角方形底：暖色渐变（模仿 iOS 实况图的橙黄色调）
bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
bd = ImageDraw.Draw(bg)
for y in range(S):
    t = y / (S - 1.0)
    r = int(255 - 18 * t)
    g = int(184 - 62 * t)
    b = int(70 - 40 * t)
    bd.line([(0, y), (S, y)], fill=(r, g, b, 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
img.paste(bg, (0, 0), mask)

# 同心圆环
cx = cy = S / 2.0
rings = [(0.415, 46), (0.290, 40), (0.170, 34)]
for frac, w in rings:
    rr = S * frac
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(255, 255, 255, 235), width=w)
# 中心实心点
rr = S * 0.070
d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(255, 255, 255, 245))

img.save(os.path.join(OUT, "app.png"))
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
img.save(os.path.join(OUT, "app.ico"), format="ICO", sizes=sizes)
print("icon written:", os.path.join(OUT, "app.ico"))
