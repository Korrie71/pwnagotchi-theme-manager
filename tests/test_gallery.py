"""Themes are installed before use: a fresh setup has none, the bundled ones live in a gallery, and an update never
changes what an existing setup was showing."""
import json
import os
import sys

from _util import T, draw_pass, finish, new_manager, ok, sandbox, scene

sandbox()

# ---------------------------------------------------------------- a fresh setup starts with nothing
ok("nothing is installed on a fresh setup", T._load_installed() == set())
tm = T.ThemeManager()
ok("...so there are no themes to use", tm._all() == {})
ok("...and the screen is plain: no theme active, black and white, no effects",
   tm._active == "" and tm._theme["bg"] == "#000000" and not tm._theme.get("effects"))
rows = tm.library_rows()
ok("the gallery still lists every bundled theme, none installed", len(rows) == len(T.BUILTIN) and not any(r["installed"] for r in rows))
ok("...each with the colors to preview it by", all({"name", "bg", "fg", "accent", "web", "animated"} <= set(r) for r in rows))

# ---------------------------------------------------------------- installing and uninstalling
ok("installing an unknown theme is refused", tm.install_theme("nope") is False)
ok("installing a bundled one works", tm.install_theme("matrix") is True)
ok("...it is now usable", list(tm._all()) == ["matrix"] and tm._all()["matrix"]["builtin"] is True)
ok("...and saved", json.load(open(T.LIBRARY_FILE))["installed"] == ["matrix"])
tm.install_theme("amber")
ok("themes come back in the gallery's order, not alphabetical", list(tm._all()) == ["matrix", "amber"])
ok("the gallery marks the installed ones", {r["name"] for r in tm.library_rows() if r["installed"]} == {"matrix", "amber"})
ok("uninstalling something not installed is refused", tm.uninstall_theme("ice") is False)

tm._view = None
tm._apply("matrix", persist=True)
ok("an installed theme can be applied", tm._active == "matrix")
try:
    tm._apply("ice")
    ok("a theme that is not installed cannot be applied", False)
except KeyError:
    ok("a theme that is not installed cannot be applied", True)
ok("uninstalling the active theme returns the screen to plain", tm.uninstall_theme("matrix") is True and tm._active == ""
   and tm._theme["bg"] == "#000000" and json.load(open(T.ACTIVE_FILE))["active"] == "")
ok("...and the other installed theme is untouched", list(tm._all()) == ["amber"])

# ---------------------------------------------------------------- swiping with nothing installed is a no-op
tm2, ui2, els2 = new_manager()
T._save_installed(set())
tm2._active = ""
tm2.applied.clear()
from _util import Panel  # noqa: E402
finger = Panel(tm2)
finger.calibrate()
tm2._menu = None
finger.swipe(380, 160, 120, 160)
ok("swiping with no themes installed does nothing, not a crash", tm2.applied == [])
tm2.open_menu("list")
ok("the touch menu lists no themes", tm2._menu["names"] == [])
from PIL import Image  # noqa: E402
T.draw_menu(Image.new("RGB", (480, 320)), tm2._menu, tm2._theme)
ok("...and draws its 'install one from the web editor' hint without crashing", True)

# ---------------------------------------------------------------- the store on the touch menu's Themes tab
ok("the Themes tab has a store button", any(a == ("store", None) for _, a in T.menu_hits(tm2._menu)))
finger.tap_rect(finger.hit("store"))
ok("tapping it opens the store: every bundled theme, none installed yet", tm2._menu["store"] is True and len(tm2._menu["library"]) == len(T.BUILTIN) + 1 and not tm2._menu["installed"])
ok("...as rows that install rather than apply", any(a[0] == "storerow" for _, a in T.menu_hits(tm2._menu)) and not any(a[0] == "pick" for _, a in T.menu_hits(tm2._menu)))
T.draw_menu(Image.new("RGB", (480, 320)), tm2._menu, tm2._theme)
ok("...and draws without crashing", True)
first = tm2._menu["library"][1]
tm2._toast = None
finger.tap_rect(finger.hit("storerow", first))
ok("tapping a theme installs it", first in T._load_installed() and first in tm2._menu["installed"] and first in tm2._menu["names"], T._load_installed())
ok("...with a toast", tm2._toast and "installed " + first in tm2._toast[0], tm2._toast)
T.draw_menu(Image.new("RGB", (480, 320)), tm2._menu, tm2._theme)
tm2._toast = None
finger.tap_rect(finger.hit("storerow", first))
ok("tapping it again uninstalls it", first not in T._load_installed() and first not in tm2._menu["names"])
ok("...with a toast", tm2._toast and "uninstalled " + first in tm2._toast[0], tm2._toast)
finger.tap_rect(finger.hit("storerow", first))
tm2._active = first
tm2._view = None
finger.tap_rect(finger.hit("store"))
ok("'back' returns to the installed list, which now has the theme", tm2._menu["store"] is False and tm2._menu["names"] == [first])
finger.tap_rect(finger.hit("pick", first))
ok("...and a tap there applies it as before", tm2.applied[-1] == first)

