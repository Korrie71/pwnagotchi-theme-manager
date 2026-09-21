"""Achievements: counting, unlocking, saving, the Awards tab, and switching it all off."""
import json
import os
import tempfile
import time

from _util import Panel, T, finish, new_manager, ok, sandbox, swipe_burst
from PIL import Image

sandbox()


def mk(**settings):
    tm, ui, els = new_manager()
    tm._display_cfg = T.clean_display({})
    tm._settings = T.clean_settings(settings)
    return tm


def unlocked(tm):
    return sorted(tm._ach["unlocked"])


# ---------------------------------------------------------------- the table and the file format
ids = [a[0] for a in T.ACHIEVEMENTS]
ok("there are 20+ achievements with unique ids", len(ids) >= 20 and len(set(ids)) == len(ids), len(ids))
ok("names fit a row on the screen", all(len(a[1]) <= 22 for a in T.ACHIEVEMENTS), [a[1] for a in T.ACHIEVEMENTS if len(a[1]) > 22])
ok("every one has a description and a positive goal", all(a[2] and a[4] > 0 for a in T.ACHIEVEMENTS))
ok("every statistic they use exists", all(a[3] in T.default_stats() or a[3] in ("hours",) for a in T.ACHIEVEMENTS), sorted({a[3] for a in T.ACHIEVEMENTS}))
ok("no data: clean defaults", T.clean_achievements(None) == {"unlocked": {}, "stats": T.default_stats()})
junk = T.clean_achievements({"unlocked": {"first_shake": 5, "bogus": 1, "shakes_10": "yesterday", "swiper": True},
                             "stats": {"handshakes": -4, "cracked": "many", "days": "monday", "themes": [1, "a"], "swipes": 3, "extra": 1}})
ok("junk is replaced by defaults, unknown keys dropped", junk["unlocked"] == {"first_shake": 5.0} and junk["stats"]["handshakes"] == 0
   and junk["stats"]["cracked"] == 0 and junk["stats"]["days"] == [] and junk["stats"]["themes"] == ["1", "a"] and junk["stats"]["swipes"] == 3
   and "extra" not in junk["stats"], junk)
ok("long lists are capped", len(T.clean_achievements({"stats": {"days": [str(i) for i in range(1000)]}})["stats"]["days"]) == T.LIST_KEPT)
ok("progress: hours come from uptime, lists count their entries",
   T.ach_progress({"uptime_seconds": 7200, "days": ["a", "b"]}, "hours") == 2 and T.ach_progress({"days": ["a", "b"]}, "days") == 2)

# ---------------------------------------------------------------- unlocking
tm = mk()
tm._stat("handshakes", add=1)
ok("the first handshake unlocks First Blood", unlocked(tm) == ["first_shake"])
ok("...and shows it on the screen", tm._toast and tm._toast[0] == "★ First Blood", tm._toast)
ok("...and saves it", json.load(open(T.ACHIEVEMENTS_FILE))["unlocked"].keys() == {"first_shake"})
tm._stat("handshakes", add=9)
ok("ten unlocks the next one and not First Blood again", unlocked(tm) == ["first_shake", "shakes_10"])
tm._toast = None
tm._stat("handshakes", add=500)
ok("several at once: one message that counts the rest", tm._toast[0].endswith("(+2 more)") or "more" in tm._toast[0], tm._toast)
ok("...all of them are unlocked", {"shakes_50", "shakes_100", "shakes_500"} <= set(unlocked(tm)))
before = dict(tm._ach["unlocked"])
tm._stat("handshakes", add=1)
ok("an unlocked one never unlocks twice (the time stays)", tm._ach["unlocked"]["first_shake"] == before["first_shake"])

