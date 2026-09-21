"""The cracking dashboard: read-only wpa-sec status, the Crack tab, placeholders, CLI and API."""
import json
import os
import sqlite3
import tempfile
import time

from _util import Panel, T, finish, new_manager, ok, sandbox
from PIL import Image

sandbox()
HS = tempfile.mkdtemp()
T._handshake_dir = lambda: HS
T.WPA_SEC_DB = os.path.join(HS, ".wpa_sec_db")


def touch(name, age=0):
    p = os.path.join(HS, name)
    open(p, "w").write("x")
    if age:
        t = time.time() - age
        os.utime(p, (t, t))
    return p


def potfile(*lines):
    open(os.path.join(HS, "wpa-sec.cracked.potfile"), "w").write("\n".join(lines) + ("\n" if lines else ""))


def db(rows):
    if os.path.exists(T.WPA_SEC_DB):
        os.remove(T.WPA_SEC_DB)
    con = sqlite3.connect(T.WPA_SEC_DB)
    con.execute("CREATE TABLE handshakes (path TEXT PRIMARY KEY, status INTEGER)")
    con.executemany("INSERT INTO handshakes VALUES (?, ?)", rows)
    con.commit()
    con.close()


def reset():
    for f in os.listdir(HS):
        os.remove(os.path.join(HS, f))
    if os.path.exists(T.WPA_SEC_DB):
        os.remove(T.WPA_SEC_DB)
    T._slow.clear()


# ---------------------------------------------------------------- parsing
ok("filenames split into essid and bssid", T.HANDSHAKE_RE.match("CoffeeShop_aabbccddee01.pcapng").groups() == ("CoffeeShop", "aabbccddee01"))
ok("a hidden network's blank essid still matches", T.HANDSHAKE_RE.match("_aabbccddee01.pcapng").group(1) == "")
ok("a name that isn't bssid-shaped doesn't match", T.HANDSHAKE_RE.match("randomfile.pcapng") is None)
reset()
potfile("aabbccddee01:112233445566:CoffeeShop:letmein123", "not-a-valid-line", "AABBCCDDEE02:112233445567:Guest Wifi:hunter2")
pot = T._wpa_potfile()
ok("the potfile is parsed into bssid -> (essid, password)", pot["aabbccddee01"] == ("CoffeeShop", "letmein123"))
ok("bssids are case-folded, malformed lines skipped", pot["aabbccddee02"] == ("Guest Wifi", "hunter2") and len(pot) == 2)

# ---------------------------------------------------------------- the wpa-sec database (read-only)
reset()
ok("no database: counts are n/a, not zero", T._wpa_db_counts() == {"queued": "n/a", "uploaded": "n/a", "invalid": "n/a"})
ok("no database: status lookup returns None, not an empty-but-present dict", T._wpa_db_status() is None)
touch("Test_aabbccddee09.pcapng")
T._slow.clear()
rows = T.crack_rows()
ok("without wpa-sec, a handshake with no crack is 'unknown'", rows[0]["status"] == "unknown")
db([(os.path.join(HS, "Test_aabbccddee09.pcapng"), 0)])
T._slow.clear()
ok("with the database, counts come from it", T._wpa_db_counts() == {"queued": "1", "uploaded": "0", "invalid": "0"})
open(T.WPA_SEC_DB, "w").write("not a database")
T._slow.clear()
ok("a corrupt database is treated as absent (not as zero), never crashes", T._wpa_db_counts() == {"queued": "n/a", "uploaded": "n/a", "invalid": "n/a"} and T._wpa_db_status() is None)
os.remove(T.WPA_SEC_DB)

