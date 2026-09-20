"""Brightness: manual dim, night window, idle dimming (and the tap that only wakes the screen)."""
import json
import os
import subprocess
import sys
import time

from _util import ROOT, Panel, T, finish, new_manager, ok, press_burst, sandbox
from PIL import Image

sandbox()


def clock(h, m, day=(2026, 9, 20)):
    return time.localtime(time.mktime((*day, h, m, 0, 0, 0, -1)))


# ---------------------------------------------------------------- validation
ok("defaults: full brightness, no night, no idle", T.clean_display({}) == {"dim": 1.0, "night": None, "idle": None})
full = T.clean_display({"dim": 0.5, "night": {"from": "22:00", "to": "07:30", "dim": 0.2}, "idle": {"minutes": 5, "dim": 0.25}})
ok("a full config is accepted", full["night"]["to"] == "07:30" and full["idle"]["minutes"] == 5 and full["dim"] == 0.5)
ok("numbers are clamped (a black screen is never possible)", T.clean_display({"dim": 0})["dim"] == 0.05 and T.clean_display({"dim": 9})["dim"] == 1.0)
for bad in ("x", [], {"dim": "bright"}, {"night": {"from": "25:00", "to": "07:00"}}, {"night": {"from": "22:00"}},
            {"night": "always"}, {"idle": [1]}, {"idle": {"minutes": "soon"}}):
    try:
        T.clean_display(bad)
        rejected = False
    except ValueError:
        rejected = True
    ok("rejects %r" % (bad,), rejected)

# ---------------------------------------------------------------- the night window
night = {"from": "22:00", "to": "07:00", "dim": 0.3}
ok("the night window crosses midnight", T.night_active(night, clock(23, 30)) and T.night_active(night, clock(3, 0))
   and T.night_active(night, clock(22, 0)) and T.night_active(night, clock(6, 59)))
ok("...and ends where it says", not T.night_active(night, clock(7, 0)) and not T.night_active(night, clock(12, 0)) and not T.night_active(night, clock(21, 59)))
day = {"from": "09:00", "to": "17:00", "dim": 0.5}
ok("a window inside one day works too", T.night_active(day, clock(12, 0)) and not T.night_active(day, clock(8, 59)) and not T.night_active(day, clock(17, 0)))
ok("no night window: never active", not T.night_active(None, clock(3, 0)))

# ---------------------------------------------------------------- the dimmest setting wins
cfg = T.clean_display({"dim": 0.6, "night": night, "idle": {"minutes": 5, "dim": 0.25}})
ok("in the daytime, awake: the manual setting", T.effective_dim(cfg, clock(12, 0), 10) == (0.6, False))
ok("at night: the night setting (it is dimmer)", T.effective_dim(cfg, clock(23, 0), 10) == (0.3, False))
ok("idle for 5 minutes: idle dimming, flagged as idle", T.effective_dim(cfg, clock(12, 0), 300) == (0.25, True))
ok("idle at night: the dimmest of them", T.effective_dim(cfg, clock(23, 0), 301) == (0.25, True))
bright_night = T.clean_display({"dim": 0.2, "night": {"from": "22:00", "to": "07:00", "dim": 0.9}})
ok("a night setting never makes the screen brighter than the manual one", T.effective_dim(bright_night, clock(23, 0), 0)[0] == 0.2)
ok("idle dimming off: never idle", T.effective_dim(T.clean_display({}), clock(3, 0), 99999) == (1.0, False))

# ---------------------------------------------------------------- the image
white = Image.new("RGB", (100, 100), (200, 100, 50))
ok("full brightness returns the image untouched", T.apply_dim(white, 1.0) is white)
dimmed = T.apply_dim(white, 0.5)
ok("dimming scales every channel", dimmed.getpixel((5, 5)) == (100, 50, 25), dimmed.getpixel((5, 5)))
ok("...and keeps size and mode", dimmed.size == (100, 100) and dimmed.mode == "RGB")

# ---------------------------------------------------------------- the manager
tm, ui, els = new_manager()
tm._started = 0
tm._touch_m = None
ok("a fresh manager is at full brightness", tm._dim == 1.0)
tm._display_cfg = T.clean_display({"dim": 0.5})
tm._update_dim(time.time())
ok("a manual setting takes effect and redraws", tm._dim == 0.5 and tm.redraws[0] >= 1)
tm._ctx = {"canvas": Image.new("1", (480, 320), 1), "layers": {}, "face": None}
tm._rot = 0
tm._theme = T._clean(T.BUILTIN["default"])
dim_frame = tm._compose(1.0)
tm._dim = 1.0
full_frame = tm._compose(1.0)
ok("the composed frame really is dimmer", sum(dim_frame.convert("L").getdata()) < sum(full_frame.convert("L").getdata()) * 0.6)
tm._dim = 0.5

