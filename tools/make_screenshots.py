"""Regenerates the README screenshots (themes, moods, face packs, touch menu) from made-up data.

    python tools/make_screenshots.py            # writes docs/images/*.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene import ROOT, T, faces, render  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images")
os.makedirs(OUT, exist_ok=True)
try:
    CAPTION = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 14)
except OSError:
    CAPTION = ImageFont.load_default()


def tile(img, text):
    out = Image.new("RGB", (img.width, img.height + 24), (15, 17, 21))
    out.paste(img, (0, 0))
    ImageDraw.Draw(out).text((8, img.height + 4), text, font=CAPTION, fill=(200, 205, 215))
    return out


def grid(items, cols, size):
    w, h = size[0], size[1] + 24
    sheet = Image.new("RGB", (cols * w, -(-len(items) // cols) * h), (15, 17, 21))
    for i, (img, caption) in enumerate(items):
        sheet.paste(tile(img.resize(size, Image.LANCZOS), caption), ((i % cols) * w, (i // cols) * h))
    return sheet


# ---- themes
names = ["matrix", "cyberpunk", "vaporwave", "amber", "ice", "blood", "paper", "gameboy"]
grid([(render(n), n) for n in names], 4, (360, 240)).save(os.path.join(OUT, "themes.png"), optimize=True)

# ---- moods: one theme, the face on screen decides the colors
moods = [("happy", faces.HAPPY), ("excited", faces.EXCITED), ("sad", faces.SAD), ("angry", faces.ANGRY),
         ("lonely", faces.LONELY), ("cool", faces.COOL)]
grid([(render("moody", face, mood=m), "mood: " + m) for m, face in moods], 3, (360, 240)).save(os.path.join(OUT, "moods.png"), optimize=True)

# ---- more themes
more = ["startrek", "lcars", "spring", "summer", "autumn", "winter", "mountain", "ocean", "forest", "desert", "aurora", "volcano",
        "halloween", "christmas", "space"]
grid([(render(n), n) for n in more], 4, (360, 240)).save(os.path.join(OUT, "themes-more.png"), optimize=True)

# ---- face packs
packs = [("blobby", faces.HAPPY, "blob: happy"), ("blobby", faces.SAD, "blob: sad"), ("blobby", faces.ANGRY, "blob: angry"),
         ("blobby", faces.COOL, "blob: cool"), ("sketch", faces.HAPPY, "outline (tinted): happy"),
         ("sketch", faces.SAD, "outline (tinted): sad"), ("sketch", faces.ANGRY, "outline (tinted): angry"),
         ("sketch", faces.LONELY, "outline (tinted): lonely")]
grid([(render(n, f), c) for n, f, c in packs], 4, (360, 240)).save(os.path.join(OUT, "faces.png"), optimize=True)

# ---- touch menu (made-up plugin names and status)
themes = {n: T._clean(v) for n, v in T.BUILTIN.items()}
menu = {"mode": "list", "tab": "themes", "page": 0, "pages": {}, "names": list(themes), "colors": themes, "active": "cyberpunk",
        "plugins": ["auto_backup", "auto-update", "bt-tether", "fix_services", "gps", "grid", "logtail", "memtemp",
                    "session-stats", "switcher", "webcfg", "webgpsmap", "wpa-sec"],
        "on": {"auto_backup", "auto-update", "bt-tether", "fix_services", "gps", "grid", "webcfg", "wpa-sec"},
        "busy": set(), "failed": set(), "confirm": None,
        "lines": ["CPU 48C  load 12%  RAM 21%", "IP 192.0.2.42", "GPS FIX 9sat  48.85837 2.29448",
                  "Up 03:12:45  Power OK  Bat n/a", "Pwned 27  Cracked 3  Session 4"], "mode_now": "AUTO"}
# achievements with made-up progress, and the elements a layout list would show
fake = {"handshakes": 27, "cracked": 3, "hours": 12.5, "days": 4, "themes": 6}
done = {"first_shake", "shakes_10", "uptime_1", "days_3", "swiper"}
award_info = {}
for aid, aname, desc, stat, goal in T.ACHIEVEMENTS:
    award_info[aid] = {"id": aid, "name": aname, "desc": desc, "goal": goal, "unlocked": 1.0 if aid in done else None,
                       "progress": fake.get(stat, 0)}
elements = ["aps", "channel", "face", "line1", "line2", "mode", "name", "shakes", "status", "uptime"]
menu.update(awards=[a[0] for a in T.ACHIEVEMENTS], award_info=award_info, awards_on=True, layout=elements,
            layout_info={"face": (12, 6), "name": (0, -4)}, overheat=False)
# a cracking dashboard with made-up handshakes (never the real ones)
crack_rows = [
    {"file": "CoffeeShop_aabbccdd0001.pcapng", "name": "CoffeeShop", "bssid": "aabbccdd0001", "status": "cracked", "password": "letmein123"},
    {"file": "GuestWifi_aabbccdd0002.pcapng", "name": "GuestWifi", "bssid": "aabbccdd0002", "status": "uploaded", "password": None},
    {"file": "Office5G_aabbccdd0003.pcapng", "name": "Office5G", "bssid": "aabbccdd0003", "status": "queued", "password": None},
    {"file": "OldRouter_aabbccdd0004.pcapng", "name": "OldRouter", "bssid": "aabbccdd0004", "status": "invalid", "password": None},
]
crack_info = {"__summary__": {"kind": "summary", "text": T._crack_summary_text(T.crack_summary(crack_rows))}}
crack_info.update({r["file"]: dict(r, kind="row") for r in crack_rows})
menu.update(crack=["__summary__"] + [r["file"] for r in crack_rows], crack_info=crack_info)
# a sonar radar with made-up nearby networks (fake, locally-administered MACs, never real ones)
radar_aps = [
    ("02:00:00:00:00:01", "CoffeeShop", 6, -45, 1, "WPA2", False),
    ("02:00:00:00:00:02", "GuestWifi", 11, -58, 0, "WPA2", False),
    ("02:00:00:00:00:03", "OldRouter", 1, -80, 0, "WPA2", True),
    ("02:00:00:00:00:04", "Office5G", 44, -66, 3, "WPA3", False),
    ("02:00:00:00:00:05", "(hidden)", 6, -72, 0, "WPA2", False),
]
radar_rows = [{"mac": mac, "name": name, "channel": ch, "rssi": rssi, "clients": clients, "encryption": enc,
               "captured": captured, "angle": T._radar_angle(mac.replace(":", "")),
               "score": T._radar_score({"mac": mac, "rssi": rssi, "clients": [None] * clients, "encryption": enc}, {mac.replace(":", "")} if captured else set())}
              for mac, name, ch, rssi, clients, enc, captured in radar_aps]
radar_rows.sort(key=lambda r: -r["score"])
menu.update(radar=radar_rows, t=3.0)
# a couple of paired nodes and one just-found candidate (fake, locally-administered MACs, never real ones),
# plus a wardrive trip in progress right under the summary (made-up stats, never a real track)
wardrive_stats = {"active": True, "distance_m": 2350, "duration_s": 1830, "aps_seen": 14, "handshakes": 3}
nodes_info = {
    "__summary__": {"kind": "summary", "text": "2 paired (1 online) · 1 found · 14 team shakes"},
    "__wardrive__": dict(wardrive_stats, kind="wardrive"),
    "__skipnet__": {"kind": "skipnet", "on": True},
    "p:02:00:00:00:00:11": {"kind": "paired", "mac": "02:00:00:00:00:11", "name": "zero-w-north", "ip": "192.0.2.10:8080", "handshakes": 14, "online": True},
    "p:02:00:00:00:00:12": {"kind": "paired", "mac": "02:00:00:00:00:12", "name": "zero-w-south", "ip": "192.0.2.11:8080", "handshakes": 3, "online": False},
    "f:02:00:00:00:00:13": {"kind": "found", "mac": "02:00:00:00:00:13", "name": "zero-w-new", "ip": "192.0.2.12:8080", "handshakes": 7},
}
menu.update(nodes=list(nodes_info), nodes_info=nodes_info, nodes_scanning=False, wardrive=wardrive_stats)
for name, extra in (("menu-themes.png", {"tab": "themes", "page": 1}), ("menu-plugins.png", {"tab": "plugins", "busy": {"bt-tether"}}),
                    ("menu-system.png", {"tab": "system", "overheat": True, "atkmode": "home"}), ("menu-awards.png", {"tab": "awards"}),
                    ("menu-layout.png", {"tab": "layout", "page": 1}), ("menu-crack.png", {"tab": "crack"}),
                    ("menu-radar.png", {"tab": "radar"}), ("menu-nodes.png", {"tab": "nodes"}),
                    ("menu-adjust.png", {"mode": "adjust", "adjust": "face", "offset": (12, 6), "box": (25, 52, 252, 122), "step_px": 5})):
    shown = dict(menu, **extra)
    shown["tab_scroll"] = T.TAB_NAMES.index(shown["tab"]) if shown["tab"] in T.TAB_NAMES else 0
    render("cyberpunk", menu=shown).save(os.path.join(OUT, name), optimize=True)
render("cyberpunk", notice=T.DISCLAIMER_TEXT).save(os.path.join(OUT, "menu-notice.png"), optimize=True)

print("wrote", ", ".join(sorted(f for f in os.listdir(OUT) if f.endswith(".png") and not f.startswith("editor"))))
