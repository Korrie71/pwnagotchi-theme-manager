"""Settings and the option that turns an overheating Pi off (off by default, with a countdown and a way to cancel)."""
import json
import os
import subprocess
import sys
import time

from _util import ROOT, Panel, T, finish, new_manager, ok, press_burst, sandbox
from PIL import Image
import pwnagotchi  # noqa: E402  (after _util, which puts the stand-in package on the path)

sandbox()

# ---------------------------------------------------------------- validation
ok("defaults: auto-off is OFF, 85 C for 60 s, achievements on, mode aggressive, node-skip off", T.clean_settings({}) == {
    "overheat_off": False, "overheat_temp": 85.0, "overheat_seconds": 60.0, "achievements": True, "mode": "aggressive",
    "node_skip_captured": False})
ok("values are clamped to safe ranges", T.clean_settings({"overheat_temp": 10})["overheat_temp"] == 70
   and T.clean_settings({"overheat_temp": 999})["overheat_temp"] == 95 and T.clean_settings({"overheat_seconds": 1})["overheat_seconds"] == 10)
try:
    T.clean_settings([1])
    rejected = False
except ValueError:
    rejected = True
ok("settings must be an object", rejected)
ok("unknown keys are dropped", set(T.clean_settings({"bogus": 1, "overheat_off": True})) == {"overheat_off", "overheat_temp", "overheat_seconds", "achievements", "mode", "node_skip_captured"})

# ---------------------------------------------------------------- the overheating logic
shutdowns = []
pwnagotchi.shutdown = lambda: shutdowns.append(time.time())


def manager(**settings):
    tm, ui, els = new_manager()
    tm._display_cfg = T.clean_display({})
    tm.save_settings(dict({"overheat_off": True, "overheat_temp": 85, "overheat_seconds": 60}, **settings))
    tm._view._agent = type("A", (), {"mode": "auto"})()
    tm._next_guard = 1e18
    tm._next_power = 1e18
    return tm


def temp_tick(tm, temp, now):
    T.cpu_temp = lambda path=None: temp
    tm._next_temp = 0
    tm._guard_tick(now)


t = 1000.0
tm = manager(overheat_off=False)
for i in range(30):
    temp_tick(tm, 95.0, t + i * 5)
ok("with the option OFF (the default) nothing ever turns off, however hot", not tm._shutdown_at and not shutdowns)

tm = manager()
temp_tick(tm, 80.0, t)
temp_tick(tm, 80.0, t + 200)
ok("below the limit nothing happens", not tm._hot_since and not tm._shutdown_at)
temp_tick(tm, 86.0, t)
temp_tick(tm, 86.0, t + 30)
ok("above the limit but not for long: still just watching", tm._hot_since == t and not tm._shutdown_at)
temp_tick(tm, 70.0, t + 40)
ok("cooling down in between forgets the heat", tm._hot_since == 0)
temp_tick(tm, 86.0, t + 100)
temp_tick(tm, 86.0, t + 165)
ok("hot for the whole time: the countdown starts", tm._shutdown_at == t + 165 + T.OVERHEAT_GRACE_S, tm._shutdown_at)
ok("...and the screen says so, with the seconds left", tm._warn.startswith("TOO HOT: OFF IN 30s"), tm._warn)
ok("...nothing has been shut down yet", not shutdowns)
tm._guard_tick(t + 165 + 10)
ok("the countdown on screen ticks down", "OFF IN 20s" in tm._warn, tm._warn)
tm._theme = T._clean(dict(T.BUILTIN["default"], warnings=False))
tm._guard_tick(t + 165 + 12)
ok("a theme that hides warnings cannot hide this one", "OFF IN" in tm._warn)
tm._guard_tick(t + 165 + T.OVERHEAT_GRACE_S + 1)
time.sleep(0.3)
ok("when the countdown ends the Pi is shut down properly, once", len(shutdowns) == 1, len(shutdowns))
tm._guard_tick(t + 165 + T.OVERHEAT_GRACE_S + 5)
time.sleep(0.2)
ok("...and not again", len(shutdowns) == 1)

# a touch cancels
shutdowns.clear()
tm = manager()
temp_tick(tm, 90.0, t)
temp_tick(tm, 90.0, t + 61)
ok("countdown running", tm._shutdown_at > 0)
tm.feed(T.EV_KEY, T.BTN_TOUCH, 1, t + 70)
ok("a touch cancels it", tm._shutdown_at == 0 and tm._toast and tm._toast[0] == "shutdown cancelled")
tm.feed(T.EV_KEY, T.BTN_TOUCH, 0, t + 70.1)
temp_tick(tm, 90.0, t + 80)
temp_tick(tm, 90.0, t + 200)
ok("...and it stays quiet for 10 minutes even though it is still hot", tm._shutdown_at == 0 and not shutdowns)
temp_tick(tm, 90.0, t + 70 + T.OVERHEAT_SNOOZE_S + 1)
temp_tick(tm, 90.0, t + 70 + T.OVERHEAT_SNOOZE_S + 70)
ok("after the quiet time the watch starts again", tm._shutdown_at > 0)

# cooling down cancels
shutdowns.clear()
tm = manager()
temp_tick(tm, 90.0, t)
temp_tick(tm, 90.0, t + 61)
temp_tick(tm, 83.0, t + 66)
ok("only a bit cooler is not enough to cancel", tm._shutdown_at > 0)
temp_tick(tm, 78.0, t + 71)
ok("properly cooled down cancels the countdown", tm._shutdown_at == 0 and not shutdowns)
tm._guard_tick(t + 200)
time.sleep(0.2)
ok("...nothing is shut down later", not shutdowns)