# idle dimming and the wake-up tap
tm2, ui2, els2 = new_manager()
finger = Panel(tm2)
finger.calibrate()
tm2._menu = None
tm2._started = 0
tm2._display_cfg = T.clean_display({"idle": {"minutes": 1, "dim": 0.25}})
tm2._last_touch = time.time() - 30
tm2._update_dim(time.time())
ok("under the idle time: full brightness", tm2._dim == 1.0 and not tm2._idle_dimmed)
tm2._last_touch = time.time() - 61
tm2._update_dim(time.time())
ok("after the idle time: dimmed", tm2._dim == 0.25 and tm2._idle_dimmed)
tm2.applied.clear()
press_burst(tm2, 2000, 2000, time.time())
ok("the first touch wakes the screen at once", tm2._dim == 1.0 and not tm2._idle_dimmed)
ok("...and is only a wake-up: it is not a tap", tm2._last_tap is None or tm2._last_tap[0] < time.time() - 5)
press_burst(tm2, 2000, 2000, time.time() + 1)
ok("the next touch is a normal tap again", tm2._last_tap is not None)
tm2._last_touch = time.time() - 61
tm2._update_dim(time.time())
tm2._menu = None
tm2.feed(T.EV_KEY, T.BTN_TOUCH, 1, time.time())
tm2.feed(T.EV_ABS, T.ABS_X, 500, time.time())
tm2.feed(T.EV_ABS, T.ABS_Y, 500, time.time())
tm2.feed(T.EV_SYN, 0, 0, time.time())
ok("touching an idle screen wakes it even before you let go", tm2._dim == 1.0)
tm2.feed(T.EV_KEY, T.BTN_TOUCH, 0, time.time() + .1)

# ---------------------------------------------------------------- the button on the System tab
tm3, ui3, els3 = new_manager()
f3 = Panel(tm3)
f3.calibrate()
tm3.open_menu("list", "system")
tm3._started = 0
ok("the dim button is on the System tab only", [r for r in T.menu_hits(tm3._menu) if r[1][0] == "dim"]
   and not [r for r in T.menu_hits(dict(tm3._menu, tab="themes")) if r[1][0] == "dim"])
seen = []
for _ in range(4):
    f3.tap_rect(f3.hit("dim"))
    seen.append(round(tm3._display_cfg["dim"], 2))
ok("each tap cycles 100% -> 60% -> 30% -> 100%", seen == [0.6, 0.3, 1.0, 0.6], seen)
ok("the choice is saved", json.load(open(T.DISPLAY_FILE))["dim"] == 0.6)
ok("the menu stays open", tm3._menu is not None and tm3._menu["tab"] == "system")
tm3._fill_status(tm3._menu)
T.draw_menu(Image.new("RGB", (480, 320)), tm3._menu, tm3._theme)
ok("the button shows the current level", tm3._menu["dim"] == 0.6)

# ---------------------------------------------------------------- the settings file
tm4, ui4, els4 = new_manager()
tm4._started = 0
T.write_json(T.DISPLAY_FILE, {"dim": 0.4, "night": {"from": "00:00", "to": "23:59", "dim": 0.2}})
tm4._last_check = 0
tm4._poll_files()
ok("a changed display.json is picked up while running", tm4._display_cfg["dim"] == 0.4 and tm4._dim == 0.2, (tm4._display_cfg, tm4._dim))
open(T.DISPLAY_FILE, "w").write("{not json")
os.utime(T.DISPLAY_FILE, (time.time() + 5, time.time() + 5))
tm4._last_check = 0
tm4._poll_files()
ok("a broken file is ignored (the old settings stay)", tm4._display_cfg["dim"] == 0.4)
os.remove(T.DISPLAY_FILE)
tm4._last_check = 0
tm4._poll_files()
ok("deleting it goes back to full brightness", tm4._dim == 1.0 and tm4._display_cfg["dim"] == 1.0)
ok("display.json is never listed as a theme", "display" not in tm4._all())

# ---------------------------------------------------------------- the command line
def cli(*args):
    """Run the real command line with the themes folder redirected to the sandbox."""
    env = dict(os.environ, THEME_MANAGER_DIR=T.THEME_DIR, PYTHONPATH=os.path.join(ROOT, "tests", "stubs"))
    return subprocess.run([sys.executable, os.path.join(ROOT, "theme_manager.py"), *args], capture_output=True, text=True, env=env)


r = cli("dim", "40")
ok("CLI: dim 40", r.returncode == 0 and json.load(open(T.DISPLAY_FILE))["dim"] == 0.4, r.stderr[-200:])
r = cli("night", "22:00", "07:00", "30")
ok("CLI: night 22:00 07:00 30", json.load(open(T.DISPLAY_FILE))["night"] == {"from": "22:00", "to": "07:00", "dim": 0.3})
r = cli("idle", "5", "25")
ok("CLI: idle 5 25", json.load(open(T.DISPLAY_FILE))["idle"] == {"minutes": 5.0, "dim": 0.25})
r = cli("night", "off")
ok("CLI: night off keeps the other settings", json.load(open(T.DISPLAY_FILE))["night"] is None and json.load(open(T.DISPLAY_FILE))["dim"] == 0.4)
r = cli("night", "25:00", "07:00", "30")
ok("CLI: a bad time is refused", r.returncode != 0 and "cannot set night" in (r.stderr + r.stdout))

finish()
