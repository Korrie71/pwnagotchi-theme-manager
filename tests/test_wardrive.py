"""Wardrive: a start/stop trip log -- a breadcrumb trail, distance, unique networks seen, and handshakes captured
while it runs. Purely a log; it never influences what pwnagotchi attacks."""
import os
import tempfile

from _util import T, finish, new_manager, ok, sandbox

sandbox()


def ap(mac):
    return {"mac": mac}


# ---------------------------------------------------------------- _haversine_m / wardrive_distance_m
ok("the same point is zero distance away", T._haversine_m(52.0, 4.0, 52.0, 4.0) == 0)
one_deg_lat = T._haversine_m(0.0, 0.0, 1.0, 0.0)
ok("a degree of latitude is roughly 111 km, everywhere", 110_000 < one_deg_lat < 112_000, one_deg_lat)
ok("an empty or single-point track has no distance", T.wardrive_distance_m([]) == 0 and T.wardrive_distance_m([{"lat": 1, "lon": 1}]) == 0)
track = [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.0}, {"lat": 1.0, "lon": 0.0}]
ok("distance sums leg by leg, not point to point", abs(T.wardrive_distance_m(track) - one_deg_lat) < 1)

# ---------------------------------------------------------------- persistence
HS = tempfile.mkdtemp()
T.WARDRIVE_FILE = os.path.join(HS, "wardrive.json")
ok("nothing saved yet loads as a clean, inactive state", T._load_wardrive() == {
    "active": False, "started_at": None, "ended_at": None, "points": [], "aps_seen": [], "handshakes_start": 0})
T._save_wardrive({"active": True, "started_at": 100.0, "ended_at": None,
                   "points": [{"lat": 1.0, "lon": 2.0, "t": 100.0}], "aps_seen": ["aabbccddeeff"], "handshakes_start": 3})
loaded = T._load_wardrive()
ok("a saved session loads back", loaded["active"] is True and loaded["points"] == [{"lat": 1.0, "lon": 2.0, "t": 100.0}]
   and loaded["aps_seen"] == ["aabbccddeeff"] and loaded["handshakes_start"] == 3)
open(T.WARDRIVE_FILE, "w").write("not json")
ok("a corrupt file loads as clean, not a crash", T._load_wardrive()["points"] == [])
T._save_wardrive({"active": False, "points": [{"lat": 1, "lon": 2, "t": 1}, {"lat": "bad"}, "garbage", {"lat": 1, "lon": 2}],
                   "aps_seen": [1, "ok", None], "started_at": None, "ended_at": None, "handshakes_start": 0})
loaded = T._load_wardrive()
ok("malformed points and aps_seen entries are dropped, not fatal", loaded["points"] == [{"lat": 1, "lon": 2, "t": 1}] and loaded["aps_seen"] == ["ok"])

# ---------------------------------------------------------------- the manager: start, log points, stop
sandbox()
T.WARDRIVE_FILE = os.path.join(HS, "wardrive2.json")
hs_dir = tempfile.mkdtemp()
T._handshake_dir = lambda: hs_dir
open(os.path.join(hs_dir, "Net_020000000001.pcapng"), "w").write("x")

tm, ui, els = new_manager()
tm._settings = T.clean_settings({})
tm._display_cfg = T.clean_display({})
ok("not active before it is started", tm.wardrive_status()["active"] is False)

tm.start_wardrive()
st = tm.wardrive_status()
ok("starting it is active right away, with a start time and zero everything else", st["active"] and st["distance_m"] == 0
   and st["duration_s"] >= 0 and st["aps_seen"] == 0 and st["handshakes"] == 0 and st["points"] == [])
ok("it remembers the handshake count at the moment it started (1, from the fixture)", tm._wd_handshakes_start == 1)

tm._gps = {"Latitude": 52.0, "Longitude": 4.0, "NumSatellites": 9, "FixQuality": "1"}
tm._wardrive_tick()
ok("a real fix logs the first point immediately (no prior point to compare against)", len(tm.wardrive_status()["points"]) == 1)
tm._wardrive_tick()
ok("...but not a second one right away (too soon, and has not moved)", len(tm.wardrive_status()["points"]) == 1)

tm._wd_points[-1]["t"] -= T.WARDRIVE_MIN_INTERVAL + 1   # pretend enough time has passed
tm._wardrive_tick()
ok("...still not logged: enough time passed, but has not actually moved", len(tm.wardrive_status()["points"]) == 1)

