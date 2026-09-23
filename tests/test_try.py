"""Trying a theme for a while: nothing is saved, and it always goes back."""
import json
import os
import time

from _util import T, finish, ok, sandbox

sandbox()


class View:
    def __init__(self):
        self.updates = 0

    def update(self, force=False, new_data={}):
        self.updates += 1


def manager(active="default"):
    tm = T.ThemeManager()
    T._save_installed(set(T.BUILTIN))
    tm._view = View()
    tm._running = True
    tm._refresh_now = lambda: None
    tm._apply(active, persist=True)
    tm._view.updates = 0
    return tm


tm = manager()
saved = open(T.ACTIVE_FILE).read()
cyber = T._clean(T.BUILTIN["cyberpunk"])
secs = tm.try_theme(cyber, 30)
ok("the theme is shown right away", tm._theme["fg"] == cyber["fg"] and tm._view.updates == 1)
ok("...for the time asked", secs == 30 and 29 < tm._try_until - time.time() <= 30)
ok("the saved theme is still 'default'", tm._active == "default")
ok("nothing was written to disk", open(T.ACTIVE_FILE).read() == saved)
tm.menu_tick(time.time() + 10)
ok("before the time is up nothing changes", tm._theme["fg"] == cyber["fg"])
tm.menu_tick(time.time() + 31)
ok("when the time is up it goes back to the saved theme", tm._theme["fg"] == T._clean(T.BUILTIN["default"])["fg"] and tm._try_until == 0)
tm2 = manager()
tm2.try_theme(cyber, 30)
tm2._end_try()
ok("...and says so on the screen", tm2._toast and tm2._toast[0] == "back to default")
ok("the saved theme was not touched", open(T.ACTIVE_FILE).read() == saved)

tm = manager()
tm.try_theme(cyber, 60)
tm._apply("matrix", persist=True)
ok("choosing a theme for real while trying cancels the revert", tm._try_until == 0 and tm._active == "matrix")
tm.menu_tick(time.time() + 120)
ok("...so nothing jumps back later", tm._theme["fg"] == T._clean(T.BUILTIN["matrix"])["fg"])

tm = manager()
tm.try_theme(cyber, 60)
tm.try_theme(T._clean(T.BUILTIN["amber"]), 60)
tm.menu_tick(time.time() + 61)
ok("trying one theme after another still returns to the saved one", tm._active == "default" and tm._theme["fg"] == T._clean(T.BUILTIN["default"])["fg"])

tm = manager()
before = dict(tm._theme)
try:
    tm.try_theme({"bg": "nope"}, 30)
    raised = False
except ValueError:
    raised = True
ok("an invalid theme is refused and nothing changes", raised and tm._theme == before and tm._try_until == 0)
ok("the time is limited to 5 seconds..10 minutes", tm.try_theme(cyber, 0) == 5 and tm.try_theme(cyber, 99999) == 600)
tm._end_try()

T.write_json(os.path.join(T.THEME_DIR, "temp-theme.json"), dict(cyber))
tm = manager("temp-theme")
tm.try_theme(T._clean(T.BUILTIN["amber"]), 30)
os.remove(os.path.join(T.THEME_DIR, "temp-theme.json"))
tm.menu_tick(time.time() + 31)
ok("if the saved theme was deleted meanwhile it falls back to default", tm._theme["fg"] == T._clean(T.BUILTIN["default"])["fg"])

tm = manager()
tm.try_theme({"bg": "#101010", "fg": "#eeeeee", "accent": "#ff0000", "web": "#00ff00", "text": [{"text": "unsaved!", "x": 5, "y": 5}]}, 30)
ok("an unsaved theme with new content can be tried", tm._theme["text"][0]["text"] == "unsaved!")
ok("...and it is not listed anywhere afterwards", not any("unsaved" in json.dumps(v) for v in tm._all().values()))

finish()
