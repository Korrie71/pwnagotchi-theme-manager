"""Generates the example face packs. Run: python3 make_face_packs.py OUT_DIR
Each pack is a folder of <mood>.png (or .gif) images, 240x90 with a transparent background."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

S = 4                      # supersampling
W, H = 240 * S, 90 * S
CX, CY, R = 120 * S, 45 * S, 40 * S
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

MOODS = {  # mood: (body color, eyes, mouth, extras)
    "look_r": ("#ffd23f", "look_r", "flat", ()),
    "sleep": ("#8da2c0", "closed", "flat", ("zzz",)),
    "awake": ("#ffd23f", "open", "smile", ()),
    "bored": ("#b8b8c4", "lidded", "flat", ()),
    "intense": ("#ff9a3d", "narrow", "o", ("brows_down",)),
    "cool": ("#4dd2ff", "shades", "smirk", ()),
    "happy": ("#7dff9a", "happy", "grin", ()),
    "grateful": ("#ffb3d1", "happy", "smile", ("blush",)),
    "excited": ("#ffe14d", "wide", "open", ()),
    "motivated": ("#ffa94d", "open", "grin", ("brows_down",)),
    "demotivated": ("#9a9ab0", "droop", "frown", ()),
    "smart": ("#9ad0ff", "glasses", "smile", ()),
    "lonely": ("#b18cff", "down", "frown", ()),
    "sad": ("#6f8cff", "open", "frown", ("tear", "brows_up")),
    "angry": ("#ff4d4d", "narrow", "frown", ("brows_down",)),
    "friend": ("#ff7fb0", "heart", "smile", ()),
    "broken": ("#c0c0c0", "x", "wavy", ()),
    "debug": ("#7fffd4", "square", "flat", ()),
    "upload": ("#a0ffa0", "digits", "flat", ()),
}


def px(v):
    return v * S


def draw_face(body, eyes, mouth, extras, style="blob", blink=False):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ink = "#101018" if style == "blob" else "#ffffff"      # features
    white = "#ffffff"
    if style == "blob":
        d.ellipse((CX - R, CY - R, CX + R, CY + R), fill=body, outline="#101018", width=px(2))
    else:
        d.ellipse((CX - R, CY - R, CX + R, CY + R), outline="#ffffff", width=px(3))
    ex, ey, er = px(24), CY - px(6), px(9)
    lw = px(3)
    eyes_kind = "closed" if blink else eyes

    for sx in (-1, 1):
        x = CX + sx * ex
        if eyes_kind in ("open", "look_r", "down", "wide", "droop"):
            rr = er + (px(3) if eyes_kind == "wide" else 0)
            d.ellipse((x - rr, ey - rr, x + rr, ey + rr), fill=white if style == "blob" else None, outline=ink, width=lw)
            ox = px(4) if eyes_kind == "look_r" else 0
            oy = px(4) if eyes_kind == "down" else (px(3) if eyes_kind == "droop" else 0)
            d.ellipse((x + ox - px(4), ey + oy - px(4), x + ox + px(4), ey + oy + px(4)), fill=ink)
            if eyes_kind == "droop":
                d.rectangle((x - rr - px(1), ey - rr - px(1), x + rr + px(1), ey - px(3)), fill=body if style == "blob" else (0, 0, 0, 0))
                d.line((x - rr, ey - px(3), x + rr, ey - px(3)), fill=ink, width=lw)
        elif eyes_kind == "closed":
            d.arc((x - er, ey - px(5), x + er, ey + px(7)), 20, 160, fill=ink, width=lw)
        elif eyes_kind == "happy":
            d.arc((x - er, ey - px(3), x + er, ey + px(11)), 200, 340, fill=ink, width=lw + px(1))
        elif eyes_kind == "lidded":
            d.ellipse((x - er, ey - er, x + er, ey + er), fill=white if style == "blob" else None, outline=ink, width=lw)
            d.rectangle((x - er - 1, ey - er - 1, x + er + 1, ey - px(1)), fill=body if style == "blob" else (0, 0, 0, 0))
            d.line((x - er, ey - px(1), x + er, ey - px(1)), fill=ink, width=lw)
            d.ellipse((x - px(3), ey + px(1), x + px(3), ey + px(6)), fill=ink)
        elif eyes_kind == "narrow":
            d.polygon([(x - er, ey - px(1)), (x + er, ey - px(1)), (x + er - px(2), ey + px(6)), (x - er + px(2), ey + px(6))], fill=ink)
        elif eyes_kind == "heart":
            d.ellipse((x - px(9), ey - px(8), x, ey + px(1)), fill="#ff2a6d" if style == "blob" else ink)
            d.ellipse((x, ey - px(8), x + px(9), ey + px(1)), fill="#ff2a6d" if style == "blob" else ink)
            d.polygon([(x - px(9), ey - px(3)), (x + px(9), ey - px(3)), (x, ey + px(9))], fill="#ff2a6d" if style == "blob" else ink)
        elif eyes_kind == "x":
            d.line((x - er, ey - er, x + er, ey + er), fill=ink, width=lw)
            d.line((x - er, ey + er, x + er, ey - er), fill=ink, width=lw)
        elif eyes_kind == "square":
            d.rectangle((x - er, ey - er, x + er, ey + er), outline=ink, width=lw)
            d.rectangle((x - px(3), ey - px(3), x + px(3), ey + px(3)), fill=ink)
        elif eyes_kind == "glasses":
            d.ellipse((x - px(12), ey - px(12), x + px(12), ey + px(12)), outline=ink, width=lw)
            d.ellipse((x - px(3), ey - px(3), x + px(3), ey + px(3)), fill=ink)
        elif eyes_kind == "digits":
            d.text((x, ey), "1" if sx < 0 else "0", font=ImageFont.truetype(FONT, px(20)), fill=ink, anchor="mm")
        elif eyes_kind == "shades":
            pass
    if eyes_kind == "shades":
        d.rounded_rectangle((CX - px(38), ey - px(9), CX - px(6), ey + px(9)), px(4), fill="#101018")
        d.rounded_rectangle((CX + px(6), ey - px(9), CX + px(38), ey + px(9)), px(4), fill="#101018")
        d.line((CX - px(6), ey - px(4), CX + px(6), ey - px(4)), fill="#101018", width=lw)
        d.line((CX - px(30), ey - px(5), CX - px(22), ey - px(5)), fill="#4dd2ff", width=px(2))

    my = CY + px(20)
    if mouth == "smile":
        d.arc((CX - px(14), my - px(12), CX + px(14), my + px(8)), 20, 160, fill=ink, width=lw)
    elif mouth == "grin":
        d.pieslice((CX - px(16), my - px(14), CX + px(16), my + px(10)), 0, 180, fill=ink if style == "blob" else None, outline=ink, width=lw)
    elif mouth == "flat":
        d.line((CX - px(10), my, CX + px(10), my), fill=ink, width=lw)
    elif mouth == "frown":
        d.arc((CX - px(14), my - px(2), CX + px(14), my + px(18)), 200, 340, fill=ink, width=lw)
    elif mouth == "o":
        d.ellipse((CX - px(6), my - px(6), CX + px(6), my + px(6)), outline=ink, width=lw)
    elif mouth == "open":
        d.ellipse((CX - px(9), my - px(9), CX + px(9), my + px(7)), fill=ink if style == "blob" else None, outline=ink, width=lw)
    elif mouth == "smirk":
        d.arc((CX - px(6), my - px(12), CX + px(16), my + px(6)), 20, 150, fill=ink, width=lw)
    elif mouth == "wavy":
        pts = [(CX - px(14) + i * px(4), my + (px(3) if i % 2 else -px(3))) for i in range(8)]
        d.line(pts, fill=ink, width=lw)

    for ex_ in extras:
        if ex_ == "tear":
            x = CX + ex
            d.polygon([(x, ey + px(12)), (x - px(4), ey + px(20)), (x + px(4), ey + px(20))], fill="#4dd2ff")
            d.ellipse((x - px(4), ey + px(16), x + px(4), ey + px(24)), fill="#4dd2ff")
        elif ex_ == "blush":
            for sx in (-1, 1):
                d.ellipse((CX + sx * px(30) - px(6), CY + px(4), CX + sx * px(30) + px(6), CY + px(11)), fill="#ff6b9a" if style == "blob" else None,
                          outline=None if style == "blob" else ink)
        elif ex_ == "brows_down":
            for sx in (-1, 1):
                x = CX + sx * ex
                d.line((x - sx * px(10), ey - px(14) + px(4), x + sx * px(10), ey - px(14) - px(4)), fill=ink, width=lw)
        elif ex_ == "brows_up":
            for sx in (-1, 1):
                x = CX + sx * ex
                d.line((x - sx * px(10), ey - px(14) - px(4), x + sx * px(10), ey - px(14) + px(4)), fill=ink, width=lw)
        elif ex_ == "zzz":
            f = ImageFont.truetype(FONT, px(14))
            d.text((CX + R - px(4), CY - R + px(6)), "z", font=f, fill=ink)
            d.text((CX + R + px(8), CY - R - px(4)), "Z", font=ImageFont.truetype(FONT, px(18)), fill=ink)
    return im.resize((W // S, H // S), Image.LANCZOS)


def build(out, name, style):
    p = os.path.join(out, name)
    os.makedirs(p, exist_ok=True)
    for mood, (body, eyes, mouth, extras) in MOODS.items():
        draw_face(body, eyes, mouth, extras, style).save(os.path.join(p, mood + ".png"))
    if style == "blob":  # animated example: awake.gif blinks every ~2.5 s
        o = draw_face(*MOODS["awake"], style="blob")
        b = draw_face(*MOODS["awake"], style="blob", blink=True)
        # GIF has 1-bit transparency, so flatten onto a key color is avoided: keep alpha via disposal=2
        o.save(os.path.join(p, "awake.gif"), save_all=True, append_images=[b, o], duration=[2500, 120, 100],
               loop=0, disposal=2, transparency=0)
        os.remove(os.path.join(p, "awake.png"))


if __name__ == "__main__":
    out = sys.argv[1]
    build(out, "blob", "blob")
    build(out, "outline", "outline")
    print("packs written to", out)
