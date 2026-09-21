"""Scenery: every scene draws, is cached, stays inside the picture and keeps the text readable."""
import json
import time

from _util import T, fake_canvas, finish, ok, sandbox
from PIL import Image, ImageChops

sandbox()
canvas = fake_canvas()


def theme(kind, **extra):
    return T._clean(dict(T.BUILTIN["default"], effects=[dict(type="scene", kind=kind, **extra)]))


# ---------------------------------------------------------------- validation
ok("there are scenes, each with a drawing function", len(T.SCENE_KINDS) >= 19 and set(T.SCENE_KINDS) == set(T.SCENES))
ok("'scene' is an effect", "scene" in T.EFFECTS)
for bad in ({"type": "scene"}, {"type": "scene", "kind": "moon base"}, {"type": "scene", "kind": 5}, "scene"):
    try:
        T._clean(dict(T.BUILTIN["default"], effects=[bad]))
        good = False
    except ValueError:
        good = True
    ok("a scene without a known kind is refused: %r" % (bad,), good)
c = T._clean_effect({"type": "scene", "kind": "ocean", "strength": 7, "speed": "fast" if False else 4, "junk": 1})
ok("strength is limited, unknown keys dropped", c == {"type": "scene", "kind": "ocean", "strength": 1.0, "speed": 4.0}, c)
ok("a theme file with a scene validates and round-trips through JSON", T._clean(json.loads(json.dumps(theme("forest")))) == theme("forest"))

# ---------------------------------------------------------------- every scene
plain = T.colorize(canvas, T._clean(T.BUILTIN["default"]), 0.0)
for kind in T.SCENE_KINDS:
    th = theme(kind)
    img = T.colorize(canvas, th, 0.0)
    diff = ImageChops.difference(img, plain).convert("L").point(lambda v: 255 if v > 12 else 0)
    share = sum(diff.getdata()) / 255 / (480 * 320)
    ok("%s: draws a full-size picture that differs from the plain background (%.0f%% of pixels)" % (kind, share * 100), img.size == (480, 320) and share > 0.05, share)
    ok("%s: animation flag matches its moving layer" % kind, T.is_animated(th) == (kind in T.ANIM_SCENES))
    if kind in T.ANIM_SCENES:
        a, b = T.colorize(canvas, th, 0.0), T.colorize(canvas, th, 1.7)
        ok("%s: really moves between frames" % kind, ImageChops.difference(a, b).getbbox() is not None)
    else:
        ok("%s: is still between frames" % kind, ImageChops.difference(T.colorize(canvas, th, 0.0), T.colorize(canvas, th, 1.7)).getbbox() is None)

# ---------------------------------------------------------------- behaviour
half = T.colorize(canvas, theme("mountains", strength=0.4), 0.0)
full = T.colorize(canvas, theme("mountains"), 0.0)
d_half = sum(ImageChops.difference(half, plain).convert("L").getdata())
d_full = sum(ImageChops.difference(full, plain).convert("L").getdata())
ok("strength fades the scenery toward the plain background", 0 < d_half < d_full)
th = theme("winter")
T.colorize(canvas, th, 0.0)
t0 = time.time()
for i in range(20):
    T.colorize(canvas, th, i * 0.3)
per = (time.time() - t0) / 20
ok("a frame with moving scenery takes well under 60 ms (%.1f ms)" % (per * 1000), per < 0.06, per)
before = len(T._cache)
for kind in T.SCENE_KINDS * 2:
    T.colorize(canvas, theme(kind), 0.0)
ok("the cache stays bounded however many scenes are used (%d entries)" % len(T._cache), len(T._cache) <= 60)

# text stays readable: on every built-in theme with a scene, the ink is far from the scenery under the face
def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


for name, t in T.BUILTIN.items():
    if not any(e["type"] == "scene" for e in t.get("effects", [])):
        continue
    th = T._clean(t)
    img = T.colorize(canvas, th, 0.0)
    fg = T._hex(th["fg"])
    region = img.crop((0, 160, 480, 300)).convert("RGB")
    px = list(region.getdata())
    close = sum(1 for p in px if abs(lum(p) - lum(fg)) < 25) / len(px)
    ok("%s: less than 8%% of the lower screen is as bright as the text (%.1f%%)" % (name, close * 100), close < 0.08, close)

# every scene theme is in the built-ins with the right kind, and is valid
scened = {n: [e["kind"] for e in t["effects"] if e["type"] == "scene"] for n, t in T.BUILTIN.items() if any(e["type"] == "scene" for e in t.get("effects", []))}
ok("%d built-in themes have scenery" % len(scened), len(scened) >= 19, sorted(scened))
ok("...and the ones named after a place show that place", scened["mountain"] == ["mountains"] and scened["ocean"] == ["ocean"] and scened["forest"] == ["forest"] and scened["desert"] == ["desert"])

finish()