# ---------------------------------------------------------------- saving and loading
ok("a change that unlocks nothing is only marked for the next periodic save", tm._ach_dirty)
tm._save_achievements()
tm2 = mk()
tm2._load_achievements()
ok("a new manager reads it back", tm2._ach["stats"]["handshakes"] == tm._ach["stats"]["handshakes"] and "shakes_500" in tm2._ach["unlocked"])
ok("...with the unlock times", tm2._ach["unlocked"]["first_shake"] == before["first_shake"])
open(T.ACHIEVEMENTS_FILE, "w").write("{broken")
tm3 = mk()
tm3._load_achievements()
ok("a damaged file starts fresh instead of crashing", tm3._ach["stats"]["handshakes"] >= 0 and isinstance(tm3._ach["unlocked"], dict))
ok("...and repairs the file", json.load(open(T.ACHIEVEMENTS_FILE))["stats"] is not None)

# ---------------------------------------------------------------- first run starts from what is already there
root = sandbox()
hs = tempfile.mkdtemp()
for i in range(120):
    open(os.path.join(hs, "%d.pcap" % i), "w").write("x")
open(os.path.join(hs, "wpa-sec.cracked.potfile"), "w").write("\n".join("a:b:n%d:pw" % i for i in range(12)) + "\n")
T._handshake_dir = lambda: hs
T._slow.clear()
tm = mk()
tm._toast = None
tm._load_achievements()
ok("first run: the existing handshakes and cracked passwords count", tm._ach["stats"]["handshakes"] == 120 and tm._ach["stats"]["cracked"] == 12)
ok("...so the matching achievements are already unlocked", {"first_shake", "shakes_100", "cracked_10"} <= set(unlocked(tm)) and "shakes_500" not in unlocked(tm))
ok("...without a burst of messages", tm._toast is None)

# ---------------------------------------------------------------- switching it off
root = sandbox()
tm = mk(achievements=False)
tm._stat("handshakes", add=5)
tm._tick_achievements(time.time())
tm._stat("themes", mark="matrix")
ok("with achievements off nothing is counted or unlocked", not unlocked(tm) and tm._ach["stats"]["handshakes"] == 0 and tm._toast is None)
ok("...and nothing is written", not os.path.exists(T.ACHIEVEMENTS_FILE))
tm.save_settings({"achievements": True})
ok("switching them on loads the saved progress", tm._ach_loaded)

# ---------------------------------------------------------------- time based ones
tm = mk()
t0 = time.mktime((2026, 9, 20, 10, 0, 0, 0, 0, -1))
tm._tick_achievements(t0)
ok("the first tick only starts the clock", tm._ach["stats"]["uptime_seconds"] == 0)
tm._tick_achievements(t0 + 0.4)
ok("ticks closer than a second are ignored", tm._ach["stats"]["uptime_seconds"] == 0)
tm._tick_achievements(t0 + 5)
ok("uptime adds the time between ticks", 4.9 < tm._ach["stats"]["uptime_seconds"] < 5.1, tm._ach["stats"]["uptime_seconds"])
tm._tick_achievements(t0 + 1000)
ok("a long gap (the Pi was off) adds at most 30 seconds", tm._ach["stats"]["uptime_seconds"] < 40, tm._ach["stats"]["uptime_seconds"])
tm._ach["stats"]["uptime_seconds"] = 3595
tm._tick_achievements(t0 + 1005)
tm._tick_achievements(t0 + 1011)
ok("an hour of running time unlocks Warming Up", "uptime_1" in unlocked(tm))
for day in (20, 21, 22):
    tm._tick_achievements(time.mktime((2026, 9, day, 12, 0, 0, 0, 0, -1)))
    tm._ach_last = 0
ok("each new day is remembered, the same day twice is not", tm._ach["stats"]["days"] == ["2026-09-20", "2026-09-21", "2026-09-22"], tm._ach["stats"]["days"])
ok("three days unlock Regular", "days_3" in unlocked(tm))
tm._tick_achievements(time.mktime((2026, 9, 23, 3, 10, 0, 0, 0, -1)))
ok("running at 3 in the morning unlocks Night Owl", "night_owl" in unlocked(tm))
tm4 = mk()
tm4._tick_achievements(time.mktime((2026, 9, 23, 14, 0, 0, 0, 0, -1)))
ok("...and only then", "night_owl" not in unlocked(tm4))
tm5 = mk()
open(os.path.join(hs, "wpa-sec.cracked.potfile"), "w").write("a:b:c:d\n")
T._slow.clear()
tm5._ach_next_slow = 0
tm5._tick_achievements(time.time())
ok("cracked passwords are picked up from the potfiles", tm5._ach["stats"]["cracked"] >= 1 and "cracked_1" in unlocked(tm5))

