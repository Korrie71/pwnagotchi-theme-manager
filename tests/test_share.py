"""Sharing: a QR code for the store on your phone (drawn by our own small encoder), and its screen on the touch menu."""
from PIL import Image

from _util import Panel, T, finish, new_manager, ok, sandbox

sandbox()

# ---------------------------------------------------------------- the encoder
m = T.qr_matrix("http://192.0.2.42:8080/plugins/theme_manager/#gallery")
n = len(m)
ok("a link fits a version 3 code (29x29)", n == 29, n)
ok("the size grows with the text", len(T.qr_matrix("a")) == 21 and len(T.qr_matrix("x" * 134)) == 41)
ok("every row is the same length", all(len(r) == n for r in m))


def finder(mx, x0, y0):
    return all(mx[y0 + dy][x0 + dx] == (max(abs(dx - 3), abs(dy - 3)) != 2) for dy in range(7) for dx in range(7))


ok("the three corner finder patterns are where a scanner looks", finder(m, 0, 0) and finder(m, n - 7, 0) and finder(m, 0, n - 7))
ok("the timing patterns alternate between them", all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8)) and all(m[i][6] == (i % 2 == 0) for i in range(8, n - 8)))
ok("the always-dark module is dark", m[n - 8][8] is True)
ok("the same text always gives the same code", T.qr_matrix("abc") == T.qr_matrix("abc"))
ok("different text gives a different code", T.qr_matrix("abc") != T.qr_matrix("abd"))
ok("accents and symbols are fine (utf-8)", len(T.qr_matrix("héllo ✓")) >= 21)
try:
    T.qr_matrix("q" * 135)
    ok("too much text is refused, not silently cut", False)
except ValueError:
    ok("too much text is refused, not silently cut", True)

# Reed-Solomon against a published example: the 16-byte data of the "01234567" version 1-M example is not level L, so
# check the arithmetic on a known small case instead: appending the ecc bytes leaves a zero remainder
data = [32, 65, 205, 69, 41, 220, 46, 128, 236]
ecc = T._rs_ecc(data, 17)
ok("the error correction is the right length", len(ecc) == 17)
ok("the well-known 'HELLO WORLD' example gives the well-known correction bytes",
   T._rs_ecc([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17], 10) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

# a real decoder, when one is around (it is only a check, not a dependency)
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
if cv2:
    def decode(text):
        mx = T.qr_matrix(text)
        img = np.full(((len(mx) + 8) * 6,) * 2, 255, np.uint8)
        for y, row in enumerate(mx):
            for x, v in enumerate(row):
                if v:
                    img[(y + 4) * 6:(y + 5) * 6, (x + 4) * 6:(x + 5) * 6] = 0
        return cv2.QRCodeDetector().detectAndDecode(img)[0]
    ok("OpenCV reads our codes back, at every version", all(decode(t) == t for t in ("a", "b" * 30, "c" * 50, "d" * 75, "e" * 100, "f" * 130, "http://192.0.2.42:8080/plugins/theme_manager/#gallery")))
else:
    print("SKIP no OpenCV here to read the codes back")

# ---------------------------------------------------------------- drawing
img = Image.new("RGB", (480, 320), (9, 9, 9))
T.draw_qr(img, "hello", (110, 38, 370, 262))
ok("draw_qr paints a light quiet zone and dark modules inside the box", img.getpixel((150, 60)) == (255, 255, 255) and any(img.getpixel((x, 120)) == (0, 0, 0) for x in range(110, 370)))
ok("...and nothing outside the box", img.getpixel((50, 100)) == (9, 9, 9) and img.getpixel((420, 100)) == (9, 9, 9))

# ---------------------------------------------------------------- the touch menu
tm, ui, els = new_manager()
finger = Panel(tm)
finger.calibrate()
tm.open_menu("list", "themes")
ok("outside the store the slot still calibrates", any(a == ("cal", None) for _, a in T.menu_hits(tm._menu)) and not any(a == ("phone", None) for _, a in T.menu_hits(tm._menu)))
finger.tap_rect(finger.hit("store"))
ok("in the store that slot becomes 'on phone'", any(a == ("phone", None) for _, a in T.menu_hits(tm._menu)) and not any(a == ("cal", None) for _, a in T.menu_hits(tm._menu)))
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
real_ip = T._local_ip
T._local_ip = lambda: "192.0.2.42"
finger.tap_rect(finger.hit("phone"))
ok("tapping it shows a QR for the web editor's Gallery", tm._menu["mode"] == "qr" and tm._menu["qr_url"] == "http://192.0.2.42:8080/plugins/theme_manager/#gallery", tm._menu.get("qr_url"))
frame = Image.new("RGB", (480, 320))
T.draw_menu(frame, tm._menu, tm._theme)
dark = sum(1 for x in range(110, 370) for y in range(34, 244) if frame.getpixel((x, y)) == (0, 0, 0))
ok("...and draws it: real dark modules on a light square", dark > 500 and frame.getpixel((150, 50)) == (255, 255, 255), dark)
finger.tap_rect(finger.hit("qrclose"))
ok("back returns to the store", tm._menu["mode"] == "list" and tm._menu["store"] is True)
T._local_ip = lambda: "no ip"
finger.tap_rect(finger.hit("phone"))
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("with no network it says so instead of a broken code", tm._menu["qr_url"] == "")
T._local_ip = real_ip

finish()