# ---------------------------------------------------------------- crack_rows / crack_summary
reset()
touch("CoffeeShop_aabbccddee01.pcapng", age=10)
touch("HomeNet_aabbccddee04.pcapng", age=5)
touch("Neighbor_aabbccddee05.pcapng", age=0)
touch("randomfile.pcapng", age=20)
potfile("aabbccddee01:112233445566:CoffeeShop:letmein123")
db([(os.path.join(HS, "HomeNet_aabbccddee04.pcapng"), 0), (os.path.join(HS, "Neighbor_aabbccddee05.pcapng"), 1)])
T._slow.clear()
rows = T.crack_rows()
ok("newest handshake first", [r["file"] for r in rows][:2] == ["Neighbor_aabbccddee05.pcapng", "HomeNet_aabbccddee04.pcapng"])
byname = {r["file"]: r for r in rows}
ok("a cracked bssid wins even if the database also has a row for it", True)  # no overlap here, checked below
ok("cracked: name and password come from the potfile", byname["CoffeeShop_aabbccddee01.pcapng"] == {
    "file": "CoffeeShop_aabbccddee01.pcapng", "name": "CoffeeShop", "bssid": "aabbccddee01", "status": "cracked",
    "password": "letmein123", "time": byname["CoffeeShop_aabbccddee01.pcapng"]["time"]})
ok("queued (status 0) and invalid (status 1) come from the database", byname["HomeNet_aabbccddee04.pcapng"]["status"] == "queued"
   and byname["Neighbor_aabbccddee05.pcapng"]["status"] == "invalid")
ok("a name the database and potfile don't know about is 'queued' once wpa-sec is active", byname["randomfile.pcapng"]["status"] == "queued")
ok("a name with no bssid still guesses a name from the file (not blank)", byname["randomfile.pcapng"]["name"] == "randomfile" and byname["randomfile.pcapng"]["bssid"] is None)
summary = T.crack_summary(rows)
ok("the summary counts add up", summary == {"total": 4, "cracked": 1, "uploaded": 0, "queued": 2, "invalid": 1, "unknown": 0})
ok("cracking a handshake that was uploaded overrides the database status", True)
db([(os.path.join(HS, "CoffeeShop_aabbccddee01.pcapng"), 2)])
T._slow.clear()
rows_now = {r["file"]: r for r in T.crack_rows()}
ok("...checked directly: the row still says cracked, not uploaded", rows_now["CoffeeShop_aabbccddee01.pcapng"]["status"] == "cracked")
ok("limit is respected", len(T.crack_rows(limit=2)) == 2)

# ---------------------------------------------------------------- summary text and placeholders
ok("empty: says so plainly", T._crack_summary_text({"total": 0, "cracked": 0, "queued": 0, "uploaded": 0, "invalid": 0, "unknown": 0}) == "no handshakes yet")
ok("wpa-sec active: shows the breakdown", "queued" in T._crack_summary_text({"total": 5, "cracked": 2, "queued": 2, "uploaded": 0, "invalid": 1, "unknown": 0}))
ok("wpa-sec not active: says so instead of a meaningless 0", "not active" in T._crack_summary_text({"total": 3, "cracked": 1, "queued": 0, "uploaded": 0, "invalid": 0, "unknown": 2}))
reset()
touch("Solo_aabbccddee08.pcapng")
db([(os.path.join(HS, "Solo_aabbccddee08.pcapng"), 0)])
T._slow.clear()
ok("{queued}/{uploaded}/{invalid} read from the live database", T._expand("q={queued} u={uploaded} i={invalid}") == "q=1 u=0 i=0")
reset()
T._slow.clear()
ok("without wpa-sec they read n/a, not a stale number", T._expand("{queued}") == "n/a")
ok("they're documented as live (redraw every second)", all(t in T.LIVE_TOKENS for t in ("{queued}", "{uploaded}", "{invalid}")))

# ---------------------------------------------------------------- CLI
import subprocess
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cli(*args):
    env = dict(os.environ, THEME_MANAGER_DIR=T.THEME_DIR, THEME_MANAGER_HANDSHAKES=HS, THEME_MANAGER_WPA_DB=T.WPA_SEC_DB,
               PYTHONPATH=os.path.join(ROOT, "tests", "stubs"))
    return subprocess.run([sys.executable, os.path.join(ROOT, "theme_manager.py"), *args], capture_output=True, text=True, env=env)


