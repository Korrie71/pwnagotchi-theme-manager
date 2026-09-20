"""Renders docs/images/demo.gif: animated effects and a mood change, from made-up data.

    python tools/make_demo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene import ROOT, T, faces, frame_with, render  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FPS = 8
SIZE = (320, 213)
OUT = os.path.join(ROOT, "docs", "images", "demo.gif")
try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 13)
except OSError:
    FONT = ImageFont.load_default()


def label(img, text):
    img = img.resize(SIZE, Image.LANCZOS)
    d = ImageDraw.Draw(img)
    w = d.textlength(text, font=FONT)
    d.rectangle((0, SIZE[1] - 22, w + 14, SIZE[1]), fill=(0, 0, 0))
    d.text((7, SIZE[1] - 19), text, font=FONT, fill=(255, 255, 255))
    return img


frames = []
# 1. matrix rain, 3 seconds
frames += [label(render("matrix", t=i / FPS), "matrix: rain, glow, scanlines") for i in range(3 * FPS)]
# 2. cyberpunk: glitch bursts and a scrolling ticker
frames += [label(render("cyberpunk", t=2.5 + i / FPS), "cyberpunk: glitch, scrolling text") for i in range(3 * FPS)]
# 3. rainbow ink
frames += [label(render("rainbow", t=i / FPS), "rainbow") for i in range(2 * FPS)]
# 4. the moody theme follows the face: happy -> sad -> angry, blended over 0.6 s
moody = T._clean(T.BUILTIN["moody"])
sequence = [("happy", faces.HAPPY), ("sad", faces.SAD), ("angry", faces.ANGRY)]
for (m0, f0), (m1, f1) in zip(sequence, sequence[1:] + [sequence[-1]]):
    hold = [label(frame_with(T.resolve(moody, m0), 1.0 + i / FPS, f0), "mood: " + m0) for i in range(int(1.4 * FPS))]
    frames += hold
    if m0 != m1:
        steps = int(T.MOOD_FADE * FPS) + 1
        for i in range(steps):
            blended = T.blend(T.resolve(moody, m0), T.resolve(moody, m1), (i + 1) / steps)
            frames.append(label(frame_with(blended, 2.0 + i / FPS, f1), "mood: %s -> %s" % (m0, m1)))

# one shared palette built from samples of every clip (a palette from the first clip alone tints all the others)
samples = frames[::4]
sheet = Image.new("RGB", (SIZE[0], SIZE[1] * len(samples)))
for i, f in enumerate(samples):
    sheet.paste(f, (0, i * SIZE[1]))
palette = sheet.quantize(colors=200, method=Image.MEDIANCUT)
quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
quantized[0].save(OUT, save_all=True, append_images=quantized[1:], duration=int(1000 / FPS), loop=0, optimize=True, disposal=1)
print("wrote %s: %d frames, %.1f MB" % (OUT, len(frames), os.path.getsize(OUT) / 1e6))
