"""Shared helpers for the tests. Run any test file directly: `python tests/test_render.py`."""
import os
import random
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(HERE, "stubs"), ROOT]      # the stand-in pwnagotchi first, then the plugin

from PIL import Image, ImageDraw  # noqa: E402
import theme_manager as T  # noqa: E402
from pwnagotchi.ui.components import LabeledValue, Line, Text  # noqa: E402
import pwnagotchi.ui.fonts as fonts  # noqa: E402

fonts.setup(12, 10, 12, 70, 25, 9)
random.seed(1234)
_failures = []
_count = [0]


def ok(name, cond, extra=""):
    _count[0] += 1
    print(("PASS " if cond else "FAIL ") + name + ((" [%s]" % (extra,)) if extra != "" else ""))
    if not cond:
        _failures.append(name)


def finish():
    print("\n%d checks, %d failed" % (_count[0], len(_failures)))
    for f in _failures:
        print("  FAILED:", f)
    sys.exit(1 if _failures else 0)


def sandbox():
    """Point every path the plugin uses at a fresh temp folder, so tests never touch a real system.
    Every upper-case setting that lives under the themes folder (present or added later) is redirected."""
    d = tempfile.mkdtemp(prefix="tm-test-")
    old = T.THEME_DIR
    for name in dir(T):
        value = getattr(T, name)
        if name.isupper() and isinstance(value, str) and (value == old or value.startswith(old + os.sep)):
            setattr(T, name, d + value[len(old):])
    os.makedirs(T.FACES_DIR, exist_ok=True)
    return d


def scene():
    """A fake pwnagotchi screen (made-up name and stats) made of real-looking widgets."""
    els = {
        "channel": LabeledValue(color=255, label="CH", value="6", position=(1, 3), label_font=fonts.Bold, text_font=fonts.Medium),
        "aps": LabeledValue(color=255, label="APS", value="5 (14)", position=(81, 3), label_font=fonts.Bold, text_font=fonts.Medium),
        "uptime": LabeledValue(color=255, label="UP", value="00:24:31", position=(401, 3), label_font=fonts.Bold, text_font=fonts.Medium),
        "line1": Line([0, 14, 480, 14], color=255),
        "line2": Line([0, 300, 480, 300], color=255),
        "face": Text(value=T_faces().AWAKE, position=(0, 34), color=255, font=fonts.Huge),
        "name": Text(value="pwnagotchi>", position=(10, 27), color=255, font=fonts.Bold),
        "status": Text(value="Hey, let's go for a walk!", position=(286, 82), color=255, font=fonts.Medium, wrap=True, max_length=25),
        "shakes": LabeledValue(color=255, label="PWND ", value="4 (27)", position=(10, 300), label_font=fonts.Bold, text_font=fonts.Medium),
        "mode": Text(value="AUTO", position=(441, 303), color=255, font=fonts.Bold),
    }

    class State:
        def items(self):
            return els.items()

    class UI:
        _state = State()
        _render_cbs = []
        _agent = None

        def get(self, key):
            return els[key].value if key in els else None

    return UI(), els


def T_faces():
    import pwnagotchi.ui.faces as faces
    return faces


def draw_pass(tm, ui, els):
    """One UI update: draw every element, then publish the frame like pwnagotchi's render callback."""
    canvas = Image.new("1", (480, 320), 0)
    d = ImageDraw.Draw(canvas)
    for e in els.values():
        e.draw(canvas, d)
    tm._on_frame(canvas)
    return canvas


def fake_canvas():
    ui, els = scene()
    tm = T.ThemeManager()
    return draw_pass(tm, ui, els)


def new_manager():
    """A ThemeManager wired to a fake UI, with the side effects (drawing to a screen, saving) replaced."""
    ui, els = scene()
    tm = T.ThemeManager()
    T._save_installed(set(T.BUILTIN))     # most tests want every bundled theme available; test_gallery covers the empty start
    tm._view = ui
    tm._wrap_elements(ui)
    tm._running = True
    tm.applied, tm.redraws = [], [0]
    tm._apply = lambda name, persist=False: tm.applied.append(name)
    tm._refresh_now = lambda: tm.redraws.__setitem__(0, tm.redraws[0] + 1)
    tm._active = "cyberpunk"
    tm._theme = T._clean({k: v for k, v in T.BUILTIN["cyberpunk"].items() if k not in ("layout", "hide", "sizes", "panels")})   # the tests' fake screen is laid out as stock
    draw_pass(tm, ui, els)
    return tm, ui, els


def press_burst(tm, x, y, t, dur=0.08):
    """A realistic burst of touch events for one tap: samples while down, garbage at release (must be ignored)."""
    tm.feed(T.EV_KEY, T.BTN_TOUCH, 1, t)
    for i in range(4):
        tm.feed(T.EV_ABS, T.ABS_X, x + random.randint(-6, 6), t + .01 * i)
        tm.feed(T.EV_ABS, T.ABS_Y, y + random.randint(-6, 6), t + .01 * i)
        tm.feed(T.EV_SYN, 0, 0, t + .01 * i)
    tm.feed(T.EV_ABS, T.ABS_X, 0, t + dur)
    tm.feed(T.EV_ABS, T.ABS_Y, 4095, t + dur)
    tm.feed(T.EV_KEY, T.BTN_TOUCH, 0, t + dur)


def panel(sx, sy):
    """Screen pixel -> raw touch reading of a panel with swapped and inverted axes, plus noise."""
    return int(4095 - (sy / 320) * 4095 + random.randint(-15, 15)), int((sx / 480) * 4095 + random.randint(-15, 15))


def swipe_burst(tm, sx0, sy0, sx1, sy1, t, dur=0.35, steps=8):
    """A finger moving from one screen pixel to another on the calibrated fake panel."""
    tm.feed(T.EV_KEY, T.BTN_TOUCH, 1, t)
    for i in range(steps + 1):
        f = i / steps
        rx, ry = panel(sx0 + (sx1 - sx0) * f, sy0 + (sy1 - sy0) * f)
        tm.feed(T.EV_ABS, T.ABS_X, rx, t + dur * f)
        tm.feed(T.EV_ABS, T.ABS_Y, ry, t + dur * f)
        tm.feed(T.EV_SYN, 0, 0, t + dur * f)
    tm.feed(T.EV_KEY, T.BTN_TOUCH, 0, t + dur)


class Panel:
    """Drives a manager the way a finger would: taps at screen pixels through a calibrated fake panel."""
    def __init__(self, tm):
        self.tm, self.t = tm, 50.0

    def tap(self, sx, sy):
        self.t += 1.5
        press_burst(self.tm, *panel(sx, sy), self.t)

    def swipe(self, sx0, sy0, sx1, sy1, dur=0.35):
        self.t += 1.5
        swipe_burst(self.tm, sx0, sy0, sx1, sy1, self.t, dur)

    def tap_rect(self, rect):
        self.tap((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)

    def calibrate(self):
        press_burst(self.tm, 2000, 2000, self.t)
        press_burst(self.tm, 2000, 2000, self.t + .3)
        for sx, sy in T.CALIB_POINTS:
            self.tap(sx, sy)

    def hit(self, act, arg=None):
        return [r for r in T.menu_hits(self.tm._menu) if r[1][0] == act and (arg is None or r[1][1] == arg)][0][0]
