"""theme_manager - theme engine for the pwnagotchi 3.5" framebuffer display.

Themes are JSON files in /etc/pwnagotchi/themes/. See README.md there.

CLI (run with /opt/.pwn/bin/python3):
  theme_manager.py list
  theme_manager.py set NAME
  theme_manager.py new NAME            create a template theme to edit
  theme_manager.py mood NAME [seconds] force a mood to preview it (NAME=off to clear)
  theme_manager.py validate FILE.json
  theme_manager.py preview NAME OUT.png [seconds]
"""
import json
import logging
import math
import os
import random
import contextlib
import fcntl
import glob
import re
import select
import socket
import struct
import threading
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import pwnagotchi.plugins as plugins

def _tame_malloc():
    """Image buffers are large and short-lived. Keep them out of glibc's per-thread heaps (which never give memory back
    to the OS) so the web server's many request threads don't slowly bloat pwnagotchi's memory."""
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.mallopt(-3, 131072)   # M_MMAP_THRESHOLD: fixed, so big buffers are mmap'ed and freed straight back
        libc.mallopt(-8, 2)        # M_ARENA_MAX: fewer per-thread heaps
        return libc
    except Exception:
        return None


_libc = _tame_malloc()


def trim_memory():
    """Hand freed heap pages back to the OS."""
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:
            pass


THEME_DIR = "/etc/pwnagotchi/themes"
ACTIVE_FILE = os.path.join(THEME_DIR, "active.json")
DOCS_FILE = os.path.join(THEME_DIR, "README.md")
FRAME_PATH = "/var/tmp/pwnagotchi/pwnagotchi.png"
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,32}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")

EFFECTS = {"scanlines", "vignette", "glow", "noise", "pulse", "rainbow",
           "glitch", "rain", "stars", "border"}
ANIMATED = {"pulse", "rainbow", "glitch", "rain", "stars", "noise"}
LIVE_TOKENS = ("{time}", "{cpu}", "{temp}", "{mem}", "{uptime}", "{ip}", "{gps}", "{lat}", "{lon}", "{sats}",
               "{handshakes}", "{cracked}", "{session}", "{battery}", "{power}", "{mode}")
NUM_LIMITS = {"strength": (0, 1), "speed": (0, 30), "size": (1, 64), "density": (0.01, 1),
              "radius": (0, 12), "interval": (0.5, 60)}
TEXT_MAX = 20
ELEMENTS_MAX = 40
MOODS = ("look_r", "sleep", "awake", "bored", "intense", "cool", "happy", "grateful", "excited", "motivated",
         "demotivated", "smart", "lonely", "sad", "angry", "friend", "broken", "debug", "upload", "handshake")
MOOD_ALIAS = {"look_l": "look_r", "look_r_happy": "happy", "look_l_happy": "happy", "sleep2": "sleep",
              "upload1": "upload", "upload2": "upload"}
MOOD_FADE = 0.6    # seconds to blend between moods
HANDSHAKE_FLASH = 4.0
FORCE_FILE = os.path.join(THEME_DIR, "force_mood.json")
FACES_DIR = os.path.join(THEME_DIR, "faces")
STATE_FILES = ("active.json", "force_mood.json", "touch.json")   # JSON files in THEME_DIR that are not themes
PACK_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")

# Built-in themes. bg/fg/accent/web are required, everything else is optional.
BUILTIN = {
    "default": {"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#4caf50"},
    "paper": {"bg": "#f4f1e8", "fg": "#1a1a1a", "accent": "#1a1a1a", "web": "#795548",
              "effects": [{"type": "noise", "strength": 0.15}, {"type": "vignette", "strength": 0.25}]},
    "matrix": {"bg": "#000800", "fg": "#00ff41", "accent": "#008f11", "web": "#00ff41", "fps": 8,
               "effects": [{"type": "rain", "density": 0.5, "speed": 8}, {"type": "glow", "radius": 2, "strength": 0.7},
                           {"type": "scanlines", "strength": 0.3}],
               "elements": {"face": "#b6ffb6", "status": "#7dff9a", "name": "#00ff41"},
               "text": [{"text": "> {name} online  {time}", "x": 10, "y": 278, "size": 11}]},
    "amber": {"bg": "#100800", "fg": "#ffb000", "accent": "#a06000", "web": "#ffb000", "fps": 6,
              "effects": [{"type": "glow", "radius": 3, "strength": 0.8}, {"type": "noise", "strength": 0.25},
                          {"type": "scanlines", "strength": 0.4}, {"type": "vignette", "strength": 0.7}],
              "text": [{"text": "VT-100  {date}", "x": 10, "y": 278, "size": 11}]},
    "cyberpunk": {"bg": "#0d0221", "fg": "#00f0ff", "accent": "#ff2a6d", "web": "#ff2a6d", "fps": 8,
                  "gradient": {"from": "#0d0221", "to": "#2a0845", "direction": "vertical"},
                  "effects": [{"type": "glow", "radius": 3, "strength": 0.8}, {"type": "glitch", "interval": 5},
                              {"type": "scanlines", "strength": 0.25}],
                  "elements": {"face": "#00f0ff", "name": "#ff2a6d", "status": "#fcee0a", "shakes": "#ff2a6d"},
                  "mood": {"sad": {"fg": "#5b7cff", "accent": "#3a4a9a", "elements": {"face": "#5b7cff"}},
                           "angry": {"fg": "#ff3030", "elements": {"face": "#ff3030"}, "effects": [{"type": "glitch", "interval": 1.5}]},
                           "handshake": {"fg": "#39ff14", "elements": {"face": "#39ff14", "name": "#39ff14"},
                                         "effects": [{"type": "glow", "radius": 6, "strength": 1}]}},
                  "text": [{"text": "// {name} //", "x": 10, "y": 262, "size": 12, "bold": True, "color": "#ff2a6d"},
                           {"text": "NETRUNNER MODE ENGAGED ::: STAY LOW ::: PWN THE PLANET ::: ", "x": 10, "y": 278,
                            "size": 11, "scroll": True, "speed": 45, "width": 290, "color": "#fcee0a"}]},
    "vaporwave": {"bg": "#1a0b2e", "fg": "#ff71ce", "accent": "#01cdfe", "web": "#b967ff", "fps": 6,
                  "gradient": {"from": "#2b0f54", "to": "#4a1580", "direction": "vertical"},
                  "effects": [{"type": "stars", "density": 0.4, "speed": 3}, {"type": "glow", "radius": 2, "strength": 0.6},
                              {"type": "border", "size": 2, "color": "#01cdfe"}],
                  "elements": {"face": "#01cdfe", "status": "#05ffa1", "name": "#fffb96"},
                  "text": [{"text": "A E S T H E T I C", "x": 10, "y": 278, "size": 12, "color": "#05ffa1"}]},
    "blood": {"bg": "#0a0000", "fg": "#ff2020", "accent": "#7a0000", "web": "#ff2020", "fps": 6,
              "effects": [{"type": "pulse", "speed": 3, "strength": 0.5}, {"type": "vignette", "strength": 0.8},
                          {"type": "glow", "radius": 3, "strength": 0.7}]},
    "ice": {"bg": "#04121f", "fg": "#9fe8ff", "accent": "#3a8fb7", "web": "#3a8fb7", "fps": 5,
            "gradient": {"from": "#04121f", "to": "#0a3350", "direction": "vertical"},
            "effects": [{"type": "stars", "density": 0.6, "speed": 2}, {"type": "glow", "radius": 2, "strength": 0.5}]},
    "gameboy": {"bg": "#9bbc0f", "fg": "#0f380f", "accent": "#306230", "web": "#306230",
                "effects": [{"type": "scanlines", "strength": 0.12}, {"type": "border", "size": 3, "color": "#306230"}]},
    "moody": {"bg": "#08080f", "fg": "#d8d8e8", "accent": "#6c6c88", "web": "#8a7bff", "fps": 8,
              "description": "colors follow pwnagotchi's mood",
              "elements": {"face": "#d8d8e8"},
              "mood": {"happy": {"fg": "#7dff9a", "accent": "#2f9a55", "elements": {"face": "#7dff9a"}},
                       "excited": {"elements": {"face": "rainbow"}, "effects": [{"type": "glow", "radius": 4, "strength": 1}]},
                       "grateful": {"fg": "#ffd166", "elements": {"face": "#ffd166"}},
                       "motivated": {"fg": "#ffa94d", "elements": {"face": "#ffa94d"}},
                       "sad": {"fg": "#5b7cff", "accent": "#33448f", "elements": {"face": "#5b7cff"}},
                       "lonely": {"fg": "#b18cff", "accent": "#5a4a8a", "elements": {"face": "#b18cff"}},
                       "bored": {"fg": "#8a8a99", "accent": "#55555f", "elements": {"face": "#8a8a99"}},
                       "angry": {"fg": "#ff3030", "accent": "#8a1f1f", "elements": {"face": "#ff3030"},
                                 "effects": [{"type": "pulse", "speed": 8, "strength": 0.5}]},
                       "intense": {"fg": "#ff8a3d", "elements": {"face": "#ff8a3d"}, "effects": [{"type": "glitch", "interval": 2}]},
                       "cool": {"fg": "#00e5ff", "elements": {"face": "#00e5ff"}},
                       "sleep": {"fg": "#4a5a7a", "accent": "#2a3550", "elements": {"face": "#4a5a7a"}},
                       "broken": {"fg": "#ff2020", "effects": [{"type": "glitch", "interval": 1}, {"type": "noise", "strength": 0.6}]},
                       "handshake": {"fg": "#39ff14", "accent": "#1c8a0a", "elements": {"face": "#39ff14"},
                                     "effects": [{"type": "glow", "radius": 6, "strength": 1}]}}},
    "blobby": {"bg": "#14142b", "fg": "#f2f2ff", "accent": "#8a7bff", "web": "#8a7bff", "fps": 5,
               "description": "colorful blob faces (face pack 'blob')",
               "gradient": {"from": "#14142b", "to": "#2b1f4a", "direction": "vertical"},
               "face_pack": "blob", "face_offset": [-10, 28],
               "elements": {"name": "#ffd23f", "status": "#7dff9a"},
               "effects": [{"type": "stars", "density": 0.3, "speed": 2}]},
    "sketch": {"bg": "#0b0b12", "fg": "#d8d8e8", "accent": "#6c6c88", "web": "#8a7bff", "fps": 8,
               "description": "outline faces tinted by mood (face pack 'outline')",
               "face_pack": "outline", "face_tint": True, "face_offset": [-10, 28],
               "elements": {"face": "#d8d8e8"},
               "mood": {"happy": {"elements": {"face": "#7dff9a"}}, "excited": {"elements": {"face": "rainbow"}},
                        "sad": {"elements": {"face": "#5b7cff"}}, "angry": {"elements": {"face": "#ff3030"}},
                        "lonely": {"elements": {"face": "#b18cff"}}, "bored": {"elements": {"face": "#8a8a99"}},
                        "cool": {"elements": {"face": "#00e5ff"}}, "grateful": {"elements": {"face": "#ffd166"}},
                        "handshake": {"elements": {"face": "#39ff14"}, "effects": [{"type": "glow", "radius": 5, "strength": 1}]}}},
    "rainbow": {"bg": "#05050a", "fg": "#ffffff", "accent": "#ffffff", "web": "#b967ff", "fps": 8,
                "effects": [{"type": "rainbow", "speed": 2}, {"type": "glow", "radius": 3, "strength": 0.7}]},
}


