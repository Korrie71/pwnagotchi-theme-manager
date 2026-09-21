"""The one-time legal notice: shown once on the very first run, logged always, tap to dismiss."""
import json
import os

from _util import Panel, T, fake_canvas, finish, new_manager, ok, sandbox
from PIL import Image

sandbox()

ok("disclaimer.json is never mistaken for a theme", "disclaimer.json" in T.STATE_FILES)
ok("the text mentions authorization and the law, not just a vague warning",
   "authoriz" in T.DISCLAIMER_TEXT.lower() and "permission" in T.DISCLAIMER_TEXT.lower() and "law" in T.DISCLAIMER_TEXT.lower())

# ---------------------------------------------------------------- first run
tm, ui, els = new_manager()
ok("before anything runs, there is nothing to show yet", tm._notice is None)
tm._maybe_show_disclaimer()
ok("the very first run shows it", tm._notice == T.DISCLAIMER_TEXT)
ok("...and remembers that, so it isn't shown again next boot", json.load(open(T.DISCLAIMER_FILE))["shown"] > 0)
canvas = fake_canvas()
tm._on_frame(canvas)
img = tm._compose(0.0)
ok("it renders on screen without crashing", img is not None and img.size == (480, 320))
T.draw_notice(Image.new("RGB", (480, 320)), T.DISCLAIMER_TEXT, T._clean(T.BUILTIN["cyberpunk"]))
ok("draw_notice itself doesn't crash on its own", True)

# ---------------------------------------------------------------- dismissing it
finger = Panel(tm)
finger.tap(50, 50)
ok("any tap, anywhere, dismisses it", tm._notice is None)
ok("...even before the touchscreen is calibrated", tm._touch_m is None)
ok("...and it does not also open the menu or start a double tap", tm._menu is None and tm._last_tap is None)

# ---------------------------------------------------------------- not shown again
tm2, ui2, els2 = new_manager()
tm2._maybe_show_disclaimer()
ok("a second manager (same install) does not show it again", tm2._notice is None)
open(T.DISCLAIMER_FILE, "w").write("{broken")
tm3, ui3, els3 = new_manager()
tm3._maybe_show_disclaimer()
ok("even a damaged marker file counts as 'already shown' (never shows twice by accident)", tm3._notice is None)

# ---------------------------------------------------------------- it takes priority, but only consumes one tap
os.remove(T.DISCLAIMER_FILE)
tm4, ui4, els4 = new_manager()
tm4._maybe_show_disclaimer()
finger4 = Panel(tm4)
finger4.calibrate()
ok("calibrating (four taps) doesn't get eaten: the very first tap only dismisses the notice", tm4._notice is None and tm4._touch_m is None)
finger4.calibrate()
ok("calibration then proceeds normally on the next four taps", tm4._touch_m is not None)

finish()
