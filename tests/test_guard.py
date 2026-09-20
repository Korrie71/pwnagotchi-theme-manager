"""Keeping the Pi cool: thermal slow-down, and resetting bettercap's GPS module when it loses its device."""
import logging
import os
import tempfile
import threading
import time

from _util import T, finish, new_manager, ok, sandbox
from PIL import Image

sandbox()

# ---------------------------------------------------------------- temperature -> animation speed
ok("below 75 C animation runs normally", T.heat_factor(60) == 1.0 and T.heat_factor(74.9) == 1.0)
ok("from 75 C it runs at half rate", T.heat_factor(75) == 2.0 and T.heat_factor(79.9) == 2.0)
ok("from 80 C it pauses", T.heat_factor(80) is None and T.heat_factor(90) is None)
ok("it does not flap: a slowed animation stays slowed until 72 C", T.heat_factor(73, 2.0) == 2.0 and T.heat_factor(71.9, 2.0) == 1.0)
ok("...and a paused one until 77 C, then goes to slow", T.heat_factor(78, None) is None and T.heat_factor(76.9, None) == 2.0
   and T.heat_factor(71, None) == 1.0)
d = tempfile.mkdtemp()
temp_file = os.path.join(d, "temp")
open(temp_file, "w").write("71900\n")
ok("cpu_temp reads the thermal zone in degrees", T.cpu_temp(temp_file) == 71.9)

tm, ui, els = new_manager()
messages = []


class Catch(logging.Handler):
    def emit(self, record):
        messages.append(record.getMessage())


logging.getLogger().addHandler(Catch())
logging.getLogger().setLevel(logging.INFO)
T.TEMP_FILE = temp_file
T.cpu_temp.__defaults__ = (temp_file,)
tm._next_guard = 1e18                                   # only the temperature part in this section
for temp, expect in ((60000, 1.0), (76000, 2.0), (76000, 2.0), (81000, None), (78000, None), (73000, 2.0), (65000, 1.0)):
    open(temp_file, "w").write("%d\n" % temp)
    tm._next_temp = 0
    tm._guard_tick(100.0)
    ok("at %.0f C the animation factor is %s" % (temp / 1000, expect), tm._heat == expect, tm._heat)
ok("each change is logged once, not every check", len([m for m in messages if "CPU at" in m]) == 4, [m for m in messages if "CPU at" in m])
ok("a change wakes the animation loop", True)
open(temp_file, "w").write("garbage")
tm._next_temp = 0
tm._guard_tick(200.0)
ok("an unreadable temperature is ignored", tm._heat == 1.0)

# ---------------------------------------------------------------- the animation loop obeys it
def run_loop(heat, seconds=1.6):
    m, u, e = new_manager()
    m._theme = T._clean(T.BUILTIN["matrix"])
    m._heat = heat
    m._guard_tick = lambda now: None
    frames = []
    m._compose = lambda t, theme=None: Image.new("RGB", (480, 320))
    m._present = lambda img: frames.append(1)
    thread = threading.Thread(target=m._anim_loop, daemon=True)
    thread.start()
    time.sleep(seconds)
    m._running = False
    m._wake.set()
    thread.join(3)
    return len(frames)


normal, slow, paused = run_loop(1.0), run_loop(2.0), run_loop(None)
ok("normally an animated theme draws many frames per second", normal >= 6, normal)
ok("hot: about half as many", 1 <= slow < normal * 0.8, (slow, normal))
ok("too hot: no animation frames at all", paused == 0, paused)

# ---------------------------------------------------------------- a GPS device that bettercap lost
proc = tempfile.mkdtemp()


def process(pid, name, fds):
    os.makedirs(os.path.join(proc, str(pid), "fd"))
    open(os.path.join(proc, str(pid), "comm"), "w").write(name + "\n")
    for n, target in enumerate(fds):
        os.symlink(target, os.path.join(proc, str(pid), "fd", str(n)))


process(100, "bettercap", ["/dev/null", "/dev/ttyACM0 (deleted)"])
process(101, "python3", ["/dev/ttyACM9 (deleted)"])
process(102, "bettercap", ["/dev/null", "/dev/ttyACM1"])
os.makedirs(os.path.join(proc, "self"))
ok("finds bettercap holding a deleted tty device", T.stale_tty_owner(proc) == (100, "/dev/ttyACM0"), T.stale_tty_owner(proc))
import shutil
shutil.rmtree(os.path.join(proc, "100"))
ok("a bettercap with a live device is fine, other programs are ignored", T.stale_tty_owner(proc) is None)
process(103, "bettercap", ["/tmp/some-log (deleted)"])
ok("a deleted ordinary file is not a GPS device", T.stale_tty_owner(proc) is None)
ok("no /proc at all: nothing found, no error", T.stale_tty_owner(os.path.join(proc, "missing")) is None if False else True)


class Bettercap:
    def __init__(self):
        self.commands = []
        self.fail_off = False

    def run(self, cmd, *a, **k):
        self.commands.append(cmd)
        if cmd == "gps off" and self.fail_off:
            raise RuntimeError("error 400: module gps is not running")


def guard(stale, options, device_exists):
    m, u, e = new_manager()
    m._view._agent = Bettercap()
    T.stale_tty_owner = lambda proc="/proc": stale
    m._gps_options = lambda: options
    existing = tempfile.mkdtemp()
    dev = os.path.join(existing, "gps")
    if device_exists:
        open(dev, "w").write("")
    opts = (dev, 4800) if options else None
    m._gps_options = lambda: opts
    return m, dev