tm._wd_points[-1]["t"] -= T.WARDRIVE_MIN_INTERVAL + 1
tm._gps["Latitude"] = 52.01   # roughly 1.1 km away, well past the move threshold
tm._wardrive_tick()
ok("moving far enough (after enough time) logs a new point", len(tm.wardrive_status()["points"]) == 2)

tm._gps = {"Latitude": 0.0, "Longitude": 0.0, "FixQuality": "0"}   # no fix
tm._wd_points[-1]["t"] -= T.WARDRIVE_MIN_INTERVAL + 1
tm._wardrive_tick()
ok("no fix does not log a point", len(tm.wardrive_status()["points"]) == 2)
tm._gps = None
tm._wardrive_tick()
ok("no gps data at all is a clean no-op, not a crash", len(tm.wardrive_status()["points"]) == 2)

tm.on_wifi_update(None, [ap("02:00:00:00:00:05"), ap("02:00:00:00:00:06"), ap(""), {}])
ok("networks seen while active are counted", tm.wardrive_status()["aps_seen"] == 2)
tm.on_wifi_update(None, [ap("02:00:00:00:00:05")])   # the same one again
ok("...and it is a set, not a running total of sightings", tm.wardrive_status()["aps_seen"] == 2)

open(os.path.join(hs_dir, "Net2_020000000002.pcapng"), "w").write("x")
st = tm.wardrive_status()
ok("a handshake captured since the start is counted (2 total - 1 at start = 1)", st["handshakes"] == 1)
ok("distance reflects the logged points (roughly 1.1 km)", 1000 < st["distance_m"] < 1300, st["distance_m"])

ok("stopping it works and freezes the end time", tm.stop_wardrive() is True)
st = tm.wardrive_status()
ok("...and it is no longer active, but the summary is still there to look at", st["active"] is False and st["points"])
ok("stopping again is a clean no-op", tm.stop_wardrive() is False)

tm._gps = {"Latitude": 60.0, "Longitude": 10.0, "FixQuality": "1"}
tm._wardrive_tick()
ok("once stopped, ticks no longer log points even if gps updates keep coming", len(tm.wardrive_status()["points"]) == len(st["points"]))

# ---------------------------------------------------------------- a restart picks the last session back up
tm2, ui2, els2 = new_manager()
tm2._settings = T.clean_settings({})
tm2._display_cfg = T.clean_display({})
st2 = tm2.wardrive_status()
ok("a fresh manager (e.g. after a restart) loads the last saved session", st2["active"] is False and len(st2["points"]) == len(st["points"]))

tm.start_wardrive()
ok("starting a new one clears the previous session's points and seen networks", tm.wardrive_status()["points"] == [] and tm.wardrive_status()["aps_seen"] == 0)

# ---------------------------------------------------------------- the touch menu
from _util import Panel  # noqa: E402

sandbox()
T.WARDRIVE_FILE = os.path.join(HS, "wardrive3.json")
tm4, ui4, els4 = new_manager()
tm4._settings = T.clean_settings({})
tm4._display_cfg = T.clean_display({})
finger = Panel(tm4)
finger.calibrate()

tm4.open_menu("list", "wardrive")
ok("the wardrive tab opens", tm4._menu["tab"] == "wardrive" and tm4._menu["wardrive"]["active"] is False)
from PIL import Image  # noqa: E402
T.draw_menu(Image.new("RGB", (480, 320)), tm4._menu, tm4._theme)
ok("...and draws the stopped state without crashing", True)

toggle_hit = finger.hit("wdtoggle")
finger.tap_rect(toggle_hit)
ok("tapping the button starts a trip", tm4.wardrive_status()["active"] is True)
ok("...and the menu reflects that right away", tm4._menu["wardrive"]["active"] is True)
ok("...with a toast to confirm it", tm4._toast and "wardrive started" in tm4._toast[0], tm4._toast)

T.draw_menu(Image.new("RGB", (480, 320)), tm4._menu, tm4._theme)
ok("...and draws the active state without crashing", True)

finger.tap_rect(toggle_hit)
ok("tapping it again stops the trip", tm4.wardrive_status()["active"] is False)
ok("...with a toast to confirm it", tm4._toast and "wardrive stopped" in tm4._toast[0], tm4._toast)

finish()
