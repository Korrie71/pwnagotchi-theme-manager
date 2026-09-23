"""Themes that change the layout of the screen, not just its colors: element positions, hidden elements, text size,
and decorative panels."""
from _util import T, draw_pass, finish, new_manager, ok, sandbox

sandbox()
BASE = {"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff"}


def theme(**kw):
    return dict(BASE, **kw)


def refuses(t):
    try:
        T._clean(t)
        return False
    except ValueError:
        return True


# ---------------------------------------------------------------- validation
c = T._clean(theme(layout={"face": [10, -20], "name": [0, 0]}, hide=["uptime", "channel", "uptime"],
                   sizes={"face": 1.5, "name": 1.0}, panels=[{"type": "rect", "x": 5, "y": 6, "w": 100, "h": 40, "fill": "accent"}]))
ok("a layout keeps real moves and drops zero ones", c["layout"] == {"face": [10, -20]})
ok("hide is a sorted list without repeats", c["hide"] == ["channel", "uptime"])
ok("a size of exactly 1 is dropped, others kept", c["sizes"] == {"face": 1.5})
ok("a panel is cleaned and given its defaults", c["panels"][0] == {"type": "rect", "x": 5, "y": 6, "w": 100, "h": 40, "width": 1, "radius": 0, "fill": "accent"})
ok("a theme with none of it carries none of it", not ({"layout", "hide", "sizes", "panels"} & set(T._clean(theme()))))
ok("moves are limited", T._clean(theme(layout={"face": [9999, -9999]}))["layout"]["face"] == [T.LAYOUT_MAX, -T.LAYOUT_MAX])
ok("sizes are limited", T._clean(theme(sizes={"face": 99}))["sizes"]["face"] == 3.0 and T._clean(theme(sizes={"face": 0.01}))["sizes"]["face"] == 0.4)
ok("a bad layout is refused", refuses(theme(layout=[1, 2])) and refuses(theme(layout={"face": [1]})) and refuses(theme(layout={"bad name!": [1, 1]})))
ok("a bad hide list is refused", refuses(theme(hide="face")) and refuses(theme(hide=["ok", "bad name!"])))
ok("a bad size is refused", refuses(theme(sizes={"face": "big"})))
ok("a panel needs a known type", refuses(theme(panels=[{"type": "circle"}])) and refuses(theme(panels=["x"])))
ok("a rect panel needs a fill or an outline", refuses(theme(panels=[{"type": "rect", "x": 0, "y": 0, "w": 5, "h": 5}])))
ok("a panel color must be a real color or a palette name", refuses(theme(panels=[{"type": "rect", "fill": "blue"}])))
ok("too many panels are refused", refuses(theme(panels=[{"type": "line", "x": 0, "y": 0, "x2": 5, "y2": 5}] * (T.PANELS_MAX + 1))))
ok("a line panel works", T._clean(theme(panels=[{"type": "line", "x": 0, "y": 20, "x2": 480, "y2": 20, "color": "#ff0000", "width": 2}]))["panels"][0]["color"] == "#ff0000")

# ---------------------------------------------------------------- drawing: hide, move, size
tm, ui, els = new_manager()
tm._settings = T.clean_settings({})


def frame(th):
    """One UI pass with `th` as the active theme; the captured pixel regions per element."""
    tm._theme = T._clean(th)
    draw_pass(tm, ui, els)
    return tm._ctx["layers"]


plain = frame(theme())
ok("with a plain theme every element is drawn", {"face", "name", "uptime", "line1"} <= set(plain))

l = frame(theme(hide=["uptime", "face"]))
ok("a hidden element is not drawn at all", "uptime" not in l and "face" not in l and "name" in l)

l = frame(theme(layout={"name": [30, 40]}))
ok("a theme's layout moves an element", l["name"][1][0] == plain["name"][1][0] + 30 and l["name"][1][1] == plain["name"][1][1] + 40, (l["name"][1], plain["name"][1]))
ok("...and puts it back afterwards, so the next frame starts from home", els["name"].xy == (10, 27))

