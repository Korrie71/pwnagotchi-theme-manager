"""Layout: moving things on the screen, from the touch menu and the API, and what stays safe."""
import json
import os

from _util import Panel, T, draw_pass, finish, new_manager, ok, sandbox
from PIL import Image

sandbox()


def rig():
    tm, ui, els = new_manager()
    tm._display_cfg = T.clean_display({})
    tm._settings = T.clean_settings({})
    ui.update = lambda force=False: draw_pass(tm, ui, els)      # a redraw, like pwnagotchi's
    return tm, ui, els


def box(tm, key):
    return tm._ctx["layers"][key][1]


# ---------------------------------------------------------------- the file format
ok("nothing saved: nothing moved", T.clean_layout(None) == {} and T.clean_layout({"offsets": 3}) == {})
c = T.clean_layout({"offsets": {"face": [10, -4], "name": [0, 0], "x": [1], "y": ["a", 2], "z": [True, 1], "big": [999, -999],
                                "f": [2.7, 3.2], "": [1, 1], "long" * 20: [1, 1], 7: [1, 1]}})
ok("junk is dropped, zero offsets are not kept, values are whole numbers within limits",
   c == {"face": [10, -4], "big": [T.LAYOUT_MAX, -T.LAYOUT_MAX], "f": [2, 3]}, c)
ok("the file is never taken for a theme", "layout.json" in T.STATE_FILES)
ok("shifting a point, and a line with two points", T.shifted((10, 20), 3, -5) == (13, 15) and T.shifted((0, 14, 480, 14), 1, 2) == (1, 16, 481, 16))

# ---------------------------------------------------------------- moving an element
tm, ui, els = rig()
before = box(tm, "name")
home = tuple(els["name"].xy)
tm.set_offset("name", 12, 7)
after = box(tm, "name")
ok("the element is drawn where it was moved", after[0] - before[0] == 12 and after[1] - before[1] == 7, (before, after))
ok("pwnagotchi's own position is never changed", tuple(els["name"].xy) == home)
ok("other elements stay where they were", box(tm, "status") == box(tm, "status") and tuple(els["status"].xy) == (286, 82))
ok("the offset is saved", json.load(open(T.LAYOUT_FILE)) == {"offsets": {"name": [12, 7]}})
tm.set_offset("name", 0, 0)
ok("0, 0 puts it back and forgets it", box(tm, "name") == before and json.load(open(T.LAYOUT_FILE)) == {"offsets": {}})
ok("moving counts for the Tinkerer achievement", tm._ach["stats"]["layout_moves"] == 2 and "tinkerer" in tm._ach["unlocked"])
tm.set_offset("name", 5000, -5000)
ok("far away is limited", tm._layout["name"] == [T.LAYOUT_MAX, -T.LAYOUT_MAX])
for bad in ("", "x" * 41, None, 5):
    try:
        tm.set_offset(bad, 1, 1)
        good = False
    except ValueError:
        good = True
    ok("a bad element name %r is refused" % (bad,), good)
try:
    tm.set_offset("name", "a", 1)
    good = False
except (ValueError, TypeError):
    good = True
ok("a bad offset is refused", good)
tm.set_offset("name", 0, 0)

# the lines with four coordinates, the face with a picture, and a hidden element
tm.set_offset("line2", 0, -20)
ok("a line moves as a whole", box(tm, "line2")[1] == 300 - 20, box(tm, "line2"))
tm.set_offset("face", 30, 10)
ok("the face position the theme uses follows the move", tm._ctx["face"][1] == (30, 44), tm._ctx["face"][1])
img = tm._compose(1.0)
ok("the screen still composes with everything moved", img is not None and img.size == (480, 320))
els["name"].value = ""
tm.set_offset("name", 3, 3)
draw_pass(tm, ui, els)
ok("an element with nothing to draw can still be set", tm._layout["name"] == [3, 3])
rows = tm.layout_rows()
ok("rows list the drawn elements, and moved ones that are empty", {r["key"] for r in rows} >= {"face", "status", "name", "line2"})
ok("...sorted top to bottom", [r["box"][1] for r in rows if r["box"]] == sorted(r["box"][1] for r in rows if r["box"]))
els["name"].value = "pwnagotchi>"
tm.reset_layout()
ok("clearing everything works and is saved", tm._layout == {} and json.load(open(T.LAYOUT_FILE))["offsets"] == {})

# ---------------------------------------------------------------- loading
tm, ui, els = rig()
open(T.LAYOUT_FILE, "w").write("{broken")
tm._load_layout()
ok("a damaged file is ignored", tm._layout == {})
open(T.LAYOUT_FILE, "w").write(json.dumps({"offsets": {"face": [4, 4], "x": "no"}}))
tm._load_layout()
ok("a saved layout is loaded and cleaned", tm._layout == {"face": [4, 4]})
draw_pass(tm, ui, els)
ok("...and used on the next frame", tm._ctx["face"][1] == (4, 38))
os.remove(T.LAYOUT_FILE)
tm._load_layout()
ok("no file means nothing moved", tm._layout == {})

