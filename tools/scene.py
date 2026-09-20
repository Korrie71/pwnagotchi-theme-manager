"""A fake pwnagotchi screen (made-up name and stats) rendered with the plugin's own code.

Used by make_screenshots.py and make_demo.py. Nothing here reads the real device, so the images never contain a real
device name, network or address.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
try:
    import pwnagotchi.ui.components  # noqa: F401  (a real pwnagotchi is installed)
except ImportError:
    sys.path.insert(0, os.path.join(ROOT, "tests", "stubs"))
sys.path.insert(0, ROOT)

import pwnagotchi  # noqa: E402
pwnagotchi.config = {"main": {"name": "pwnagotchi"}, "bettercap": {"handshakes": "/nonexistent"}}   # never the real name

import theme_manager as T  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pwnagotchi.ui.components import LabeledValue, Line, Text  # noqa: E402
import pwnagotchi.ui.faces as faces  # noqa: E402
import pwnagotchi.ui.fonts as fonts  # noqa: E402

fonts.setup(12, 10, 12, 70, 25, 9)
T._stats["t"] = 0

els = {
    "channel": LabeledValue(color=255, label="CH", value="6", position=(1, 3), label_font=fonts.Bold, text_font=fonts.Medium),
    "aps": LabeledValue(color=255, label="APS", value="5 (14)", position=(81, 3), label_font=fonts.Bold, text_font=fonts.Medium),
    "uptime": LabeledValue(color=255, label="UP", value="00:24:31", position=(401, 3), label_font=fonts.Bold, text_font=fonts.Medium),
    "line1": Line([0, 14, 480, 14], color=255),
    "line2": Line([0, 300, 480, 300], color=255),
    "face": Text(value=faces.AWAKE, position=(0, 34), color=255, font=fonts.Huge),
    "name": Text(value="pwnagotchi>", position=(10, 27), color=255, font=fonts.Bold),
    "status": Text(value="Hey, let's go for a walk!", position=(286, 82), color=255, font=fonts.Medium, wrap=True, max_length=25),
    "shakes": LabeledValue(color=255, label="PWND ", value="4 (27)", position=(10, 300), label_font=fonts.Bold, text_font=fonts.Medium),
    "mode": Text(value="AUTO", position=(441, 303), color=255, font=fonts.Bold),
    "points": LabeledValue(color=255, label="Pts", value="1.2K", position=(320, 258), label_font=fonts.Bold, text_font=fonts.Medium),
    "level": LabeledValue(color=255, label="Lvl", value="7", position=(320, 272), label_font=fonts.Bold, text_font=fonts.Medium),
}


class _State:
    def items(self):
        return els.items()


class _UI:
    _state = _State()


manager = T.ThemeManager()
manager._view = _UI()
manager._wrap_elements(manager._view)


def draw(face):
    els["face"].value = face
    canvas = Image.new("1", (480, 320), 0)
    d = ImageDraw.Draw(canvas)
    for e in els.values():
        e.draw(canvas, d)
    manager._on_frame(canvas)


def render(theme, face=None, mood=None, t=0.7, menu=None):
    """One frame of `theme` (a built-in name or a theme dict) with the given face on screen."""
    face = face or faces.AWAKE
    draw(face)
    th = T._clean(theme if isinstance(theme, dict) else T.BUILTIN[theme])
    effective = T.resolve(th, mood or T._mood_map().get(face))
    manager._theme, manager._force = th, (None, 0)
    ctx = manager._ctx
    img = T.colorize(ctx["canvas"], effective, t, ctx["layers"], manager._face_frame(effective, t))
    if menu:
        T.draw_menu(img, menu, th)
    return img


def frame_with(effective_theme, t, face=None):
    """A frame for an already-resolved theme dict (used for mood blends in the demo)."""
    draw(face or faces.AWAKE)
    ctx = manager._ctx
    return T.colorize(ctx["canvas"], effective_theme, t, ctx["layers"], manager._face_frame(effective_theme, t))