tm._layout = {"name": [5, 5]}
l = frame(theme(layout={"name": [30, 40]}))
ok("a theme's layout and your own moves add up", l["name"][1][0] == plain["name"][1][0] + 35, l["name"][1])
tm._layout = {}

l = frame(theme(sizes={"name": 2.0}))
w0 = plain["name"][1][2] - plain["name"][1][0]
w1 = l["name"][1][2] - l["name"][1][0]
ok("a size makes an element's text bigger", w1 > w0 * 1.6, (w0, w1))
ok("...and the element's own font is restored afterwards", els["name"].font is not None and not hasattr(els["name"].font, "_tm"))
l = frame(theme(sizes={"shakes": 1.5}))
ok("a two-font element (label + value) scales too", l["shakes"][1][2] - l["shakes"][1][0] > plain["shakes"][1][2] - plain["shakes"][1][0])
frame(theme())
ok("switching back to a plain theme restores the layout", tm._ctx["layers"]["name"][1] == plain["name"][1])

# ---------------------------------------------------------------- panels
def px(th, xy):
    tm._theme = T._clean(th)
    draw_pass(tm, ui, els)
    return T.colorize(tm._ctx["canvas"], tm._theme, 0.0, tm._ctx["layers"]).getpixel(xy)


ok("a filled panel paints its area", px(theme(panels=[{"type": "rect", "x": 100, "y": 150, "w": 50, "h": 50, "fill": "#123456"}]), (120, 170)) == (0x12, 0x34, 0x56))
ok("...and only its area", px(theme(panels=[{"type": "rect", "x": 100, "y": 150, "w": 50, "h": 50, "fill": "#123456"}]), (160, 170)) == (0, 0, 0))
ok("a panel can use the theme's own palette", px(theme(accent="#00ff00", panels=[{"type": "rect", "x": 100, "y": 150, "w": 50, "h": 50, "fill": "accent"}]), (120, 170)) == (0, 255, 0))
ok("an outlined panel leaves its inside alone", px(theme(panels=[{"type": "rect", "x": 100, "y": 150, "w": 50, "h": 50, "outline": "#ff0000"}]), (120, 170)) == (0, 0, 0)
   and px(theme(panels=[{"type": "rect", "x": 100, "y": 150, "w": 50, "h": 50, "outline": "#ff0000"}]), (100, 170)) == (255, 0, 0))
ok("a line panel draws", px(theme(panels=[{"type": "line", "x": 0, "y": 200, "x2": 480, "y2": 200, "color": "#0000ff"}]), (240, 200)) == (0, 0, 255))
ok("a rounded panel draws without complaint", px(theme(panels=[{"type": "rect", "x": 100, "y": 150, "w": 50, "h": 50, "fill": "#ffffff", "radius": 12}]), (125, 175)) == (255, 255, 255))
ok("panels sit behind the ink, not over it", px(theme(panels=[{"type": "rect", "x": 0, "y": 0, "w": 480, "h": 320, "fill": "#101010"}]), (5, 200)) == (0x10, 0x10, 0x10))

# ---------------------------------------------------------------- previews show the structure too
tm._theme = T._clean(theme())
draw_pass(tm, ui, els)
plain_png = tm._preview_png(T._clean(theme()))
moved_png = tm._preview_png(T._clean(theme(layout={"name": [120, 100]}, hide=["face"])))
ok("a preview of a theme with a different layout is a different picture", plain_png != moved_png)
laid = tm.render_structure(T._clean(theme(hide=["face"])))
ok("render_structure leaves out what the theme hides", laid is not None and "face" not in laid[1] and "name" in laid[1])
ok("...and reports where the face would be when it is shown", tm.render_structure(T._clean(theme()))[2] is not None)
ok("a preview does not disturb the live layout", tm._ctx["layers"]["name"][1] == plain["name"][1])
tm._view = None
ok("with no UI yet there is nothing to lay out", tm.render_structure(T._clean(theme())) is None)

finish()