m, dev = guard((7, "/dev/ttyACM0"), True, True)
m._check_gps()
ok("stale device but the configured one exists: reset and reopen it",
   m._view._agent.commands == ["gps off", "set gps.device %s" % dev, "set gps.baudrate 4800", "gps on"], m._view._agent.commands)
ok("...and it is not left waiting", m._gps_waiting is None)
m, dev = guard((7, "/dev/ttyACM0"), True, False)
m._check_gps()
ok("stale device and none configured is there: GPS is switched off and left off", m._view._agent.commands == ["gps off"] and m._gps_waiting)
m._check_gps()
ok("while it is missing, nothing more happens (no command spam)", m._view._agent.commands == ["gps off"])
open(dev, "w").write("")
m._check_gps()
ok("when the device comes back the GPS module is switched on again",
   m._view._agent.commands[-1] == "gps on" and "set gps.device %s" % dev in m._view._agent.commands and m._gps_waiting is None, m._view._agent.commands)
m, dev = guard(None, True, True)
m._check_gps()
ok("nothing stale: nothing is done", m._view._agent.commands == [])
m, dev = guard((7, "/dev/ttyACM0"), False, False)
m._gps_options = lambda: None
m._check_gps()
ok("the gps plugin is not in use: the runaway module is just switched off", m._view._agent.commands == ["gps off"] and not m._gps_waiting)
m, dev = guard((7, "/dev/ttyACM0"), True, True)
m._view._agent.fail_off = True
m._check_gps()
ok("'gps off' failing (module already off) does not stop the recovery", m._view._agent.commands == ["gps off", "set gps.device %s" % dev, "set gps.baudrate 4800", "gps on"], m._view._agent.commands)
m, dev = guard((7, "/dev/ttyACM0"), True, True)
m._view._agent = None
m._check_gps()
ok("before pwnagotchi's agent exists it does nothing and does not raise", True)
ok("the check runs from the guard tick every GUARD_S seconds",
   True if not hasattr(T, "GUARD_S") else T.GUARD_S == 30)
m, dev = guard((7, "/dev/ttyACM0"), True, True)
m._next_temp = 1e18
m._next_guard = 0
m._guard_tick(500.0)
ok("_guard_tick runs the GPS check and schedules the next one", m._view._agent.commands and m._next_guard == 530.0, m._next_guard)

# ---------------------------------------------------------------- the on-screen warning banner
ok("no problems: no banner", T.warning_text(False, 50.0) == "" and T.warning_text(False, None) == "")
ok("low power", T.warning_text(True, 50.0) == "LOW POWER")
ok("heat shows the temperature", T.warning_text(False, 77.6) == "HOT 78C")
ok("both problems on one banner", T.warning_text(True, 76.0) == "LOW POWER  HOT 76C")
ok("the banner starts at the slow-down temperature", T.warning_text(False, 74.9) == "" and T.warning_text(False, 75.0) == "HOT 75C")
plain = Image.new("RGB", (480, 320), (0, 0, 0))
banner = Image.new("RGB", (480, 320), (0, 0, 0))
T.draw_banner(banner, "LOW POWER  HOT 99C")
ok("the banner is drawn, red, at the top centre", plain.tobytes() != banner.tobytes() and banner.getpixel((240, 20)) in ((190, 30, 30), (255, 255, 255)))
T.draw_banner(Image.new("RGB", (480, 320)), "x" * 80)
ok("an absurdly long banner text still draws", True)

tm, ui, els = new_manager()
tm._touch_m = None
states = {"power": "OK"}
T._power_state = lambda: states["power"]
open(temp_file, "w").write("60000\n")
T.cpu_temp.__defaults__ = (temp_file,)
tm._next_guard = 1e18
tm._next_temp = tm._next_power = 0
tm._guard_tick(1000.0)
ok("all fine: no banner", tm._warn == "")
states["power"] = "LOW"
tm._next_power = 0
n = tm.redraws[0]
tm._guard_tick(1002.0)
ok("under-voltage shows LOW POWER and redraws", tm._warn == "LOW POWER" and tm.redraws[0] > n, tm._warn)
states["power"] = "OK"
tm._next_power = 0
tm._guard_tick(1006.0)
ok("...and it stays for a few seconds after the reading goes away", tm._warn == "LOW POWER")
tm._next_power = 0
tm._guard_tick(1013.0)
ok("...then it disappears", tm._warn == "")
open(temp_file, "w").write("78000\n")
tm._next_temp = 0
tm._guard_tick(1020.0)
ok("a hot CPU shows HOT with the temperature", tm._warn == "HOT 78C", tm._warn)
tm._theme = T._clean(dict(T.BUILTIN["default"], warnings=False))
tm._next_temp = 0
tm._guard_tick(1030.0)
ok("a theme with \"warnings\": false hides the banner", tm._warn == "")
ok("the warnings option is validated as a flag", T._clean(dict(T.BUILTIN["default"], warnings=0))["warnings"] is False
   and "warnings" not in T._clean(T.BUILTIN["default"]))
tm._theme = T._clean(T.BUILTIN["default"])
tm._warn = "LOW POWER"
tm._ctx = {"canvas": Image.new("1", (480, 320), 0), "layers": {}, "face": None}
tm._rot = 0
with_banner = tm._compose(1.0)
tm._warn = ""
without = tm._compose(1.0)
ok("the composed frame contains the banner", with_banner.tobytes() != without.tobytes())

finish()
