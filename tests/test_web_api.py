"""The web API for the screen itself: layout, settings and achievements (skipped where Flask is not installed)."""
import json
import sys

from _util import T, draw_pass, finish, new_manager, ok, sandbox

sandbox()
try:
    import flask
except ImportError:
    print("SKIP flask is not installed")
    sys.exit(0)

app = flask.Flask(__name__)
tm, ui, els = new_manager()
tm._display_cfg = T.clean_display({})
tm._settings = T.clean_settings({})
ui.update = lambda force=False: draw_pass(tm, ui, els)


def call(path, body=None):
    with app.test_request_context("/" + path, method="POST" if body is not None else "GET", json=body):
        r = tm.on_webhook(path, flask.request)
        r, code = r if isinstance(r, tuple) else (r, 200)
        return code, json.loads(r.get_data())


code, j = call("api/layout")
ok("layout: lists the elements with their boxes", code == 200 and {"face", "name"} <= {r["key"] for r in j["rows"]} and j["max"] == T.LAYOUT_MAX)
code, j = call("api/layout", {"key": "face", "dx": 10, "dy": -5})
ok("layout: moving returns the new rows", j["ok"] and next(r for r in j["rows"] if r["key"] == "face")["dx"] == 10 and tm._layout["face"] == [10, -5])
code, j = call("api/layout", {"key": 5, "dx": 1, "dy": 1})
ok("layout: a bad name is a 400, not a crash", code == 400 and not j["ok"])
code, j = call("api/layout", {"key": "face", "dx": "abc", "dy": 1})
ok("layout: a bad number is a 400", code == 400)
code, j = call("api/layout", {"key": "face", "dx": 10 ** 30, "dy": 1})
ok("layout: a huge number is limited or refused, never stored as is", code == 400 or tm._layout["face"][0] == T.LAYOUT_MAX)
code, j = call("api/layout", {"reset": True})
ok("layout: reset clears it", j["ok"] and tm._layout == {})

code, j = call("api/settings")
ok("settings: shows the current values", j["settings"]["overheat_off"] is False and j["display"]["dim"] == 1.0 and j["limits"]["overheat_temp"] == [70, 95])
code, j = call("api/settings", {"settings": {"overheat_off": True, "overheat_temp": 88}})
ok("settings: a change is stored and the rest is kept", j["ok"] and tm._settings["overheat_off"] and tm._settings["overheat_temp"] == 88 and tm._settings["achievements"])
ok("...and saved to the file", json.load(open(T.SETTINGS_FILE))["overheat_temp"] == 88)
code, j = call("api/settings", {"settings": {"overheat_temp": 5000}})
ok("settings: an out of range number is limited", j["ok"] and tm._settings["overheat_temp"] == 95)
code, j = call("api/settings", {"settings": {"overheat_temp": 88, "overheat_seconds": "x"}})
ok("settings: something that is not a number is refused and nothing changes", code == 400 and not j["ok"] and tm._settings["overheat_temp"] == 95, tm._settings)
code, j = call("api/settings", {"settings": {"overheat_temp": 90}, "display": {"dim": "bright"}})
ok("settings: one bad half means neither is saved", code == 400 and tm._settings["overheat_temp"] == 95)
code, j = call("api/settings", {"display": {"dim": 0.5, "night": {"from": "22:00", "to": "06:30", "dim": 0.2}, "idle": {"minutes": 3, "dim": 0.4}}})
ok("display: brightness, night and idle are stored", j["ok"] and tm._display_cfg["dim"] == 0.5 and tm._display_cfg["night"]["to"] == "06:30" and tm._display_cfg["idle"]["minutes"] == 3)
ok("...and saved", json.load(open(T.DISPLAY_FILE))["night"]["from"] == "22:00")
code, j = call("api/settings", {"display": {"night": {"from": "25:99", "to": "06:30"}}})
ok("display: a bad time is refused", code == 400 and not j["ok"] and tm._display_cfg["night"]["from"] == "22:00")
code, j = call("api/settings", {"display": "no"})
ok("display: something that is not an object is refused", code == 400)
code, j = call("api/settings", {"settings": "no"})
ok("settings: something that is not an object is refused and nothing changes", code == 400 and tm._settings["overheat_temp"] == 95 and tm._settings["overheat_off"])

code, j = call("api/achievements")
ok("achievements: listed with progress", j["enabled"] and len(j["achievements"]) == len(T.ACHIEVEMENTS) and {"id", "name", "desc", "goal", "progress", "unlocked"} <= set(j["achievements"][0]))
code, j = call("api/settings", {"settings": {"achievements": False}})
code, j = call("api/achievements")
ok("achievements: switched off shows as off", j["enabled"] is False)

# ---------------------------------------------------------------- the PWA bits (installable on a phone home screen)
def raw(path):
    with app.test_request_context("/" + path, method="GET"):
        r = tm.on_webhook(path, flask.request)
        r, code = r if isinstance(r, tuple) else (r, 200)
        return code, r.get_data(), r.mimetype


code, data, mime = raw("manifest.json")
manifest = json.loads(data)
ok("the manifest is valid JSON with a name and icons", code == 200 and manifest["name"] and len(manifest["icons"]) == 2)
ok("...served as a manifest, not plain json", mime == "application/manifest+json")
ok("both declared icon sizes are actually servable", all(raw(i["src"])[0] == 200 for i in manifest["icons"]))
code, data, mime = raw("icon-192.png")
ok("the icon is a real PNG", code == 200 and data[:8] == b"\x89PNG\r\n\x1a\n" and mime == "image/png")
from PIL import Image
import io as _io
img = Image.open(_io.BytesIO(data))
ok("...at the size the manifest promised", img.size == (192, 192))
code, data, mime = raw("icon-512.png")
ok("the larger icon is too", code == 200 and Image.open(_io.BytesIO(data)).size == (512, 512))
code, data, mime = raw("sw.js")
ok("there is a service worker (needed for a phone to treat this as installable)", code == 200 and "fetch" in data.decode() and "javascript" in mime)

finish()
