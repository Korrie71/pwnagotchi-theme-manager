"""Touch menu tabs: switching plugins on and off, the System tab's confirm-before-acting buttons, config safety."""
import os
import tempfile
import time

from _util import Panel, T, finish, new_manager, ok, sandbox   # _util first: it puts the stand-in pwnagotchi on the path
import pwnagotchi
import pwnagotchi.plugins as plugins
import pwnagotchi.utils as utils
from PIL import Image

sandbox()


def calibrated():
    tm, ui, els = new_manager()
    finger = Panel(tm)
    finger.calibrate()
    return tm, ui, finger


def wait_idle(tm, seconds=3):
    end = time.time() + seconds
    while tm._menu and tm._menu["busy"] and time.time() < end:
        time.sleep(0.05)


# ---------------------------------------------------------------- a fake plugin registry
names = ["webcfg", "grid", "age", "memtemp", "theme_manager", "bt-tether", "gps", "wigle", "logtail", "ups_lite", "switcher"]
plugins.database.clear()
plugins.database.update({n: "/x/%s.py" % n for n in names})
plugins.loaded.clear()
plugins.loaded.update({n: object() for n in ("webcfg", "grid", "age", "theme_manager")})
calls = []


def fake_toggle(name, enable=True):
    calls.append((name, enable))
    time.sleep(0.3)
    if enable:
        plugins.loaded[name] = object()
    else:
        plugins.loaded.pop(name, None)
    return True


plugins.toggle_plugin = fake_toggle

tm, ui, finger = calibrated()
tm.open_menu("list")
ok("the plugin list is sorted and hides theme_manager itself",
   "theme_manager" not in tm._menu["plugins"] and tm._menu["plugins"] == sorted(tm._menu["plugins"]) and len(tm._menu["plugins"]) == 10)
ok("the menu starts on the themes tab", tm._menu["tab"] == "themes")
finger.tap_rect(finger.hit("tab", "plugins"))
ok("the Plugins tab opens and the menu stays open", tm._menu and tm._menu["tab"] == "plugins" and tm._menu["page"] == 0)
rows = [r for r in T.menu_hits(tm._menu) if r[1][0] == "toggle"]
ok("plugin rows are 5 per page", len(rows) == 5 and rows[0][1][1] == tm._menu["plugins"][0])
ok("each row shows what is really loaded", tm._menu["on"] == {"webcfg", "grid", "age", "theme_manager"})
name = rows[1][1][1]
was_on = name in plugins.loaded
finger.tap_rect(rows[1][0])
ok("tapping a row starts switching it (busy) and keeps the menu open", name in tm._menu["busy"] and tm._menu is not None)
finger.tap_rect(rows[1][0])
tm._menu["until"] = 9e9
wait_idle(tm)
ok("a second tap while it is busy is ignored", calls == [(name, not was_on)], calls)
ok("when done the row shows the new state", name not in tm._menu["busy"] and (name in tm._menu["on"]) != was_on)
on_row = [r for r in T.menu_hits(tm._menu) if r[1][0] == "toggle" and r[1][1] in tm._menu["on"]][0]
finger.tap_rect(on_row[0])
wait_idle(tm)
ok("tapping an enabled plugin disables it", calls[-1] == (on_row[1][1], False) and on_row[1][1] not in tm._menu["on"], calls[-1])
finger.tap_rect(finger.hit("next"))
ok("plugins have their own pages", tm._menu["page"] == 1)
finger.tap_rect(finger.hit("tab", "themes"))
ok("the themes tab keeps its own page", tm._menu["tab"] == "themes" and tm._menu["page"] == 0)
finger.tap_rect(finger.hit("tab", "plugins"))
ok("coming back restores the plugin page", tm._menu["page"] == 1 and len(calls) == 2)
finger.tap_rect(finger.hit("tab", "themes"))
finger.tap_rect([r for r in T.menu_hits(tm._menu) if r[1][0] == "pick"][0][0])
ok("picking a theme still works", tm.applied and tm._menu is None, tm.applied)

# ---------------------------------------------------------------- a plugin that cannot load
def boom(name, enable=True):
    raise RuntimeError("plugin exploded")


