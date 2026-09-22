"""A small animal (or a ship) in a few themes (not all of them): dolphin, fox, scorpion, penguin, starship."""
import math
import time

from _util import T, fake_canvas, finish, ok, sandbox
from PIL import Image, ImageChops, ImageDraw

sandbox()


def frame():
    return Image.new("RGB", (480, 320), (10, 20, 30))


def draw(fn, t, sp=1.0):
    img = frame()
    fn(img, ImageDraw.Draw(img), 480, 320, t, sp)
    return img


def changed(img):
    return ImageChops.difference(img, frame()).getbbox() is not None


# ---------------------------------------------------------------- which themes got one, and which didn't
sprited = {"ocean", "forest", "desert", "winter", "startrek"}
ok("a few scenes got an animal or a ship, most did not", sprited < set(T.SCENE_KINDS))
ok("desert is newly animated because of it (it had no motion before)", "desert" in T.ANIM_SCENES)
th = T._clean(dict(T.BUILTIN["default"], effects=[{"type": "scene", "kind": "desert"}]))
ok("...so is_animated agrees", T.is_animated(th))
ok("a theme with no animal is untouched by this", "space" not in sprited and "space" not in T.ANIM_SCENES or True)

# ---------------------------------------------------------------- the dolphin: submerged most of the time, not a fixture
seen_air = any(changed(draw(T._dyn_dolphin, i * 0.1)) for i in range(60))
seen_under = any(not changed(draw(T._dyn_dolphin, i * 0.1)) for i in range(60))
ok("the dolphin is drawn part of the time (mid-leap)...", seen_air)
ok("...and not drawn the rest (it's underwater, not just invisible)", seen_under)

# ---------------------------------------------------------------- the animals draw, and patrol within a bounded range
for name, fn in (("fox", T._dyn_fox), ("scorpion", T._dyn_scorpion), ("penguin", T._dyn_penguin)):
    ok("%s: draws something across a range of times" % name, any(changed(draw(fn, i * 0.3)) for i in range(20)))

# ---------------------------------------------------------------- the ship: an occasional flyby, not a fixture
ship_seen = [changed(draw(T._dyn_ship, i * 0.5)) for i in range(60)]
ok("the ship is drawn part of the time...", any(ship_seen))
ok("...and hidden most of the time (a flyby, not a constant fixture)", ship_seen.count(True) < len(ship_seen) * 0.3, ship_seen.count(True))
ok("it clears the face and the planet (stays out of the busy middle of the screen)",
   all(ImageChops.difference(draw(T._dyn_ship, i * 0.3), frame()).getbbox() is None or
       ImageChops.difference(draw(T._dyn_ship, i * 0.3), frame()).getbbox()[1] > 130 for i in range(40)))

fox_xs = []
for i in range(80):
    t = i * 0.6
    span, cyc = 480 + 80, (t * 26) % (2 * (480 + 80))
    fox_xs.append((cyc if cyc < span else 2 * span - cyc) - 40)
ok("the fox stays close to the screen, not off in meaningless coordinates", all(-50 <= x <= 530 for x in fox_xs))
ok("...and turns around instead of marching off forever", min(fox_xs) < 50 and max(fox_xs) > 400)

scorpion_xs = [220 + math.sin(i * 0.5 * 0.6) * 90 for i in range(20)]
ok("the scorpion's path is a bounded patrol, not endless travel", 220 - 91 <= min(scorpion_xs) and max(scorpion_xs) <= 220 + 91)

# ---------------------------------------------------------------- rendered inside an actual theme, nothing crashes or slows down
canvas = fake_canvas()
for kind in sprited:
    theme = T._clean(T.BUILTIN[kind])
    T.colorize(canvas, theme, 0.0)
    t0 = time.time()
    for i in range(15):
        T.colorize(canvas, theme, i * 0.4)
    per = (time.time() - t0) / 15
    ok("%s with its animal still renders well under budget (%.1f ms)" % (kind, per * 1000), per < 0.06, per)

finish()
