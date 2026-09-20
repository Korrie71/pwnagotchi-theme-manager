"""Touch menu: tap detection, double tap, calibration, the Themes tab, reading events from a device."""
import builtins
import io
import json
import os
import threading
import time

from _util import Panel, T, finish, new_manager, ok, panel, press_burst, sandbox, swipe_burst
from PIL import Image

sandbox()


def fresh(calibrated=False):
    """A manager; optionally with a saved calibration for the fake panel."""
    tm, ui, els = new_manager()
    if os.path.exists(T.TOUCH_FILE):
        os.remove(T.TOUCH_FILE)
    finger = Panel(tm)
    if calibrated:
        finger.calibrate()
    return tm, finger


# ---------------------------------------------------------------- what counts as a tap
tm, finger = fresh()
press_burst(tm, 2000, 2000, 100.0)
ok("a single tap does not open the menu", tm._menu is None)
press_burst(tm, 2000, 2000, 101.0)
ok("two taps a second apart do not either", tm._menu is None)
tm, finger = fresh()
press_burst(tm, 500, 500, 10.0)
press_burst(tm, 3500, 3500, 10.3)
ok("two quick taps far apart do not", tm._menu is None)
tm, finger = fresh()
press_burst(tm, 2000, 2000, 10.0, dur=1.5)
press_burst(tm, 2000, 2000, 10.3)
ok("a long press is not a tap", tm._menu is None)
tm, finger = fresh()
tm.feed(T.EV_KEY, T.BTN_TOUCH, 1, 5.0)
tm.feed(T.EV_KEY, T.BTN_TOUCH, 0, 5.05)
ok("a touch without coordinates is ignored", tm._last_tap is None)
tm, finger = fresh()
press_burst(tm, 2000, 2000, 10.0)
press_burst(tm, 2050, 1980, 10.4)
ok("a double tap opens the menu, straight into calibration when none is saved", tm._menu and tm._menu["mode"] == "calib")

# ---------------------------------------------------------------- calibration
tm, finger = fresh(calibrated=True)
ok("four taps calibrate and switch to the theme list", tm._menu and tm._menu["mode"] == "list")
saved = json.load(open(T.TOUCH_FILE))
ok("the matrix is saved with a small error", saved["error_px"] < 12, saved["error_px"])
worst = 0
for sx, sy in [(60, 60), (240, 160), (420, 290), (100, 250), (400, 50)]:
    x, y = T.to_screen(tm._touch_m, *panel(sx, sy))
    worst = max(worst, abs(x - sx), abs(y - sy))
ok("...and the mapping is accurate on points it never saw", worst < 12, worst)
ok("no temp files are left behind by the save", not [f for f in os.listdir(T.THEME_DIR) if f.endswith(".tmp")])
os.remove(T.TOUCH_FILE)
tm2, ui2, els2 = new_manager()
f2 = Panel(tm2)
press_burst(tm2, 2000, 2000, f2.t)
press_burst(tm2, 2000, 2000, f2.t + .3)
for raw in [(500, 500), (3500, 500), (500, 3500), (2000, 2000)]:       # the last point does not fit the others
    f2.t += 1.5
    press_burst(tm2, *raw, f2.t)
ok("an inconsistent calibration is rejected and restarts", tm2._menu["mode"] == "calib" and tm2._menu["step"] == 0
   and "try again" in tm2._menu.get("msg", ""))
ok("no calibration file is written for a rejected attempt", not os.path.exists(T.TOUCH_FILE))
pts = [(40, 40), (440, 40), (40, 280), (440, 280)]
m, err = T.fit_affine([(x * 8, y * 12) for x, y in pts], pts)
sx, sy = T.to_screen(m, 240 * 8, 160 * 12)
ok("fit_affine recovers a plain scaling", err < 1e-6 and abs(sx - 240) <= 1 and abs(sy - 160) <= 1, (err, sx, sy))