plugins.toggle_plugin = boom
tm.open_menu("list", "plugins")
first = [r for r in T.menu_hits(tm._menu) if r[1][0] == "toggle"][0]
finger.tap_rect(first[0])
wait_idle(tm)
ok("a plugin that raises does not break the menu and is flagged ERR", tm._menu and not tm._menu["busy"] and first[1][1] in tm._menu["failed"])
config = {"main": {"plugins": {first[1][1]: {"enabled": True}}}, "personality": {"channels": []}}
pwnagotchi.config = config
saves = []
real_save = utils.save_config
utils.save_config = lambda c, target: saves.append((target, c["main"]["plugins"][first[1][1]]["enabled"]))
tm._forget_enabled(first[1][1])
utils.save_config = real_save
ok("pwnagotchi marks a plugin enabled before loading it: the menu sets it back to disabled",
   config["main"]["plugins"][first[1][1]]["enabled"] is False and saves and saves[-1][1] is False, saves)
pwnagotchi.config = None
tm._forget_enabled("x")
ok("with no config loaded that is a harmless no-op", True)
img = Image.new("RGB", (480, 320))
T.draw_menu(img, tm._menu, tm._theme)
tm._menu["plugins"][0] = "a-really-long-plugin-name-that-would-overflow-the-row"
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("ERR pills and long plugin names draw", True)

# ---------------------------------------------------------------- the config-save guard
d = tempfile.mkdtemp()
cfg_file = os.path.join(d, "config.toml")
open(cfg_file, "w").write('[personality]\nchannels = []\nrecon_time = 30\n')
seen = {}
utils.save_config = lambda c, target: seen.update(channels=list(c["personality"]["channels"]))
cfg = {"personality": {"channels": [1, 6, 11, 36], "recon_time": 30}}
with T.config_save_guard():
    utils.save_config(cfg, cfg_file)
ok("while saving, channels are what is on disk (not what the agent discovered)", seen["channels"] == [])
ok("afterwards the running config keeps its runtime channels", cfg["personality"]["channels"] == [1, 6, 11, 36])
open(cfg_file, "w").write('[personality]\nchannels = [1, 6]\n')
cfg["personality"]["channels"] = [9]
with T.config_save_guard():
    utils.save_config(cfg, cfg_file)
ok("a channel list the user set on disk is kept too", seen["channels"] == [1, 6])
with T.config_save_guard():
    utils.save_config(cfg, os.path.join(d, "missing.toml"))
ok("with no file on disk it falls back to a normal save", seen["channels"] == [9])
guard_target = utils.save_config
try:
    with T.config_save_guard():
        raise RuntimeError("x")
except RuntimeError:
    pass
ok("save_config is restored even if the body raises", utils.save_config is guard_target)
utils.save_config = real_save

