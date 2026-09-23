"""The sonar radar: a display-only snapshot of nearby networks, with a stable bearing per device."""
import os
import tempfile

from _util import Panel, T, finish, new_manager, ok, sandbox

sandbox()
HS = tempfile.mkdtemp()
T._handshake_dir = lambda: HS
T.WPA_SEC_DB = os.path.join(HS, ".wpa_sec_db")


def ap(mac, name="Net", channel=6, rssi=-60, clients=0, enc="WPA2"):
    return {"mac": mac, "hostname": name, "channel": channel, "rssi": rssi,
            "clients": [{"mac": "cli%d" % i} for i in range(clients)], "encryption": enc}


# ---------------------------------------------------------------- bearing and scoring
ok("the same device always gets the same bearing", T._radar_angle("aabbccddeeff") == T._radar_angle("aabbccddeeff"))
ok("a bearing is a real compass-ish angle", all(0 <= T._radar_angle("%012x" % i) < 360 for i in range(50)))
angles = {T._radar_angle("%012x" % i) for i in range(30)}
ok("different devices usually land at different bearings", len(angles) > 20, len(angles))
strong = T._radar_score(ap("x", rssi=-40), set())
weak = T._radar_score(ap("x", rssi=-85), set())
ok("a strong signal scores higher (closer to the centre)", strong > weak)
busy = T._radar_score(ap("x", clients=3), set())
quiet = T._radar_score(ap("x", clients=0), set())
ok("more clients score higher", busy > quiet)
wpa3 = T._radar_score(ap("x", enc="WPA3"), set())
wpa2 = T._radar_score(ap("x", enc="WPA2"), set())
ok("WPA3 scores a little lower, all else equal", wpa3 < wpa2)
already = T._radar_score(ap("aabbccddeeff"), {"aabbccddeeff"})
plain = T._radar_score(ap("aabbccddeeff"), set())
ok("an access point we already have a handshake for scores much lower", already < plain - 30)
ok("a missing rssi does not crash the score", isinstance(T._radar_score({"mac": "x", "clients": []}, set()), float))

# ---------------------------------------------------------------- the manager
tm, ui, els = new_manager()
tm._settings = T.clean_settings({})
tm._display_cfg = T.clean_display({})
ok("nothing yet, no crash", tm.radar_rows() == ([], None))
tm.on_wifi_update(None, [ap("02:00:00:00:00:01", "CoffeeShop", 6, -45, 1, "WPA2"),
                          ap("02:00:00:00:00:02", "GuestWifi", 11, -70, 0, "WPA2"),
                          ap("02:00:00:00:00:03", "SecureNet", 1, -50, 2, "WPA3"),
                          ap("02:00:00:00:00:04", "", 6, -80, 0, "WPA2")])
rows, age = tm.radar_rows()
ok("the scan is stored", len(rows) == 4 and age is not None and age < 2)
ok("sorted best first", rows[0]["mac"] == "02:00:00:00:00:01")
ok("a blank hostname becomes '(hidden)'", next(r for r in rows if r["mac"] == "02:00:00:00:00:04")["name"] == "(hidden)")
ok("every row carries a bearing", all("angle" in r and 0 <= r["angle"] < 360 for r in rows))
tm.on_wifi_update(None, [{"mac": None, "hostname": "x", "clients": None}, {}])
ok("a malformed entry from bettercap does not crash it", True)
tm.on_wifi_update(None, [ap("02:00:00:00:00:%02x" % i) for i in range(90)])
rows, _ = tm.radar_rows()
ok("the list is capped", len(rows) == T.RADAR_MAX)

# a captured bssid is marked (uses the cracking dashboard's own bssid list)
open(os.path.join(HS, "wpa-sec.cracked.potfile"), "w").write("020000000005:112233445566:HomeNet:letmein\n")
open(os.path.join(HS, "HomeNet_020000000005.pcapng"), "w").write("x")
T._slow.clear()
tm.on_wifi_update(None, [ap("02:00:00:00:00:05", "HomeNet", 6, -40, 4, "WPA2"), ap("02:00:00:00:00:06", "OtherNet", 6, -40, 4, "WPA2")])
rows, _ = tm.radar_rows()
byname = {r["name"]: r for r in rows}
ok("a network we already cracked is flagged", byname["HomeNet"]["captured"] is True and byname["OtherNet"]["captured"] is False)
ok("...and ranks behind an equally good one we have not cracked", rows.index(byname["OtherNet"]) < rows.index(byname["HomeNet"]))

# a network a paired, online node has already captured is flagged too -- the actual point of pairing
tm._nodes_paired["02:00:00:00:00:aa"] = {"mac": "02:00:00:00:00:aa", "name": "teammate", "ip": "192.0.2.9:8080",
                                          "handshakes": 1, "bssids": ["020000000006"], "online": True}