# ---------------------------------------------------------------- validation
def write_json(path, obj, **kw):
    """Write atomically, so the plugin never reads a half-written file."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as fp:
        json.dump(obj, fp, **kw)
    os.replace(tmp, path)


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _color(v, what):
    v = str(v).strip()
    if not HEX_RE.fullmatch(v):
        raise ValueError("%s must be a #rrggbb color" % what)
    return v.lower()


def _num(v, lo, hi, what):
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % what)
    return max(lo, min(hi, v))


def _clean_effect(e):
    if isinstance(e, str):
        e = {"type": e}
    if not isinstance(e, dict) or e.get("type") not in EFFECTS:
        raise ValueError("effect type must be one of: " + ", ".join(sorted(EFFECTS)))
    out = {"type": e["type"]}
    for k, (lo, hi) in NUM_LIMITS.items():
        if k in e:
            out[k] = _num(e[k], lo, hi, "%s.%s" % (e["type"], k))
    if "color" in e:
        out["color"] = _color(e["color"], "%s.color" % e["type"])
    return out


def _clean_text(t):
    if not isinstance(t, dict) or not isinstance(t.get("text"), str):
        raise ValueError("each text line needs a 'text' field with a string")
    out = {"text": str(t["text"])[:200],
           "x": int(_num(t.get("x", 0), -480, 960, "text.x")),
           "y": int(_num(t.get("y", 0), -320, 640, "text.y")),
           "size": int(_num(t.get("size", 12), 6, 64, "text.size")),
           "bold": bool(t.get("bold", False)),
           "align": t.get("align", "left") if t.get("align") in ("left", "center", "right") else "left",
           "scroll": bool(t.get("scroll", False)),
           "speed": _num(t.get("speed", 40), 1, 300, "text.speed"),
           "width": int(_num(t.get("width", 300), 10, 480, "text.width"))}
    if "color" in t:
        out["color"] = _color(t["color"], "text.color")
    return out


def _clean_elements(elements):
    if not isinstance(elements, dict) or len(elements) > ELEMENTS_MAX:
        raise ValueError("elements must be an object with at most %d entries" % ELEMENTS_MAX)
    out = {}
    for k, v in elements.items():
        if not KEY_RE.fullmatch(str(k)):
            raise ValueError("bad element name %r" % k)
        out[str(k)] = "rainbow" if v == "rainbow" else _color(v, "elements.%s" % k)
    return out


def _clean_mood(m):
    if not isinstance(m, dict):
        raise ValueError("a mood must be an object")
    out = {k: _color(m[k], "mood." + k) for k in ("bg", "fg", "accent") if k in m}
    g = m.get("gradient")
    if g:
        out["gradient"] = {"from": _color(g.get("from"), "gradient.from"), "to": _color(g.get("to"), "gradient.to"),
                           "direction": "horizontal" if g.get("direction") == "horizontal" else "vertical"}
    if m.get("elements"):
        out["elements"] = _clean_elements(m["elements"])
    if m.get("effects"):
        if not isinstance(m["effects"], list):
            raise ValueError("mood effects must be a list")
        out["effects"] = [_clean_effect(e) for e in m["effects"]]
    return out


def _clean(theme):
    try:
        return _clean_theme(theme)
    except (TypeError, AttributeError, KeyError, IndexError) as e:
        raise ValueError("invalid theme structure (%s)" % e)


def _clean_theme(theme):
    if not isinstance(theme, dict):
        raise ValueError("theme must be a JSON object")
    out = {k: _color(theme.get(k, ""), k) for k in ("bg", "fg", "accent", "web")}
    if theme.get("description"):
        out["description"] = str(theme["description"])[:120]
    if "fps" in theme:
        out["fps"] = _num(theme["fps"], 1, 10, "fps")
    g = theme.get("gradient")
    if g:
        out["gradient"] = {"from": _color(g.get("from"), "gradient.from"), "to": _color(g.get("to"), "gradient.to"),
                           "direction": "horizontal" if g.get("direction") == "horizontal" else "vertical"}
    effects = theme.get("effects") or []
    if not isinstance(effects, list):
        raise ValueError("effects must be a list")
    if effects:
        out["effects"] = [_clean_effect(e) for e in effects]
    texts = theme.get("text") or []
    if not isinstance(texts, list) or len(texts) > TEXT_MAX:
        raise ValueError("text must be a list of at most %d lines" % TEXT_MAX)
    if texts:
        out["text"] = [_clean_text(t) for t in texts]
    if theme.get("elements"):
        out["elements"] = _clean_elements(theme["elements"])
    moods = theme.get("mood") or {}
    if not isinstance(moods, dict):
        raise ValueError("mood must be an object")
    if moods:
        out["mood"] = {}
        for name, m in moods.items():
            if name not in MOODS:
                raise ValueError("unknown mood %r, use one of: %s" % (name, ", ".join(MOODS)))
            out["mood"][name] = _clean_mood(m)
    if theme.get("face_pack"):
        if not PACK_RE.fullmatch(str(theme["face_pack"])):
            raise ValueError("face_pack must be a folder name (letters, digits, _ and -)")
        out["face_pack"] = str(theme["face_pack"])
        if "face_scale" in theme:
            out["face_scale"] = _num(theme["face_scale"], 0.25, 4, "face_scale")
        off = theme.get("face_offset")
        if off is not None:
            if not (isinstance(off, list) and len(off) == 2):
                raise ValueError("face_offset must be [x, y]")
            out["face_offset"] = [int(_num(off[0], -300, 300, "face_offset")), int(_num(off[1], -300, 300, "face_offset"))]
        if theme.get("face_tint"):
            out["face_tint"] = True
    faces = theme.get("faces")
    if faces:
        if not isinstance(faces, dict):
            raise ValueError("faces must be an object like {\"HAPPY\": \"(^o^)\"}")
        out["faces"] = {str(k).upper(): str(v) for k, v in faces.items()}
    return out


def _rainbow_elements(theme):
    return "rainbow" in (theme.get("elements") or {}).values()


def is_animated(theme):
    if _rainbow_elements(theme):
        return True
    if any(e["type"] in ANIMATED for e in theme.get("effects", [])):
        return True
    for t in theme.get("text", []):
        if t.get("scroll") or any(tok in t["text"] for tok in LIVE_TOKENS):
            return True
    return False


# ------------------------------------------------------------------ rendering
# Everything that doesn't change from frame to frame (masks, blur, gradients, glyphs,
# text bitmaps, shading maps) is cached, so an animated frame is a few cheap pastes.
_fonts = {}
_stats = {"t": 0, "v": {}}
_cache = {}
_cache_lock = threading.Lock()
CONTINUOUS = {"pulse", "rainbow", "rain", "stars", "noise"}


def _memo(key, refs, make, cap=48):
    """Small LRU. `refs` are objects whose identity is part of the key (kept alive so id() can't be reused)."""
    with _cache_lock:
        hit = _cache.pop(key, None)
        if hit is not None and len(hit[0]) == len(refs) and all(a is b for a, b in zip(hit[0], refs)):
            _cache[key] = hit
            return hit[1]
    val = make()
    with _cache_lock:
        _cache[key] = (refs, val)
        while len(_cache) > cap:
            _cache.pop(next(iter(_cache)))
    return val


def _font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype(FONT_DIR + ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"), size)
        except Exception:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def _sysstats():
    now = time.time()
    if now - _stats["t"] < 2:
        return _stats["v"]
    v = {}
    try:
        import pwnagotchi
        v["name"] = pwnagotchi.config["main"]["name"]
    except Exception:
        v["name"] = os.uname().nodename
    try:
        v["cpu"] = "%d%%" % min(99, int(float(open("/proc/loadavg").read().split()[0]) * 25))
    except Exception:
        v["cpu"] = "?"
    try:
        v["temp"] = "%dC" % (int(open("/sys/class/thermal/thermal_zone0/temp").read()) // 1000)
    except Exception:
        v["temp"] = "?"
    try:
        m = dict(l.split(":") for l in open("/proc/meminfo").read().splitlines()[:3])
        tot, avail = int(m["MemTotal"].split()[0]), int(m["MemAvailable"].split()[0])
        v["mem"] = "%d%%" % (100 - avail * 100 // tot)
    except Exception:
        v["mem"] = "?"
    try:
        s = int(float(open("/proc/uptime").read().split()[0]))
        v["uptime"] = "%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)
    except Exception:
        v["uptime"] = "?"
    _stats["t"], _stats["v"] = now, v
    return v


_slow = {}
STAT_SOURCE = None    # set by the plugin: values that need pwnagotchi's live state (GPS fix, mode, session count)


def _cached(key, ttl, fn):
    now = time.time()
    hit = _slow.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = "?"
    _slow[key] = (now, val)
    return val


def _iface_ip(name):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
        try:
            return socket.inet_ntoa(fcntl.ioctl(sk.fileno(), 0x8915, struct.pack("256s", name[:15].encode()))[20:24])
        except OSError:
            return None


def _local_ip():
    """IPv4 of the interface that carries the default route, else the first interface that has an address."""
    first = []
    try:
        for line in open("/proc/net/route").read().splitlines()[1:]:
            f = line.split()
            if f[1] == "00000000":
                first.append(f[0])
    except OSError:
        pass
    for name in first + sorted(os.listdir("/sys/class/net")):
        if name != "lo" and not name.endswith("mon"):
            ip = _iface_ip(name)
            if ip:
                return ip
    return "no ip"


def _handshake_dir():
    try:
        import pwnagotchi
        return pwnagotchi.config["bettercap"]["handshakes"]
    except Exception:
        return "/etc/pwnagotchi/handshakes"


def _count_handshakes():
    with os.scandir(_handshake_dir()) as it:
        return str(sum(1 for e in it if e.name.endswith((".pcap", ".pcapng"))))


def _count_cracked():
    d, n = _handshake_dir(), 0
    for f in os.listdir(d):
        if f.endswith(".potfile"):
            with open(os.path.join(d, f), errors="ignore") as fp:
                n += sum(1 for line in fp if line.strip())
    return str(n)


def _power_state():
    """OK / LOW from the Pi's undervoltage flag."""
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if open(h + "/name").read().strip() == "rpi_volt":
                return "LOW" if open(h + "/in0_lcrit_alarm").read().strip() == "1" else "OK"
        except OSError:
            continue
    return "n/a"


def _battery():
    for d in sorted(glob.glob("/sys/class/power_supply/*")):
        try:
            if open(d + "/type").read().strip() == "Mains":
                continue
            return "%d%%" % int(open(d + "/capacity").read())
        except (OSError, ValueError):
            continue
    return "n/a"


PROVIDERS = {"ip": (15, _local_ip), "handshakes": (15, _count_handshakes), "cracked": (15, _count_cracked),
             "power": (2, _power_state), "battery": (10, _battery)}


class _Lazy(dict):
    """format_map source that only reads a value when the text asks for it."""
    def __missing__(self, key):
        if key in ("name", "cpu", "temp", "mem", "uptime"):
            return _sysstats().get(key, "?")
        if key == "time":
            return time.strftime("%H:%M:%S")
        if key == "date":
            return time.strftime("%Y-%m-%d")
        if key in PROVIDERS:
            ttl, fn = PROVIDERS[key]
            return _cached(key, ttl, fn)
        if STAT_SOURCE is not None:
            try:
                v = STAT_SOURCE(key)
            except Exception:
                v = "?"
            if v is not None:
                return v
        return "{%s}" % key


def _expand(text):
    try:
        return text.format_map(_Lazy())
    except Exception:
        return text


def _scale(c, k):
    return tuple(int(x * k) for x in c)


def _base(theme, w, h):
    def make():
        g = theme.get("gradient")
        if not g:
            return Image.new("RGB", (w, h), _hex(theme["bg"]))
        c1, c2 = np.array(_hex(g["from"]), np.float32), np.array(_hex(g["to"]), np.float32)
        ramp = np.linspace(0, 1, w if g["direction"] == "horizontal" else h)
        ramp = ramp[None, :, None] if g["direction"] == "horizontal" else ramp[:, None, None]
        arr = np.broadcast_to(c1 + (c2 - c1) * ramp, (h, w, 3)).astype(np.uint8)
        return Image.fromarray(arr, "RGB")
    return _memo(("base", id(theme), w, h), (theme,), make).copy()


def _region(layer):
    """(cropped mask, box) covering only the non-empty part of an L mask, so pastes stay small."""
    box = layer.getbbox()
    return (layer.crop(box), box) if box else None


def _layers(canvas, w, h, bar_top, bar_bottom, hide=None):
    def make():
        mask = canvas.convert("L")
        if hide is not None:  # a face image replaces the drawn face
            mask.paste(0, hide[1], hide[0])
        bars = []
        for box in ((0, 0, w, bar_top + 1), (0, bar_bottom, w, h)):
            part = mask.crop(box)
            bb = part.getbbox()
            if bb:
                bars.append((part.crop(bb), (box[0] + bb[0], box[1] + bb[1], box[0] + bb[2], box[1] + bb[3])))
        return mask, _region(mask), bars
    return _memo(("mask", id(canvas), hide is not None), (canvas,), make)


def _halo(canvas, mask, radius, strength):
    return _memo(("halo", id(canvas), radius, strength), (canvas,), lambda: _region(mask.filter(
        ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * strength * 1.6)))))


def _stamp(img, ink, region):
    """Paste a color (or same-size image) through a cached region mask."""
    if region is None:
        return
    m, box = region
    img.paste(ink.crop(box) if isinstance(ink, Image.Image) else ink, box, m)


RAIN_CHARS = "01$#%&*+=<>?abcdef"


def _glyphs():
    def make():
        font, out = _font(9), {}
        for ch in RAIN_CHARS:
            m = Image.new("L", (8, 12), 0)
            ImageDraw.Draw(m).text((0, 0), ch, font=font, fill=255)
            for i in range(9):  # one pre-faded mask per trail position
                out[ch, i] = m.point(lambda v, k=166 * (1 - i / 9.0) / 255: int(v * k))
        return out
    return _memo(("glyphs",), (), make)


def _rain(img, w, h, t, e, fg):
    color = _hex(e["color"]) if "color" in e else fg
    density, speed = e.get("density", 0.5), e.get("speed", 8)
    glyphs = _glyphs()
    for col, x in enumerate(range(0, w, 10)):
        seed = (col * 7919) % 997
        if (seed % 100) / 100.0 > density:
            continue
        sp = speed * (0.6 + (seed % 5) * 0.25) * 6
        head = int((t * sp + seed * 13) % (h + 120)) - 40
        for i in range(9):
            y = head - i * 11
            if 0 <= y < h:
                img.paste(color, (x, y), glyphs[RAIN_CHARS[(seed + i + int(t * 3)) % len(RAIN_CHARS)], i])


def _stars(img, w, h, t, e, fg):
    color = _hex(e["color"]) if "color" in e else fg
    n, speed = int(120 * e.get("density", 0.5)), e.get("speed", 3)

    def make():
        rng = random.Random(1234)
        return [(rng.randrange(w), rng.randrange(h), 1 if i % 7 == 0 else 0) for i in range(n)]
    d = ImageDraw.Draw(img)
    for i, (x, y, s) in enumerate(_memo(("stars", w, h, n), (), make)):
        b = 0.5 + 0.5 * math.sin(t * speed + i * 1.7)
        under = img.getpixel((x, y))
        k = 0.15 + 0.75 * b
        d.rectangle((x, y, x + s, y + s), fill=tuple(int(under[j] + (color[j] - under[j]) * k) for j in range(3)))


def _rainbow(w, h, t, e):
    def make():
        hue = (np.arange(2 * w) * 255 / w) % 256
        arr = np.zeros((h, 2 * w, 3), np.uint8)
        arr[:, :, 0] = hue.astype(np.uint8)[None, :]
        arr[:, :, 1:] = 255
        return Image.fromarray(arr, "HSV").convert("RGB")
    off = int(t * e.get("speed", 2) * 40 * w / 256) % w
    return _memo(("rainbow", w, h), (), make).crop((off, 0, off + w, h))


def _text_mask(text, size, bold):
    def make():
        font = _font(size, bold)
        tw = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=font))
        m = Image.new("L", (tw + 2, size + 6), 0)
        ImageDraw.Draw(m).text((0, 1), text, font=font, fill=255)
        return m
    return _memo(("text", text, size, bold), (), make)


def _draw_text(img, line, t, default_color):
    color = _hex(line["color"]) if "color" in line else default_color
    m = _text_mask(_expand(line["text"]), line["size"], line["bold"])
    x, y = line["x"], line["y"]
    if line["scroll"]:
        sw = line["width"]
        strip = Image.new("L", (sw, m.height), 0)
        strip.paste(m, (sw - int((t * line["speed"]) % (m.width + sw)), 0))
        img.paste(color, (x, y, x + sw, y + m.height), strip)
        return
    if line["align"] == "center":
        x -= m.width // 2
    elif line["align"] == "right":
        x -= m.width
    img.paste(color, (x, y, x + m.width, y + m.height), m)