# ---------------------------------------------------------------- the System tab
tm, ui, finger = calibrated()
tm._view._agent = type("Agent", (), {"mode": "auto"})()
T.STAT_SOURCE = tm._live_stat      # the plugin registers this when it installs itself
recorded, bettercap = [], []
pwnagotchi.restart = lambda mode, restart_bettercap=True: (time.sleep(0.3), recorded.append(("restart", mode)), bettercap.append(restart_bettercap))
pwnagotchi.reboot = lambda mode=None: (time.sleep(0.3), recorded.append(("reboot", mode)))
pwnagotchi.shutdown = lambda: (time.sleep(0.3), recorded.append(("shutdown", None)))
tm.open_menu("list")
finger.tap_rect(finger.hit("tab", "system"))
ok("the System tab opens", tm._menu["tab"] == "system")
tm._fill_status(tm._menu)
lines = tm._menu["lines"]
ok("it shows five status lines with real values", len(lines) == 5 and all("{" not in x for x in lines), lines)
ok("there are no page buttons on it", not [r for r in T.menu_hits(tm._menu) if r[1][0] in ("prev", "next")])
# ---- the refresh button
updates = []
tm._view.update = lambda force=False, new_data={}: updates.append(force)
tm._prev = "pretend this is what is on the panel"
n0 = tm.redraws[0]
finger.tap_rect(finger.hit("refresh"))
ok("refresh forgets what is on the panel, so every row gets written again", tm._prev is None and tm._full_at == 0)
ok("refresh rebuilds the UI frame and redraws", updates == [True] and tm.redraws[0] > n0, (updates, tm.redraws[0] - n0))
ok("refresh keeps the menu open on the System tab", tm._menu and tm._menu["tab"] == "system" and tm._menu["confirm"] is None)
ok("refresh needs no confirmation and runs nothing dangerous", not recorded)
finger.tap_rect(finger.hit("power", "reboot"))
finger.tap_rect(finger.hit("refresh"))
ok("refresh also cancels a pending power confirmation", tm._menu["confirm"] is None and not recorded)
ok("the refresh button only exists on the System tab", not [r for r in T.menu_hits(dict(tm._menu, tab="themes")) if r[1][0] == "refresh"])
finger.tap_rect(finger.hit("power", "restart"))
ok("the first tap on a power button only asks to confirm", tm._menu and tm._menu["confirm"][0] == "restart" and not recorded)
time.sleep(0.4)
ok("...and nothing has run", not recorded)
t0 = time.time()
finger.tap_rect(finger.hit("power", "restart"))
took = time.time() - t0
ok("the second tap runs it and closes the menu", tm._menu is None)
ok("a slow action does not block the touch thread", took < 0.25, "%.2fs" % took)
time.sleep(0.5)
ok("restart ran exactly once in the current mode", recorded == [("restart", "AUTO")], recorded)
ok("...without restarting bettercap (that would reload the Wi-Fi driver)", bettercap == [False], bettercap)
recorded.clear()
tm.open_menu("list", "system")
finger.tap_rect(finger.hit("power", "reboot"))
finger.tap_rect(finger.hit("power", "shutdown"))
ok("asking for one action and then another runs neither", not recorded and tm._menu["confirm"][0] == "shutdown")
finger.tap_rect(finger.hit("tab", "themes"))
ok("changing tab cancels a pending confirmation", tm._menu["confirm"] is None)
finger.tap_rect(finger.hit("tab", "system"))
finger.tap_rect(finger.hit("power", "reboot"))
tm._menu["confirm"] = ("reboot", finger.t - 1)
tm.menu_tick(finger.t)
ok("a confirmation expires by itself", tm._menu["confirm"] is None)
finger.tap_rect(finger.hit("power", "reboot"))
finger.tap_rect(finger.hit("power", "reboot"))
time.sleep(0.5)
ok("reboot runs after a confirmation", recorded == [("reboot", None)], recorded)
recorded.clear()
tm.open_menu("list", "system")
finger.tap_rect(finger.hit("power", "shutdown"))
finger.tap_rect(finger.hit("power", "shutdown"))
time.sleep(0.5)
ok("shutdown runs after a confirmation", recorded == [("shutdown", None)], recorded)
recorded.clear()
tm.open_menu("list", "system")
finger.tap_rect(finger.hit("mode"))
finger.tap_rect(finger.hit("mode"))
time.sleep(0.5)
ok("the mode button restarts into MANU when in AUTO, leaving bettercap alone", recorded == [("restart", "MANU")] and bettercap[-1] is False, recorded)
tm._view._agent.mode = "manual"
recorded.clear()
tm.open_menu("list", "system")
finger.tap_rect(finger.hit("mode"))
finger.tap_rect(finger.hit("mode"))
time.sleep(0.5)
ok("...and into AUTO when in MANU", recorded == [("restart", "AUTO")], recorded)
tm.open_menu("list")
finger.tap_rect(finger.hit("tab", "plugins"))
finger.tap_rect(finger.hit("tab", "system"))
ok("all three tabs can be reached from each other", tm._menu["tab"] == "system")
tm.open_menu("list", "system")
tm._fill_status(tm._menu)
for name_ in ("cyberpunk", "paper", "gameboy"):
    tm._theme = T._clean(T.BUILTIN[name_])
    T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
tm._menu["confirm"] = ("shutdown", 9e9)
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("the System tab draws, also in the confirm state", True)

finish()