# turning the option off during a countdown
tm = manager()
temp_tick(tm, 90.0, t)
temp_tick(tm, 90.0, t + 61)
tm.save_settings({"overheat_off": False})
ok("switching the option off stops a running countdown", tm._shutdown_at == 0 and tm._hot_since == 0)

# a broken temperature reading does not trigger anything
tm = manager()
T.cpu_temp = lambda path=None: (_ for _ in ()).throw(OSError("no sensor"))
tm._next_temp = 0
tm._guard_tick(t + 5000)
ok("no temperature reading: no countdown", not tm._shutdown_at)

# ---------------------------------------------------------------- the settings file
tm, ui, els = new_manager()
tm._display_cfg = T.clean_display({})
T.write_json(T.SETTINGS_FILE, {"overheat_off": True, "overheat_temp": 88})
tm._last_check = 0
tm._poll_files()
ok("a changed settings.json is picked up while running", tm._settings["overheat_off"] and tm._settings["overheat_temp"] == 88)
open(T.SETTINGS_FILE, "w").write("{broken")
os.utime(T.SETTINGS_FILE, (time.time() + 9, time.time() + 9))
tm._last_check = 0
tm._poll_files()
ok("a broken file is ignored (the last good settings stay)", tm._settings["overheat_off"])
os.remove(T.SETTINGS_FILE)
tm._last_check = 0
tm._poll_files()
ok("deleting it goes back to the defaults", not tm._settings["overheat_off"])
ok("settings.json is never listed as a theme", "settings" not in tm._all())

# ---------------------------------------------------------------- the toggle on the System tab
tm, ui, els = new_manager()
tm._display_cfg = T.clean_display({})
finger = Panel(tm)
finger.calibrate()
tm.open_menu("list", "system")
ok("the toggle is on the System tab, next to the mode button", finger.hit("overheat") and finger.hit("mode")[2] <= finger.hit("overheat")[0] + 10)
ok("the two buttons do not overlap", finger.hit("mode")[2] < finger.hit("overheat")[0])
tm._fill_status(tm._menu)
ok("it starts OFF", tm._menu["overheat"] is False)
finger.tap_rect(finger.hit("overheat"))
ok("one tap turns it on (and saves it)", tm._settings["overheat_off"] and json.load(open(T.SETTINGS_FILE))["overheat_off"])
ok("...and says so", tm._toast and "ON" in tm._toast[0] and "85" in tm._toast[0], tm._toast)
ok("the menu stays open", tm._menu and tm._menu["tab"] == "system")
tm._fill_status(tm._menu)
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("the button shows ON", tm._menu["overheat"] is True)
finger.tap_rect(finger.hit("overheat"))
ok("the next tap turns it off again", not tm._settings["overheat_off"])
tm._display_cfg = T.clean_display({})
finger.tap_rect(finger.hit("mode"))
ok("the shortened mode button still asks for confirmation", tm._menu["confirm"] and tm._menu["confirm"][0] == "mode")
tm._fill_status(tm._menu)
tm._menu["confirm"] = ("mode", 9e9)
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("...and its label fits", True)

# ---------------------------------------------------------------- the command line
def cli(*args):
    env = dict(os.environ, THEME_MANAGER_DIR=T.THEME_DIR, PYTHONPATH=os.path.join(ROOT, "tests", "stubs"))
    return subprocess.run([sys.executable, os.path.join(ROOT, "theme_manager.py"), *args], capture_output=True, text=True, env=env)


r = cli("overheat", "on", "82", "45")
saved = json.load(open(T.SETTINGS_FILE))
ok("CLI: overheat on 82 45", r.returncode == 0 and saved["overheat_off"] and saved["overheat_temp"] == 82 and saved["overheat_seconds"] == 45, r.stderr[-150:])
r = cli("overheat", "off")
ok("CLI: overheat off keeps the numbers", not json.load(open(T.SETTINGS_FILE))["overheat_off"] and json.load(open(T.SETTINGS_FILE))["overheat_temp"] == 82)
r = cli("overheat", "on", "20")
ok("CLI: an out-of-range temperature is clamped", json.load(open(T.SETTINGS_FILE))["overheat_temp"] == 70)
r = cli("overheat", "maybe")
ok("CLI: nonsense is refused", r.returncode != 0)
r = cli("achievements", "off")
ok("CLI: achievements off", r.returncode == 0 and json.load(open(T.SETTINGS_FILE))["achievements"] is False and json.load(open(T.SETTINGS_FILE))["overheat_temp"] == 70)
r = cli("achievements", "on")
ok("CLI: achievements on", json.load(open(T.SETTINGS_FILE))["achievements"] is True)
r = cli("achievements", "sometimes")
ok("CLI: achievements needs on or off", "achievements" in r.stdout and "sometimes" not in r.stdout or r.returncode != 0)
open(T.LAYOUT_FILE, "w").write(json.dumps({"offsets": {"face": [3, 4], "junk": "x"}}))
r = cli("layout", "show")
ok("CLI: layout show prints the cleaned layout", json.loads(r.stdout) == {"face": [3, 4]}, r.stdout)
r = cli("layout", "reset")
ok("CLI: layout reset clears it", json.loads(r.stdout) == {} and json.load(open(T.LAYOUT_FILE)) == {"offsets": {}})

finish()