def _shade(w, h, scan, vig):
    def make():
        s = np.ones((h, 1, 1), np.float32)
        if scan:
            s[1::2] = 1 - scan
        if vig:
            xs, ys = (np.arange(w) - w / 2) / (w / 2), (np.arange(h) - h / 2) / (h / 2)
            s = s * (1 - vig * (np.sqrt(xs[None, :] ** 2 + ys[:, None] ** 2) / math.sqrt(2)) ** 2).astype(np.float32)[:, :, None]
        return s
    return _memo(("shade", w, h, scan, vig), (), make)


def _noise(w, h, n):
    def make():
        rng = np.random.default_rng(7)
        return [rng.integers(-n, n + 1, (h, w, 1)).astype(np.float32) for _ in range(6)]
    return _memo(("noise", w, h, n), (), make)


def colorize(canvas, theme, t=0.0, layers=None, face=None, bar_top=14, bar_bottom=300):
    """Turn the 1-bit pwnagotchi canvas into a themed RGB image at time t.

    layers maps UI element names to (mask, box) regions captured while the canvas was drawn."""
    w, h = canvas.size
    fx = {e["type"]: e for e in theme.get("effects", [])}
    fg, acc = _hex(theme["fg"]), _hex(theme["accent"])
    hide = layers.get("face") if (face and layers) else None
    mask, ink_region, bars = _layers(canvas, w, h, bar_top, bar_bottom, hide)
    img = _base(theme, w, h)

    if "stars" in fx:
        _stars(img, w, h, t, fx["stars"], fg)
    if "rain" in fx:
        _rain(img, w, h, t, fx["rain"], fg)

    k = 1.0
    if "pulse" in fx:
        p = fx["pulse"]
        k = 1 - p.get("strength", 0.5) * (0.5 + 0.5 * math.sin(t * p.get("speed", 3)))
    halo = None
    if "glow" in fx:
        gl = fx["glow"]
        halo = _halo(canvas, mask, gl.get("radius", 3), gl.get("strength", 0.8))
    if "rainbow" in fx:
        ink = _rainbow(w, h, t, fx["rainbow"])
        if k < 1:
            ink = ink.point(lambda v: int(v * k))
        _stamp(img, ink, halo)
        _stamp(img, ink, ink_region)
    else:
        f, a = _scale(fg, k), _scale(acc, k)
        _stamp(img, f, halo)
        _stamp(img, f, ink_region)
        if acc != fg:
            for region in bars:
                _stamp(img, a, region)

    elems = theme.get("elements")
    if elems and layers:
        for key, color in elems.items():
            region = layers.get(key)
            if region is not None and not (key == "face" and face):
                _stamp(img, _rainbow(w, h, t, {}) if color == "rainbow" else _scale(_hex(color), k), region)

    if face:
        pic, pos = face
        if theme.get("face_tint"):
            face_color = (elems or {}).get("face", theme["fg"])
            tint = _rainbow(w, h, t, {}).crop((pos[0], pos[1], pos[0] + pic.width, pos[1] + pic.height)) \
                if face_color == "rainbow" else Image.new("RGB", pic.size, _scale(_hex(face_color), k))
            img.paste(tint, pos, ImageChops.multiply(pic.convert("L"), pic.getchannel("A")))
        else:
            img.paste(pic, pos, pic)

    for line in theme.get("text", []):
        try:
            _draw_text(img, line, t, fg)
        except Exception as e:
            logging.debug("[theme_manager] text: %s", e)

    if "border" in fx:
        b = fx["border"]
        ImageDraw.Draw(img).rectangle((0, 0, w - 1, h - 1), outline=_hex(b["color"]) if "color" in b else acc,
                                      width=int(b.get("size", 2)))

    scan = fx["scanlines"].get("strength", 0.35) if "scanlines" in fx else 0
    vig = fx["vignette"].get("strength", 0.6) if "vignette" in fx else 0
    glitching = "glitch" in fx and t % fx["glitch"].get("interval", 4) < 0.25
    if not (scan or vig or "noise" in fx or glitching):
        return img

    arr = np.asarray(img, dtype=np.float32)
    if scan or vig:
        arr *= _shade(w, h, scan, vig)
    if "noise" in fx:
        arr += _noise(w, h, int(fx["noise"].get("strength", 0.3) * 30))[int(t * 8) % 6]
    np.clip(arr, 0, 255, out=arr)
    out = arr.astype(np.uint8)
    if glitching:
        rng = random.Random(int(t * 20))
        for _ in range(rng.randint(3, 6)):
            y0 = rng.randrange(h - 20)
            y1 = y0 + rng.randint(4, 20)
            out[y0:y1] = np.roll(out[y0:y1], rng.choice((-1, 1)) * rng.randint(5, 40), axis=1)
        out[:, :, 0] = np.roll(out[:, :, 0], 3, axis=1)
    return Image.fromarray(out, "RGB")


def pack_frames(pack, mood, scale=1.0):
    """[(RGBA image, milliseconds)] for <pack>/<mood>.gif|png, or None. Cached, re-read when the folder changes."""
    d = os.path.join(FACES_DIR, pack)
    try:
        stamp = os.stat(d).st_mtime
    except OSError:
        return None

    def make():
        for ext in ("gif", "png"):
            path = os.path.join(d, "%s.%s" % (mood, ext))
            if not os.path.isfile(path):
                continue
            try:
                im = Image.open(path)
                frames = []
                for i in range(min(getattr(im, "n_frames", 1), 60)):
                    im.seek(i)
                    f = im.convert("RGBA")
                    if scale != 1.0:
                        f = f.resize((max(1, int(f.width * scale)), max(1, int(f.height * scale))), Image.NEAREST)
                    frames.append((f, max(20, int(im.info.get("duration", 100)))))
                return frames
            except Exception as e:
                logging.warning("[theme_manager] face %s: %s", path, e)
        return None
    return _memo(("pack", pack, mood, scale, stamp), (), make)


def list_packs():
    out = {}
    try:
        for name in sorted(os.listdir(FACES_DIR)):
            p = os.path.join(FACES_DIR, name)
            if os.path.isdir(p) and PACK_RE.fullmatch(name):
                out[name] = sorted({os.path.splitext(f)[0] for f in os.listdir(p) if f.endswith((".png", ".gif"))})
    except OSError:
        pass
    return out


def _mood_map():
    """face string -> mood name, from pwnagotchi's current face table."""
    import pwnagotchi.ui.faces as faces
    out = {}
    for name in dir(faces):
        if name.isupper() and name not in ("PNG", "POSITION_X", "POSITION_Y"):
            v = getattr(faces, name)
            for face in (v if isinstance(v, list) else [v]):
                out.setdefault(str(face), MOOD_ALIAS.get(name.lower(), name.lower()))
    return out


def resolve(theme, mood):
    """The theme with the given mood's overrides applied."""
    m = (theme.get("mood") or {}).get(mood)
    if not m:
        return theme

    def make():
        out = dict(theme)
        for k in ("bg", "fg", "accent", "gradient"):
            if k in m:
                out[k] = m[k]
        if "elements" in m:
            out["elements"] = dict(theme.get("elements") or {}, **m["elements"])
        if "effects" in m:
            out["effects"] = list(theme.get("effects", [])) + m["effects"]
        return out
    return _memo(("resolve", id(theme), mood), (theme,), make)


def _lerp_color(a, b, k):
    if a == b or a == "rainbow" or b == "rainbow":
        return b
    x, y = _hex(a), _hex(b)
    return "#%02x%02x%02x" % tuple(int(x[i] + (y[i] - x[i]) * k) for i in range(3))


def blend(a, b, k):
    """Colors k of the way from theme a to theme b (effects and text come from b)."""
    out = dict(b)
    for c in ("bg", "fg", "accent"):
        out[c] = _lerp_color(a[c], b[c], k)
    ea, eb = a.get("elements") or {}, b.get("elements") or {}
    if ea or eb:
        out["elements"] = {key: _lerp_color(ea.get(key, a["fg"]), eb.get(key, b["fg"]), k) for key in set(ea) | set(eb)}
    out.pop("gradient", None) if not (a.get("gradient") and b.get("gradient")) else out.update(
        gradient=dict(b["gradient"], **{"from": _lerp_color(a["gradient"]["from"], b["gradient"]["from"], k),
                                        "to": _lerp_color(a["gradient"]["to"], b["gradient"]["to"], k)}))
    return out


_ROT = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}


def _body(request):
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def rotate(img, deg):
    """Rotate counterclockwise by a multiple of 90 degrees (pwnagotchi's ui.display.rotation)."""
    deg %= 360
    return img.transpose(_ROT[deg]) if deg in _ROT else img


THERMAL_SLOW_C = 75       # animation runs at half rate above this CPU temperature
THERMAL_STOP_C = 80       # ...and pauses above this one (Pi 5 starts throttling itself at 85)
TEMP_FILE = "/sys/class/thermal/thermal_zone0/temp"
GUARD_S = 30              # how often to look for a GPS device that bettercap lost


def cpu_temp(path=TEMP_FILE):
    return int(open(path).read()) / 1000.0


def heat_factor(temp, current=1.0):
    """Animation speed multiplier for a CPU temperature: 1.0 normal, 2.0 slow, None paused.
    Each state is left 3 degrees below the temperature that entered it, so it does not flap."""
    if temp >= THERMAL_STOP_C - (3 if current is None else 0):
        return None
    if temp >= THERMAL_SLOW_C - (3 if current in (2.0, None) else 0):
        return 2.0
    return 1.0


def stale_tty_owner(proc="/proc"):
    """(pid, device) if bettercap holds a /dev/tty* file that no longer exists (a GPS receiver that was unplugged
    or renumbered). Bettercap then spins on the dead handle and burns a whole CPU core, else None."""
    for entry in os.listdir(proc):
        if not entry.isdigit():
            continue
        try:
            if open("%s/%s/comm" % (proc, entry)).read().strip() != "bettercap":
                continue
            for fd in os.listdir("%s/%s/fd" % (proc, entry)):
                target = os.readlink("%s/%s/fd/%s" % (proc, entry, fd))
                if target.startswith("/dev/tty") and target.endswith(" (deleted)"):
                    return int(entry), target[:-len(" (deleted)")]
        except OSError:
            continue
    return None


def frame_interval(theme, t):
    """Seconds until the next animation frame is worth drawing."""
    fx = {e["type"]: e for e in theme.get("effects", [])}
    if CONTINUOUS & fx.keys() or _rainbow_elements(theme) or any(l["scroll"] for l in theme.get("text", [])):
        iv = 1.0 / theme.get("fps", 5)
    else:
        iv = 1.0  # only live text (clock etc.) changes
        if "glitch" in fx:
            gi = fx["glitch"].get("interval", 4)
            ph = t % gi
            iv = 0.06 if ph < 0.25 else min(1.0, gi - ph)
    try:
        if os.getloadavg()[0] > 3.5:  # back off when the Pi is busy
            iv *= 2
    except OSError:
        pass
    return iv


# ------------------------------------------------------------------ touch menu
# Double tap on the screen opens a theme menu. The touch controller reports raw numbers, so the first time a
# 4-point calibration maps them to screen pixels (saved in touch.json).
TOUCH_FILE = os.path.join(THEME_DIR, "touch.json")
EVENT = struct.Struct("@llHHi")            # struct input_event on 64-bit Linux (24 bytes)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BTN_TOUCH, ABS_X, ABS_Y = 0x14A, 0, 1
DOUBLE_TAP_S = 0.6        # max time between the two taps
DOUBLE_TAP_RAW = 900      # max distance between them, in raw units (range is 0-4095)
TAP_MAX_S = 0.8           # longer presses are not taps
MENU_TIMEOUT = 20.0
CALIB_TIMEOUT = 60.0
CALIB_POINTS = ((40, 40), (440, 40), (40, 280), (440, 280))
MENU_ROWS = 5
CONFIRM_S = 4.0          # a power button must be tapped twice within this time
GPS_TOKENS = ("gps", "lat", "lon", "sats")
STATUS_LINES = ("CPU {temp}  load {cpu}  RAM {mem}", "IP {ip}", "GPS {gps}  {lat} {lon}",
                "Up {uptime}  Power {power}  Bat {battery}", "Pwned {handshakes}  Cracked {cracked}  Session {session}")
TABS = (("themes", (28, 10, 138, 38)), ("plugins", (144, 10, 254, 38)), ("system", (260, 10, 370, 38)))
PROTECTED_PLUGINS = ('theme_manager',)   # never listed: switching it off would remove the menu itself


@contextlib.contextmanager
def config_save_guard():
    """pwnagotchi's toggle_plugin rewrites config.toml from memory. Keep `personality.channels` as it is on disk, so
    the channels the agent discovered at runtime don't get frozen into the file."""
    import pwnagotchi.utils as u
    orig = u.save_config

    def guarded(config, target):
        cur = None
        try:
            import tomllib
            with open(target, "rb") as fp:
                disk = tomllib.load(fp)["personality"]["channels"]
            cur = config["personality"]["channels"]
            config["personality"]["channels"] = disk
        except Exception:
            cur = None
        try:
            return orig(config, target)
        finally:
            if cur is not None:
                config["personality"]["channels"] = cur
    u.save_config = guarded
    try:
        yield
    finally:
        u.save_config = orig


def find_touch_device(hint="ads7846"):
    """/dev/input/eventN of the touchscreen, or None."""
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return None
    for want in (hint, "touch"):
        for b in blocks:
            name = re.search(r'Name="([^"]*)"', b)
            ev = re.search(r"Handlers=.*?\b(event\d+)\b", b)
            if name and ev and want in name.group(1).lower():
                return "/dev/input/" + ev.group(1)
    return None


def fit_affine(raw, screen):
    """Least-squares affine map from raw touch points to screen points: ([a,b,c], [d,e,f]) and the worst error in px."""
    A = np.array([[x, y, 1.0] for x, y in raw])
    cx, *_ = np.linalg.lstsq(A, np.array([p[0] for p in screen], float), rcond=None)
    cy, *_ = np.linalg.lstsq(A, np.array([p[1] for p in screen], float), rcond=None)
    err = max(math.hypot(A[i] @ cx - screen[i][0], A[i] @ cy - screen[i][1]) for i in range(len(raw)))
    return [list(map(float, cx)), list(map(float, cy))], float(err)


def to_screen(m, x, y):
    return int(m[0][0] * x + m[0][1] * y + m[0][2]), int(m[1][0] * x + m[1][1] * y + m[1][2])


