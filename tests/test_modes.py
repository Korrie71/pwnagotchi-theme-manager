"""Attack modes: aggressive (normal), passive recon, and home defense (passive + a rogue-AP watch)."""
import json
import os
import subprocess
import sys
import tempfile

from _util import Panel, T, finish, new_manager, ok, sandbox
from PIL import Image

sandbox()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def agent_with(deauth=True, associate=True, whitelist=()):
    cfg = {"personality": {"deauth": deauth, "associate": associate}, "main": {"whitelist": list(whitelist)}}
    return type("Agent", (), {"config": lambda self: cfg})(), cfg


# ---------------------------------------------------------------- validation
ok("the default mode is aggressive", T.clean_settings({})["mode"] == "aggressive")
ok("only a real mode is accepted", T.clean_settings({"mode": "nonsense"})["mode"] == "aggressive")
for m in T.ATTACK_MODES:
    ok("%s is a valid mode" % m, T.clean_settings({"mode": m})["mode"] == m)

# ---------------------------------------------------------------- applying it to the live agent
tm, ui, els = new_manager()
tm._display_cfg = T.clean_display({})
agent, cfg = agent_with()
tm._view._agent = agent
tm._settings = T.clean_settings({"mode": "aggressive"})
tm._apply_mode()
ok("aggressive leaves the agent's own settings alone", cfg["personality"] == {"deauth": True, "associate": True})
tm.save_settings(dict(tm._settings, mode="passive"))
ok("passive turns deauth and associate off immediately", cfg["personality"]["deauth"] is False and cfg["personality"]["associate"] is False)
tm.save_settings(dict(tm._settings, mode="aggressive"))
ok("switching back restores exactly what the user had (not just True/True)", cfg["personality"] == {"deauth": True, "associate": True})

agent2, cfg2 = agent_with(deauth=False, associate=True)   # a user who already had deauth off
tm._view._agent = agent2
tm.save_settings(dict(tm._settings, mode="home"))
ok("home defense also disables both, regardless of mode", cfg2["personality"] == {"deauth": False, "associate": False})
tm.save_settings(dict(tm._settings, mode="aggressive"))
ok("...and restores the original mix on the way back, not just True", cfg2["personality"] == {"deauth": False, "associate": True})
tm._view._agent = None
tm._apply_mode()
ok("no agent yet: does nothing, never crashes", True)
tm._guard_tick(0)
ok("the periodic safety-net call is harmless too", True)

# ---------------------------------------------------------------- home defense: the rogue-AP watch
tm2, ui2, els2 = new_manager()
tm2._display_cfg = T.clean_display({})
tm2._settings = T.clean_settings({"mode": "aggressive"})
agent3, _ = agent_with(whitelist=["Netwerk Koen"])
tm2._toast = None
tm2.on_wifi_update(agent3, [{"mac": "02:00:00:00:00:01", "hostname": "Netwerk Koen"}])
ok("aggressive mode: the watch does nothing at all", tm2._home_watch == {} and tm2._toast is None)
tm2._settings = T.clean_settings({"mode": "home"})
tm2.on_wifi_update(agent3, [{"mac": "02:00:00:00:00:01", "hostname": "Netwerk Koen"}])
ok("home mode, first sighting: learned quietly, no alarm", tm2._home_watch == {"Netwerk Koen": ["020000000001"]} and tm2._toast is None, tm2._home_watch)
tm2.on_wifi_update(agent3, [{"mac": "02:00:00:00:00:01", "hostname": "Netwerk Koen"}])
ok("seeing the same device again is not news", tm2._toast is None)
tm2.on_wifi_update(agent3, [{"mac": "02:00:00:00:00:99", "hostname": "Netwerk Koen"}])
ok("a second, unrecognized device with the same network name is flagged", tm2._toast and "Netwerk Koen" in tm2._toast[0], tm2._toast)
ok("...and remembered, so it is not re-learned as if new", "020000000099" in tm2._home_watch["Netwerk Koen"])
tm2._toast = None
tm2.on_wifi_update(agent3, [{"mac": "some other network's ap", "hostname": "Somebody Elses Wifi"}])
ok("a network that is not yours is none of its business", tm2._toast is None)
agent_nowl, _ = agent_with(whitelist=[])
tm2.on_wifi_update(agent_nowl, [{"mac": "02:00:00:00:00:02", "hostname": "Anything"}])
ok("an empty whitelist means nothing to protect, so it does nothing", tm2._toast is None)
tm2.on_wifi_update(agent3, [{"mac": None, "hostname": "Netwerk Koen"}, {}])
ok("a malformed access point does not crash the hook", True)