# ---------------------------------------------------------------- store filters
rows = tm.library_rows()
by = {r["name"]: r for r in rows}
ok("the gallery knows which themes are animated, have scenery, and are dark or light", by["matrix"]["animated"] and by["matrix"]["dark"] and by["paper"]["dark"] is False and by["ocean"]["scene"])
ok("...and which need a face pack", by["blobby"]["pack"] == "blob" and by["matrix"]["pack"] is None)
ok("'all' keeps everything", len(T.store_filter(rows, "all")) == len(rows))
ok("'animated' keeps only the animated ones", {r["name"] for r in T.store_filter(rows, "animated")} == {r["name"] for r in rows if r["animated"]} and 0 < len(T.store_filter(rows, "animated")) < len(rows))
ok("'scenery' keeps only those with a scene", all(r["scene"] for r in T.store_filter(rows, "scenery")) and T.store_filter(rows, "scenery"))
ok("'dark' and 'light' split the whole gallery between them", len(T.store_filter(rows, "dark")) + len(T.store_filter(rows, "light")) == len(rows))
ok("'not installed' leaves out what you already have", all(not r["installed"] for r in T.store_filter(rows, "not installed")))
ok("an unknown filter shows everything rather than nothing", len(T.store_filter(rows, "bogus")) == len(rows))

tm5, ui5, els5 = new_manager()
T._save_installed(set())
tm5._active = ""
f5 = Panel(tm5)
f5.calibrate()
tm5.open_menu("list", "themes")
f5.tap_rect(f5.hit("store"))
ok("the store's first row is the filter, then the themes", tm5._menu["library"][0] == "__filter__" and len(tm5._menu["library"]) == len(T.BUILTIN) + 1)
T.draw_menu(Image.new("RGB", (480, 320)), tm5._menu, tm5._theme)
f5.tap_rect(f5.hit("storerow", "__filter__"))
ok("tapping it moves to the next filter and narrows the list", tm5._menu["filter"] == "animated" and 1 < len(tm5._menu["library"]) < len(T.BUILTIN) + 1, tm5._menu["filter"])
ok("...and knows how many it is showing", tm5._menu["shown"] == len(tm5._menu["library"]) - 1)
T.draw_menu(Image.new("RGB", (480, 320)), tm5._menu, tm5._theme)
for _ in range(len(T.STORE_FILTERS) - 1):
    f5.tap_rect(f5.hit("storerow", "__filter__"))
ok("the filters wrap around to 'all'", tm5._menu["filter"] == "all")
tm5._menu["filter"] = "not installed"
tm5.install_theme(tm5._menu["library"][1])
tm5._sync_store_menu(tm5._menu)
ok("'not installed' updates as you install things", tm5._menu["shown"] == len(T.BUILTIN) - 1)
for name in list(T.BUILTIN):
    tm5.install_theme(name)
tm5._sync_store_menu(tm5._menu)
ok("...and can be empty, which still draws", tm5._menu["shown"] == 0 and T.draw_menu(Image.new("RGB", (480, 320)), tm5._menu, tm5._theme) is None)

# ---------------------------------------------------------------- theme packs: a theme brings the face pack it needs
import io  # noqa: E402
import time as _time  # noqa: E402

buf = io.BytesIO()
Image.new("RGBA", (12, 12), (255, 0, 0, 255)).save(buf, "PNG")
PNG = buf.getvalue()
asked = []


def fake_get(url, timeout=6):
    asked.append(url)
    rest = url[len(T.PACK_RAW):] if url.startswith(T.PACK_RAW) else ""
    return {"blob/happy.png": PNG, "blob/sad.png": PNG, "blob/angry.png": b"not an image"}.get(rest)


real_get = T._http_get
T._http_get = fake_get
sandbox()
added, problems = T.fetch_face_pack("blob")
ok("a face pack is downloaded, one face at a time, from the project's faces folder", added == 2 and all(u.startswith(T.PACK_RAW + "blob/") for u in asked), asked[:3])
ok("...and stored like an upload", sorted(os.listdir(os.path.join(T.FACES_DIR, "blob"))) == ["happy.png", "sad.png"])
ok("...a bad image is reported, not stored", len(problems) == 1 and "angry" in problems[0])
try:
    T.fetch_face_pack("../evil")
    ok("a pack name that is not a plain name is refused", False)
except ValueError:
    ok("a pack name that is not a plain name is refused", True)
T._http_get = real_get
ok("only https is ever fetched", T._http_get("http://example.test/x") is None and T._http_get("file:///etc/passwd") is None)

T._http_get = fake_get
sandbox()
tmp, uip, elp = new_manager()
ok("a theme that needs no pack downloads nothing", tmp.install_theme("matrix") and not tmp._pack_busy and not os.path.isdir(os.path.join(T.FACES_DIR, "blob")))
tmp._toast = None
ok("installing a bundled theme that uses a face pack starts downloading it", tmp.install_theme("blobby") is True)
end = _time.time() + 5
while not os.path.isdir(os.path.join(T.FACES_DIR, "blob")) and _time.time() < end:
    _time.sleep(0.02)
end = _time.time() + 3
while tmp._pack_busy and _time.time() < end:
    _time.sleep(0.02)