def menu_items(menu):
    return menu["names"] if menu.get("tab", "themes") == "themes" else menu["plugins"]


def menu_hits(menu):
    """[(rect, (action, arg))] for the current menu page, in upright screen pixels."""
    tab, page = menu.get("tab", "themes"), menu["page"]
    tabs = [(rect, ("tab", name)) for name, rect in TABS]
    common = [((220, 268, 320, 308), ("cal", None)), ((380, 268, 452, 308), ("close", None))] + tabs
    if tab == "system":
        return [((28, 268, 118, 308), ("refresh", None)), ((28, 166, 452, 200), ("mode", None)), ((28, 208, 152, 248), ("power", "restart")),
                ((158, 208, 282, 248), ("power", "reboot")), ((288, 208, 412, 248), ("power", "shutdown"))] + common
    act = "pick" if tab == "themes" else "toggle"
    hits = [((28, 44 + i * 44, 452, 44 + i * 44 + 40), (act, n))
            for i, n in enumerate(menu_items(menu)[page * MENU_ROWS:(page + 1) * MENU_ROWS])]
    return hits + [((28, 268, 118, 308), ("prev", None)), ((124, 268, 214, 308), ("next", None))] + common


def _mixc(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def draw_menu(img, menu, theme):
    """Draw the menu (or the calibration prompt) onto an upright RGB frame."""
    d = ImageDraw.Draw(img)
    bg, fg, acc = _hex(theme["bg"]), _hex(theme["fg"]), _hex(theme["accent"])
    panel, line = _mixc(bg, (0, 0, 0), 0.35), _mixc(bg, fg, 0.18)
    d.rectangle((16, 8, 464, 312), fill=panel, outline=acc, width=2)
    if menu["mode"] == "calib":
        i = menu["step"]
        d.text((240, 60), "Touch calibration", font=_font(22, True), fill=fg, anchor="mm")
        d.text((240, 100), "tap the + mark (%d/%d)" % (i + 1, len(CALIB_POINTS)), font=_font(16), fill=fg, anchor="mm")
        if menu.get("msg"):
            d.text((240, 140), menu["msg"], font=_font(14), fill=acc, anchor="mm")
        x, y = CALIB_POINTS[i]
        d.line((x - 16, y, x + 16, y), fill=acc, width=3)
        d.line((x, y - 16, x, y + 16), fill=acc, width=3)
        d.ellipse((x - 9, y - 9, x + 9, y + 9), outline=fg, width=2)
        return
    tab, page = menu.get("tab", "themes"), menu["page"]
    pages = max(1, -(-len(menu_items(menu)) // MENU_ROWS))
    if tab != "system":
        d.text((452, 16), "%d/%d" % (page + 1, pages), font=_font(14), fill=fg, anchor="ra")
    else:
        for i, text in enumerate(menu.get("lines", ())):
            d.text((32, 46 + i * 24), text, font=_font(16), fill=fg)
    for rect, (act, arg) in menu_hits(menu):
        x0, y0, x1, y1 = rect
        if act in ("mode", "power"):
            key = "mode" if act == "mode" else arg
            ask = bool(menu.get("confirm")) and menu["confirm"][0] == key
            other = "AUTO" if menu.get("mode_now") == "MANU" else "MANU"
            if act == "mode":
                label = "tap again: restart in %s" % other if ask else "Mode: %s  (tap to switch)" % menu.get("mode_now", "?")
            else:
                label = "tap again" if ask else arg
            d.rounded_rectangle(rect, 8, fill=acc if ask else line, outline=acc, width=2)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), label, font=_font(16, True), fill=bg if ask else fg, anchor="mm")
        elif act == "tab":
            on = arg == tab
            d.rectangle(rect, fill=acc if on else line, outline=acc, width=1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), arg.capitalize(), font=_font(16, True),
                   fill=bg if on else fg, anchor="mm")
        elif act == "pick":
            cur = arg == menu["active"]
            d.rectangle(rect, fill=line, outline=acc if cur else line, width=2)
            d.text((x0 + 12, (y0 + y1) // 2), ("\u25CF " if cur else "") + arg, font=_font(20, cur), fill=fg, anchor="lm")
            for j, key in enumerate(("bg", "fg", "accent")):
                sx = x1 - 78 + j * 24
                d.rectangle((sx, y0 + 10, sx + 18, y1 - 10), fill=_hex(menu["colors"][arg][key]), outline=fg)
        elif act == "toggle":
            busy, on, bad = arg in menu["busy"], arg in menu["on"], arg in menu.get("failed", ())
            d.rectangle(rect, fill=line, outline=acc if on else line, width=2)
            d.text((x0 + 12, (y0 + y1) // 2), arg if len(arg) <= 22 else arg[:21] + "\u2026", font=_font(20, on), fill=fg, anchor="lm")
            px0, px1 = x1 - 82, x1 - 10
            d.rounded_rectangle((px0, y0 + 7, px1, y1 - 7), 10, fill=acc if on and not busy else panel, outline=acc, width=2)
            d.text(((px0 + px1) // 2, (y0 + y1) // 2), "..." if busy else ("ERR" if bad else "ON" if on else "OFF"), font=_font(16, True),
                   fill=bg if on and not busy else fg, anchor="mm")
        else:
            label = {"prev": "<", "next": ">", "cal": "calibrate", "close": "close", "refresh": "refresh"}[act]
            d.rectangle(rect, fill=line, outline=acc, width=1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), label, font=_font(16, True), fill=fg, anchor="mm")


# --------------------------------------------------------------------- plugin
class ThemeManager(plugins.Plugin):
    __author__ = "theme_manager contributors"
    __version__ = "2.1.0"
    __license__ = "GPL3"
    __description__ = "Theme engine for the 3.5 inch display: colors, effects, animations, custom text, web GUI."

    def __init__(self):
        self._lock = threading.Lock()
        self._install_lock = threading.Lock()
        self._render_lock = threading.Lock()
        self._view = None
        self._display = None
        self._orig_render = None
        self._orig_clear = None
        self._running = False
        self._ctx = None
        self._wake = threading.Event()
        self._menu = None
        self._menu_lock = threading.Lock()
        self._gps = None
        self._gps_wanted = 0
        self._heat = 1.0
        self._next_temp = 0
        self._next_guard = 0
        self._gps_waiting = None
        self._gps_evt = threading.Event()
        self._touch_m = None
        self._last_tap = None
        self._down = None
        self._abs = [None, None]
        self._last_trim = 0
        self._face_multi = False
        self._mood = None
        self._mood_base = None
        self._mood_theme = None
        self._trans = None
        self._event_until = 0
        self._force = (None, 0)
        self._force_mtime = 0
        self._building = {"layers": {}, "face": None}
        self._wrapped = []
        self._prev = None
        self._rot = 0
        self._full_at = 0
        self._fast = False
        self._active = "default"
        self._theme = _clean(BUILTIN["default"])
        self._mtime = 0
        self._last_check = 0
        self._orig_faces = {}

    # ---- storage
    def _user_themes(self):
        themes = {}
        if os.path.isdir(THEME_DIR):
            for f in sorted(os.listdir(THEME_DIR)):
                if f.endswith(".json") and f not in STATE_FILES:
                    try:
                        with open(os.path.join(THEME_DIR, f)) as fp:
                            themes[f[:-5]] = _clean(json.load(fp))
                    except Exception as e:
                        logging.warning("[theme_manager] bad theme %s: %s", f, e)
        return themes

    def _all(self):
        t = {k: dict(_clean(v), builtin=True) for k, v in BUILTIN.items()}
        t.update(self._user_themes())
        return t

    def _save_active(self, name):
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(ACTIVE_FILE, {"active": name})
        self._mtime = os.path.getmtime(ACTIVE_FILE)

    # ---- applying
    def _apply(self, name, persist=False):
        themes = self._all()
        if name not in themes:
            raise KeyError(name)
        theme = _clean(themes[name])
        with self._lock:
            self._active = name
            self._theme = theme
            self._trans = None
            self._mood = None
        self._apply_web(theme)
        self._apply_faces(theme)
        if persist:
            self._save_active(name)
        if self._view:
            try:
                self._view.update(force=True)
            except Exception as e:
                logging.debug("[theme_manager] refresh failed: %s", e)
        logging.info("[theme_manager] theme -> %s", name)

    def _apply_web(self, theme):
        try:
            import pwnagotchi
            r, g, b = _hex(theme["web"])
            web = pwnagotchi.config["ui"]["web"]
            web.setdefault("theme", {})
            web["theme"]["accent_r"], web["theme"]["accent_g"], web["theme"]["accent_b"] = r, g, b
        except Exception as e:
            logging.debug("[theme_manager] web accent: %s", e)

    def _apply_faces(self, theme):
        import pwnagotchi.ui.faces as faces
        for k, v in self._orig_faces.items():
            setattr(faces, k, v)
        for k, v in (theme.get("faces") or {}).items():
            if hasattr(faces, k):
                self._orig_faces.setdefault(k, getattr(faces, k))
                setattr(faces, k, v)

    def _poll_files(self):
        now = time.time()
        if now - self._last_check < 1:
            return
        self._last_check = now
        try:
            m = os.path.getmtime(FORCE_FILE)
            if m != self._force_mtime:
                with open(FORCE_FILE) as fp:
                    f = json.load(fp)
                self._force_mtime = m
                mood = f.get("mood")
                self._force = (mood if mood in MOODS else None, float(f.get("until", 0)))
                self._wake.set()
        except (FileNotFoundError, ValueError, OSError):
            pass
        try:
            m = os.path.getmtime(ACTIVE_FILE)
            if m != self._mtime:
                with open(ACTIVE_FILE) as fp:
                    name = json.load(fp).get("active")
                self._mtime = m
                if name and name != self._active:
                    self._apply(name)
        except (FileNotFoundError, ValueError):
            pass  # missing, or caught mid-write: try again on the next tick
        except Exception as e:
            logging.warning("[theme_manager] poll: %s", e)

    # ---- animation
    # ---- element capture
    def _wrap_elements(self, ui):
        """Wrap each UI element's draw() so we learn which pixels belong to it."""
        try:
            items = list(ui._state.items())
        except Exception:
            return
        mgr = self
        for key, elem in items:
            if getattr(elem, "_tm_wrapped", False) or not callable(getattr(elem, "draw", None)):
                continue

            def wrapped(canvas, drawer, _orig=elem.draw, _key=key, _elem=elem):
                if canvas.mode != "1":
                    return _orig(canvas, drawer)
                before = canvas.copy()
                _orig(canvas, drawer)
                try:
                    changed = ImageChops.logical_and(ImageChops.logical_xor(before, canvas), canvas)
                    box = changed.getbbox()
                    if box:
                        mgr._building["layers"][_key] = (changed.crop(box).convert("L"), box)
                    if _key == "face":
                        mgr._building["face"] = (_elem.value, tuple(_elem.xy))
                except Exception as e:
                    logging.debug("[theme_manager] capture %s: %s", _key, e)

            elem.draw = wrapped
            elem._tm_wrapped = True
            self._wrapped.append(elem)

    def _on_frame(self, canvas):
        """Runs synchronously at the end of every UI draw pass: publish what the elements drew."""
        done, self._building = self._building, {"layers": {}, "face": None}
        done["canvas"] = canvas
        self._ctx = done
        if self._view is not None:
            self._wrap_elements(self._view)

    def current_mood(self, t):
        forced, until = self._force
        if forced and t < until:
            return forced
        if t < self._event_until:
            return "handshake"
        ctx = self._ctx
        face = ctx["face"] if ctx else None
        return _mood_map().get(str(face[0])) if face else None

    def _current(self, t):
        """The theme to draw right now: base theme + mood overrides, blended while the mood changes."""
        with self._lock:
            base = self._theme
        if not base.get("mood"):
            return base
        mood = self.current_mood(t)
        target = resolve(base, mood)
        if self._mood_base is not base:
            self._mood_base, self._mood_theme, self._mood, self._trans = base, target, mood, None
        elif mood != self._mood:
            self._trans = (self._mood_theme if self._trans is None else self._trans_now(t), target, t)
            self._mood = mood
            self._wake.set()
        self._mood_theme = target
        return self._trans_now(t) if self._trans else target

    def _trans_now(self, t):
        a, b, t0 = self._trans
        k = (t - t0) / MOOD_FADE
        if k >= 1:
            self._trans = None
            return b
        return blend(a, b, k)

    def face_mood(self, t, override=None):
        """Mood used to pick a face image (ignores the handshake flash, which has no face of its own)."""
        if override:
            return None if override == "handshake" else override
        forced, until = self._force
        if forced and t < until and forced != "handshake":
            return forced
        ctx = self._ctx
        face = ctx["face"] if ctx else None
        return _mood_map().get(str(face[0])) if face else None

    def _face_frame(self, theme, t, mood=None):
        """(image, position) for the theme's face pack at time t, or None to keep the drawn text face."""
        pack = theme.get("face_pack")
        ctx = self._ctx
        if not pack or not ctx or not ctx["face"]:
            self._face_multi = False
            return None
        scale = theme.get("face_scale", 1.0)
        frames = pack_frames(pack, self.face_mood(t, mood) or "default", scale) or pack_frames(pack, "default", scale)
        if not frames:
            self._face_multi = False
            return None
        self._face_multi = len(frames) > 1
        if self._face_multi:
            total = sum(ms for _, ms in frames)
            pos_ms = int(t * 1000) % total
            for pic, ms in frames:
                if pos_ms < ms:
                    break
                pos_ms -= ms
        else:
            pic = frames[0][0]
        off = theme.get("face_offset", (0, 0))
        x, y = ctx["face"][1]
        return pic, (int(x + off[0]), int(y + off[1]))

    def _compose(self, t, theme=None):
        """Themed, panel-rotated frame for the latest UI state, or None before the first frame."""
        ctx = self._ctx
        if ctx is None:
            return None
        theme = theme or self._current(t)
        img = colorize(ctx["canvas"], theme, t, ctx["layers"], self._face_frame(theme, t))
        menu = self._menu
        if menu is not None:
            if menu.get("tab") == "system" and menu["mode"] == "list":
                self._fill_status(menu)
            draw_menu(img, menu, self._theme)
        return rotate(img, self._rot)

    def _present(self, img):
        """Write a frame to the framebuffer, sending only the rows that changed."""
        fbm = self._display._display
        if not self._fast:
            fbm.show_img(img)
            return
        a = np.asarray(img)
        r, g, b = (a[:, :, i].astype(np.uint16) for i in range(3))
        v = (b >> 3 << 11 | g >> 2 << 5 | r >> 3) if fbm.RGB else (r >> 3 << 11 | g >> 2 << 5 | b >> 3)
        now = time.time()
        prev = self._prev
        if prev is not None and prev.shape == v.shape and now - self._full_at < 60:
            rows = np.flatnonzero((v != prev).any(axis=1))
            if rows.size == 0:
                return
            r0, r1 = int(rows[0]), int(rows[-1]) + 1
        else:
            r0, r1 = 0, v.shape[0]
            self._full_at = now
        fbm.mm.seek(r0 * fbm.w * 2)
        fbm.mm.write(v[r0:r1].astype("<u2").tobytes())
        self._prev = v

    # ---- touch
    def _load_touch(self):
        try:
            with open(TOUCH_FILE) as fp:
                m = json.load(fp)["matrix"]
            if len(m) == 2 and all(len(r) == 3 for r in m):
                self._touch_m = m
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._touch_m = None

    def _refresh_now(self):
        """Redraw the screen right away (menu opened/changed/closed)."""
        try:
            img = self._compose(time.time())
            if img is not None:
                with self._render_lock:
                    self._present(img)
        except Exception as e:
            logging.error("[theme_manager] menu redraw: %s", e)

    def _plugin_names(self):
        try:
            return sorted(n for n in plugins.database if n not in PROTECTED_PLUGINS)
        except Exception:
            return []

    def open_menu(self, mode=None, tab="themes"):
        now = time.time()
        self._load_touch()
        if mode is None:
            mode = "list" if self._touch_m else "calib"
        themes = self._all()
        with self._menu_lock:
            self._menu = {"mode": mode, "tab": tab if tab in ("themes", "plugins", "system") else "themes", "page": 0,
                          "pages": {"themes": 0, "plugins": 0, "system": 0}, "confirm": None, "plugins": self._plugin_names(),
                          "on": set(plugins.loaded), "busy": set(), "failed": set(), "step": 0, "raw": [], "names": list(themes),
                          "colors": {n: t for n, t in themes.items()}, "active": self._active,
                          "until": now + (CALIB_TIMEOUT if mode == "calib" else MENU_TIMEOUT)}
        self._wake.set()
        self._refresh_now()

    def close_menu(self):
        with self._menu_lock:
            self._menu = None
        self._refresh_now()

    def menu_tick(self, now):
        m = self._menu
        if m is not None and now > m["until"]:
            self.close_menu()
        elif m is not None and m.get("confirm") and now > m["confirm"][1]:
            m["confirm"] = None
            self._refresh_now()

    def on_tap(self, rx, ry, now):
        """A finished tap at raw touch coordinates."""
        menu = self._menu
        if menu is None:
            last = self._last_tap
            if last and now - last[0] <= DOUBLE_TAP_S and abs(rx - last[1]) + abs(ry - last[2]) < DOUBLE_TAP_RAW:
                self._last_tap = None
                logging.info("[theme_manager] double tap: opening the theme menu")
                self.open_menu()
            else:
                self._last_tap = (now, rx, ry)
            return
        if menu["mode"] == "calib":
            menu["raw"].append((rx, ry))
            menu["until"] = now + CALIB_TIMEOUT
            if len(menu["raw"]) < len(CALIB_POINTS):
                menu["step"] = len(menu["raw"])
                menu.pop("msg", None)
            else:
                m, err = fit_affine(menu["raw"], CALIB_POINTS)
                if err > 40:
                    logging.warning("[theme_manager] calibration rejected (error %.0f px)", err)
                    menu.update(step=0, raw=[], msg="that did not fit, try again")
                else:
                    write_json(TOUCH_FILE, {"matrix": m, "error_px": round(err, 1)})
                    logging.info("[theme_manager] touch calibrated (error %.1f px)", err)
                    self._touch_m = m
                    menu.update(mode="list", page=0)
                    menu["until"] = now + MENU_TIMEOUT
            self._refresh_now()
            return
        if self._touch_m is None:
            return
        x, y = to_screen(self._touch_m, rx, ry)
        menu["until"] = now + MENU_TIMEOUT
        for (x0, y0, x1, y1), (act, arg) in menu_hits(menu):
            if x0 <= x <= x1 and y0 <= y <= y1:
                pages = max(1, -(-len(menu_items(menu)) // MENU_ROWS))
                if act not in ("power", "mode"):
                    menu["confirm"] = None
                if act == "tab":
                    menu["pages"][menu["tab"]] = menu["page"]
                    menu["tab"] = arg
                    menu["page"] = menu["pages"][arg]
                elif act in ("power", "mode"):
                    key = "mode" if act == "mode" else arg
                    ask = menu.get("confirm")
                    if ask and ask[0] == key and now <= ask[1]:
                        menu["confirm"] = None
                        self._do_system(key)
                        return
                    menu["confirm"] = (key, now + CONFIRM_S)
                elif act == "toggle":
                    if arg not in menu["busy"]:
                        menu["busy"].add(arg)
                        threading.Thread(target=self._toggle_plugin, args=(arg, menu), daemon=True, name="theme-toggle").start()
                elif act == "pick":
                    self.close_menu()
                    try:
                        self._apply(arg, persist=True)
                    except KeyError:
                        pass
                    return
                elif act == "prev":
                    menu["page"] = (menu["page"] - 1) % pages
                elif act == "next":
                    menu["page"] = (menu["page"] + 1) % pages
                elif act == "refresh":
                    self.refresh_screen()
                    return
                elif act == "cal":
                    menu.update(mode="calib", step=0, raw=[])
                    menu["until"] = now + CALIB_TIMEOUT
                else:
                    self.close_menu()
                    return
                self._refresh_now()
                return
        menu["confirm"] = None
        if not (16 <= x <= 464 and 8 <= y <= 312):   # a tap outside the panel closes it
            self.close_menu()

    def refresh_screen(self):
        """Force a full redraw: flash the panel black, forget what we think is on it (so every row is written again,
        which clears a garbled or stuck display) and rebuild the UI frame."""
        self._prev = None
        self._full_at = 0
        try:
            with self._render_lock:
                self._display._display.black_scr()
        except Exception as e:
            logging.debug("[theme_manager] refresh: %s", e)
        try:
            if self._view:
                self._view.update(force=True)
        except Exception as e:
            logging.debug("[theme_manager] refresh: %s", e)
        self._refresh_now()
        logging.info("[theme_manager] screen refreshed from the touch menu")

    # ---- guard: keep the Pi cool
    def _guard_tick(self, now):
        if now >= self._next_temp:
            self._next_temp = now + 5
            try:
                temp = cpu_temp()
            except (OSError, ValueError):
                temp = None
            if temp is not None:
                new = heat_factor(temp, self._heat)
                if new != self._heat:
                    logging.warning("[theme_manager] CPU at %.0f C: animation %s", temp,
                                    "paused" if new is None else "slowed down" if new > 1 else "back to normal")
                    self._heat = new
                    self._wake.set()
        if now >= self._next_guard:
            self._next_guard = now + GUARD_S
            try:
                self._check_gps()
            except Exception as e:
                logging.debug("[theme_manager] gps guard: %s", e)

    def _gps_options(self):
        try:
            import pwnagotchi
            opts = pwnagotchi.config["main"]["plugins"]["gps"]
            return (opts["device"], opts.get("speed", 19200)) if opts.get("enabled") else None
        except Exception:
            return None

    def _bettercap(self, *commands):
        agent = getattr(self._view, "_agent", None)
        if agent is None:
            return False
        for cmd in commands:
            try:
                agent.run(cmd)
            except Exception:
                if cmd != "gps off":          # "module gps is not running" is fine when switching it off
                    raise
        return True

    def _reopen_gps(self, device, speed):
        self._bettercap("gps off", "set gps.device %s" % device, "set gps.baudrate %s" % speed, "gps on")
        self._gps_waiting = None
        logging.info("[theme_manager] bettercap's GPS module reopened %s", device)

    def _check_gps(self):
        """A GPS receiver that is unplugged or renumbered leaves bettercap spinning on a dead file handle, using a whole
        CPU core (and heating the Pi). Reset its GPS module, and bring it back when the device is there again."""
        opts = self._gps_options()
        if self._gps_waiting and opts and os.path.exists(opts[0]):
            self._reopen_gps(*opts)
            return
        if self._gps_waiting:
            return
        stale = stale_tty_owner()
        if not stale:
            return
        logging.warning("[theme_manager] bettercap holds a GPS device that no longer exists (%s): resetting its GPS module", stale[1])
        if opts and os.path.exists(opts[0]):
            self._reopen_gps(*opts)
            return
        self._bettercap("gps off")
        if opts:
            self._gps_waiting = True
            logging.warning("[theme_manager] GPS device %s is not there: GPS stays off until it is plugged in again", opts[0])

    def _agent_mode(self):
        try:
            return "MANU" if self._view._agent.mode == "manual" else "AUTO"
        except Exception:
            return "AUTO"

    def _fill_status(self, menu):
        menu["lines"] = [_expand(t) for t in STATUS_LINES]
        menu["mode_now"] = self._agent_mode()

    def _do_system(self, key):
        """restart / reboot / shutdown / switch mode: the same pwnagotchi calls the web UI makes, run off the touch thread."""
        import pwnagotchi
        mode = self._agent_mode()
        # restart_bettercap=False: restarting only pwnagotchi is enough, and bettercap's restart reloads the Wi-Fi driver
        actions = {"restart": (pwnagotchi.restart, (mode, False)), "reboot": (pwnagotchi.reboot, ()),
                   "shutdown": (pwnagotchi.shutdown, ()),
                   "mode": (pwnagotchi.restart, ("AUTO" if mode == "MANU" else "MANU", False))}
        fn, args = actions[key]
        logging.warning("[theme_manager] touch menu: %s%s", key, " -> " + args[0] if args else "")
        self.close_menu()
        threading.Thread(target=fn, args=args, daemon=True, name="theme-system").start()

    def _live_stat(self, key):
        """Placeholder values that need pwnagotchi's live state (see _Lazy)."""
        if key in GPS_TOKENS:
            now = time.time()
            if now - self._gps_wanted > 30:
                self._gps_evt.set()          # nobody asked for a while: refresh right away
            self._gps_wanted = now
            g = self._gps
            if g is None:
                return {"gps": "n/a"}.get(key, "-")
            try:
                lat, lon = float(g.get("Latitude") or 0), float(g.get("Longitude") or 0)
            except (TypeError, ValueError):
                lat = lon = 0.0
            try:
                sats = int(g.get("NumSatellites") or 0)
            except (TypeError, ValueError):
                sats = 0
            fix = bool(lat or lon) and str(g.get("FixQuality", "1")) not in ("0", "")
            if key == "gps":
                return "FIX %dsat" % sats if fix else "no fix"
            if key == "sats":
                return str(sats)
            return "%.5f" % (lat if key == "lat" else lon) if fix else "-"
        if key == "session":
            m = re.match(r"\s*(\d+)", str(self._view.get("shakes") or "")) if self._view else None
            return m.group(1) if m else "0"
        if key == "mode":
            return self._agent_mode()
        return None

    def _gps_loop(self):
        while self._running:
            if time.time() - self._gps_wanted < 60:
                try:
                    sess = self._view._agent.session()
                    self._gps = sess.get("gps") if isinstance(sess, dict) else None
                except Exception:
                    self._gps = None
                    self._gps_evt.wait(25)
            self._gps_evt.wait(5)
            self._gps_evt.clear()

    def _forget_enabled(self, name):
        """toggle_plugin marks a plugin enabled before loading it. If it could not load, don't leave that in config.toml."""
        try:
            import pwnagotchi
            from pwnagotchi.utils import save_config
            if pwnagotchi.config and name in pwnagotchi.config["main"]["plugins"]:
                pwnagotchi.config["main"]["plugins"][name]["enabled"] = False
                with config_save_guard():
                    import pwnagotchi.utils as u
                    u.save_config(pwnagotchi.config, "/etc/pwnagotchi/config.toml")
        except Exception as e:
            logging.debug("[theme_manager] could not reset %s in the config: %s", name, e)

    def _toggle_plugin(self, name, menu):
        """Enable/disable one plugin like the web UI does (persisted), off the touch thread because enabling takes seconds."""
        self._refresh_now()
        try:
            want = name not in plugins.loaded
            with config_save_guard():
                plugins.toggle_plugin(name, want)
            logging.info("[theme_manager] plugin %s %s from the touch menu", name, "enabled" if want else "disabled")
            menu["failed"].discard(name)
        except Exception as e:
            logging.error("[theme_manager] toggling %s failed: %s", name, e)
            menu["failed"].add(name)
            if want:
                self._forget_enabled(name)
        finally:
            menu["on"] = set(plugins.loaded)
            menu["busy"].discard(name)
            menu["until"] = time.time() + MENU_TIMEOUT
            self._refresh_now()

    def feed(self, etype, code, value, now):
        """One input event from the touch controller."""
        if etype == EV_ABS and code in (ABS_X, ABS_Y):
            self._abs[code] = value
        elif etype == EV_KEY and code == BTN_TOUCH:
            if value:
                self._down = (now, [])
            elif self._down:
                t0, samples = self._down
                self._down = None
                if samples and now - t0 <= TAP_MAX_S:
                    xs, ys = sorted(p[0] for p in samples), sorted(p[1] for p in samples)
                    self.on_tap(xs[len(xs) // 2], ys[len(ys) // 2], now)
        elif etype == EV_SYN and self._down and None not in self._abs:
            self._down[1].append(tuple(self._abs))

    def _touch_loop(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            logging.warning("[theme_manager] touch device %s: %s", path, e)
            return
        logging.info("[theme_manager] touch menu ready on %s (double tap the screen)", path)
        try:
            buf = b""
            while self._running:
                if not select.select([fd], [], [], 1.0)[0]:
                    continue
                buf += os.read(fd, EVENT.size * 32)
                while len(buf) >= EVENT.size:
                    _, _, etype, code, value = EVENT.unpack(buf[:EVENT.size])
                    buf = buf[EVENT.size:]
                    try:
                        self.feed(etype, code, value, time.time())
                    except Exception as e:
                        logging.error("[theme_manager] touch: %s", e)
        except OSError as e:
            logging.warning("[theme_manager] touch reader stopped: %s", e)
        finally:
            os.close(fd)

    def _anim_loop(self):
        while self._running:
            start = time.time()
            self._poll_files()
            self.menu_tick(start)
            self._guard_tick(start)
            if start - self._last_trim > 20:
                self._last_trim = start
                trim_memory()
            theme = self._current(start)
            busy = self._trans is not None or start < self._event_until + 0.3 or start < self._force[1] + 0.3
            m = self._menu
            live_menu = m is not None and m.get("tab") == "system" and m["mode"] == "list"
            animate = busy or live_menu or self._face_multi or is_animated(theme)
            if self._heat is None and not live_menu:      # too hot: only redraw when the UI itself changes
                animate = False
            if self._ctx is None or not animate:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            try:
                img = self._compose(start, theme)
                with self._render_lock:
                    self._present(img)
            except Exception as e:
                logging.error("[theme_manager] animation: %s", e)
                time.sleep(2)
            iv = 0.05 if busy else frame_interval(theme, start)
            if self._face_multi and not busy:
                iv = min(iv, 0.1)
            if live_menu and not busy:
                iv = min(iv, 1.0)
            iv *= self._heat or 1.0
            time.sleep(min(1.0, max(0.03, iv - (time.time() - start))))

    # ---- hooks
    def on_loaded(self):
        try:
            with open(ACTIVE_FILE) as fp:
                name = json.load(fp).get("active", "default")
            self._mtime = os.path.getmtime(ACTIVE_FILE)
            themes = self._all()
            if name in themes:
                self._active = name
                self._theme = _clean(themes[name])
        except Exception:
            pass
        logging.info("[theme_manager] loaded, theme=%s", self._active)
        self._install_live()

    def on_display_setup(self, display):
        self._install(display)

    def _install_live(self):
        """Enabled from the web UI while pwnagotchi is running: attach to the existing display and UI."""
        try:
            from pwnagotchi.ui import view
            ui = getattr(view, "ROOT", None)
            impl = getattr(ui, "_implementation", None)
            if ui is not None and impl is not None and self._display is None:
                self.on_ui_setup(ui)
                self._install(impl)
                if self._view:
                    self._view.update(force=True)
        except Exception as e:
            logging.warning("[theme_manager] live install failed: %s", e)

    def _install(self, display):
        with self._install_lock:
            self._install_locked(display)

    def _install_locked(self, display):
        if self._display is display:
            return
        if getattr(display, "name", "") != "waveshare35lcd":
            logging.warning("[theme_manager] display %s is not waveshare35lcd, skipping",
                            getattr(display, "name", "?"))
            return
        self._display = display
        self._orig_render = orig = display.render
        self._orig_clear = display.clear
        mgr = self

        try:
            import pwnagotchi
            rot = int(pwnagotchi.config["ui"]["display"].get("rotation", 0)) % 360
            self._rot = rot if rot in (0, 90, 180, 270) else 0
        except Exception:
            self._rot = 0

        def themed_render(canvas):
            # pwnagotchi hands us the canvas already rotated for the panel; theme it upright, then rotate back
            try:
                img = mgr._compose(time.time())
                if img is None:
                    with mgr._lock:
                        theme = mgr._theme
                    img = rotate(colorize(rotate(canvas, -mgr._rot), theme, time.time()), mgr._rot)
            except Exception as e:
                logging.error("[theme_manager] colorize failed: %s", e)
                img = canvas.convert("RGB")
            with mgr._render_lock:
                mgr._present(img)

        def themed_clear():
            mgr._prev = None
            return orig_clear()

        fbm = display._display
        self._fast = (getattr(fbm, "bpp", 0) == 16 and fbm.vx == 0 and fbm.vy == 0
                      and fbm.vw == fbm.w and fbm.vh <= fbm.h)
        logging.info("[theme_manager] fast framebuffer path: %s", self._fast)
        orig_clear = display.clear
        display.clear = themed_clear
        display.render = themed_render
        self._apply_web(self._theme)
        self._apply_faces(self._theme)
        self._running = True
        threading.Thread(target=self._anim_loop, daemon=True, name="theme-anim").start()
        global STAT_SOURCE
        STAT_SOURCE = self._live_stat
        threading.Thread(target=self._gps_loop, daemon=True, name="theme-gps").start()
        dev = find_touch_device()
        if dev:
            self._load_touch()
            threading.Thread(target=self._touch_loop, args=(dev,), daemon=True, name="theme-touch").start()
        else:
            logging.info("[theme_manager] no touchscreen found, touch menu disabled")

    def on_ui_setup(self, ui):
        self._view = ui
        if self._on_frame not in ui._render_cbs:
            ui._render_cbs.insert(0, self._on_frame)  # must run before the display's own callback
        self._wrap_elements(ui)

    def on_ui_update(self, ui):
        self._view = ui

    def on_handshake(self, agent, filename, access_point, *args):
        self._event_until = time.time() + HANDSHAKE_FLASH
        self._wake.set()

    def on_unload(self, ui):
        self._running = False
        for elem in self._wrapped:
            try:
                del elem.draw
                del elem._tm_wrapped
            except AttributeError:
                pass
        self._wrapped = []
        self._menu = None
        self._ctx = self._building = self._prev = None  # drop references to frames and framebuffer copies
        with _cache_lock:
            _cache.clear()
        _fonts.clear()
        try:
            ui._render_cbs.remove(self._on_frame)
        except (ValueError, AttributeError):
            pass
        if self._display is not None and self._orig_render is not None:
            self._display.render = self._orig_render
            if self._orig_clear is not None:
                self._display.clear = self._orig_clear
        self._view = None

    # ---- web
    def _preview_png(self, theme, t=None, mood=None):
        import io
        ctx = self._ctx
        if ctx is not None:
            frame, layers = ctx["canvas"], ctx["layers"]
        else:
            layers = None
            try:
                frame = Image.open(FRAME_PATH).convert("1")
            except Exception:
                frame = Image.new("1", (480, 320), 0)
        buf = io.BytesIO()
        try:
            t = float(t)
            if not (math.isfinite(t) and abs(t) < 1e9):
                raise ValueError
        except (TypeError, ValueError):
            t = time.time()
        if mood:
            theme = resolve(theme, mood)
        colorize(frame, theme, t, layers, self._face_frame(theme, t, mood) if ctx is not None else None).save(buf, "PNG")
        return buf.getvalue()

    def on_webhook(self, path, request):
        from flask import jsonify, render_template_string, Response
        path = path or ""
        png = lambda b: Response(b, mimetype="image/png", headers={"Cache-Control": "no-store"})

        if path == "api/themes":
            return jsonify({"active": self._active, "themes": self._all()})

        if path == "api/packs":
            return jsonify(list_packs())

        if path == "api/elements":
            ctx = self._ctx or {"layers": {}}
            names = set(ctx["layers"])
            try:
                names |= {k for k, _ in self._view._state.items()}
            except Exception:
                pass
            return jsonify(sorted(names))

        if path == "api/entities":
            ctx = self._ctx or {"layers": {}}
            out = {k: {"key": k, "box": list(region[1])} for k, region in ctx["layers"].items()}
            try:
                for k, _ in self._view._state.items():
                    out.setdefault(k, {"key": k, "box": None})
            except Exception:
                pass
            return jsonify(sorted(out.values(), key=lambda e: e["key"]))

        if path.startswith("api/face/"):
            parts = path.split("/")
            if len(parts) == 4 and PACK_RE.fullmatch(parts[2]) and (parts[3] in MOODS or parts[3] == "default"):
                frames = pack_frames(parts[2], parts[3])
                if frames:
                    import io
                    buf = io.BytesIO()
                    frames[0][0].save(buf, "PNG")
                    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "max-age=60"})
            return Response("not found", status=404)

        if path == "docs":
            try:
                return Response(open(DOCS_FILE, encoding="utf-8").read(), mimetype="text/plain; charset=utf-8")
            except OSError:
                return Response("README.md not found in " + THEME_DIR, status=404)

        if path == "api/preview":
            try:
                if request.method == "POST":
                    data = _body(request)
                    mood = data.get("mood") if data.get("mood") in MOODS else None
                    return png(self._preview_png(_clean(data.get("theme", {})), data.get("t"), mood))
                themes = self._all()
                name = request.args.get("theme", self._active)
                if name not in themes:
                    return jsonify({"error": "unknown theme"}), 404
                return png(self._preview_png(_clean(themes[name])))
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400

        if request.method == "POST":
            data = _body(request)
            try:
                if path == "api/menu":
                    if data.get("open", True):
                        self.open_menu(data.get("mode") if data.get("mode") in ("list", "calib") else None, data.get("tab", "themes"))
                    else:
                        self.close_menu()
                    return jsonify({"ok": True})
                if path == "api/mood":
                    mood = data.get("mood")
                    if mood not in MOODS and mood is not None:
                        return jsonify({"ok": False, "error": "unknown mood"}), 400
                    self._force = (mood, time.time() + max(1, min(60, float(data.get("seconds", 10)))))
                    self._wake.set()
                    if self._view:
                        self._view.update(force=True)
                    return jsonify({"ok": True})
                if path == "api/apply":
                    self._apply(str(data.get("name", "")), persist=True)
                    return jsonify({"ok": True, "active": self._active})
                if path == "api/save":
                    name = str(data.get("name", "")).strip()
                    if not NAME_RE.fullmatch(name) or name in BUILTIN:
                        return jsonify({"ok": False, "error": "invalid or reserved name"}), 400
                    theme = _clean(data.get("theme", {}))
                    os.makedirs(THEME_DIR, exist_ok=True)
                    write_json(os.path.join(THEME_DIR, name + ".json"), theme, indent=2)
                    if name == self._active:
                        self._apply(name)
                    return jsonify({"ok": True})
                if path == "api/delete":
                    name = str(data.get("name", ""))
                    if name in BUILTIN or not NAME_RE.fullmatch(name):
                        return jsonify({"ok": False, "error": "cannot delete"}), 400
                    os.remove(os.path.join(THEME_DIR, name + ".json"))
                    if self._active == name:
                        self._apply("default", persist=True)
                    return jsonify({"ok": True})
            except (ValueError, TypeError, KeyError, FileNotFoundError, OverflowError) as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            return jsonify({"ok": False, "error": "unknown endpoint"}), 404

        if path in ('', 'index.html'):
            return render_template_string(PAGE)
        return Response('not found', status=404)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf_token" content="{{ csrf_token() }}">
<title>Theme Manager</title>
<style>
:root{--bg:#0f1115;--panel:#181b22;--line:#2a2f3a;--text:#e6e6e6;--dim:#8a93a3;--acc:#4caf50}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif;padding:16px}
h1{font-size:18px;margin:0 0 12px;display:flex;justify-content:space-between;align-items:center}
h1 a{font-size:13px;color:var(--acc)}.wrap{max-width:920px;margin:auto}
.pv{position:relative;max-width:480px;border:2px solid var(--line);border-radius:6px;background:#000;touch-action:pan-y}
.pv img{width:100%;display:block}#ov{position:absolute;inset:0;pointer-events:none}
.h{position:absolute;border:1px dashed var(--acc);background:rgba(76,175,80,.18);cursor:move;touch-action:none;pointer-events:auto;font-size:10px;color:#fff;overflow:hidden;user-select:none}
#msg{color:var(--dim);min-height:20px;margin:6px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px;cursor:pointer;font-size:13px}
.card.sel{border-color:var(--acc)}.card.act::after{content:" \25CF";color:var(--acc)}.card small{color:var(--dim)}
.sw{display:flex;height:18px;border-radius:4px;overflow:hidden;margin-bottom:6px;border:1px solid var(--line)}.sw i{flex:1}
.bar,.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
.tabs{display:flex;gap:4px;overflow-x:auto;margin-top:12px}.tabs button{border-radius:6px 6px 0 0;border-color:var(--line);color:var(--dim)}
.tabs button.on{border-color:var(--acc);color:var(--text);background:var(--panel)}
.ed{background:var(--panel);border:1px solid var(--line);border-radius:0 8px 8px 8px;padding:12px}
label{color:var(--dim);font-size:12px;display:flex;flex-direction:column;gap:3px}
label.ck{flex-direction:row;align-items:center;gap:6px;color:var(--text);font-size:13px}
label.sl{flex-direction:row;align-items:center;gap:8px;min-width:230px}label.sl span{width:74px;color:var(--dim)}label.sl b{width:38px;text-align:right;font-weight:400}
input[type=range]{flex:1;min-width:90px;accent-color:var(--acc)}
input[type=color]{width:52px;height:32px;border:1px solid var(--line);background:none;padding:0}
input[type=text],input[type=number],select,textarea{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:4px;padding:6px;font:inherit}
input[type=number]{width:72px}textarea{width:100%;height:320px;font:12px ui-monospace,monospace}textarea.bad{border-color:#e53935}
button{background:var(--panel);color:var(--text);border:1px solid var(--acc);border-radius:4px;padding:7px 12px;cursor:pointer;font:inherit}
button.d{border-color:#e53935}.fxbox{display:flex;flex-direction:column;gap:6px;margin:6px 0 12px}
.fxbox .sub{margin-left:22px;display:flex;flex-direction:column;gap:4px}
.tl{border:1px solid var(--line);border-radius:6px;padding:8px;margin-bottom:8px}
.chips button{font-size:11px;padding:2px 7px;border-color:var(--line);color:var(--dim)}
.gbar{height:22px;border-radius:4px;border:1px solid var(--line);margin:6px 0}
.thumbs{display:flex;flex-wrap:wrap;gap:6px}.thumbs figure{margin:0;text-align:center;font-size:10px;color:var(--dim)}
.thumbs img{width:96px;height:36px;background:#222;border-radius:4px;object-fit:contain}
#ov[data-mode=ent]{pointer-events:none}
.eb{position:absolute;border:1px dotted rgba(255,255,255,.55);pointer-events:auto;cursor:pointer}
.eb:hover,.eb.sel{background:rgba(76,175,80,.3);border:1px solid var(--acc)}
.pickbar{margin:6px 0;padding:6px 8px;border:1px solid var(--acc);border-radius:8px;background:var(--panel);max-width:480px}
.ent{display:flex;flex-direction:column;gap:3px;margin:6px 0}
.erow{display:flex;align-items:center;gap:10px;padding:3px 6px;border:1px solid transparent;border-radius:6px;flex-wrap:wrap}
.erow.set{border-color:var(--line)}.erow.sel{border-color:var(--acc);background:rgba(76,175,80,.12)}
.ename{width:120px;font:12px ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis}
.erow:not(.set) .x{visibility:hidden}.erow button.x{padding:2px 8px;font-size:12px;border-color:var(--line);color:var(--dim)}
.erow .inh{font-size:11px;color:var(--dim)}
h2{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin:14px 0 6px}
</style></head><body><div class="wrap">
<h1>Theme Manager <a href="docs" target="_blank">guide &rarr;</a></h1>
<div class="pv"><img id="prev" alt="preview"><div id="ov"></div></div>
<div id="msg"></div>
<div id="pick"></div>
<div id="grid" class="grid"></div>
<div class="bar">
<input type="text" id="name" maxlength="32" placeholder="theme name">
<button id="apply">Apply to screen</button><button id="save">Save</button>
<button id="export">Export</button><button id="import">Import</button><button id="del" class="d">Delete</button>
<input type="file" id="file" accept=".json,application/json" hidden></div>
<div id="tabs" class="tabs"></div>
<div id="panel" class="ed"></div>
</div>
{% raw %}<script>
const CSRF=document.querySelector('meta[name="csrf_token"]').content;
const base=location.pathname.replace(/\/$/,'');
const $=id=>document.getElementById(id);
const E=(tag,props,...kids)=>{const e=document.createElement(tag);
 for(const[k,v]of Object.entries(props||{})){
  if(k==='class')e.className=v;else if(k.startsWith('on'))e.addEventListener(k.slice(2),v);
  else if(k==='checked'||k==='disabled')e[k]=v;else if(k!=='value')e.setAttribute(k,v)}
 for(const c of kids.flat(9))if(c!=null&&c!==false)e.append(c);
 if(props&&'value'in props)e.value=props.value;return e};
const FX={glow:{radius:[0,12,1,3],strength:[0,1,.05,.8]},scanlines:{strength:[0,1,.05,.35]},vignette:{strength:[0,1,.05,.6]},
 border:{size:[1,12,1,2],color:1},noise:{strength:[0,1,.05,.3]},pulse:{speed:[0,30,.5,3],strength:[0,1,.05,.5]},
 rainbow:{speed:[0,30,.5,2]},glitch:{interval:[.5,20,.5,4]},rain:{density:[.05,1,.05,.5],speed:[0,30,.5,8],color:1},
 stars:{density:[.05,1,.05,.5],speed:[0,30,.5,3],color:1}};
const ANIM=['pulse','rainbow','glitch','rain','stars','noise'];
const MOODS=['look_r','sleep','awake','bored','intense','cool','happy','grateful','excited','motivated','demotivated','smart','lonely','sad','angry','friend','broken','debug','upload','handshake'];
const HOLDERS=['{name}','{time}','{date}','{cpu}','{temp}','{mem}','{uptime}','{ip}','{mode}','{gps}','{lat}','{lon}','{sats}','{handshakes}','{cracked}','{session}','{power}','{battery}'];
const TABS=['Colors','Effects','Text','Elements','Moods','Faces','JSON'];
let S={active:'',themes:{}},sel='',cur={},info={elements:[],entities:[],packs:{}},tab='Colors',mood='sad',pvMood=null,busy=false,dirty=false,pvErr=false,timer=null;
const say=t=>$('msg').textContent=t||'';
const post=(p,b)=>fetch(base+'/api/'+p,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':CSRF},body:JSON.stringify(b)});
const clone=o=>JSON.parse(JSON.stringify(o));
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

/* ---- theme object helpers ---- */
function normalize(o){const fx=l=>(l||[]).map(e=>typeof e==='string'?{type:e}:e);
 if(o.effects)o.effects=fx(o.effects);for(const m of Object.values(o.mood||{}))if(m.effects)m.effects=fx(m.effects);return o}
function prune(o){for(const k of['effects','text','elements','mood','gradient','faces']){const v=o[k];if(v===undefined)continue;
  if(v===null||v===false||(Array.isArray(v)?!v.length:!Object.keys(v).length))delete o[k]}
 if(!o.face_pack){delete o.face_scale;delete o.face_offset;delete o.face_tint}else if(!o.face_tint)delete o.face_tint;
 for(const[m,v]of Object.entries(o.mood||{})){for(const k of['elements','effects'])if(v[k]&&!Object.keys(v[k]).length)delete v[k];
  if(!Object.keys(v).length)delete o.mood[m]}
 return o}
const canon=v=>Array.isArray(v)?v.map(canon):(v&&typeof v==='object')?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canon(v[k])])):v;
const strip=o=>{const c=clone(o);delete c.builtin;return canon(prune(c))};
const same=(a,b)=>JSON.stringify(strip(a))===JSON.stringify(strip(b));
function animated(){const fx=(cur.effects||[]).some(e=>ANIM.includes(e.type));
 const tx=(cur.text||[]).some(l=>l.scroll||/\{(time|cpu|temp|mem|uptime|ip|mode|gps|lat|lon|sats|handshakes|cracked|session|power|battery)\}/.test(l.text||''));
 return fx||tx||!!cur.face_pack||Object.values(cur.elements||{}).includes('rainbow')||Object.keys(cur.mood||{}).length>0}

/* ---- preview ---- */
function schedule(){clearInterval(timer);preview();if(animated())timer=setInterval(preview,600)}
async function preview(){if(busy){dirty=true;return}busy=true;
 try{const r=await post('preview',{theme:prune(clone(cur)),t:Date.now()/1000%100000,mood:pvMood});
  if(r.ok){const im=$('prev'),old=im.src;im.onload=overlay;im.src=URL.createObjectURL(await r.blob());if(old.startsWith('blob:'))URL.revokeObjectURL(old);if(pvErr){say('');pvErr=false}}
  else{say((await r.json()).error);pvErr=true}}catch(e){say('preview failed');pvErr=true}
 busy=false;if(dirty){dirty=false;preview()}}
function touch(){prune(cur);const j=$('json');if(j&&document.activeElement!==j)j.value=JSON.stringify(cur,null,2);schedule()}

/* ---- small widgets ---- */
const field=(l,c)=>E('label',{},l,c);
const colorIn=(v,cb)=>E('input',{type:'color',value:/^#[0-9a-f]{6}$/i.test(v)?v:'#ffffff',oninput:e=>cb(e.target.value)});
const check=(l,v,cb)=>E('label',{class:'ck'},E('input',{type:'checkbox',checked:!!v,onchange:e=>cb(e.target.checked)}),l);
const select=(opts,v,cb)=>E('select',{onchange:e=>cb(e.target.value),value:v},opts.map(o=>Array.isArray(o)?E('option',{value:o[0]},o[1]):E('option',{value:o},o)));
function slider(l,[mn,mx,st],v,cb){const out=E('b',{},String(v));
 const r=E('input',{type:'range',min:mn,max:mx,step:st,value:v,oninput:e=>{const x=parseFloat(e.target.value);out.textContent=x;cb(x)}});
 return E('label',{class:'sl'},E('span',{},l),r,out)}
const numIn=(v,cb,mn,mx)=>E('input',{type:'number',min:mn,max:mx,value:v,oninput:e=>{const x=parseInt(e.target.value);if(!isNaN(x))cb(clamp(x,mn,mx))}});

/* ---- generic editors ---- */
function effectsEditor(getList){const box=E('div',{class:'fxbox'});
 for(const[type,params]of Object.entries(FX)){const have=getList().find(e=>e.type===type);
  box.append(check(type,!!have,on=>{const l=getList();
   if(on){const o={type};for(const[k,d]of Object.entries(params))if(Array.isArray(d))o[k]=d[3];l.push(o)}
   else{const i=l.findIndex(e=>e.type===type);if(i>=0)l.splice(i,1)}touch();panel()}));
  if(have){const sub=E('div',{class:'sub'});
   for(const[k,d]of Object.entries(params))sub.append(Array.isArray(d)?slider(k,d,have[k]??d[3],v=>{have[k]=v;touch()}):
    E('div',{class:'row'},field(k+' (optional)',colorIn(have[k]||'#ffffff',v=>{have[k]=v;touch()}))));
   box.append(sub)}}
 return box}
/* One row per on-screen entity: the color square assigns a color immediately, "reset" goes back to the theme color. */
const inheritColor=(k,bx,src)=>{const t=Object.assign({},cur,src||{});return bx&&(bx[1]<=14||bx[3]>=300)?(t.accent||'#ffffff'):(t.fg||'#ffffff')};
let entCtx=null,pickKey=null;
const entBox=k=>{const e=info.entities.find(e=>e.key===k);return e?e.box:null};
function entityRow(k,getObj,src){const v=(getObj(false)||{})[k];const eff=v&&v!=='rainbow'?v:inheritColor(k,entBox(k),src);
 const again=()=>{panel();if(pickKey)showPick(pickKey)};
 const row=E('div',{class:'erow'+(v!==undefined?' set':''),'data-key':k},E('span',{class:'ename',title:k},k),
  colorIn(eff,c=>{getObj(true)[k]=c;
   document.querySelectorAll('.erow[data-key="'+k+'"]').forEach(r=>{r.classList.add('set');const ci=r.querySelector('input[type=color]');if(ci&&ci.value!==c)ci.value=c;const h=r.querySelector('.inh');if(h)h.remove()});
   touch()}),
  check('rainbow',v==='rainbow',on=>{getObj(true)[k]=on?'rainbow':eff;touch();again()}),
  E('button',{class:'x',title:'back to the theme color',onclick:()=>{delete getObj(true)[k];touch();again()}},'reset'),
  v===undefined?E('span',{class:'inh'},'theme color'):null);
 return row}
function entityEditor(getObj,src){entCtx={getObj,src};const box=E('div',{class:'ent'});
 const keys=new Set(info.entities.map(e=>e.key));for(const k of Object.keys(getObj(false)||{}))keys.add(k);
 for(const k of [...keys].sort((a,b)=>a.localeCompare(b)))box.append(entityRow(k,getObj,src));
 const inp=E('input',{type:'text',placeholder:'other element name',maxlength:40});
 box.append(E('div',{class:'row'},inp,E('button',{onclick:()=>{const k=inp.value.trim();if(/^[A-Za-z0-9_.\-]{1,40}$/.test(k)){getObj(true)[k]=cur.fg||'#ffffff';touch();panel()}}},'add'),
  E('button',{class:'d',onclick:()=>{const o=getObj(false);if(o){for(const k of Object.keys(o))delete o[k];touch();panel();if(pickKey)showPick(pickKey)}}},'reset all')));
 return box}
/* clicking a part of the preview shows its controls right under the preview (no scrolling away from it) */
function showPick(k){const bar=$('pick');bar.innerHTML='';pickKey=k;
 if(!k||!entCtx||(tab!=='Elements'&&tab!=='Moods')){bar.className='';pickKey=null;return}
 bar.className='pickbar';bar.append(entityRow(k,entCtx.getObj,entCtx.src),E('button',{class:'x',style:'margin-left:8px;padding:2px 8px',onclick:()=>{selectEntity(null)}},'close'))}
function selectEntity(k){document.querySelectorAll('#panel .erow').forEach(r=>r.classList.toggle('sel',r.dataset.key===k));
 document.querySelectorAll('#ov .eb').forEach(d=>d.classList.toggle('sel',d.dataset.key===k));showPick(k)}

/* ---- panels ---- */
function panelColors(){const p=E('div');
 p.append(E('div',{class:'row'},[['bg','background'],['fg','ink (text)'],['accent','top/bottom bars'],['web','web accent']].map(([k,l])=>field(l,colorIn(cur[k],v=>{cur[k]=v;touch()})))));
 const g=cur.gradient;
 p.append(check('gradient background',!!g,on=>{cur.gradient=on?{from:cur.bg,to:cur.bg,direction:'vertical'}:undefined;touch();panel()}));
 if(g){const bar=E('div',{class:'gbar'});const sb=()=>bar.style.background='linear-gradient('+(g.direction==='horizontal'?'90deg':'180deg')+','+g.from+','+g.to+')';sb();
  p.append(E('div',{class:'row'},field('from',colorIn(g.from,v=>{g.from=v;sb();touch()})),field('to',colorIn(g.to,v=>{g.to=v;sb();touch()})),
   field('direction',select(['vertical','horizontal'],g.direction,v=>{g.direction=v;sb();touch()})),
   E('button',{onclick:()=>{[g.from,g.to]=[g.to,g.from];touch();panel()}},'swap')),bar)}
 p.append(E('div',{class:'row'},slider('animation fps',[1,10,1],cur.fps??5,v=>{cur.fps=v;touch()})));
 return p}
const panelEffects=()=>effectsEditor(()=>cur.effects=cur.effects||[]);
function panelText(){const p=E('div');const L=()=>cur.text=cur.text||[];
 p.append(E('p',{style:'color:var(--dim);margin:0 0 8px'},'Drag the green boxes on the preview to place a line. Placeholders: '+HOLDERS.join(' ')));
 L().forEach((l,i)=>{const t=E('div',{class:'tl'});
  const txt=E('input',{type:'text',value:l.text,maxlength:200,style:'flex:1;min-width:180px',oninput:e=>{l.text=e.target.value;touch();overlay()}});
  t.append(E('div',{class:'row'},txt,E('button',{class:'d',onclick:()=>{L().splice(i,1);touch();panel();overlay()}},'delete')));
  t.append(E('div',{class:'row chips'},HOLDERS.map(h=>E('button',{onclick:()=>{l.text=(l.text||'')+h;txt.value=l.text;touch();overlay()}},h))));
  t.append(E('div',{class:'row'},slider('size',[6,48,1],l.size||12,v=>{l.size=v;touch();overlay()}),
   field('x',E('input',{type:'number',id:'tx'+i,min:-480,max:960,value:l.x||0,oninput:e=>{l.x=clamp(parseInt(e.target.value)||0,-480,960);touch();overlay()}})),
   field('y',E('input',{type:'number',id:'ty'+i,min:-320,max:640,value:l.y||0,oninput:e=>{l.y=clamp(parseInt(e.target.value)||0,-320,640);touch();overlay()}}))));
  t.append(E('div',{class:'row'},check('own color',!!l.color,on=>{l.color=on?(cur.fg||'#ffffff'):undefined;touch();panel()}),
   l.color?colorIn(l.color,v=>{l.color=v;touch()}):null,check('bold',l.bold,on=>{l.bold=on;touch()}),
   field('align',select(['left','center','right'],l.align||'left',v=>{l.align=v;touch();overlay()})),
   check('scroll',l.scroll,on=>{l.scroll=on;touch();panel();overlay()})));
  if(l.scroll)t.append(E('div',{class:'row'},slider('speed px/s',[1,300,1],l.speed||40,v=>{l.speed=v;touch()}),slider('box width',[10,480,5],l.width||300,v=>{l.width=v;touch();overlay()})));
  p.append(t)});
 p.append(E('button',{onclick:()=>{L().push({text:'{name} {time}',x:10,y:270,size:12});touch();panel();overlay()}},'+ add text line'));return p}
const panelElements=()=>E('div',{},E('p',{style:'color:var(--dim);margin:0 0 8px'},'Give each part of the screen its own color: click a part on the preview, or use the color squares. \u201Ctheme color\u201D means it follows the theme.'),
 entityEditor(c=>c?(cur.elements=cur.elements||{}):cur.elements));
function moodObj(create){if(!cur.mood){if(!create)return undefined;cur.mood={}}
 if(!cur.mood[mood]){if(!create)return undefined;cur.mood[mood]={}}return cur.mood[mood]}
function panelMoods(){const p=E('div');
 p.append(E('p',{style:'color:var(--dim);margin:0 0 8px'},'Overrides applied while pwnagotchi is in a mood (colors blend smoothly). ● = has overrides.'));
 p.append(E('div',{class:'row'},select(MOODS.map(m=>[m,(cur.mood&&cur.mood[m]?'● ':'')+m]),mood,v=>{mood=v;pvMood=v;panel();schedule()}),
  E('button',{onclick:()=>{pvMood=mood;schedule()}},'preview here'),E('button',{onclick:()=>{pvMood=null;schedule()}},'stop preview'),
  E('button',{onclick:async()=>{const r=await(await post('mood',{mood,seconds:15})).json();say(r.ok?'showing '+mood+' on the screen for 15 s (uses the applied theme)':r.error)}},'show on screen'),
  E('button',{class:'d',onclick:()=>{if(cur.mood)delete cur.mood[mood];touch();panel()}},'clear')));
 const m=moodObj(false)||{};
 p.append(E('h2',{},'Colors'),E('div',{class:'row'},['fg','accent','bg'].map(k=>E('div',{class:'row'},
  check(k,m[k]!==undefined,on=>{const o=moodObj(true);if(on)o[k]=cur[k];else delete o[k];touch();panel()}),m[k]!==undefined?colorIn(m[k],v=>{moodObj(true)[k]=v;touch()}):null))));
 p.append(E('h2',{},'Element colors'),entityEditor(c=>{const o=moodObj(c);return o?(c?(o.elements=o.elements||{}):o.elements):undefined},moodObj(false)));
 p.append(E('h2',{},'Extra effects'),effectsEditor(()=>{const o=moodObj(true);return o.effects=o.effects||[]}));return p}
function panelFaces(){const p=E('div');const packs=info.packs;
 p.append(E('p',{style:'color:var(--dim);margin:0 0 8px'},'Face packs are folders of PNG/GIF images named after moods, in /etc/pwnagotchi/themes/faces/.'));
 p.append(E('div',{class:'row'},field('face pack',select([['','(none: text faces)'],...Object.keys(packs).map(k=>[k,k])],cur.face_pack||'',v=>{cur.face_pack=v||undefined;touch();panel()}))));
 if(cur.face_pack){p.append(E('div',{class:'row'},slider('scale',[.25,4,.25],cur.face_scale||1,v=>{cur.face_scale=v;touch()}),
   field('offset x',numIn((cur.face_offset||[0,0])[0],v=>{cur.face_offset=[v,(cur.face_offset||[0,0])[1]];touch()},-300,300)),
   field('offset y',numIn((cur.face_offset||[0,0])[1],v=>{cur.face_offset=[(cur.face_offset||[0,0])[0],v];touch()},-300,300)),
   check('tint with face color (for white outline faces)',cur.face_tint,on=>{cur.face_tint=on;touch()})));
  p.append(E('h2',{},'Faces in this pack'),E('div',{class:'thumbs'},(packs[cur.face_pack]||[]).map(m=>E('figure',{},E('img',{src:base+'/api/face/'+cur.face_pack+'/'+m,alt:m}),m))))}
 return p}
function panelJson(){prune(cur);const ta=E('textarea',{id:'json',spellcheck:'false',value:JSON.stringify(cur,null,2)});
 ta.oninput=()=>{try{const o=normalize(JSON.parse(ta.value));ta.classList.remove('bad');cur=o;schedule()}catch(e){ta.classList.add('bad')}};
 return E('div',{},E('p',{style:'color:var(--dim);margin:0 0 8px'},'Full theme JSON. Changes apply to the preview as you type.'),ta)}
const PANELS={Colors:panelColors,Effects:panelEffects,Text:panelText,Elements:panelElements,Moods:panelMoods,Faces:panelFaces,JSON:panelJson};
function panel(){const p=$('panel');p.innerHTML='';p.append(PANELS[tab]());
 const t=$('tabs');t.innerHTML='';for(const n of TABS)t.append(E('button',{class:n===tab?'on':'',onclick:async()=>{tab=n;pickKey=null;$('pick').innerHTML='';$('pick').className='';pvMood=n==='Moods'?mood:null;if(n==='Elements'||n==='Moods'){try{info.entities=await(await fetch(base+'/api/entities')).json()}catch(e){}}panel();overlay();schedule()}},n))}

/* ---- drag text lines on the preview ---- */
const est=t=>(t||'').replace(/\{time\}/g,'00:00:00').replace(/\{date\}/g,'0000-00-00').replace(/\{\w+\}/g,'0000').length;
const boxW=l=>l.scroll?(l.width||300):Math.max(20,est(l.text)*(l.size||12)*.602);
/* handles are updated in place (never rebuilt while the count is unchanged) so a drag survives preview reloads */
function overlay(){const ov=$('ov');const mode=tab==='Text'?'text':(tab==='Elements'||tab==='Moods')?'ent':'';
 if(ov.dataset.mode!==mode){ov.innerHTML='';ov.dataset.mode=mode}
 if(!mode)return;const sc=$('prev').clientWidth/480;
 if(mode==='ent'){const E_=info.entities.filter(e=>e.box).sort((a,b)=>area(b.box)-area(a.box));
  if(ov.children.length!==E_.length){ov.innerHTML='';E_.forEach(e=>{const d=E('div',{class:'eb','data-key':e.key,title:e.key});d.addEventListener('click',()=>selectEntity(e.key));ov.append(d)})}
  E_.forEach((e,i)=>{const[x0,y0,x1,y1]=e.box;ov.children[i].style.cssText='left:'+x0*sc+'px;top:'+y0*sc+'px;width:'+Math.max(4,(x1-x0)*sc)+'px;height:'+Math.max(4,(y1-y0)*sc)+'px'});return}
 const T=cur.text||[];
 if(ov.children.length!==T.length){ov.innerHTML='';T.forEach((l,i)=>{const d=E('div',{class:'h','data-i':i},'#'+(i+1));d.addEventListener('pointerdown',e=>drag(e,i,d));ov.append(d)})}
 T.forEach((l,i)=>{const w=boxW(l),h=(l.size||12)+6;let x=l.x||0;if(l.align==='center')x-=w/2;else if(l.align==='right')x-=w;
  ov.children[i].style.cssText='left:'+x*sc+'px;top:'+(l.y||0)*sc+'px;width:'+w*sc+'px;height:'+h*sc+'px'})}
const area=b=>(b[2]-b[0])*(b[3]-b[1]);
function drag(e,i,d){e.preventDefault();d.setPointerCapture(e.pointerId);
 const sc=$('prev').clientWidth/480,sx=e.clientX,sy=e.clientY,l0=cur.text[i],ox=l0.x||0,oy=l0.y||0;
 const mv=ev=>{const l=cur.text[i];if(!l)return;l.x=clamp(Math.round(ox+(ev.clientX-sx)/sc),-480,960);l.y=clamp(Math.round(oy+(ev.clientY-sy)/sc),-320,640);
  overlay();const a=$('tx'+i),b=$('ty'+i);if(a)a.value=l.x;if(b)b.value=l.y;touch()};
 const up=()=>{d.removeEventListener('pointermove',mv);d.removeEventListener('pointerup',up)};
 d.addEventListener('pointermove',mv);d.addEventListener('pointerup',up)}

/* ---- theme list + buttons ---- */
function render(){const g=$('grid');g.innerHTML='';
 for(const[n,t]of Object.entries(S.themes)){const c=E('div',{class:'card'+(n===sel?' sel':'')+(n===S.active?' act':''),'data-name':n,onclick:()=>{sel=n;pick()}},
  E('div',{class:'sw'},[t.bg,t.fg,t.accent,t.web].map(x=>{const i=E('i');i.style.background=x;return i})),n);
  const f=(t.effects||[]).length+(t.text||[]).length+Object.keys(t.elements||{}).length+(t.face_pack?1:0)+Object.keys(t.mood||{}).length;
  if(f)c.append(E('small',{},' +'+f));g.append(c)}}
function pick(){cur=normalize(clone(S.themes[sel]));delete cur.builtin;$('name').value=sel;pvMood=tab==='Moods'?mood:null;render();panel();overlay();schedule()}
async function refresh(keep){S=await(await fetch(base+'/api/themes')).json();if(!S.themes[sel])sel=S.active;
 try{info.elements=await(await fetch(base+'/api/elements')).json();info.entities=await(await fetch(base+'/api/entities')).json();info.packs=await(await fetch(base+'/api/packs')).json()}catch(e){}
 if(keep){render()}else pick()}
const nameOk=n=>/^[A-Za-z0-9_\- ]{1,32}$/.test(n);
async function saveAs(n){const r=await(await post('save',{name:n,theme:prune(clone(cur))})).json();if(!r.ok)say(r.error);return r.ok}
$('save').onclick=async()=>{const n=$('name').value.trim();
 if(!nameOk(n))return say('name: letters, digits, space, _ and - (max 32)');
 if(S.themes[n]&&S.themes[n].builtin)return say('"'+n+'" is built in. Type a new name to save your changes.');
 if(await saveAs(n)){say('saved '+n);sel=n;await refresh()}};
$('apply').onclick=async()=>{const n=$('name').value.trim();const ex=S.themes[n];
 if(ex&&ex.builtin){if(!same(cur,ex))return say('built-in themes can\'t be changed: type a new name, Save, then Apply');}
 else{if(!nameOk(n))return say('give the theme a name first');if(!(ex&&same(cur,ex))&&!await saveAs(n))return}
 const r=await(await post('apply',{name:n})).json();say(r.ok?'applied '+n+' to the screen':r.error);sel=n;await refresh()};
$('del').onclick=async()=>{const r=await(await post('delete',{name:sel})).json();say(r.ok?'deleted '+sel:r.error);if(r.ok){sel='';await refresh()}};
$('export').onclick=()=>{const n=($('name').value.trim()||'theme');const a=E('a',{href:URL.createObjectURL(new Blob([JSON.stringify(prune(clone(cur)),null,2)],{type:'application/json'})),download:n+'.json'});document.body.append(a);a.click();a.remove()};
$('import').onclick=()=>$('file').click();
$('file').onchange=async e=>{const f=e.target.files[0];if(!f)return;
 try{cur=normalize(JSON.parse(await f.text()));$('name').value=f.name.replace(/\.json$/i,'').replace(/[^A-Za-z0-9_\- ]/g,'_').slice(0,32);
  panel();overlay();schedule();say('imported: check the preview, then Save')}catch(err){say('not a valid theme file')}e.target.value=''};
window.addEventListener('resize',overlay);
refresh();
</script>{% endraw %}</body></html>
"""


# ------------------------------------------------------------------------ CLI
if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    tm = ThemeManager.__new__(ThemeManager)
    cmd = a[0] if a else ""
    if cmd == "list":
        cur = json.load(open(ACTIVE_FILE))["active"] if os.path.exists(ACTIVE_FILE) else "default"
        for n, t in tm._all().items():
            print("%s %-16s %s" % ("*" if n == cur else " ", n, "animated" if is_animated(t) else ""))
    elif cmd == "set" and len(a) == 2:
        if a[1] not in tm._all():
            sys.exit("unknown theme")
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(ACTIVE_FILE, {"active": a[1]})
        print("active ->", a[1], "(applies within seconds)")
    elif cmd == "new" and len(a) == 2 and NAME_RE.fullmatch(a[1]):
        p = os.path.join(THEME_DIR, a[1] + ".json")
        if os.path.exists(p):
            sys.exit(p + " exists")
        os.makedirs(THEME_DIR, exist_ok=True)
        tpl = dict(BUILTIN["cyberpunk"], description="my theme")
        write_json(p, tpl, indent=2)
        print("created", p)
    elif cmd == "mood" and len(a) in (2, 3) and a[1] in MOODS + ("off",):
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(FORCE_FILE, {"mood": None if a[1] == "off" else a[1],
                                "until": time.time() + (float(a[2]) if len(a) == 3 else 15)})
        print("mood ->", a[1])
    elif cmd == "validate" and len(a) == 2:
        try:
            t = _clean(json.load(open(a[1])))
            print("OK  animated=%s effects=%d text=%d" % (is_animated(t), len(t.get("effects", [])), len(t.get("text", []))))
        except Exception as e:
            sys.exit("INVALID: %s" % e)
    elif cmd == "preview" and len(a) >= 3:
        src = Image.open(FRAME_PATH).convert("1") if os.path.exists(FRAME_PATH) else Image.new("1", (480, 320), 0)
        colorize(src, _clean(tm._all()[a[1]]), float(a[3]) if len(a) > 3 else 1.0).save(a[2])
        print("wrote", a[2])
    else:
        print(__doc__)