# ---------------------------------------------------------------- the Themes tab
tm, finger = fresh(calibrated=True)
names = tm._menu["names"]
ok("the menu lists every theme", len(names) == len(T.BUILTIN), len(names))
rows = [r for r in T.menu_hits(tm._menu) if r[1][0] == "pick"]
finger.tap_rect(rows[2][0])
ok("tapping a row applies that theme and closes the menu", tm.applied == [names[2]] and tm._menu is None, tm.applied)
tm.open_menu("list")
n0 = tm.redraws[0]
finger.tap_rect(finger.hit("next"))
ok("'>' shows the next page and redraws", tm._menu["page"] == 1 and tm.redraws[0] > n0)
row = [r for r in T.menu_hits(tm._menu) if r[1][0] == "pick"][1]
finger.tap_rect(row[0])
ok("a row on page 2 applies the right theme", tm.applied[-1] == names[T.MENU_ROWS + 1], tm.applied[-1])
tm.open_menu("list")
finger.tap_rect(finger.hit("prev"))
ok("'<' wraps around to the last page", tm._menu["page"] == -(-len(names) // T.MENU_ROWS) - 1)
finger.tap_rect(finger.hit("close"))
ok("close closes", tm._menu is None)
tm.open_menu("list")
finger.tap(2, 2)
ok("a tap outside the panel closes it", tm._menu is None)
tm.open_menu("list")
finger.tap_rect(finger.hit("cal"))
ok("'calibrate' starts calibration again", tm._menu["mode"] == "calib")
tm.open_menu("list")
tm._menu["until"] = time.time() - 1
tm.menu_tick(time.time())
ok("the menu closes itself after a while", tm._menu is None)
tm.open_menu("list")
before = dict(tm._menu)
finger.tap(240, 264)                                    # the gap between the last row and the buttons
ok("a tap in a gap does nothing and keeps the menu open", tm._menu is not None and tm._menu["page"] == before["page"] and not tm.applied[len(tm.applied):])

# ---------------------------------------------------------------- swipes change theme
tm, finger = fresh(calibrated=True)
tm._menu = None
names = list(T.BUILTIN)
tm._active = names[3]
tm.applied.clear()
finger.swipe(380, 160, 120, 160)
ok("swiping left goes to the next theme", tm.applied == [names[4]], tm.applied)
ok("...and shows the new theme's name for a moment", tm._toast and tm._toast[0] == names[4])
tm._active = names[4]
finger.swipe(120, 160, 380, 160)
ok("swiping right goes to the previous theme", tm.applied[-1] == names[3], tm.applied)
tm._active = names[0]
finger.swipe(120, 160, 380, 160)
ok("...and wraps around at the start of the list", tm.applied[-1] == names[-1])
tm._active = names[-1]
finger.swipe(380, 160, 120, 160)
ok("...and at the end", tm.applied[-1] == names[0])
n = len(tm.applied)
finger.swipe(240, 50, 240, 280)
ok("a vertical swipe does nothing", len(tm.applied) == n and tm._menu is None)
finger.swipe(200, 160, 250, 160)
ok("a short movement is not a swipe", len(tm.applied) == n)
finger.swipe(300, 60, 200, 280)
ok("a diagonal swipe that is mostly vertical does nothing", len(tm.applied) == n)
finger.swipe(380, 160, 120, 160, dur=2.0)
ok("a slow drag is not a swipe either", len(tm.applied) == n)
finger.t += 3
swipe_burst(tm, 380, 160, 120, 160, finger.t)
swipe_burst(tm, 380, 160, 120, 160, finger.t + 0.5)
ok("two swipes within a second only change theme once", len(tm.applied) == n + 1, tm.applied[n:])
tm.open_menu("list")
n = len(tm.applied)
finger.swipe(380, 160, 120, 160)
ok("with the menu open a swipe does nothing", len(tm.applied) == n and tm._menu is not None)
tm._menu = None
tm._touch_m = None
tm._last_tap = None
finger.swipe(380, 160, 120, 160)
ok("before calibration a swipe is ignored (and is not mistaken for a tap)", len(tm.applied) == n and tm._menu is None and tm._last_tap is None)
tm._touch_m = json.load(open(T.TOUCH_FILE))["matrix"]
tm.feed(T.EV_KEY, T.BTN_TOUCH, 1, 900.0)
for i in range(4):
    tm.feed(T.EV_ABS, T.ABS_X, 2000 + 60 * i, 900.0 + i * .01)
    tm.feed(T.EV_ABS, T.ABS_Y, 2000, 900.0 + i * .01)
    tm.feed(T.EV_SYN, 0, 0, 900.0 + i * .01)
tm.feed(T.EV_KEY, T.BTN_TOUCH, 0, 900.1)
ok("a tap with a little finger drift is still a tap", tm._last_tap is not None and tm._last_tap[0] == 900.1)
tm._toast = ("hello", 1000.0)
tm._refresh_now = lambda: None
tm.menu_tick(1001.0)
ok("the toast goes away by itself", tm._toast is None)
before = tm._compose(1.0) if tm._ctx else None
tm._ctx = {"canvas": Image.new("1", (480, 320), 0), "layers": {}, "face": None}
plain = tm._compose(1.0)
tm._toast = ("cyberpunk", 9e9)
with_toast = tm._compose(1.0)
ok("the toast is drawn on the frame", plain.tobytes() != with_toast.tobytes())
tm._toast = ("a" * 200, 9e9)
tm._compose(1.0)
ok("an over-long toast text still draws", True)
tm._toast = None

# ---------------------------------------------------------------- drawing
for theme_name in ("cyberpunk", "paper", "gameboy", "default", "matrix"):
    tm._theme = T._clean(T.BUILTIN[theme_name])
    tm.open_menu("list")
    for pg in range(3):
        tm._menu["page"] = pg
        T.draw_menu(Image.new("RGB", (480, 320), (20, 20, 20)), tm._menu, tm._theme)
tm.open_menu("calib")
for step in range(4):
    tm._menu["step"] = step
    T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("the menu and the calibration screens draw for every theme and page", True)
tm.open_menu("list")
tm._ctx = {"canvas": Image.new("1", (480, 320), 0), "layers": {}, "face": None}
tm._rot = 180
with_menu = tm._compose(1.0)
tm._menu = None
ok("the composed frame contains the menu", with_menu.tobytes() != tm._compose(1.0).tobytes())

# ---------------------------------------------------------------- finding the device
DEVICES = """I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="pwr_button"
H: Handlers=kbd event0

I: Bus=0001 Vendor=0000 Product=0000 Version=0000
N: Name="ADS7846 Touchscreen"
H: Handlers=mouse0 event1

I: Bus=0003 Vendor=1234 Product=0001 Version=0100
N: Name="Some Other Touch Panel"
H: Handlers=mouse1 event7
"""
real_open = builtins.open


def fake_open(path, *a, **k):
    return io.StringIO(DEVICES) if path == "/proc/bus/input/devices" else real_open(path, *a, **k)


T.open = fake_open
ok("the ADS7846 touchscreen is preferred", T.find_touch_device() == "/dev/input/event1")
DEVICES = DEVICES.replace("ADS7846 Touchscreen", "Generic Pointer")
ok("otherwise any device with 'touch' in its name", T.find_touch_device() == "/dev/input/event7")
DEVICES = DEVICES.replace("Some Other Touch Panel", "Keyboard")
ok("no touchscreen: None", T.find_touch_device() is None)
del T.open

# ---------------------------------------------------------------- reading events from a device node
fifo = os.path.join(T.THEME_DIR, "fake-event")
os.mkfifo(fifo)
tm, finger = fresh(calibrated=True)
tm._menu = None
opened = []
tm.open_menu = lambda mode=None, tab="themes": opened.append(1)
reader = threading.Thread(target=tm._touch_loop, args=(fifo,), daemon=True)
reader.start()
time.sleep(0.3)
w = os.open(fifo, os.O_WRONLY)


def event(t, c, v):
    os.write(w, T.EVENT.pack(0, 0, t, c, v))


def kernel_tap(x, y):
    event(T.EV_KEY, T.BTN_TOUCH, 1)
    for _ in range(3):
        event(T.EV_ABS, T.ABS_X, x)
        event(T.EV_ABS, T.ABS_Y, y)
        event(T.EV_SYN, 0, 0)
        time.sleep(0.02)
    event(T.EV_KEY, T.BTN_TOUCH, 0)
    event(T.EV_SYN, 0, 0)


kernel_tap(1500, 2500)
time.sleep(0.15)
ok("a real event stream: one tap does nothing", not opened)
kernel_tap(1520, 2490)
time.sleep(0.4)
ok("...and a double tap opens the menu", len(opened) == 1)
tm._running = False
reader.join(3)
ok("the reader thread stops on shutdown", not reader.is_alive())
os.close(w)

finish()