# ---------------------------------------------------------------- persistence
d = sandbox()
tm3, ui3, els3 = new_manager()
tm3._display_cfg = T.clean_display({})
tm3._settings = T.clean_settings({"mode": "home"})
agent4, _ = agent_with(whitelist=["Home"])
tm3.on_wifi_update(agent4, [{"mac": "02:00:00:00:00:11", "hostname": "Home"}])
ok("the learned devices are saved to disk", json.load(open(T.HOME_WATCH_FILE)) == {"Home": ["020000000011"]})
tm4, ui4, els4 = new_manager()
tm4._load_home_watch()
ok("a fresh manager picks up what was already learned", tm4._home_watch == {"Home": ["020000000011"]})
open(T.HOME_WATCH_FILE, "w").write("{broken")
tm4._load_home_watch()
ok("a damaged file starts fresh instead of crashing", tm4._home_watch == {})

# ---------------------------------------------------------------- the touch menu
tm5, ui5, els5 = new_manager()
tm5._display_cfg = T.clean_display({})
tm5._settings = T.clean_settings({"mode": "aggressive"})
tm5._view._agent = type("Agent", (), {"mode": "auto", "config": lambda self: {"personality": {"deauth": True, "associate": True}}})()
finger = Panel(tm5)
finger.calibrate()
tm5.open_menu("list", "system")
tm5._fill_status(tm5._menu)
ok("the mode button, hot-off and the new attack-mode button all fit without overlapping", True)
hits = {h[1][0]: h[0] for h in T.menu_hits(tm5._menu)}
ok("mode / overheat / atkmode sit side by side, none overlapping", hits["mode"][2] < hits["overheat"][0] < hits["overheat"][2] < hits["atkmode"][0])
T.draw_menu(Image.new("RGB", (480, 320)), tm5._menu, tm5._theme)
ok("the row draws in every mode", True)
finger.tap_rect(hits["atkmode"])
ok("tapping it cycles to the next mode", tm5._settings["mode"] == "passive")
finger.tap_rect(hits["atkmode"])
ok("...and the next", tm5._settings["mode"] == "home")
finger.tap_rect(hits["atkmode"])
ok("...wrapping back to aggressive", tm5._settings["mode"] == "aggressive")
ok("no confirmation needed, unlike restart/reboot/shutdown", tm5._menu is not None and tm5._menu["confirm"] is None)
for m in T.ATTACK_MODES:
    tm5._menu["atkmode"] = m
    T.draw_menu(Image.new("RGB", (480, 320)), tm5._menu, tm5._theme)
ok("every mode's label draws", True)

# ---------------------------------------------------------------- CLI
def cli(*args):
    env = dict(os.environ, THEME_MANAGER_DIR=T.THEME_DIR, PYTHONPATH=os.path.join(ROOT, "tests", "stubs"))
    return subprocess.run([sys.executable, os.path.join(ROOT, "theme_manager.py"), *args], capture_output=True, text=True, env=env)


r = cli("mode")
ok("CLI: mode with no argument shows the current one", r.returncode == 0 and r.stdout.strip() == "aggressive", r.stdout)
r = cli("mode", "home")
ok("CLI: mode home sets it", r.returncode == 0 and r.stdout.strip() == "home")
ok("...and it is saved", json.load(open(T.SETTINGS_FILE))["mode"] == "home")
r = cli("mode", "nonsense")
ok("CLI: a bad mode name is refused", r.returncode != 0)
ok("...and does not change what was saved", json.load(open(T.SETTINGS_FILE))["mode"] == "home")

finish()