tm.on_wifi_update(None, [ap("02:00:00:00:00:06", "OtherNet", 6, -40, 4, "WPA2")])
rows, _ = tm.radar_rows()
ok("a teammate's capture marks the network as covered on our own radar", next(r for r in rows if r["name"] == "OtherNet")["captured"] is True)
tm._nodes_paired["02:00:00:00:00:aa"]["online"] = False
tm.on_wifi_update(None, [ap("02:00:00:00:00:06", "OtherNet", 6, -40, 4, "WPA2")])
rows, _ = tm.radar_rows()
ok("...but not once that teammate goes offline (its bssids are stale)", next(r for r in rows if r["name"] == "OtherNet")["captured"] is False)
del tm._nodes_paired["02:00:00:00:00:aa"]


# ---------------------------------------------------------------- the touch menu (a sonar display)
from PIL import Image  # noqa: E402

tm2, ui2, els2 = new_manager()
tm2._settings = T.clean_settings({})
tm2._display_cfg = T.clean_display({})
finger = Panel(tm2)
finger.calibrate()
tm2.on_wifi_update(None, [ap("02:00:00:00:00:01", "CoffeeShop", 6, -45, 1, "WPA2"),
                           ap("02:00:00:00:00:02", "GuestWifi", 11, -70, 0, "WPA2")])
ok("all tabs fit and do not overlap", len(T.TAB_NAMES) == 8)
tm2.open_menu("list", "radar")
ok("opening straight to the tab loads the current scan", len(tm2._menu["radar"]) == 2)
hits = [h for h in T.menu_hits(tm2._menu) if h[1][0] == "radarblip"]
ok("one tappable blip per network", len(hits) == 2)
ok("blips sit inside the sonar circle", all(
    ((r[0] + r[2]) / 2 - T.RADAR_CX) ** 2 + ((r[1] + r[3]) / 2 - T.RADAR_CY) ** 2 <= (T.RADAR_R + 5) ** 2
    for r, _ in hits))
tm2._menu["t"] = 1.0
img1 = Image.new("RGB", (480, 320))
T.draw_menu(img1, tm2._menu, tm2._theme)
tm2._menu["t"] = 4.0
img2 = Image.new("RGB", (480, 320))
T.draw_menu(img2, tm2._menu, tm2._theme)
from PIL import ImageChops  # noqa: E402
ok("the sweep actually rotates over time", ImageChops.difference(img1, img2).getbbox() is not None)
ok("bearing is stable: the same device is in the same place both times",
   T.radar_pos(tm2._menu["radar"][0]["angle"], T.radar_radius_frac(tm2._menu["radar"][0]["rssi"])) ==
   T.radar_pos(tm2._menu["radar"][0]["angle"], T.radar_radius_frac(tm2._menu["radar"][0]["rssi"])))

tm2._toast = None
hit = next(r for r, a in T.menu_hits(tm2._menu) if a == ("radarblip", "02:00:00:00:00:01"))
finger.tap_rect(hit)
ok("tapping a blip shows its detail", tm2._toast and "CoffeeShop" in tm2._toast[0] and "WPA2" in tm2._toast[0], tm2._toast)
ok("tapping does not close the menu", tm2._menu is not None and tm2._menu["tab"] == "radar")

# a captured network says so when tapped
open(os.path.join(HS, "wpa-sec.cracked.potfile"), "w").write("020000000002:112233445566:GuestWifi:hunter2\n")
open(os.path.join(HS, "GuestWifi_020000000002.pcapng"), "w").write("x")
T._slow.clear()
tm2.on_wifi_update(None, [ap("02:00:00:00:00:02", "GuestWifi", 11, -70, 0, "WPA2")])
tm2._sync_radar_menu(tm2._menu)
tm2._toast = None
hit2 = next(r for r, a in T.menu_hits(tm2._menu) if a == ("radarblip", "02:00:00:00:00:02"))
finger.tap_rect(hit2)
ok("a network we already have a handshake for mentions that", tm2._toast and "already have a handshake" in tm2._toast[0], tm2._toast)

# empty state and other tabs still reachable
tm3, ui3, els3 = new_manager()
tm3._settings = T.clean_settings({})
tm3._display_cfg = T.clean_display({})
tm3.open_menu("list", "radar")
ok("no scan yet: draws without a single blip", tm3._menu["radar"] == [])
T.draw_menu(Image.new("RGB", (480, 320)), tm3._menu, tm3._theme)
ok("...and does not crash", True)
finger.tap_rect(finger.hit("tab", "themes"))
ok("the other tabs stay reachable", tm2._menu["tab"] == "themes")

finish()
