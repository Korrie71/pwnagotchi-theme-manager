"""The radar: a display-only ranking of nearby networks from pwnagotchi's own on_wifi_update hook."""
import os
import tempfile

from _util import Panel, T, finish, new_manager, ok, sandbox
from PIL import Image

sandbox()
HS = tempfile.mkdtemp()
T._handshake_dir = lambda: HS
T.WPA_SEC_DB = os.path.join(HS, ".wpa_sec_db")


def ap(mac, name="Net", channel=6, rssi=-60, clients=0, enc="WPA2"):
    return {"mac": mac, "hostname": name, "channel": channel, "rssi": rssi,
            "clients": [{"mac": "cli%d" % i} for i in range(clients)], "encryption": enc}


# ---------------------------------------------------------------- scoring
strong = T._ap_score(ap("a", rssi=-40), set())
weak = T._ap_score(ap("a", rssi=-85), set())
ok("a strong signal scores higher than a weak one", strong > weak)
busy = T._ap_score(ap("a", clients=3), set())
quiet = T._ap_score(ap("a", clients=0), set())
ok("more clients score higher", busy > quiet)
wpa3 = T._ap_score(ap("a", enc="WPA3"), set())
wpa2 = T._ap_score(ap("a", enc="WPA2"), set())
ok("WPA3 scores lower than WPA2, all else equal", wpa3 < wpa2)
plain = T._ap_score(ap("02:00:00:00:00:ff"), set())
already = T._ap_score(ap("02:00:00:00:00:ff"), {"0200000000ff"})
ok("an access point we already have a handshake for scores much lower", already < plain - 30)
ok("a missing rssi doesn't crash the score", isinstance(T._ap_score({"mac": "x", "clients": []}, set()), float))

# ---------------------------------------------------------------- the hook and radar_rows
tm, ui, els = new_manager()
tm._settings = T.clean_settings({})
tm._display_cfg = T.clean_display({})
ok("before the first scan there is nothing, and no crash", tm.radar_rows() == ([], None))
tm.on_wifi_update(None, [ap("02:00:00:00:00:01", "CoffeeShop", 6, -45, 1, "WPA2"),
                          ap("02:00:00:00:00:02", "GuestWifi", 11, -70, 0, "WPA2"),
                          ap("02:00:00:00:00:03", "SecureNet", 1, -50, 2, "WPA3"),
                          ap("02:00:00:00:00:04", "", 6, -80, 0, "WPA2")])
rows, age = tm.radar_rows()
ok("the scan is stored", len(rows) == 4 and age is not None and age < 2)
ok("sorted best first", rows[0]["mac"] == "02:00:00:00:00:01")
ok("a blank hostname becomes '(hidden)'", next(r for r in rows if r["mac"] == "02:00:00:00:00:04")["name"] == "(hidden)")
ok("mac addresses are lower-cased", all(r["mac"] == r["mac"].lower() for r in rows))
bad_ap = {"mac": None, "hostname": None, "clients": None}
tm.on_wifi_update(None, [bad_ap])
ok("a malformed entry from bettercap doesn't crash the hook (radar just stays as it was, or clears cleanly)", True)
tm.on_wifi_update(None, [ap("x%d" % i) for i in range(90)])
rows, _ = tm.radar_rows()
ok("the list is capped", len(rows) == T.RADAR_MAX)

# a captured bssid is marked and ranks lower
os.remove(os.path.join(HS, "*") ) if False else None
open(os.path.join(HS, "wpa-sec.cracked.potfile"), "w").write("020000000005:112233445566:HomeNet:letmein\n")
open(os.path.join(HS, "HomeNet_020000000005.pcapng"), "w").write("x")
T._slow.clear()
tm.on_wifi_update(None, [ap("02:00:00:00:00:05", "HomeNet", 6, -40, 4, "WPA2"), ap("02:00:00:00:00:06", "OtherNet", 6, -40, 4, "WPA2")])
rows, _ = tm.radar_rows()
byname = {r["name"]: r for r in rows}
ok("a network we already cracked is flagged", byname["HomeNet"]["captured"] is True and byname["OtherNet"]["captured"] is False)
ok("...and ranks behind an equally good one we haven't", rows.index(byname["OtherNet"]) < rows.index(byname["HomeNet"]))

# ---------------------------------------------------------------- summary text
ok("nothing seen yet", T._radar_summary_text([], None) == "no networks seen yet")
ok("a fresh scan names the best one", T._radar_summary_text([{"name": "CoffeeShop", "clients": 3}], 1.0) == "1 networks  ·  best: CoffeeShop (3 clients)")
ok("a stale scan says how old it is", "minutes old" in T._radar_summary_text([{"name": "x", "clients": 0}], 300))

# ---------------------------------------------------------------- the touch menu
tm2, ui2, els2 = new_manager()
tm2._settings = T.clean_settings({})
tm2._display_cfg = T.clean_display({})
finger = Panel(tm2)
finger.calibrate()
tm2.on_wifi_update(None, [ap("02:00:00:00:00:01", "CoffeeShop", 6, -45, 1, "WPA2"),
                           ap("02:00:00:00:00:02", "GuestWifi", 11, -70, 0, "WPA2")])
tm2.open_menu("list")
ok("seven tabs that fit and do not overlap", len(T.TABS) == 7 and all(T.TABS[i][1][2] < T.TABS[i + 1][1][0] for i in range(6)) and T.TABS[-1][1][2] <= 452)
finger.tap_rect(finger.hit("tab", "radar"))
ok("the Radar tab opens with a summary row first", tm2._menu["tab"] == "radar" and tm2._menu["radar"][0] == "__summary__")
ok("...and the networks after it, ranked", tm2._menu["radar"][1] == "02:00:00:00:00:01")
T.draw_menu(Image.new("RGB", (480, 320)), tm2._menu, tm2._theme)
ok("the tab draws", True)
tm2._toast = None
hit = next(r for r in T.menu_hits(tm2._menu) if r[1] == ("radrow", "02:00:00:00:00:01"))
finger.tap_rect(hit[0])
ok("tapping a network shows its detail", tm2._toast and "CoffeeShop" in tm2._toast[0] and "WPA2" in tm2._toast[0], tm2._toast)
tm2._toast = None
summary_hit = next(r for r in T.menu_hits(tm2._menu) if r[1] == ("radrow", "__summary__"))
finger.tap_rect(summary_hit[0])
ok("tapping the summary row does nothing harmful", tm2._menu is not None and tm2._menu["tab"] == "radar")

# empty state
tm3, ui3, els3 = new_manager()
tm3._settings = T.clean_settings({})
tm3._display_cfg = T.clean_display({})
tm3.open_menu("list", "radar")
ok("no scan yet: the summary row says so", tm3._menu["radar_info"]["__summary__"]["text"] == "no networks seen yet")
T.draw_menu(Image.new("RGB", (480, 320)), tm3._menu, tm3._theme)
ok("...and still draws", True)
finger.tap_rect(finger.hit("tab", "system"))
ok("the other tabs stay reachable", tm2._menu["tab"] == "system")

finish()