# ---------------------------------------------------------------- what the features report
tm = mk()
for name in ("default", "matrix", "amber", "paper", "blood"):
    tm._stat("themes", mark=name)
ok("five different themes unlock Stylist (the same theme twice counts once)", "themes_5" in unlocked(tm))
tm._stat("themes", mark="blood")
ok("...repeats are ignored", len(tm._ach["stats"]["themes"]) == 5)
tm, ui, els = new_manager()
tm._settings = T.clean_settings({})
f = Panel(tm)
f.calibrate()
tm._menu = None
tm._active = "default"
f.swipe(380, 160, 120, 160)
ok("a swipe unlocks Swiper", "swiper" in tm._ach["unlocked"])
tm = mk()
T.cpu_temp = lambda path=None: 78.0
tm._next_temp = 0
tm._next_guard = 1e18
tm._next_power = 1e18
tm._guard_tick(time.time())
ok("the heat guard stepping in unlocks Too Hot to Handle", "too_hot" in unlocked(tm))

# ---------------------------------------------------------------- the Awards tab
root = sandbox()
tm, ui, els = new_manager()
tm._display_cfg = T.clean_display({})
tm._settings = T.clean_settings({})
finger = Panel(tm)
finger.calibrate()
tm._stat("handshakes", add=12)
tm._ach["stats"]["uptime_seconds"] = 5400
tm.open_menu("list")
ok("every tab is inside the panel", len(T.TABS) == len(T.TAB_NAMES) and "awards" in T.TAB_NAMES and all(r[2] <= 452 for _, r in T.TABS) and all(r[0] >= 28 for _, r in T.TABS))
ok("the tabs do not overlap", all(T.TABS[i][1][2] < T.TABS[i + 1][1][0] for i in range(len(T.TABS) - 1)))
finger.tap_rect(finger.hit("tab", "awards"))
ok("the Awards tab opens", tm._menu["tab"] == "awards" and len(tm._menu["awards"]) == len(T.ACHIEVEMENTS))
rows = [r for r in T.menu_hits(tm._menu) if r[1][0] == "award"]
ok("five rows per page", len(rows) == 5 and rows[0][1][1] == "first_shake")
info = tm._menu["award_info"]
ok("each row knows its progress", info["first_shake"]["unlocked"] is not None and info["shakes_50"]["progress"] == 12 and info["uptime_24"]["progress"] == 1.5)
tm._toast = None
finger.tap_rect(rows[1][0])
ok("tapping a row shows what it is for", tm._toast and tm._toast[0] == "Capture 10 handshakes" and tm._menu is not None, tm._toast)
finger.tap_rect(finger.hit("next"))
ok("the list pages like the others", tm._menu["page"] == 1)
for pg in range(-(-len(T.ACHIEVEMENTS) // T.MENU_ROWS)):
    tm._menu["page"] = pg
    T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("every page draws (done, in progress and locked rows)", True)
tm2, ui2, els2 = new_manager()
tm2._display_cfg = T.clean_display({})
tm2._settings = T.clean_settings({"achievements": False})
tm2.open_menu("list", "awards")
ok("with achievements off the tab is empty and says so", tm2._menu["awards"] == [] and tm2._menu["awards_on"] is False)
T.draw_menu(Image.new("RGB", (480, 320)), tm2._menu, tm2._theme)
ok("...and draws", True)
finger.tap_rect(finger.hit("tab", "system"))
ok("the other tabs are still reachable from it", tm._menu["tab"] == "system")

finish()