ok("...and the pack arrives", sorted(os.listdir(os.path.join(T.FACES_DIR, "blob"))) == ["happy.png", "sad.png"])
ok("...with a toast", tmp._toast and "blob faces ready" in tmp._toast[0], tmp._toast)
before = len(asked)
ok("a pack that is already here is not downloaded again", tmp.ensure_face_pack("blob") is False and len(asked) == before)
ok("an empty pack name is nothing to do", tmp.ensure_face_pack("") is False and tmp.ensure_face_pack(None) is False)
T._http_get = lambda url, timeout=6: None
sandbox()
tm7, ui7, el7 = new_manager()
tm7._toast = None
tm7.install_theme("blobby")
end = _time.time() + 3
while tm7._pack_busy and _time.time() < end:
    _time.sleep(0.02)
ok("with no network the theme still installs, and says the faces could not be fetched", "blobby" in T._load_installed() and tm7._toast and "could not download" in tm7._toast[0], tm7._toast)
T._http_get = real_get

# ---------------------------------------------------------------- migration: an update never changes anyone's screen
def migrate(active_json):
    d = sandbox()
    if active_json is not None:
        open(T.ACTIVE_FILE, "w").write(json.dumps(active_json))
    m = T.ThemeManager()
    m._migrate_library()
    return d, m


d, m = migrate({"active": "cyberpunk"})
ok("an existing setup keeps the bundled theme it was using", T._load_installed() == {"cyberpunk"})
d, m = migrate(None)
ok("a fresh setup keeps nothing", T._load_installed() == set())
d, m = migrate({"active": "my own"})
open(os.path.join(T.THEME_DIR, "my own.json"), "w").write(json.dumps({"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff"}))
ok("a setup on its own theme installs nothing extra and keeps its own file", T._load_installed() == set() and "my own" in m._all())
_, m = migrate({"active": "cyberpunk"})
T._save_installed({"cyberpunk", "ice"})
m._migrate_library()
ok("migrating twice does not undo what was installed since", T._load_installed() == {"cyberpunk", "ice"})
open(T.LIBRARY_FILE, "w").write("garbage")
ok("a corrupt library file reads as nothing installed, not a crash", T._load_installed() == set())
ok("the library file is not mistaken for a theme", "library" not in T.ThemeManager()._user_themes())

# ---------------------------------------------------------------- the web API
try:
    import flask
except ImportError:
    print("SKIP flask is not installed")
    finish()
sandbox()
app = flask.Flask(__name__)
tm3 = T.ThemeManager()
tm3._view = None
tm3._settings = T.clean_settings({})
tm3._display_cfg = T.clean_display({})


def call(path, body=None, query=""):
    with app.test_request_context("/" + path + query, method="POST" if body is not None else "GET", json=body):
        r = tm3.on_webhook(path, flask.request)
        r, code = r if isinstance(r, tuple) else (r, 200)
        return code, (json.loads(r.get_data()) if r.mimetype == "application/json" else r.get_data())


code, j = call("api/themes")
ok("api/themes: nothing installed, and it hands over the plain theme to start an edit from", code == 200 and j["themes"] == {} and j["active"] == "" and j["stock"]["bg"] == "#000000")
code, j = call("api/library")
ok("api/library: lists the gallery", code == 200 and len(j["themes"]) == len(T.BUILTIN) and not any(t["installed"] for t in j["themes"]))
code, j = call("api/install", {"name": "ocean"})
ok("api/install: installs one", code == 200 and j["ok"] and "ocean" in call("api/themes")[1]["themes"])
code, j = call("api/install", {"name": "nope"})
ok("api/install: an unknown name fails cleanly", j["ok"] is False)
code, data = call("api/preview", query="?theme=ice")
ok("api/preview: a theme can be previewed before it is installed", code == 200 and data[:4] == b"\x89PNG")
code, j = call("api/apply", {"name": "ice"})
ok("api/apply: an uninstalled theme is refused", code == 400 and not j["ok"])
code, j = call("api/apply", {"name": "ocean"})
ok("api/apply: an installed one works", code == 200 and j["ok"] and tm3._active == "ocean")
code, j = call("api/delete", {"name": "ocean"})
ok("api/delete: refuses a bundled theme (uninstall is the way)", code == 400)
T._http_get = fake_get
code, j = call("api/save", {"name": "with-faces", "theme": {"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff", "face_pack": "blob"}, "fetch_pack": True})
end = _time.time() + 5
while (tm3._pack_busy or not os.path.isdir(os.path.join(T.FACES_DIR, "blob"))) and _time.time() < end:
    _time.sleep(0.02)
ok("api/save: an online theme that names a face pack brings it along", code == 200 and j["ok"] and os.path.isdir(os.path.join(T.FACES_DIR, "blob")))
T._http_get = real_get
code, j = call("api/uninstall", {"name": "ocean"})
ok("api/uninstall: works, and the screen goes plain", code == 200 and j["ok"] and tm3._active == "")
code, j = call("api/uninstall", {"name": "ocean"})
ok("api/uninstall: twice fails cleanly", j["ok"] is False)

finish()
