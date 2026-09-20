"""Themes: validation, rendering, fuzzing, per-element colors, moods and face packs."""
import glob
import json
import os
import random
import threading
import time

from _util import *  # noqa: F401,F403 (ok, finish, T, sandbox, ...)
from _util import ROOT, T, draw_pass, fake_canvas, finish, new_manager, ok, sandbox, scene, T_faces
from PIL import Image, ImageDraw

tmp = sandbox()
canvas = fake_canvas()
faces = T_faces()
FILE = {}


def theme(**extra):
    return T._clean(dict({"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff"}, **extra))


# ---------------------------------------------------------------- built-in and example themes
examples = {}
for path in sorted(glob.glob(os.path.join(ROOT, "themes", "*.json"))):
    examples[os.path.basename(path)[:-5]] = T._clean(json.load(open(path)))
ok("example theme files are valid", len(examples) >= 2, sorted(examples))
everything = {n: T._clean(v) for n, v in T.BUILTIN.items()}
everything.update(examples)
for name, th in everything.items():
    for i in range(30):
        img = T.colorize(canvas, th, i * 0.37)
        assert img.size == (480, 320) and img.mode == "RGB", name
    for mood in T.MOODS:
        T.colorize(canvas, T.resolve(th, mood), 1.7)
ok("all %d built-in and example themes render at many times and in every mood" % len(everything), True)
ok("frame_interval is sane for every theme", all(0.03 <= T.frame_interval(th, 1.0) <= 2.5 for th in everything.values()))
ok("static themes are not animated, animated ones are",
   not T.is_animated(everything["default"]) and T.is_animated(everything["matrix"]))

# ---------------------------------------------------------------- validation
def rejects(bad):
    try:
        T._clean(bad)
    except ValueError:
        return True
    except Exception:
        return False
    return False


base = {"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff"}
garbage = [None, 1, "x", [], {}, {"bg": 1}, {"bg": "#000000", "fg": "#fff"},
           dict(base, effects="scanlines"), dict(base, effects=[None]), dict(base, effects=[{"type": "glow", "radius": "x"}]),
           dict(base, text=[{"text": None}]), dict(base, text=[1]), dict(base, text=[{"text": "a", "x": "q"}]),
           dict(base, elements=[1]), dict(base, elements={"bad key!": "#ffffff"}), dict(base, elements={"face": "red"}),
           dict(base, mood={"sad": [1]}), dict(base, mood={"grumpy": {}}), dict(base, gradient="x"),
           dict(base, face_pack="../etc"), dict(base, face_pack="x", face_offset="ab"), dict(base, fps="fast"),
           dict(base, faces=[1]), dict(base, text=[{"text": "a"}] * 40)]
ok("garbage themes raise ValueError and nothing else", all(rejects(g) for g in garbage),
   [g for g in garbage if not rejects(g)][:2])
ok("out-of-range numbers are clamped, not rejected",
   T._clean(dict(base, fps=99, effects=[{"type": "glow", "radius": 500}]))["fps"] == 10)
ok("an effect may be written as a plain string", T._clean(dict(base, effects=["scanlines"]))["effects"] == [{"type": "scanlines"}])

# ---------------------------------------------------------------- fuzz
rnd = random.Random(42)


def rc():
    return "#%06x" % rnd.randrange(1 << 24)


def random_theme():
    t = {"bg": rc(), "fg": rc(), "accent": rc(), "web": rc()}
    if rnd.random() < .5:
        t["gradient"] = {"from": rc(), "to": rc(), "direction": rnd.choice(["vertical", "horizontal", "x"])}
    t["effects"] = [dict({"type": rnd.choice(sorted(T.EFFECTS))},
                         **{k: rnd.uniform(-5, 100) for k in T.NUM_LIMITS if rnd.random() < .5})
                    for _ in range(rnd.randint(0, 6))]
    t["text"] = [{"text": rnd.choice(["hi", "{time} {cpu} {temp} {x}", "{{}}", "", "{name", "a" * 300, "☃ {date}"]),
                  "x": rnd.randint(-600, 1100), "y": rnd.randint(-400, 700), "size": rnd.randint(1, 90),
                  "align": rnd.choice(["left", "center", "right", "bogus"]), "scroll": rnd.random() < .4,
                  "speed": rnd.uniform(0, 500), "width": rnd.randint(-5, 900)} for _ in range(rnd.randint(0, 4))]
    t["elements"] = {k: (rc() if rnd.random() < .8 else "rainbow")
                     for k in rnd.sample(["face", "name", "status", "channel", "aps", "uptime", "shakes", "mode", "zzz"], rnd.randint(0, 6))}
    if rnd.random() < .5:
        t["mood"] = {m: {"fg": rc(), "elements": {"face": rc()}, "effects": [{"type": "glow"}]} for m in rnd.sample(T.MOODS, 3)}
    return t