# ---------------------------------------------------------------- the touch menu
tm, ui, els = rig()
finger = Panel(tm)
finger.calibrate()
tm.open_menu("list")
ok("the tabs fit and do not overlap", all(T.TABS[i][1][2] < T.TABS[i + 1][1][0] for i in range(len(T.TABS) - 1)) and T.TABS[-1][1][2] <= 452)
finger.tap_rect(finger.hit("tab", "layout"))
ok("the Layout tab lists what is on the screen", tm._menu["tab"] == "layout" and {"face", "name", "status"} <= set(tm._menu["layout"]))
rows = [r for r in T.menu_hits(tm._menu) if r[1][0] == "adjust"]
ok("a row per element, five to a page", len(rows) == 5)
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
name_row = next(r for r in T.menu_hits(tm._menu) if r[1] == ("adjust", "face")) if any(r[1] == ("adjust", "face") for r in T.menu_hits(tm._menu)) else None
tm._menu["page"] = tm._menu["layout"].index("status") // T.MENU_ROWS
finger.tap_rect(finger.hit("adjust", "status"))
m = tm._menu
ok("tapping an element starts moving it", m["mode"] == "adjust" and m["adjust"] == "status" and m["box"] == box(tm, "status"))
hits = T.menu_hits(m)
ok("only the popup's buttons are active", {h[1][0] for h in hits} == {"nudge", "step", "reset1", "done"}, [h[1] for h in hits])
px = T.adjust_popup(m)
ok("the popup is on the half away from the element and inside the screen", 0 <= px[1] and px[3] <= 320 and (px[3] < m["box"][1] or px[1] > m["box"][3]), (px, m["box"]))
ok("no button overlaps another", all(not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]) for i, (a, _) in enumerate(hits) for (b, _) in hits[i + 1:]))
ok("all buttons are inside the popup", all(px[0] <= r[0] and r[2] <= px[2] and px[1] <= r[1] and r[3] <= px[3] for r, _ in hits))
ok("...and big enough for a finger (30 px)", all(r[2] - r[0] >= 30 and r[3] - r[1] >= 28 for r, _ in hits))
b0 = box(tm, "status")
finger.tap_rect(finger.hit("nudge", (1, 0)))
finger.tap_rect(finger.hit("nudge", (1, 0)))
finger.tap_rect(finger.hit("nudge", (0, -1)))
tm._compose(1.0)
ok("X+ X+ Y- moves it 2 right and 1 up", tm._layout["status"] == [2, -1] and box(tm, "status")[0] - b0[0] == 2 and box(tm, "status")[1] - b0[1] == -1, tm._layout)
ok("the popup shows the offset and the box follows", tm._menu["offset"] == (2, -1) and tm._menu["box"] == box(tm, "status"))
finger.tap_rect(finger.hit("step"))
finger.tap_rect(finger.hit("nudge", (-1, 0)))
ok("step 5 moves 5 pixels", tm._menu["step_px"] == 5 and tm._layout["status"] == [-3, -1], tm._layout)
finger.tap_rect(finger.hit("step"))
finger.tap_rect(finger.hit("step"))
ok("the step cycles 1 - 5 - 10 - 1", tm._menu["step_px"] == 1)
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("the adjust screen draws", True)
finger.tap(5, 5)
ok("a tap beside the popup does nothing (it does not close)", tm._menu is not None and tm._menu["mode"] == "adjust")
finger.tap_rect(finger.hit("reset1"))
ok("reset puts just that element back", "status" not in tm._layout and box(tm, "status") == b0)
finger.tap_rect(finger.hit("nudge", (0, 1)))
finger.tap_rect(finger.hit("done"))
ok("done goes back to the list, keeping the move", tm._menu["mode"] == "list" and tm._menu["tab"] == "layout" and tm._layout["status"] == [0, 1])
ok("...and the list shows the new offset", tm._menu["layout_info"]["status"] == (0, 1))
finger.tap_rect(finger.hit("resetall"))
ok("clear asks first", tm._layout != {} and tm._menu["confirm"][0] == "resetall")
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
finger.tap_rect(finger.hit("resetall"))
ok("...and clears on the second tap", tm._layout == {} and tm._menu["layout_info"]["status"] == (0, 0))
finger.tap_rect(finger.hit("resetall"))
finger.tap_rect(finger.hit("next"))
ok("...another tap in between cancels the question", tm._menu["confirm"] is None)

# popup placement for elements at the top and the bottom
m = {"mode": "adjust", "box": (10, 20, 100, 40)}
ok("an element at the top gets the popup at the bottom", T.adjust_popup(m)[1] > 150)
m = {"mode": "adjust", "box": (10, 280, 100, 300)}
ok("an element at the bottom gets the popup at the top", T.adjust_popup(m)[3] < 150)
m = {"mode": "adjust", "box": None}
ok("an element that is not drawn still gets a popup", T.adjust_popup(m)[3] <= 320)

# the menu times out later while adjusting, and the wake / swipe logic is not confused
tm.open_menu("list", "layout")
finger.tap_rect(finger.hit("adjust", tm._menu["layout"][0]))
ok("adjusting keeps the menu open longer", tm._menu["until"] - finger.t >= T.ADJUST_TIMEOUT - 3, tm._menu["until"] - finger.t)

# an element that vanished while its popup is open
tm._menu["adjust"] = "gone"
tm._compose(1.0)
ok("an element that stops being drawn just loses its box", tm._menu["box"] is None)
tm._menu["adjust"] = tm._menu["layout"][0]
finger.tap_rect(finger.hit("nudge", (1, 0)))
ok("...and everything keeps working", True)

finish()