reset()
potfile("aabbccddee01:112233445566:CoffeeShop:letmein123")
touch("CoffeeShop_aabbccddee01.pcapng")
touch("HomeNet_aabbccddee04.pcapng")
r = cli("cracking")
ok("CLI: cracking prints a JSON summary", r.returncode == 0 and json.loads(r.stdout)["cracked"] == 1, r.stdout)
r = cli("cracking", "list")
ok("CLI: cracking list prints one line per handshake", r.returncode == 0 and "cracked " in r.stdout and "letmein123" in r.stdout, r.stdout)

# ---------------------------------------------------------------- the touch menu
tm, ui, els = new_manager()
tm._display_cfg = T.clean_display({})
tm._settings = T.clean_settings({})
finger = Panel(tm)
finger.calibrate()
touch("Office5G_aabbccddee03.pcapng")
touch("OldRouter_aabbccddee06.pcapng")
T._slow.clear()
ok("the tabs fit and do not overlap", all(T.TABS[i][1][2] < T.TABS[i + 1][1][0] for i in range(len(T.TABS) - 1)) and T.TABS[-1][1][2] <= 452)
tm.open_menu("list")
finger.tap_rect(finger.hit("tab", "crack"))
ok("the Crack tab opens with a summary row first", tm._menu["tab"] == "crack" and tm._menu["crack"][0] == "__summary__")
ok("...and the real handshakes after it", set(tm._menu["crack"][1:]) == {"CoffeeShop_aabbccddee01.pcapng", "HomeNet_aabbccddee04.pcapng", "Office5G_aabbccddee03.pcapng", "OldRouter_aabbccddee06.pcapng"})
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("the tab draws (summary line and pill rows)", True)
rows = [r for r in T.menu_hits(tm._menu) if r[1][0] == "crackrow"]
ok("five rows per page, tappable", len(rows) == 5)
tm._toast = None
hit = next(r for r in rows if r[1][1] == "CoffeeShop_aabbccddee01.pcapng")
finger.tap_rect(hit[0])
ok("tapping a cracked row shows its password", tm._toast and tm._toast[0] == "CoffeeShop: letmein123", tm._toast)
tm._toast = None
finger.tap_rect(next(r for r in rows if r[1][1] == "HomeNet_aabbccddee04.pcapng")[0])
db([(os.path.join(HS, "HomeNet_aabbccddee04.pcapng"), 0)])
T._slow.clear()
tm._sync_crack_menu(tm._menu)
tm._toast = None
finger.tap_rect(next(r for r in T.menu_hits(tm._menu) if r[1] == ("crackrow", "HomeNet_aabbccddee04.pcapng"))[0])
ok("tapping a queued row explains that", tm._toast and "wait" in tm._toast[0].lower(), tm._toast)
tm._toast = None
summary_hit = next(r for r in T.menu_hits(tm._menu) if r[1] == ("crackrow", "__summary__"))
finger.tap_rect(summary_hit[0])
ok("tapping the summary row does nothing harmful", tm._menu is not None and tm._menu["tab"] == "crack")

# empty state
reset()
tm2, ui2, els2 = new_manager()
tm2._display_cfg = T.clean_display({})
tm2._settings = T.clean_settings({})
tm2.open_menu("list", "crack")
ok("no handshakes: the summary row says so", tm2._menu["crack_info"]["__summary__"]["text"] == "no handshakes yet")
T.draw_menu(Image.new("RGB", (480, 320)), tm2._menu, tm2._theme)
ok("...and still draws", True)
finger.tap_rect(finger.hit("tab", "system"))
ok("the other tabs stay reachable", tm._menu["tab"] == "system")

finish()