tm, ui, els = new_manager()
errors, valid = [], 0
for _ in range(300):
    try:
        th = T._clean(random_theme())
    except ValueError:
        continue
    valid += 1
    try:
        tm._theme = th
        for tt in (0.0, 0.4, 3.3, 999.9):
            eff = tm._current(tt)
            T.colorize(canvas, eff, tt, tm._ctx["layers"], tm._face_frame(eff, tt))
            tm._compose(tt)
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))
ok("fuzz: %d random valid themes render without an exception" % valid, valid > 200 and not errors, errors[:2])

# ---------------------------------------------------------------- caches and threads
before = len(T._cache)
for i in range(400):
    T.colorize(canvas.copy(), theme(effects=[{"type": "glow"}, {"type": "rain"}]), i * .1)
ok("the cache is capped (LRU)", len(T._cache) <= 48, len(T._cache))
failures = []


def worker():
    try:
        for i in range(100):
            T.colorize(canvas, everything["cyberpunk"], i * .13)
    except Exception as e:  # noqa: BLE001
        failures.append(repr(e))


threads = [threading.Thread(target=worker) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
ok("four threads rendering at once is fine", not failures, failures[:1])

# ---------------------------------------------------------------- rotation
ok("rotate: any angle works and 180 twice is the identity",
   list(T.rotate(T.rotate(canvas, 180), 180).getdata()) == list(canvas.getdata())
   and all(T.rotate(canvas, d).size in ((480, 320), (320, 480)) for d in (0, 90, 180, 270, 360, -90)))

# ---------------------------------------------------------------- per-element colors
tm, ui, els = new_manager()
layers = tm._ctx["layers"]
ok("every drawn element was captured", {"face", "name", "status", "channel", "aps", "uptime", "line1", "line2", "shakes", "mode"} <= set(layers), sorted(layers))
ui2, els2 = scene()
plain = Image.new("1", (480, 320), 0)
d = ImageDraw.Draw(plain)
for e in els2.values():
    e.draw(plain, d)
ok("capturing changes nothing about what is drawn", plain.tobytes() == tm._ctx["canvas"].tobytes())
th = theme(elements={"face": "#ff0000", "name": "#00ff00"})
img = T.colorize(tm._ctx["canvas"], th, 0, layers)


def dominant(im, box):
    px = [p for p in im.crop(box).getdata() if p != (0, 0, 0)]
    return max(set(px), key=px.count) if px else None


ok("assigned elements get their color", dominant(img, layers["face"][1]) == (255, 0, 0) and dominant(img, layers["name"][1]) == (0, 255, 0))
ok("unassigned elements keep the ink color", dominant(img, layers["status"][1]) == (255, 255, 255))
els["face"].value = faces.SAD
draw_pass(tm, ui, els)
ok("each UI update starts from a clean set of layers", len(tm._ctx["layers"]) == len(layers))
for e in tm._wrapped:
    del e.draw
ok("the wrapping can be removed again", all("draw" not in vars(e) for e in els.values()))

# ---------------------------------------------------------------- moods
mm = T._mood_map()
ok("the face on screen decides the mood", mm[faces.SAD] == "sad" and mm[faces.ANGRY] == "angry" and mm[faces.LOOK_L_HAPPY] == "happy" and mm.get("(nope)") is None)
moody = everything["moody"]
sad = T.resolve(moody, "sad")
ok("a mood's overrides win, others fall back", sad["fg"] != moody["fg"] and T.resolve(moody, "smart") is moody and T.resolve(moody, None) is moody)
for k in (0, .001, .5, .999, 1):
    T.blend(moody, sad, k)
ok("blend works at every fraction, with and without gradients", True)
T.blend(everything["cyberpunk"], dict(everything["cyberpunk"], gradient=None), .5)
tm, ui, els = new_manager()
tm._theme = moody
tm._ctx["face"] = (faces.SAD, (0, 0))
t0 = 1000.0
tm._current(t0)
tm._ctx["face"] = (faces.ANGRY, (0, 0))
mid = tm._current(t0 + 1)
ok("a mood change starts a blend", tm._mood == "angry" and tm._trans is not None)
done = tm._current(t0 + 1 + T.MOOD_FADE + .1)
ok("...and ends on the new mood's colors", tm._trans is None and done["fg"] == T.resolve(moody, "angry")["fg"])
tm._force = ("cool", t0 + 100)
ok("a forced mood wins", tm.current_mood(t0 + 5) == "cool")
tm._force = (None, 0)
tm._event_until = t0 + 104
ok("a handshake flash wins for a few seconds, then it ends", tm.current_mood(t0 + 101) == "handshake" and tm.current_mood(t0 + 105) == "angry")

# ---------------------------------------------------------------- face packs
pack = os.path.join(T.FACES_DIR, "testpack")
os.makedirs(pack)
Image.new("RGBA", (240, 90), (0, 0, 0, 0)).save(os.path.join(pack, "default.png"))      # fully transparent
solid = Image.new("RGBA", (240, 90), (0, 0, 0, 0))
ImageDraw.Draw(solid).ellipse((80, 10, 160, 80), fill=(255, 255, 255, 255))
solid.save(os.path.join(pack, "sad.png"))
frames = [Image.new("RGBA", (40, 20), c) for c in ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))]
frames[0].save(os.path.join(pack, "awake.gif"), save_all=True, append_images=frames[1:], duration=[500, 100, 200], loop=0)
ok("packs are listed with their moods", T.list_packs() == {"testpack": ["awake", "default", "sad"]}, T.list_packs())
ok("missing pack or mood gives None", T.pack_frames("nope", "sad") is None and T.pack_frames("testpack", "zzz") is None)
ok("a gif keeps its frame timings", [ms for _, ms in T.pack_frames("testpack", "awake")] == [500, 100, 200])
tm, ui, els = new_manager()
els["face"].value = faces.SAD
draw_pass(tm, ui, els)
pk = theme(face_pack="testpack", face_offset=[5, 7])
tm._theme = pk
frame = tm._face_frame(pk, 1.0)
ok("the image goes where the text face was, plus the offset", frame and frame[1] == (5, 7 + 34), frame and frame[1])
plain_img = T.colorize(tm._ctx["canvas"], pk, 1.0, tm._ctx["layers"], None)
hidden = T.colorize(tm._ctx["canvas"], pk, 1.0, tm._ctx["layers"], (Image.new("RGBA", (2, 2), (0, 0, 0, 0)), (0, 0)))
box = tm._ctx["layers"]["face"][1]
ok("the drawn text face is hidden when an image replaces it", plain_img.crop(box).tobytes() != hidden.crop(box).tobytes()
   and dominant(hidden, box) is None)
tint = theme(face_pack="testpack", face_tint=True, elements={"face": "#ff8800"})
shown = T.colorize(tm._ctx["canvas"], tint, 1.0, tm._ctx["layers"], tm._face_frame(tint, 1.0))
ok("a tinted face takes the face element's color", dominant(shown, (85, 44, 160, 114)) == (255, 136, 0), dominant(shown, (85, 44, 160, 114)))
tm._force = ("awake", time.time() + 999)
seen = {id(tm._face_frame(pk, i * .05)[0]) for i in range(300)}
ok("an animated face cycles through its frames", len(seen) == 3 and tm._face_multi)
tm._force = (None, 0)
ok("a pack without an image for the mood falls back to default.png", tm._face_frame(pk, 1.0) is not None)

finish()
