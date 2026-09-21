"""theme_manager - theme engine for the pwnagotchi 3.5" framebuffer display.

Themes are JSON files in /etc/pwnagotchi/themes/. See README.md there.

CLI (run with /opt/.pwn/bin/python3):
  theme_manager.py list
  theme_manager.py set NAME
  theme_manager.py new NAME            create a template theme to edit
  theme_manager.py mood NAME [seconds] force a mood to preview it (NAME=off to clear)
  theme_manager.py dim PERCENT            screen brightness, 5-100
  theme_manager.py night 22:00 07:00 30   dim to 30% at night (or: night off)
  theme_manager.py idle 5 25              dim to 25% after 5 minutes without a touch (or: idle off)
  theme_manager.py overheat on 85 60      turn the Pi off after 60 s at 85 C (or: overheat off)
  theme_manager.py achievements on|off    keep track of achievements or not
  theme_manager.py layout show|reset      what was moved on the screen, or put everything back
  theme_manager.py cracking [list]        handshake upload/crack counts, or the full list
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
import io
import re
import select
import shutil
import socket
import sqlite3
import struct
import textwrap
import threading
import time
import zipfile

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


THEME_DIR = os.environ.get("THEME_MANAGER_DIR", "/etc/pwnagotchi/themes")   # the variable is for testing
ACTIVE_FILE = os.path.join(THEME_DIR, "active.json")
DOCS_FILE = os.path.join(THEME_DIR, "README.md")
FRAME_PATH = "/var/tmp/pwnagotchi/pwnagotchi.png"
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,32}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")

EFFECTS = {"scanlines", "vignette", "glow", "noise", "pulse", "rainbow",
           "glitch", "rain", "stars", "border", "scene"}
SCENE_KINDS = ("mountains", "glacier", "ocean", "forest", "desert", "aurora", "volcano", "winter", "spring", "summer", "autumn",
               "halloween", "christmas", "space", "startrek", "city", "vaporwave", "bloodmoon", "pixel")
ANIMATED = {"pulse", "rainbow", "glitch", "rain", "stars", "noise"}
LIVE_TOKENS = ("{time}", "{cpu}", "{temp}", "{mem}", "{uptime}", "{ip}", "{gps}", "{lat}", "{lon}", "{sats}",
               "{handshakes}", "{cracked}", "{session}", "{battery}", "{power}", "{mode}", "{queued}", "{uploaded}", "{invalid}")
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
STATE_FILES = ("active.json", "force_mood.json", "touch.json", "display.json", "settings.json", "achievements.json", "layout.json", "disclaimer.json")   # JSON files in THEME_DIR that are not themes
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
                  "effects": [{"type": "scene", "kind": "city"}, {"type": "glow", "radius": 3, "strength": 0.8}, {"type": "glitch", "interval": 5},
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
                  "effects": [{"type": "scene", "kind": "vaporwave"}, {"type": "stars", "density": 0.4, "speed": 3}, {"type": "glow", "radius": 2, "strength": 0.6},
                              {"type": "border", "size": 2, "color": "#01cdfe"}],
                  "elements": {"face": "#01cdfe", "status": "#05ffa1", "name": "#fffb96"},
                  "text": [{"text": "A E S T H E T I C", "x": 10, "y": 278, "size": 12, "color": "#05ffa1"}]},
    "blood": {"bg": "#0a0000", "fg": "#ff2020", "accent": "#c01010", "web": "#ff2020", "fps": 6,
              "effects": [{"type": "scene", "kind": "bloodmoon"}, {"type": "pulse", "speed": 3, "strength": 0.5}, {"type": "vignette", "strength": 0.8},
                          {"type": "glow", "radius": 3, "strength": 0.7}]},
    "ice": {"bg": "#04121f", "fg": "#9fe8ff", "accent": "#3a8fb7", "web": "#3a8fb7", "fps": 5,
            "gradient": {"from": "#04121f", "to": "#0a3350", "direction": "vertical"},
            "effects": [{"type": "scene", "kind": "glacier"}, {"type": "stars", "density": 0.6, "speed": 2}, {"type": "glow", "radius": 2, "strength": 0.5}]},
    "gameboy": {"bg": "#9bbc0f", "fg": "#0f380f", "accent": "#306230", "web": "#306230",
                "effects": [{"type": "scene", "kind": "pixel"}, {"type": "scanlines", "strength": 0.12}, {"type": "border", "size": 3, "color": "#306230"}]},
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
    # ---- inspired by places, seasons and stories
    "startrek": {"bg": "#000000", "fg": "#ff9900", "accent": "#cc99cc", "web": "#9999ff", "fps": 5,
                 "description": "starship-console look: orange, lavender and blue on black, red alert when angry",
                 "elements": {"face": "#99ccff", "name": "#ffcc66", "status": "#ffcc99", "channel": "#9999ff", "aps": "#9999ff",
                              "uptime": "#cc6666", "shakes": "#ffcc66", "mode": "#cc99cc"},
                 "effects": [{"type": "scene", "kind": "startrek"}, {"type": "border", "size": 3, "color": "#ff9900"}, {"type": "glow", "radius": 2, "strength": 0.5},
                             {"type": "scanlines", "strength": 0.12}],
                 "text": [{"text": "STARDATE {stardate}", "x": 10, "y": 262, "size": 12, "bold": True, "color": "#cc99cc"},
                          {"text": "ALL SYSTEMS NOMINAL ::: SCANNING ::: STANDING BY ::: ", "x": 10, "y": 278, "size": 11,
                           "scroll": True, "speed": 30, "width": 290, "color": "#9999ff"}],
                 "mood": {"angry": {"fg": "#ff3030", "accent": "#ff3030", "elements": {"face": "#ff3030", "name": "#ff3030"},
                                    "effects": [{"type": "pulse", "speed": 8, "strength": 0.5}]},
                          "broken": {"fg": "#ff3030", "accent": "#ff3030", "elements": {"face": "#ff3030"},
                                     "effects": [{"type": "glitch", "interval": 1.5}]},
                          "sad": {"fg": "#ffcc00", "accent": "#ffcc00", "elements": {"face": "#ffcc00"}},
                          "handshake": {"elements": {"face": "#66ff99", "name": "#66ff99"}, "effects": [{"type": "glow", "radius": 5, "strength": 1}]}}},
    "spring": {"bg": "#0f2a1c", "fg": "#e6ffd0", "accent": "#ff9ecb", "web": "#ff9ecb", "fps": 4,
               "description": "fresh green with drifting blossoms",
               "gradient": {"from": "#0f2a1c", "to": "#2f6b4a", "direction": "vertical"},
               "elements": {"face": "#ffd6e8", "name": "#b8f5a0"},
               "effects": [{"type": "scene", "kind": "spring"}, {"type": "glow", "radius": 2, "strength": 0.4}],
               "text": [{"text": "spring  {date}", "x": 10, "y": 278, "size": 11, "color": "#ffb7d5"}],
               "mood": {"happy": {"elements": {"face": "#fff2a8"}}, "sad": {"fg": "#cfe8ff", "elements": {"face": "#cfe8ff"}}}},
    "summer": {"bg": "#0b3d91", "fg": "#fff3c4", "accent": "#ffb703", "web": "#ffb703", "fps": 4,
               "description": "deep blue sky and sea with sun sparkles",
               "gradient": {"from": "#0b3d91", "to": "#006d77", "direction": "vertical"},
               "elements": {"face": "#fff3c4", "name": "#ffe066", "status": "#ffffff"},
               "effects": [{"type": "scene", "kind": "summer"}, {"type": "glow", "radius": 3, "strength": 0.6}],
               "text": [{"text": "summer  {time}", "x": 10, "y": 278, "size": 11, "color": "#ffe066"}],
               "mood": {"excited": {"elements": {"face": "rainbow"}}, "sad": {"fg": "#d7ecff", "elements": {"face": "#d7ecff"}}}},
    "autumn": {"bg": "#2a1206", "fg": "#ffcf8a", "accent": "#e07a1f", "web": "#e07a1f", "fps": 4,
               "description": "warm browns and falling embers",
               "gradient": {"from": "#2a1206", "to": "#5c2a0a", "direction": "vertical"},
               "elements": {"face": "#ffb347", "name": "#ffd9a0"},
               "effects": [{"type": "scene", "kind": "autumn"}, {"type": "stars", "density": 0.7, "speed": 2, "color": "#ff8c1a"}, {"type": "vignette", "strength": 0.5}],
               "text": [{"text": "autumn  {date}", "x": 10, "y": 278, "size": 11, "color": "#ff9a3d"}],
               "mood": {"angry": {"fg": "#ff6b3d", "elements": {"face": "#ff6b3d"}}}},
    "winter": {"bg": "#04121f", "fg": "#eaf6ff", "accent": "#9fd3f0", "web": "#9fd3f0", "fps": 4,
               "description": "cold blue night with falling snow",
               "gradient": {"from": "#04121f", "to": "#12466b", "direction": "vertical"},
               "elements": {"face": "#d7f0ff", "name": "#9fd3f0"},
               "effects": [{"type": "scene", "kind": "winter"}, {"type": "stars", "density": 1.0, "speed": 1, "color": "#ffffff"}, {"type": "vignette", "strength": 0.3}],
               "text": [{"text": "winter  {date}", "x": 10, "y": 278, "size": 11, "color": "#9fd3f0"}],
               "mood": {"sad": {"fg": "#8fb3d9", "elements": {"face": "#8fb3d9"}}, "happy": {"elements": {"face": "#fff6c9"}}}},
    "mountain": {"bg": "#0d1b2e", "fg": "#f0f6ff", "accent": "#8fb3d9", "web": "#8fb3d9", "fps": 3,
                 "description": "dusk over snowy peaks",
                 "gradient": {"from": "#0d1b2e", "to": "#2a4365", "direction": "vertical"},
                 "elements": {"face": "#dbe8f7", "name": "#ffd59e", "status": "#c5d8ee"},
                 "effects": [{"type": "scene", "kind": "mountains"}, {"type": "stars", "density": 0.3, "speed": 1.5, "color": "#ffffff"}, {"type": "vignette", "strength": 0.5}],
                 "text": [{"text": "\u25B2 {name}  {time}", "x": 10, "y": 278, "size": 12, "color": "#ffd59e"}],
                 "mood": {"sad": {"fg": "#a9b8c9", "elements": {"face": "#a9b8c9"}}, "excited": {"elements": {"face": "#ffd59e"}}}},
    "ocean": {"bg": "#00132b", "fg": "#caf0f8", "accent": "#48cae4", "web": "#48cae4", "fps": 4,
              "description": "deep water with drifting plankton",
              "gradient": {"from": "#00132b", "to": "#005f73", "direction": "vertical"},
              "elements": {"face": "#90e0ef", "name": "#caf0f8"},
              "effects": [{"type": "scene", "kind": "ocean"}, {"type": "stars", "density": 0.5, "speed": 2, "color": "#90e0ef"}, {"type": "glow", "radius": 3, "strength": 0.6}],
              "text": [{"text": "depth  {uptime}", "x": 10, "y": 278, "size": 11, "color": "#48cae4"}],
              "mood": {"sad": {"fg": "#7aa5c4", "elements": {"face": "#7aa5c4"}}, "excited": {"elements": {"face": "rainbow"}}}},
    "forest": {"bg": "#06140b", "fg": "#c7f9cc", "accent": "#80ed99", "web": "#80ed99", "fps": 4,
               "description": "night woods with fireflies",
               "gradient": {"from": "#06140b", "to": "#123524", "direction": "vertical"},
               "elements": {"face": "#b7ffbf", "name": "#ffe66d"},
               "effects": [{"type": "scene", "kind": "forest"}, {"type": "stars", "density": 0.35, "speed": 2.5, "color": "#ffe66d"}, {"type": "vignette", "strength": 0.5}],
               "text": [{"text": "{name} in the woods", "x": 10, "y": 278, "size": 11, "color": "#80ed99"}],
               "mood": {"angry": {"fg": "#ff8a5c", "elements": {"face": "#ff8a5c"}}}},
    "desert": {"bg": "#2b0f3a", "fg": "#ffe8b5", "accent": "#ffb347", "web": "#ffb347", "fps": 3,
               "description": "purple dusk fading into orange sand",
               "gradient": {"from": "#2b0f3a", "to": "#a44a1f", "direction": "vertical"},
               "elements": {"face": "#fff1cf", "name": "#ffd18a"},
               "effects": [{"type": "scene", "kind": "desert"}, {"type": "noise", "strength": 0.12}, {"type": "vignette", "strength": 0.45}],
               "text": [{"text": "{date}  {temp}", "x": 10, "y": 278, "size": 11, "color": "#ffd18a"}],
               "mood": {"sad": {"fg": "#e8c9a0", "elements": {"face": "#e8c9a0"}}}},
    "aurora": {"bg": "#020c14", "fg": "#7dffb2", "accent": "#b18cff", "web": "#b18cff", "fps": 6,
               "description": "northern lights: green and violet glow on a dark sky",
               "gradient": {"from": "#020c14", "to": "#0b3a3a", "direction": "vertical"},
               "elements": {"face": "#7dffb2", "name": "#b18cff", "status": "#c8ffe0"},
               "effects": [{"type": "scene", "kind": "aurora"}, {"type": "glow", "radius": 3, "strength": 0.8}, {"type": "pulse", "speed": 1.5, "strength": 0.25},
                           {"type": "stars", "density": 0.4, "speed": 2, "color": "#ffffff"}],
               "mood": {"excited": {"elements": {"face": "rainbow"}}, "sad": {"fg": "#8fa8ff", "elements": {"face": "#8fa8ff"}}}},
    "volcano": {"bg": "#0a0000", "fg": "#ff8a3d", "accent": "#ff3d00", "web": "#ff3d00", "fps": 6,
                "description": "black rock with a glowing orange heart",
                "gradient": {"from": "#0a0000", "to": "#4a0d00", "direction": "vertical"},
                "elements": {"face": "#ffb347", "name": "#ff3d00"},
                "effects": [{"type": "scene", "kind": "volcano"}, {"type": "pulse", "speed": 2, "strength": 0.35}, {"type": "noise", "strength": 0.2},
                            {"type": "glow", "radius": 3, "strength": 0.7}],
                "mood": {"angry": {"elements": {"face": "#ff2200"}, "effects": [{"type": "glitch", "interval": 2}]}}},
    "halloween": {"bg": "#12001f", "fg": "#ff9a1f", "accent": "#b04bff", "web": "#b04bff", "fps": 6,
                  "description": "orange and purple with a flickering glow",
                  "gradient": {"from": "#12001f", "to": "#2b0a3d", "direction": "vertical"},
                  "elements": {"face": "#ffb347", "name": "#d9a0ff"},
                  "effects": [{"type": "scene", "kind": "halloween"}, {"type": "pulse", "speed": 3, "strength": 0.3}, {"type": "stars", "density": 0.3, "speed": 2, "color": "#ff9a1f"},
                              {"type": "vignette", "strength": 0.6}],
                  "text": [{"text": "boo!  {time}", "x": 10, "y": 278, "size": 12, "bold": True, "color": "#ff9a1f"}],
                  "mood": {"excited": {"elements": {"face": "#7dff5a"}}}},
    "christmas": {"bg": "#0a2a14", "fg": "#f5fff5", "accent": "#e63946", "web": "#e63946", "fps": 4,
                  "description": "red and green with falling snow",
                  "gradient": {"from": "#0a2a14", "to": "#3b0d0d", "direction": "vertical"},
                  "elements": {"face": "#ffffff", "name": "#80ed99", "status": "#ffd6d6"},
                  "effects": [{"type": "scene", "kind": "christmas"}, {"type": "stars", "density": 0.8, "speed": 1.5, "color": "#ffffff"}, {"type": "glow", "radius": 2, "strength": 0.5}],
                  "text": [{"text": "happy holidays  {date}", "x": 10, "y": 278, "size": 11, "color": "#ffd6d6"}],
                  "mood": {"excited": {"elements": {"face": "#ffe066"}}}},
    "space": {"bg": "#000005", "fg": "#cfd8ff", "accent": "#6c7bff", "web": "#6c7bff", "fps": 5,
              "description": "deep space with a slow star field",
              "gradient": {"from": "#000005", "to": "#0a0a26", "direction": "vertical"},
              "elements": {"face": "#e8ecff", "name": "#9aa8ff"},
              "effects": [{"type": "scene", "kind": "space"}, {"type": "stars", "density": 1.0, "speed": 2, "color": "#ffffff"}, {"type": "glow", "radius": 2, "strength": 0.4}],
              "text": [{"text": "orbit {uptime}", "x": 10, "y": 278, "size": 11, "color": "#9aa8ff"}],
              "mood": {"excited": {"elements": {"face": "rainbow"}}, "angry": {"fg": "#ff6b6b", "elements": {"face": "#ff6b6b"}}}},
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
    if e["type"] == "scene":
        if e.get("kind") not in SCENE_KINDS:
            raise ValueError("scene.kind must be one of: " + ", ".join(SCENE_KINDS))
        out["kind"] = e["kind"]
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
    if "warnings" in theme:
        out["warnings"] = bool(theme["warnings"])
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
    if any(e["type"] in ANIMATED or (e["type"] == "scene" and e["kind"] in ANIM_SCENES) for e in theme.get("effects", [])):
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
    override = os.environ.get("THEME_MANAGER_HANDSHAKES")     # for testing: a real pwnagotchi never sets this
    if override:
        return override
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


# ---------------------------------------------------------------- cracking dashboard
# Read-only: the wpa-sec plugin (if installed and enabled) tracks each handshake's upload in a small sqlite database
# and writes cracked results to a potfile; this only ever reads those, never writes them or changes what gets attacked.
WPA_SEC_DB = os.environ.get("THEME_MANAGER_WPA_DB", "/etc/pwnagotchi/.wpa_sec_db")   # env var is for testing
CRACK_STATUS = {0: "queued", 1: "invalid", 2: "uploaded"}    # the wpa-sec plugin's own status codes
BSSID_HEX = re.compile(r"[0-9a-fA-F]{12}")
HANDSHAKE_RE = re.compile(r"^(.*)_([0-9a-fA-F]{12})\.(?:pcap|pcapng)$")
CRACK_PILL = {"cracked": ("PWND", True), "uploaded": ("WAIT", False), "queued": ("NEW", False),
              "invalid": ("BAD", False), "unknown": ("?", False)}


def _wpa_db_status():
    """{path: status} from the wpa-sec plugin's database, or None if it isn't there or can't be read."""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % WPA_SEC_DB, uri=True, timeout=2)
        try:
            return dict(con.execute("SELECT path, status FROM handshakes").fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _wpa_db_counts():
    """{"queued", "uploaded", "invalid"}: how many handshakes are in each state, or "n/a" if wpa-sec isn't set up."""
    status = _wpa_db_status()
    if status is None:
        return {"queued": "n/a", "uploaded": "n/a", "invalid": "n/a"}
    out = {"queued": 0, "uploaded": 0, "invalid": 0}
    for s in status.values():
        name = CRACK_STATUS.get(s, "queued")
        out[name] = out.get(name, 0) + 1
    return {k: str(v) for k, v in out.items()}


def _wpa_potfile():
    """{bssid: (essid, password)} parsed from wpa-sec.cracked.potfile (bssid:station_mac:essid:password lines)."""
    out = {}
    try:
        with open(os.path.join(_handshake_dir(), "wpa-sec.cracked.potfile"), errors="ignore") as fp:
            for line in fp:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 4 and BSSID_HEX.fullmatch(parts[0]):
                    out[parts[0].lower()] = (parts[2], parts[3])
    except OSError:
        pass
    return out


def _crack_rows_impl(limit):
    d = _handshake_dir()
    try:
        entries = [(e.name, e.stat().st_mtime) for e in os.scandir(d)
                   if e.is_file() and e.name.endswith((".pcap", ".pcapng"))]
    except OSError:
        return []
    entries.sort(key=lambda e: -e[1])
    pot = _wpa_potfile()
    db_status = _wpa_db_status()
    have_db = db_status is not None
    db_base = {os.path.basename(k): v for k, v in db_status.items()} if have_db else {}
    rows = []
    for name, mtime in entries[:limit]:
        m = HANDSHAKE_RE.match(name)
        essid, bssid = (m.group(1), m.group(2).lower()) if m else (os.path.splitext(name)[0], None)
        if bssid and bssid in pot:
            pot_essid, password = pot[bssid]
            rows.append({"file": name, "name": pot_essid or essid or "(hidden)", "bssid": bssid,
                         "status": "cracked", "password": password, "time": mtime})
            continue
        code = db_base.get(name)
        status = CRACK_STATUS.get(code, "queued") if code is not None else ("queued" if have_db else "unknown")
        rows.append({"file": name, "name": essid or "(hidden)", "bssid": bssid, "status": status,
                     "password": None, "time": mtime})
    return rows


def crack_rows(limit=300):
    """One row per captured handshake (newest first): file, name, bssid, status, password (if cracked)."""
    return _cached(("crack-rows", limit), 5, lambda: _crack_rows_impl(limit))


def crack_summary(rows=None):
    """{"total", "cracked", "uploaded", "queued", "invalid", "unknown"} counted from crack_rows()."""
    rows = crack_rows() if rows is None else rows
    out = {"total": len(rows), "cracked": 0, "uploaded": 0, "queued": 0, "invalid": 0, "unknown": 0}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def _crack_summary_text(summary):
    if summary["total"] == 0:
        return "no handshakes yet"
    if summary["unknown"]:
        return "%d cracked of %d  \u00b7  wpa-sec plugin not active" % (summary["cracked"], summary["total"])
    if summary["queued"] or summary["uploaded"] or summary["invalid"]:
        return "%d cracked of %d  \u00b7  %d queued  %d invalid" % (summary["cracked"], summary["total"], summary["queued"], summary["invalid"])
    return "%d cracked of %d handshakes" % (summary["cracked"], summary["total"])


# ---------------------------------------------------------------- radar (display-only ranking, never touches attacks)
RADAR_MAX = 60      # networks kept, best first


def _ap_score(ap, captured):
    """A rough 'worth attacking' score from what pwnagotchi already knows about an access point: a closer signal and
    more clients mean more chances at a handshake; one already captured, or WPA3-only, counts against it. Display
    only: nothing here changes what bettercap actually attacks."""
    rssi = ap.get("rssi")
    sig = max(0.0, min(1.0, (rssi + 90) / 60.0)) if isinstance(rssi, (int, float)) else 0.3
    score = sig * 40 + min(len(ap.get("clients") or []), 5) * 12
    if (ap.get("mac") or "").lower().replace(":", "") in captured:
        score -= 60
    if "WPA3" in (ap.get("encryption") or "").upper():
        score -= 15
    return round(score, 1)


def _radar_summary_text(rows, age):
    if not rows:
        return "no networks seen yet"
    if age is not None and age > 120:
        return "%d networks (scan is %d minutes old)" % (len(rows), int(age // 60))
    best = rows[0]
    return "%d networks  ·  best: %s (%d clients)" % (len(rows), best["name"], best["clients"])


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


def _stardate():
    """A made-up 'stardate' from the calendar, like 26264.4 (year since 2000, thousandths of the year, tenths of the day)."""
    lt = time.localtime()
    days = 366 if (lt.tm_year % 4 == 0 and (lt.tm_year % 100 != 0 or lt.tm_year % 400 == 0)) else 365
    return "%d.%d" % ((lt.tm_year - 2000) * 1000 + lt.tm_yday * 1000 // days, (lt.tm_hour * 60 + lt.tm_min) * 10 // 1440)


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
        if key == "stardate":
            return _stardate()
        if key in ("queued", "uploaded", "invalid"):
            return _cached("wpa-counts", 20, _wpa_db_counts).get(key, "n/a")
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


# ------------------------------------------------------------------ scenery
# A "scene" effect paints a landscape behind the ink: mountains, sea, forest... The still part is drawn once (at double
# size, then scaled down for smooth edges) and cached; a few scenes also have a light moving layer (snow, waves, embers).
SS = 2


class _Cv:
    """A drawing surface at double size, starting from the theme's own background."""

    def __init__(self, base):
        self.w, self.h = base.size
        self.im = base.resize((self.w * SS, self.h * SS), Image.BICUBIC)
        self.d = ImageDraw.Draw(self.im)

    def poly(self, pts, color):
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=color)

    def circle(self, x, y, r, color):
        self.d.ellipse(((x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS), fill=color)

    def rect(self, x0, y0, x1, y1, color):
        self.d.rectangle((x0 * SS, y0 * SS, x1 * SS - 1, y1 * SS - 1), fill=color)

    def line(self, pts, color, width=1):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=color, width=max(1, int(width * SS)))

    def glow(self, x, y, r, color, spread, peak=0.85):
        """A soft light: full strength up to r, fading out over `spread` pixels."""
        x0, y0 = int(max(0, (x - r - spread) * SS)), int(max(0, (y - r - spread) * SS))
        x1, y1 = int(min(self.w * SS, (x + r + spread) * SS)), int(min(self.h * SS, (y + r + spread) * SS))
        if x1 <= x0 or y1 <= y0:
            return
        reg = np.asarray(self.im.crop((x0, y0, x1, y1))).astype(np.float32)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dist = np.hypot(xx - x * SS, yy - y * SS) / SS
        a = (np.clip(1 - (dist - r) / spread, 0, 1) ** 2 * peak)[..., None]
        reg = reg * (1 - a) + np.array(color, np.float32) * a
        self.im.paste(Image.fromarray(reg.astype(np.uint8), "RGB"), (x0, y0))

    def out(self):
        return self.im.resize((self.w, self.h), Image.LANCZOS)


def _ridge(w, base, amp, seed, sharp=False, step=3):
    """Points along a hilly (or, with sharp, peaked) skyline."""
    rng = random.Random(seed)
    comps = [(f, rng.uniform(0, 6.283), a) for f, a in ((0.011, 1.0), (0.027, 0.5), (0.061, 0.22), (0.13, 0.1))]
    pts = []
    for x in range(-step, w + 2 * step, step):
        v = 0.0
        for f, p, a in comps:
            s = math.sin(x * f + p)
            v += a * (1 - abs(s) * 2) if sharp else a * s
        pts.append((x, base - amp * v / 1.8))
    return pts


def _ry(pts, x):
    """Height of a skyline at x (the nearest sampled point)."""
    return min(pts, key=lambda p: abs(p[0] - x))[1]


def _under(c, pts, color, bottom=None):
    bottom = c.h + 4 if bottom is None else bottom
    c.poly(pts + [(pts[-1][0], bottom), (pts[0][0], bottom)], color)


def _caps(c, pts, level, color):
    """Snow on every part of a skyline that rises above `level` (one polygon per peak)."""
    run = []
    for x, y in pts + [(pts[-1][0] + 1, level + 1)]:
        if y < level:
            run.append((x, y))
        elif run:
            if len(run) > 1:
                c.poly(run + [(px, y0 + (level - y0) * 0.85) for px, y0 in run[::-1]], color)
            run = []


def _tree(c, x, y, h, color, wide=0.38):
    """A pine: stacked triangles standing on (x, y)."""
    for i in range(3):
        top = y - h + i * h * 0.26
        half = h * wide * (0.55 + 0.25 * i)
        c.poly([(x, top), (x - half, top + h * 0.42), (x + half, top + h * 0.42)], color)
    c.rect(x - h * 0.05, y - h * 0.08, x + h * 0.05, y + 2, color)


def _bare_tree(c, x, y, h, color, seed=1):
    rng = random.Random(seed)
    c.line([(x, y), (x, y - h)], color, 3)

    def branch(bx, by, ang, ln, depth):
        ex, ey = bx + math.cos(ang) * ln, by - math.sin(ang) * ln
        c.line([(bx, by), (ex, ey)], color, max(1, depth * 0.8))
        if depth > 1:
            branch(ex, ey, ang + rng.uniform(0.3, 0.8), ln * 0.68, depth - 1)
            branch(ex, ey, ang - rng.uniform(0.3, 0.8), ln * 0.68, depth - 1)
    branch(x, y - h * 0.45, 1.9, h * 0.42, 4)
    branch(x, y - h * 0.62, 1.2, h * 0.4, 4)
    branch(x, y - h, 1.57, h * 0.3, 3)


def _cloud(c, x, y, s, color):
    for dx, dy, r in ((0, 0, 9), (11, -5, 12), (24, 0, 10), (12, 3, 10)):
        c.circle(x + dx * s, y + dy * s, r * s, color)


def _sun(c, x, y, r, color, halo, spread=60, peak=0.5):
    c.glow(x, y, r, halo, spread, peak)
    c.circle(x, y, r, color)


def _scene_mountains(c, snow=(232, 240, 250)):
    w, h = c.w, c.h
    _sun(c, 388, 78, 22, (255, 246, 214), (255, 226, 160))
    far = _ridge(w, 190, 78, 11, True)
    _under(c, far, (74, 96, 132))
    _caps(c, far, 138, snow)
    mid = _ridge(w, 226, 58, 5, True)
    _under(c, mid, (44, 62, 92))
    _caps(c, mid, 186, (170, 190, 214))
    near = _ridge(w, 268, 32, 23)
    _under(c, near, (20, 30, 46))
    for x in (46, 96, 330, 388, 440):
        y = min(p[1] for p in near if abs(p[0] - x) < 4) + 3
        _tree(c, x, y, 28 + (x % 3) * 5, (11, 20, 30))


def _scene_glacier(c):
    w = c.w
    c.glow(120, 70, 8, (190, 235, 255), 90, 0.35)
    far = _ridge(w, 200, 84, 4, True)
    _under(c, far, (58, 116, 150))
    _caps(c, far, 150, (236, 250, 255))
    near = _ridge(w, 246, 56, 9, True)
    _under(c, near, (30, 76, 108))
    _caps(c, near, 205, (188, 226, 244))
    ice = _ridge(w, 282, 14, 15)
    _under(c, ice, (16, 44, 68))


def _scene_ocean(c):
    w, h = c.w, c.h
    hor = 176
    _sun(c, 330, hor - 6, 24, (255, 232, 176), (255, 196, 128), 90, 0.55)
    c.rect(0, hor, w, h + 2, (6, 58, 92))
    for i in range(9):   # a band of lighter water below the horizon, fading down
        y = hor + i * 13
        c.rect(0, y, w, y + 13, _mixc((8, 74, 112), (5, 40, 70), i / 9))
    c.glow(330, hor + 40, 6, (255, 214, 150), 70, 0.22)
    far = _ridge(w, hor + 2, 14, 3)
    _under(c, [(x, min(y, hor + 1)) for x, y in far], (18, 46, 74), hor + 2)
    c.rect(0, hor, w, hor + 1, (150, 200, 220))


def _scene_forest(c):
    w, h = c.w, c.h
    c.glow(370, 70, 20, (200, 230, 200), 70, 0.4)
    c.circle(370, 70, 20, (226, 244, 222))
    back = _ridge(w, 214, 26, 8)
    _under(c, back, (14, 52, 36))
    for x in range(-10, w + 20, 21):
        y = _ry(back, x) + 6
        _tree(c, x, y, 40 + (x * 7) % 14, (12, 44, 30))
    front = _ridge(w, 262, 16, 19)
    _under(c, front, (8, 32, 22))
    for x in range(8, w, 27):
        y = _ry(front, x) + 8
        _tree(c, x, y, 56 + (x * 11) % 22, (5, 22, 15))


def _scene_desert(c):
    w, h = c.w, c.h
    _sun(c, 340, 168, 30, (255, 214, 140), (255, 160, 90), 110, 0.6)
    _under(c, _ridge(w, 206, 16, 6), (150, 68, 46))
    _under(c, _ridge(w, 238, 20, 2), (112, 48, 40))
    near = _ridge(w, 276, 22, 12)
    _under(c, near, (62, 26, 34))
    for x, s in ((60, 1.0), (392, 1.25)):
        y = _ry(near, x) + 6
        col = (30, 12, 24)
        c.rect(x - 3 * s, y - 42 * s, x + 3 * s, y, col)
        c.rect(x - 14 * s, y - 28 * s, x - 9 * s, y - 14 * s, col)
        c.rect(x - 14 * s, y - 16 * s, x - 3 * s, y - 12 * s, col)
        c.rect(x + 9 * s, y - 34 * s, x + 14 * s, y - 20 * s, col)
        c.rect(x + 3 * s, y - 22 * s, x + 14 * s, y - 18 * s, col)


def _scene_aurora(c):
    w = c.w
    far = _ridge(w, 230, 46, 7, True)
    _under(c, far, (8, 26, 34))
    _caps(c, far, 200, (60, 100, 110))
    _under(c, _ridge(w, 268, 20, 3), (3, 12, 18))


def _scene_volcano(c):
    w, h = c.w, c.h
    c.glow(300, 140, 10, (255, 100, 30), 120, 0.45)
    _under(c, _ridge(w, 240, 26, 3, True), (30, 10, 10))
    c.poly([(140, 300), (258, 156), (300, 148), (342, 156), (460, 300)], (34, 12, 12))
    c.d.ellipse((272 * SS, 141 * SS, 328 * SS, 158 * SS), fill=(255, 112, 32))
    c.d.ellipse((282 * SS, 144 * SS, 318 * SS, 154 * SS), fill=(255, 190, 90))
    for x0, sway, x1 in ((296, -8, 262), (304, 10, 340), (300, 2, 296)):
        pts = [(x0 + sway * math.sin(i * 0.9) * (i / 9), 154 + i * 16.5) for i in range(9)]
        pts[-1] = (x1, 300)
        c.line(pts, (255, 96, 24), 2)
        c.line(pts, (255, 170, 60), 1)
    c.glow(300, 152, 4, (255, 140, 50), 50, 0.35)
    _under(c, _ridge(w, 294, 9, 6), (14, 4, 4))


def _scene_winter(c):
    w, h = c.w, c.h
    c.glow(416, 56, 16, (200, 220, 245), 60, 0.35)
    c.circle(416, 56, 16, (232, 240, 252))
    far = _ridge(w, 214, 30, 5)
    _under(c, far, (58, 88, 128))
    for x in range(30, w, 62):
        y = _ry(far, x) + 4
        _tree(c, x, y, 34 + (x % 3) * 6, (24, 60, 62))
    near = _ridge(w, 262, 22, 9)
    _under(c, near, (86, 114, 158))
    for x in (60, 380, 430):
        y = _ry(near, x) + 6
        _tree(c, x, y, 52, (14, 44, 46))


def _scene_spring(c):
    w, h = c.w, c.h
    _sun(c, 420, 62, 20, (255, 246, 190), (255, 240, 170), 60, 0.4)
    for x, y, s in ((250, 150, 0.9), (330, 100, 1.0), (120, 170, 1.2)):
        _cloud(c, x, y, s, (208, 232, 232))
    _under(c, _ridge(w, 208, 24, 3), (54, 122, 84))
    near = _ridge(w, 246, 20, 8)
    _under(c, near, (34, 96, 62))
    rng = random.Random(4)
    for i in range(70):
        x = rng.randrange(0, w)
        y = _ry(near, x) + rng.randrange(6, 56)
        c.circle(x, y, 1.6, rng.choice(((255, 158, 203), (255, 236, 130), (255, 255, 255), (198, 160, 255))))


def _scene_summer(c):
    w, h = c.w, c.h
    hor = 190
    for i in range(6):
        c.rect(0, hor - 60 + i * 10, w, hor - 50 + i * 10, _mixc((250, 200, 90), (120, 200, 230), i / 6))
    _sun(c, 250, hor - 4, 38, (255, 244, 170), (255, 224, 120), 120, 0.5)
    c.rect(0, hor, w, h + 2, (18, 130, 158))
    c.rect(0, hor, w, hor + 1, (210, 240, 245))
    beach = _ridge(w, 284, 14, 5)
    _under(c, beach, (150, 112, 66))
    _under(c, _ridge(w, 300, 6, 2), (118, 84, 48))
    for x, y, lean in ((72, 292, 1), (420, 290, -1)):   # two palms
        c.line([(x, y), (x + 8 * lean, y - 48), (x + 4 * lean, y - 78)], (74, 44, 22), 4)
        top = (x + 4 * lean, y - 78)
        for ang in (0.3, 0.9, 1.6, 2.3, 2.9):
            ex, ey = top[0] + math.cos(ang) * 30, top[1] - math.sin(ang) * 14 + 10
            c.poly([top, (top[0] + math.cos(ang) * 16, top[1] - math.sin(ang) * 16 - 4), (ex, ey)], (24, 92, 58))


def _scene_autumn(c):
    w, h = c.w, c.h
    _sun(c, 372, 150, 26, (255, 178, 84), (255, 130, 60), 100, 0.5)
    _under(c, _ridge(w, 214, 26, 6), (108, 44, 20))
    near = _ridge(w, 262, 18, 14)
    _under(c, near, (58, 24, 12))
    for x, h_ in ((70, 96), (150, 70), (410, 88)):
        y = _ry(near, x) + 8
        _bare_tree(c, x, y, h_, (30, 12, 6), seed=x)
        rng = random.Random(x)
        for _ in range(26):
            c.circle(x + rng.uniform(-h_ * .42, h_ * .42), y - h_ * rng.uniform(.5, 1.05), 2.2, rng.choice(((214, 96, 24), (232, 150, 40), (176, 52, 20))))


def _scene_halloween(c):
    w, h = c.w, c.h
    c.glow(420, 44, 30, (255, 168, 70), 90, 0.4)
    c.circle(420, 44, 30, (255, 196, 96))
    for dx, dy, r in ((-9, -7, 5), (7, 5, 7), (-3, 12, 4)):
        c.circle(420 + dx, 44 + dy, r, (236, 168, 76))
    _under(c, _ridge(w, 244, 20, 3), (38, 12, 54))
    near = _ridge(w, 276, 14, 11)
    _under(c, near, (16, 4, 26))
    _bare_tree(c, 80, 286, 130, (10, 2, 16), seed=3)
    for x in (300, 340, 390):
        y = _ry(near, x) + 8
        c.poly([(x - 6, y), (x - 6, y - 16), (x, y - 22), (x + 6, y - 16), (x + 6, y)], (30, 12, 44))


def _scene_christmas(c):
    w, h = c.w, c.h
    c.circle(410, 60, 14, (250, 246, 220))
    far = _ridge(w, 226, 22, 4)
    _under(c, far, (24, 80, 52))
    near = _ridge(w, 268, 16, 10)
    _under(c, near, (120, 146, 168))
    for x, hh in ((46, 88), (128, 64), (330, 76), (420, 96)):
        y = _ry(near, x) + 6
        _tree(c, x, y, hh, (14, 66, 40), 0.42)
        c.poly([(x, y - hh - 8), (x - 4, y - hh + 2), (x + 4, y - hh + 2)], (255, 214, 90))


def _scene_space(c):
    w, h = c.w, c.h
    for x, y, r, col in ((90, 240, 120, (58, 30, 110)), (400, 90, 90, (24, 52, 120)), (250, 150, 70, (86, 30, 90))):
        c.glow(x, y, 0, col, r, 0.42)
    px, py = 372, 200
    c.glow(px, py, 44, (110, 130, 255), 34, 0.3)
    c.circle(px, py, 44, (36, 40, 96))
    c.circle(px - 8, py - 10, 34, (52, 60, 130))
    c.circle(px - 18, py - 18, 18, (92, 108, 190))
    c.d.arc(((px - 78) * SS, (py - 14) * SS, (px + 78) * SS, (py + 14) * SS), 0, 360, fill=(150, 160, 230), width=3 * SS)
    c.circle(70, 120, 7, (150, 156, 200))


def _scene_startrek(c):
    w, h = c.w, c.h
    bars = ((0, 24, (255, 153, 0)), (26, 60, (204, 153, 204)), (62, 110, (153, 153, 255)), (112, 150, (255, 204, 153)),
            (152, 200, (204, 102, 102)), (202, 250, (255, 153, 0)), (252, 290, (153, 153, 204)))
    for y0, y1, col in bars:
        c.rect(0, 18 + y0 * 0.95, 7, 18 + y1 * 0.95, col)
        c.rect(w - 7, 18 + y0 * 0.95, w, 18 + y1 * 0.95, col)
    c.circle(300, 230, 46, (30, 30, 60))
    c.circle(292, 222, 40, (46, 50, 100))
    c.d.arc((232 * SS, 210 * SS, 368 * SS, 250 * SS), 190, 350, fill=(204, 153, 204), width=2 * SS)


def _scene_city(c):
    w, h = c.w, c.h
    rng = random.Random(9)
    for layer, (base, col, wins) in enumerate(((236, (26, 10, 60), (120, 40, 140)), (272, (12, 4, 34), (0, 200, 220)))):
        x = 0
        while x < w:
            bw = rng.randrange(22, 46)
            bh = rng.randrange(40, 120) if layer == 0 else rng.randrange(20, 76)
            c.rect(x, base - bh, x + bw, h + 2, col)
            for wy in range(int(base - bh + 6), base - 4, 9):
                for wx in range(x + 4, x + bw - 4, 7):
                    if rng.random() < 0.28:
                        c.rect(wx, wy, wx + 3, wy + 4, wins)
            x += bw + rng.randrange(0, 5)
    c.rect(0, 282, w, h + 2, (8, 2, 24))
    c.rect(0, 282, w, 283, (255, 42, 109))


def _scene_vaporwave(c):
    w, h = c.w, c.h
    hor = 206
    c.glow(240, hor - 20, 60, (255, 90, 190), 90, 0.5)
    c.circle(240, hor - 20, 58, (255, 140, 120))
    for i in range(7):    # stripes cut into the sun
        y = hor - 40 + i * 9
        c.rect(170, y, 310, y + 1.5 + i * 0.6, (43, 15, 84))
    c.rect(0, hor, w, h + 2, (26, 8, 60))
    c.rect(0, hor, w, hor + 1, (1, 205, 254))
    for i in range(-12, 13):   # the floor grid's lines, fanning out from the horizon
        c.line([(240 + i * 8, hor), (240 + i * 60, h)], (84, 30, 136), 1)


def _scene_bloodmoon(c):
    w, h = c.w, c.h
    c.glow(370, 96, 44, (190, 20, 16), 120, 0.55)
    c.circle(370, 96, 44, (206, 30, 24))
    c.circle(358, 84, 40, (236, 56, 40))
    _under(c, _ridge(w, 246, 26, 8, True), (62, 8, 10))
    near = _ridge(w, 280, 12, 4)
    _under(c, near, (28, 4, 4))
    _bare_tree(c, 410, 284, 110, (8, 0, 0), seed=8)
    for x in (60, 100, 140):
        y = _ry(near, x) + 8
        c.poly([(x - 5, y), (x - 5, y - 18), (x, y - 24), (x + 5, y - 18), (x + 5, y)], (22, 4, 4))


def _scene_pixel(c):
    """Hills and clouds in blocks, in the four greens of an old handheld."""
    w, h = c.w, c.h
    g0, g1, g2 = (155, 188, 15), (139, 172, 15), (48, 98, 48)
    for x, y in ((60, 60), (240, 44), (380, 76)):
        for dx, dy, ww in ((0, 8, 44), (8, 0, 28), (0, 16, 52)):
            c.rect(x + dx, y + dy, x + dx + ww, y + dy + 8, g1)
    for x in range(0, w, 8):
        top = 226 - int(20 * math.sin(x * 0.02) + 12 * math.sin(x * 0.055 + 1))
        c.rect(x, top - top % 8, x + 8, h, g1)
    for x in range(0, w, 8):
        top = 268 - int(10 * math.sin(x * 0.03 + 2))
        c.rect(x, top - top % 8, x + 8, h, g2)


SCENES = {"mountains": _scene_mountains, "glacier": _scene_glacier, "ocean": _scene_ocean, "forest": _scene_forest,
          "desert": _scene_desert, "aurora": _scene_aurora, "volcano": _scene_volcano, "winter": _scene_winter,
          "spring": _scene_spring, "summer": _scene_summer, "autumn": _scene_autumn, "halloween": _scene_halloween,
          "christmas": _scene_christmas, "space": _scene_space, "startrek": _scene_startrek, "city": _scene_city,
          "vaporwave": _scene_vaporwave, "bloodmoon": _scene_bloodmoon, "pixel": _scene_pixel}


# ---- the moving layers (drawn at normal size onto the cached scene, every animation frame)
def _blend_px(img, d, x, y, color, k, size=1):
    x, y = int(x), int(y)
    if 0 <= x < img.width - size and 0 <= y < img.height - size:
        under = img.getpixel((x, y))
        d.rectangle((x, y, x + size - 1, y + size - 1), fill=tuple(int(under[j] + (color[j] - under[j]) * k) for j in range(3)))


def _particles(n, seed, w, h):
    rng = random.Random(seed)
    return _memo(("scene-pts", n, seed, w, h), (), lambda: [(rng.random() * w, rng.random() * h, rng.random()) for _ in range(n)])


def _dyn_snow(img, d, w, h, t, sp, count=70, color=(240, 246, 255)):
    for x, y, r in _particles(count, 5, w, h):
        fall = 8 + 16 * r
        yy = (y + t * fall * sp) % h
        xx = x + math.sin(t * 0.7 * sp + r * 20) * 6
        _blend_px(img, d, xx, yy, color, 0.55 + 0.4 * r, 2 if r > 0.7 else 1)


def _dyn_waves(img, d, w, h, t, sp, top=178, color=(150, 205, 225)):
    for i in range(8):
        y0 = top + 8 + i * 15 + i * i
        amp = 1 + i * 0.35
        pts = [(x, y0 + math.sin(x * (0.03 - i * 0.002) + t * sp * (1.2 + i * 0.15) + i * 2) * amp) for x in range(0, w + 8, 8)]
        col = _mixc(color, (10, 60, 90), i / 9)
        d.line(pts, fill=col, width=1)


def _dyn_embers(img, d, w, h, t, sp):
    for x, y, r in _particles(36, 6, 60, 200):
        yy = 150 - ((t * (10 + 20 * r) * sp + y) % 200)
        xx = 300 + (x - 30) * (1 + (150 - yy) / 90) + math.sin(t * sp + r * 9) * 6
        if 8 < yy < 160:
            k = min(1.0, (yy - 8) / 60)
            _blend_px(img, d, xx, yy, (255, 150 + int(90 * (1 - k)), 40), 0.9 * k, 2)
    pulse = 0.5 + 0.5 * math.sin(t * sp * 1.5)
    ov = Image.new("RGBA", (70, 30), (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse((10, 8, 60, 22), fill=(255, 200, 110, int(50 + 90 * pulse)))
    ov = ov.filter(ImageFilter.GaussianBlur(4))
    img.paste(ov, (300 - 35, 142 - 8), ov)


def _dyn_leaves(img, d, w, h, t, sp):
    for x, y, r in _particles(34, 7, w, h):
        yy = (y + t * (12 + 14 * r) * sp) % h
        xx = x + math.sin(t * 1.1 * sp + r * 30) * 14 + (t * 6 * sp)
        _blend_px(img, d, xx % w, yy, ((214, 96, 24), (232, 150, 40), (176, 52, 20))[int(r * 3) % 3], 0.9, 3)


def _dyn_fireflies(img, d, w, h, t, sp):
    for x, y, r in _particles(26, 8, w, h * 0.45):
        y += h * 0.5
        b = max(0.0, math.sin(t * sp * 1.3 + r * 40))
        _blend_px(img, d, x + math.sin(t * 0.5 * sp + r * 9) * 8, y + math.cos(t * 0.4 * sp + r * 7) * 6, (222, 255, 120), b * 0.9, 2)


def _dyn_aurora(img, d, w, h, t, sp):
    """Soft curtains of light, drawn at half size and blurred so they look like light and not stripes."""
    hw, hh = w // 2, h // 2
    ov = Image.new("RGBA", (hw, hh), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for band, (col, y0) in enumerate((((50, 255, 140), 30), ((140, 90, 255), 44), ((50, 210, 200), 22))):
        for x in range(0, hw, 2):
            sway = math.sin(x * 0.034 + t * sp * 0.5 + band * 2) * 14 + math.sin(x * 0.09 - t * sp * 0.8) * 4
            length = 42 + 20 * math.sin(x * 0.05 + t * sp * 0.3 + band)
            for j in range(4):
                a = int(62 * (1 - j / 4) * (0.6 + 0.4 * math.sin(x * 0.12 + band)))
                od.line([(x, y0 + sway + j * length / 4), (x, y0 + sway + (j + 1) * length / 4)], fill=col + (a,), width=2)
    ov = ov.filter(ImageFilter.GaussianBlur(1.6)).resize((w, h), Image.BILINEAR)
    img.paste(ov, (0, 0), ov)


def _dyn_warp(img, d, w, h, t, sp):
    cx, cy = 240, 160
    for x, y, r in _particles(34, 9, 1, 1):
        ang = (x * 6.283) + r
        p = (t * sp * 0.25 + y) % 1.0
        r0, r1 = 20 + p * p * 300, 20 + min(1.0, p * 1.15) ** 2 * 300
        k = 0.15 + 0.7 * p
        col = tuple(int(c * k) for c in (200, 210, 255))
        d.line([(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0 * 0.7), (cx + math.cos(ang) * r1, cy + math.sin(ang) * r1 * 0.7)], fill=col, width=1)


CHRISTMAS_TREES = ((46, 88), (128, 64), (330, 76), (420, 96))


def _dyn_lights(img, d, w, h, t, sp):
    cols = ((255, 60, 60), (255, 214, 90), (90, 200, 255), (120, 255, 140))
    near = _memo(("xmas-ridge", w), (), lambda: _ridge(w, 268, 16, 10))
    n = 0
    for x, hh in CHRISTMAS_TREES:
        base = _ry(near, x) + 6
        for k in range(8):
            y = base - hh * (k + 1.4) / 10.5
            half = hh * 0.36 * (1 - k / 9.5)
            xx = x + math.sin(k * 2.7 + x) * half
            b = 0.5 + 0.5 * math.sin(t * sp * 2 + n * 1.9)
            _blend_px(img, d, xx, y, cols[n % 4], 0.3 + 0.7 * b, 2)
            n += 1


def _dyn_bats(img, d, w, h, t, sp):
    for i in range(3):
        x = (t * (30 + i * 12) * sp + i * 170) % (w + 60) - 30
        y = 60 + i * 34 + math.sin(t * 2 * sp + i) * 10
        flap = math.sin(t * 9 * sp + i) * 4
        d.line([(x - 9, y - flap), (x - 4, y - 2), (x, y), (x + 4, y - 2), (x + 9, y - flap)], fill=(12, 2, 20), width=2)


def _dyn_grid(img, d, w, h, t, sp):
    hor = 206
    for i in range(8):     # the floor lines glide toward you
        p = ((i + t * sp * 0.4) % 8) / 8
        y = hor + (h - hor) * p * p
        d.line([(0, y), (w, y)], fill=(110, 44, 170), width=1)


DYNAMIC = {"winter": _dyn_snow, "glacier": lambda *a: _dyn_snow(*a, count=40), "christmas": lambda *a: (_dyn_snow(*a, count=60), _dyn_lights(*a)),
           "mountains": lambda *a: _dyn_snow(*a, count=30), "ocean": _dyn_waves,
           "summer": lambda *a: _dyn_waves(*a, top=190, color=(120, 200, 215)), "volcano": _dyn_embers, "autumn": _dyn_leaves,
           "forest": _dyn_fireflies, "aurora": _dyn_aurora, "startrek": _dyn_warp, "halloween": _dyn_bats, "vaporwave": _dyn_grid}
ANIM_SCENES = set(DYNAMIC)


def _scene_still(theme, kind, w, h, strength):
    def make():
        base = _base(theme, w, h)
        c = _Cv(base)
        SCENES[kind](c)
        out = c.out()
        return Image.blend(base, out, strength) if strength < 1 else out
    return _memo(("scene", id(theme), kind, w, h, strength), (theme,), make, cap=12)


def _scene_apply(theme, e, w, h, t):
    """The theme's background with its scenery painted in, ready for the rest of the effects."""
    kind, strength = e["kind"], e.get("strength", 1.0)
    img = _scene_still(theme, kind, w, h, strength).copy()
    if kind in DYNAMIC:
        DYNAMIC[kind](img, ImageDraw.Draw(img), w, h, t, e.get("speed", 3) / 3.0)
    return img


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
    img = _scene_apply(theme, fx["scene"], w, h, t) if "scene" in fx else _base(theme, w, h)

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


# ------------------------------------------------------------ backup, restore and face uploads
BACKUP_MAX_BYTES = 20 * 1024 * 1024
BACKUP_MAX_ENTRIES = 500
THEME_MAX_BYTES = 256 * 1024
FACE_MAX_BYTES = 1024 * 1024
FACE_MAX_SIZE = (480, 320)
FACE_NAMES = tuple(m for m in MOODS if m != "handshake") + ("default",)
FACE_EXTS = (".png", ".gif", ".jpg", ".jpeg", ".webp")
THEME_ENTRY = re.compile(r"themes/([A-Za-z0-9_\- ]{1,32})\.json")
FACE_ENTRY = re.compile(r"faces/([A-Za-z0-9_\-]{1,32})/([a-z_]+)\.(png|gif)")


def make_backup():
    """A zip (as bytes) with the user's themes and face packs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        try:
            for name in sorted(os.listdir(THEME_DIR)):
                if name.endswith(".json") and name not in STATE_FILES and THEME_ENTRY.fullmatch("themes/" + name):
                    z.write(os.path.join(THEME_DIR, name), "themes/" + name)
        except OSError:
            pass
        for pack in list_packs():
            for f in sorted(os.listdir(os.path.join(FACES_DIR, pack))):
                if FACE_ENTRY.fullmatch("faces/%s/%s" % (pack, f)):
                    z.write(os.path.join(FACES_DIR, pack, f), "faces/%s/%s" % (pack, f))
    return buf.getvalue()


def store_face(pack, filename, data, overwrite=True):
    """Validate an uploaded image and save it as faces/<pack>/<mood>.png|gif. Returns 'added', 'replaced' or 'skipped'.
    Raises ValueError with a reason for anything that is not a usable face."""
    if not PACK_RE.fullmatch(str(pack)):
        raise ValueError("pack names use letters, digits, _ and - (max 32)")
    stem, ext = os.path.splitext(os.path.basename(str(filename)).lower())
    if stem not in FACE_NAMES:
        raise ValueError("%s: name the file after a mood (%s, ...) or 'default'" % (filename, ", ".join(FACE_NAMES[:4])))
    if ext not in FACE_EXTS:
        raise ValueError("%s: use png, gif, jpg or webp" % filename)
    if len(data) > FACE_MAX_BYTES:
        raise ValueError("%s: larger than %d KB" % (filename, FACE_MAX_BYTES // 1024))
    try:
        Image.open(io.BytesIO(data)).verify()
        im = Image.open(io.BytesIO(data))
        frames = getattr(im, "n_frames", 1)
    except Exception:
        raise ValueError("%s: not a readable image" % filename)
    if im.width > FACE_MAX_SIZE[0] * 2 or im.height > FACE_MAX_SIZE[1] * 2 or frames > 60:
        raise ValueError("%s: too big (max %dx%d, 60 frames)" % (filename, FACE_MAX_SIZE[0], FACE_MAX_SIZE[1]))
    animated = ext == ".gif" and frames > 1
    if animated and (im.width > FACE_MAX_SIZE[0] or im.height > FACE_MAX_SIZE[1]):
        raise ValueError("%s: an animated gif must be at most %dx%d" % (filename, FACE_MAX_SIZE[0], FACE_MAX_SIZE[1]))
    folder = os.path.join(FACES_DIR, pack)
    target = os.path.join(folder, stem + (".gif" if animated else ".png"))
    other = os.path.join(folder, stem + (".png" if animated else ".gif"))
    existed = os.path.exists(target) or os.path.exists(other)
    if existed and not overwrite:
        return "skipped"
    os.makedirs(folder, exist_ok=True)
    tmp = target + ".%d.tmp" % os.getpid()
    if animated:
        with open(tmp, "wb") as fp:
            fp.write(data)
    else:
        im = im.convert("RGBA")
        im.thumbnail(FACE_MAX_SIZE)
        im.save(tmp, "PNG")
    os.replace(tmp, target)
    if os.path.exists(other):
        os.remove(other)          # a png and a gif for one mood would be confusing (the gif would win)
    return "replaced" if existed else "added"


def delete_pack(pack):
    if not PACK_RE.fullmatch(str(pack)):
        raise ValueError("bad pack name")
    folder = os.path.join(FACES_DIR, pack)
    if not os.path.isdir(folder) or os.path.islink(folder):
        return False
    shutil.rmtree(folder)
    return True


def restore_backup(data, overwrite=False):
    """Put themes and face packs from a backup zip back. Only well-formed entries are read, and their names are matched
    against strict patterns (never used as paths), so a hostile zip cannot write anywhere else. Returns a report."""
    report = {"added": [], "skipped": [], "invalid": []}
    if len(data) > BACKUP_MAX_BYTES:
        raise ValueError("the backup is larger than %d MB" % (BACKUP_MAX_BYTES // 1024 // 1024))
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("that is not a zip file")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > BACKUP_MAX_ENTRIES or sum(i.file_size for i in infos) > BACKUP_MAX_BYTES:
        raise ValueError("the backup has too many or too large files")
    for info in infos:
        name = info.filename
        theme, face = THEME_ENTRY.fullmatch(name), FACE_ENTRY.fullmatch(name)
        try:
            if (theme and info.file_size > THEME_MAX_BYTES) or (face and info.file_size > FACE_MAX_BYTES):
                report["invalid"].append(name + " (too large)")      # checked before anything is read into memory
                continue
            if theme:
                stem = theme.group(1)
                if stem in BUILTIN:
                    report["skipped"].append(name + " (a built-in name)")
                    continue
                cleaned = _clean(json.loads(z.read(info).decode("utf-8")))
                path = os.path.join(THEME_DIR, stem + ".json")
                if os.path.exists(path) and not overwrite:
                    report["skipped"].append(name + " (already there)")
                    continue
                os.makedirs(THEME_DIR, exist_ok=True)
                write_json(path, cleaned, indent=2)
                report["added"].append(name)
            elif face:
                result = store_face(face.group(1), "%s.%s" % (face.group(2), face.group(3)), z.read(info), overwrite)
                if result == "skipped":
                    report["skipped"].append(name + " (already there)")
                else:
                    report["added"].append(name)
            else:
                report["invalid"].append(name + " (not a theme or face file)")
        except (ValueError, UnicodeDecodeError, zipfile.BadZipFile) as e:
            report["invalid"].append("%s (%s)" % (name, e))
    return report


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
    if CONTINUOUS & fx.keys() or ("scene" in fx and fx["scene"]["kind"] in ANIM_SCENES) or _rainbow_elements(theme) or any(l["scroll"] for l in theme.get("text", [])):
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
DISPLAY_FILE = os.path.join(THEME_DIR, "display.json")
SETTINGS_FILE = os.path.join(THEME_DIR, "settings.json")
ACHIEVEMENTS_FILE = os.path.join(THEME_DIR, "achievements.json")
LAYOUT_FILE = os.path.join(THEME_DIR, "layout.json")
LAYOUT_MAX = 200          # furthest an element can be moved, in pixels
LAYOUT_STEPS = (1, 5, 10)
EVENT = struct.Struct("@llHHi")            # struct input_event on 64-bit Linux (24 bytes)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BTN_TOUCH, ABS_X, ABS_Y = 0x14A, 0, 1
DOUBLE_TAP_S = 0.6        # max time between the two taps
DOUBLE_TAP_RAW = 900      # max distance between them, in raw units (range is 0-4095)
TAP_MAX_S = 0.8           # longer presses are not taps
SWIPE_RAW = 500           # a press that moves this far (raw units) is a swipe, not a tap
SWIPE_PX = 90             # a swipe changes theme if it covers this many screen pixels, mostly sideways
SWIPE_MAX_S = 1.2
TOAST_S = 1.5
TRY_MIN_S, TRY_MAX_S = 5, 600      # how long a temporary theme may be tried
OVERHEAT_GRACE_S = 30        # the on-screen countdown before an overheating Pi turns itself off
OVERHEAT_SNOOZE_S = 600      # a touch cancels the countdown and keeps it quiet for this long
WARN_HOLD_S = 10             # a low-power banner stays this long after the last under-voltage reading
DIM_STEPS = (1.0, 0.6, 0.3)     # what the dim button on the System tab cycles through
MENU_TIMEOUT = 20.0
CALIB_TIMEOUT = 60.0
ADJUST_TIMEOUT = 60.0
CALIB_POINTS = ((40, 40), (440, 40), (40, 280), (440, 280))
MENU_ROWS = 5
CONFIRM_S = 4.0          # a power button must be tapped twice within this time
GPS_TOKENS = ("gps", "lat", "lon", "sats")
STATUS_LINES = ("CPU {temp}  load {cpu}  RAM {mem}", "IP {ip}", "GPS {gps}  {lat} {lon}",
                "Up {uptime}  Power {power}  Bat {battery}", "Pwned {handshakes}  Cracked {cracked}  Session {session}")
TAB_NAMES = ("themes", "plugins", "system", "awards", "layout", "crack", "radar")
TAB_WINDOW = 4      # tabs shown at once before it needs '<'/'>' to see the rest
TAB_ARROW_W = 36
PROTECTED_PLUGINS = ('theme_manager',)   # never listed: switching it off would remove the menu itself


def tab_layout(scroll):
    """[(name, rect)] for the tabs currently visible, plus '<'/'>' rects (or None, None if they all fit)."""
    n = len(TAB_NAMES)
    if n <= TAB_WINDOW:
        w = 424 // n
        return [(name, (28 + i * w, 10, 28 + i * w + w - 4, 38)) for i, name in enumerate(TAB_NAMES)], None, None
    w = (424 - 2 * TAB_ARROW_W) // TAB_WINDOW
    x = 28 + TAB_ARROW_W
    tabs = []
    for i in range(TAB_WINDOW):
        tabs.append((TAB_NAMES[(scroll + i) % n], (x, 10, x + w - 4, 38)))
        x += w
    return tabs, (28, 10, 28 + TAB_ARROW_W - 4, 38), (x, 10, 452, 38)


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
    tab = menu.get("tab", "themes")
    return {"themes": menu["names"], "awards": menu["awards"], "layout": menu["layout"], "crack": menu["crack"],
            "radar": menu["radar"]}.get(tab, menu["plugins"])


def adjust_popup(menu):
    """Rectangle of the nudge popup: on the half of the screen away from the element being moved."""
    box = menu.get("box")
    y0 = 6 if box and (box[1] + box[3]) / 2 >= 160 else 218
    return (60, y0, 424, y0 + 96)


def adjust_hits(menu):
    x0, y0, x1, y1 = adjust_popup(menu)
    r1, r2 = y0 + 26, y0 + 62
    return [((x0 + 12, r1, x0 + 92, r1 + 30), ("nudge", (-1, 0))), ((x0 + 100, r1, x0 + 180, r1 + 30), ("nudge", (1, 0))),
            ((x0 + 188, r1, x0 + 268, r1 + 30), ("nudge", (0, -1))), ((x0 + 276, r1, x0 + 352, r1 + 30), ("nudge", (0, 1))),
            ((x0 + 12, r2, x0 + 122, r2 + 28), ("step", None)), ((x0 + 130, r2, x0 + 230, r2 + 28), ("reset1", None)),
            ((x0 + 238, r2, x0 + 352, r2 + 28), ("done", None))]


def menu_hits(menu):
    """[(rect, (action, arg))] for the current menu page, in upright screen pixels."""
    tab, page = menu.get("tab", "themes"), menu["page"]
    if menu["mode"] == "adjust":
        return adjust_hits(menu)
    tab_names, left, right = tab_layout(menu.get("tab_scroll", 0))
    tabs = [(rect, ("tab", name)) for name, rect in tab_names]
    if left:
        tabs += [(left, ("tabscroll", -1)), (right, ("tabscroll", 1))]
    common = [((220, 268, 320, 308), ("cal", None)), ((380, 268, 452, 308), ("close", None))] + tabs
    if tab == "system":
        return [((28, 268, 118, 308), ("refresh", None)), ((124, 268, 214, 308), ("dim", None)),
                ((28, 166, 236, 200), ("mode", None)), ((242, 166, 452, 200), ("overheat", None)), ((28, 208, 152, 248), ("power", "restart")),
                ((158, 208, 282, 248), ("power", "reboot")), ((288, 208, 412, 248), ("power", "shutdown"))] + common
    act = {"themes": "pick", "awards": "award", "layout": "adjust", "crack": "crackrow", "radar": "radrow"}.get(tab, "toggle")
    hits = [((28, 44 + i * 44, 452, 44 + i * 44 + 40), (act, n))
            for i, n in enumerate(menu_items(menu)[page * MENU_ROWS:(page + 1) * MENU_ROWS])]
    if tab == "layout":
        hits.append(((326, 268, 374, 308), ("resetall", None)))
    return hits + [((28, 268, 118, 308), ("prev", None)), ((124, 268, 214, 308), ("next", None))] + common


def _mixc(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def draw_adjust(d, menu, bg, fg, acc, panel, line):
    """The element being moved gets a box around it, and a small popup with - and + buttons sits on the other half of the screen."""
    box = menu.get("box")
    if box:
        d.rectangle((box[0] - 3, box[1] - 3, box[2] + 2, box[3] + 2), outline=acc, width=2)
        d.rectangle((box[0] - 5, box[1] - 5, box[2] + 4, box[3] + 4), outline=fg, width=1)
    x0, y0, x1, y1 = adjust_popup(menu)
    d.rounded_rectangle((x0, y0, x1, y1), 10, fill=panel, outline=acc, width=2)
    dx, dy = menu.get("offset", (0, 0))
    name = menu.get("adjust", "")
    d.text((x0 + 12, y0 + 13), (name if len(name) <= 16 else name[:15] + "\u2026"), font=_font(15, True), fill=fg, anchor="lm")
    d.text((x1 - 12, y0 + 13), "x %+d   y %+d" % (dx, dy), font=_font(15), fill=fg, anchor="rm")
    for rect, (act, arg) in adjust_hits(menu):
        rx0, ry0, rx1, ry1 = rect
        big = act == "nudge"
        label = ("%s %s" % ("X" if arg[0] else "Y", "+" if sum(arg) > 0 else "-")) if big else \
            "step %d" % menu.get("step_px", 1) if act == "step" else "reset" if act == "reset1" else "done"
        d.rounded_rectangle(rect, 8, fill=acc if act == "done" else line, outline=acc, width=2)
        d.text(((rx0 + rx1) // 2, (ry0 + ry1) // 2), label, font=_font(20 if big else 16, True), fill=bg if act == "done" else fg, anchor="mm")


def draw_menu(img, menu, theme):
    """Draw the menu (or the calibration prompt) onto an upright RGB frame."""
    d = ImageDraw.Draw(img)
    bg, fg, acc = _hex(theme["bg"]), _hex(theme["fg"]), _hex(theme["accent"])
    panel, line = _mixc(bg, (0, 0, 0), 0.35), _mixc(bg, fg, 0.18)
    if menu["mode"] == "adjust":
        draw_adjust(d, menu, bg, fg, acc, panel, line)
        return
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
    if tab == "awards" and not menu.get("awards_on", True):
        d.text((240, 150), "Achievements are switched off", font=_font(16, True), fill=fg, anchor="mm")
        d.text((240, 178), "(Settings in the web editor, or settings.json)", font=_font(12), fill=_mixc(fg, bg, 0.4), anchor="mm")
    if tab == "layout" and not menu["layout"]:
        d.text((240, 150), "Nothing on the screen yet", font=_font(16, True), fill=fg, anchor="mm")
    if tab == "system":
        for i, text in enumerate(menu.get("lines", ())):
            d.text((32, 46 + i * 24), text, font=_font(16), fill=fg)
    for rect, (act, arg) in menu_hits(menu):
        x0, y0, x1, y1 = rect
        if act in ("mode", "power"):
            key = "mode" if act == "mode" else arg
            ask = bool(menu.get("confirm")) and menu["confirm"][0] == key
            other = "AUTO" if menu.get("mode_now") == "MANU" else "MANU"
            if act == "mode":
                label = "tap again: %s" % other if ask else "Mode: %s" % menu.get("mode_now", "?")
            else:
                label = "tap again" if ask else arg
            d.rounded_rectangle(rect, 8, fill=acc if ask else line, outline=acc, width=2)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), label, font=_font(16, True), fill=bg if ask else fg, anchor="mm")
        elif act == "overheat":
            on = menu.get("overheat", False)
            d.rounded_rectangle(rect, 8, fill=acc if on else line, outline=acc, width=2)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), "Hot-off: %s" % ("ON" if on else "OFF"), font=_font(16, True),
                   fill=bg if on else fg, anchor="mm")
        elif act == "tab":
            on = arg == tab
            d.rectangle(rect, fill=acc if on else line, outline=acc, width=1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), arg.capitalize(), font=_font(16, True),
                   fill=bg if on else fg, anchor="mm")
        elif act == "tabscroll":
            d.rectangle(rect, fill=line, outline=acc, width=1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), "‹" if arg < 0 else "›", font=_font(18, True), fill=fg, anchor="mm")
        elif act == "pick":
            cur = arg == menu["active"]
            d.rectangle(rect, fill=line, outline=acc if cur else line, width=2)
            d.text((x0 + 12, (y0 + y1) // 2), ("\u25CF " if cur else "") + arg, font=_font(20, cur), fill=fg, anchor="lm")
            for j, key in enumerate(("bg", "fg", "accent")):
                sx = x1 - 78 + j * 24
                d.rectangle((sx, y0 + 10, sx + 18, y1 - 10), fill=_hex(menu["colors"][arg][key]), outline=fg)
        elif act == "award":
            info = menu["award_info"][arg]
            done = info["unlocked"] is not None
            d.rectangle(rect, fill=line, outline=acc if done else line, width=2)
            title = ("\u2605 " if done else "") + info["name"]
            d.text((x0 + 12, (y0 + y1) // 2), title if len(title) <= 21 else title[:20] + "\u2026",
                   font=_font(18, done), fill=fg if done else _mixc(fg, bg, 0.45), anchor="lm")
            px0, px1 = x1 - 96, x1 - 10
            d.rounded_rectangle((px0, y0 + 7, px1, y1 - 7), 10, fill=acc if done else panel, outline=acc, width=2)
            d.text(((px0 + px1) // 2, (y0 + y1) // 2), "done" if done else "%d/%d" % (min(int(info["progress"]), info["goal"] - 1 if info["goal"] > 1 else 0), info["goal"]),
                   font=_font(15, True), fill=bg if done else fg, anchor="mm")
        elif act == "adjust":
            dx, dy = menu["layout_info"].get(arg, (0, 0))
            moved = bool(dx or dy)
            d.rectangle(rect, fill=line, outline=acc if moved else line, width=2)
            d.text((x0 + 12, (y0 + y1) // 2), arg if len(arg) <= 22 else arg[:21] + "\u2026", font=_font(20, moved), fill=fg, anchor="lm")
            px0, px1 = x1 - 120, x1 - 10
            d.rounded_rectangle((px0, y0 + 7, px1, y1 - 7), 10, fill=acc if moved else panel, outline=acc, width=2)
            d.text(((px0 + px1) // 2, (y0 + y1) // 2), "%+d,%+d" % (dx, dy) if moved else "move", font=_font(15, True),
                   fill=bg if moved else fg, anchor="mm")
        elif act == "crackrow":
            info = menu["crack_info"][arg]
            if info["kind"] == "summary":
                d.text((x0 + 6, (y0 + y1) // 2), info["text"], font=_font(14, True), fill=fg, anchor="lm")
            else:
                label, done = CRACK_PILL.get(info["status"], ("?", False))
                name = info["name"] if len(info["name"]) <= 21 else info["name"][:20] + "…"
                d.rectangle(rect, fill=line, outline=acc if done else line, width=2)
                d.text((x0 + 12, (y0 + y1) // 2), name, font=_font(18, done), fill=fg if done else _mixc(fg, bg, 0.45), anchor="lm")
                px0, px1 = x1 - 78, x1 - 10
                d.rounded_rectangle((px0, y0 + 7, px1, y1 - 7), 10, fill=acc if done else panel, outline=acc, width=2)
                d.text(((px0 + px1) // 2, (y0 + y1) // 2), label, font=_font(14, True), fill=bg if done else fg, anchor="mm")
        elif act == "radrow":
            info = menu["radar_info"][arg]
            if info["kind"] == "summary":
                d.text((x0 + 6, (y0 + y1) // 2), info["text"], font=_font(14, True), fill=fg, anchor="lm")
            else:
                got, hot = info["captured"], info["clients"] > 0
                name = info["name"] if len(info["name"]) <= 18 else info["name"][:17] + "…"
                sub = "ch%s  %sdBm  %s" % (info["channel"], info["rssi"], info["encryption"])
                d.rectangle(rect, fill=line, outline=acc if hot and not got else line, width=2)
                d.text((x0 + 12, y0 + 12), name, font=_font(16, hot and not got), fill=_mixc(fg, bg, 0.45) if got else fg, anchor="lm")
                d.text((x0 + 12, y1 - 11), sub, font=_font(11), fill=_mixc(fg, bg, 0.4), anchor="lm")
                px0, px1 = x1 - 62, x1 - 10
                d.rounded_rectangle((px0, y0 + 9, px1, y1 - 9), 8, fill=acc if hot and not got else panel, outline=acc, width=2)
                d.text(((px0 + px1) // 2, (y0 + y1) // 2), "%d STA" % info["clients"],
                       font=_font(12, True), fill=bg if hot and not got else fg, anchor="mm")
        elif act == "resetall":
            ask = bool(menu.get("confirm")) and menu["confirm"][0] == "resetall"
            d.rectangle(rect, fill=acc if ask else line, outline=acc, width=1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), "sure?" if ask else "clear", font=_font(14, True), fill=bg if ask else fg, anchor="mm")
        elif act == "toggle":
            busy, on, bad = arg in menu["busy"], arg in menu["on"], arg in menu.get("failed", ())
            d.rectangle(rect, fill=line, outline=acc if on else line, width=2)
            d.text((x0 + 12, (y0 + y1) // 2), arg if len(arg) <= 22 else arg[:21] + "\u2026", font=_font(20, on), fill=fg, anchor="lm")
            px0, px1 = x1 - 82, x1 - 10
            d.rounded_rectangle((px0, y0 + 7, px1, y1 - 7), 10, fill=acc if on and not busy else panel, outline=acc, width=2)
            d.text(((px0 + px1) // 2, (y0 + y1) // 2), "..." if busy else ("ERR" if bad else "ON" if on else "OFF"), font=_font(16, True),
                   fill=bg if on and not busy else fg, anchor="mm")
        else:
            label = {"prev": "<", "next": "> %d/%d" % (page + 1, pages) if pages > 1 else ">", "cal": "calibrate", "close": "close", "refresh": "refresh",
                     "dim": "dim %d%%" % round(menu.get("dim", 1.0) * 100)}[act]
            d.rectangle(rect, fill=line, outline=acc, width=1)
            d.text(((x0 + x1) // 2, (y0 + y1) // 2), label, font=_font(16, True), fill=fg, anchor="mm")


# --------------------------------------------------------------------- plugin
# id, name, description, statistic, goal
ACHIEVEMENTS = (
    ("first_shake", "First Blood", "Capture your first handshake", "handshakes", 1),
    ("shakes_10", "Getting Going", "Capture 10 handshakes", "handshakes", 10),
    ("shakes_50", "Collector", "Capture 50 handshakes", "handshakes", 50),
    ("shakes_100", "Centurion", "Capture 100 handshakes", "handshakes", 100),
    ("shakes_500", "Legend", "Capture 500 handshakes", "handshakes", 500),
    ("uptime_1", "Warming Up", "Run for 1 hour in total", "hours", 1),
    ("uptime_24", "Around the Clock", "Run for 24 hours in total", "hours", 24),
    ("uptime_100", "Marathon", "Run for 100 hours in total", "hours", 100),
    ("days_3", "Regular", "Use it on 3 different days", "days", 3),
    ("days_7", "A Week Strong", "Use it on 7 different days", "days", 7),
    ("days_30", "Habit", "Use it on 30 different days", "days", 30),
    ("themes_5", "Stylist", "Try 5 different themes", "themes", 5),
    ("themes_15", "Fashionista", "Try 15 different themes", "themes", 15),
    ("night_owl", "Night Owl", "Be running at 3 in the morning", "night_owl", 1),
    ("swiper", "Swiper", "Change theme by swiping the screen", "swipes", 1),
    ("tinkerer", "Tinkerer", "Move something on the screen", "layout_moves", 1),
    ("too_hot", "Too Hot to Handle", "Make the heat guard step in", "hot_events", 1),
    ("designer", "Face Designer", "Upload your own face images", "face_uploads", 1),
    ("prepared", "Prepared", "Download a backup of your themes", "backups", 1),
)
ACH_INDEX = {a[0]: a for a in ACHIEVEMENTS}
LIST_STATS = ("days", "themes")
LIST_KEPT = 400


def default_stats():
    return {"handshakes": 0, "uptime_seconds": 0.0, "days": [], "themes": [], "night_owl": 0,
            "swipes": 0, "layout_moves": 0, "hot_events": 0, "face_uploads": 0, "backups": 0}


def clean_achievements(data):
    """Saved achievement state {unlocked: {id: time}, stats: {...}}. Unknown keys are dropped and junk falls back to defaults,
    so a hand-edited or damaged file can never break anything."""
    out = {"unlocked": {}, "stats": default_stats()}
    if not isinstance(data, dict):
        return out
    unlocked = data.get("unlocked")
    for k, v in (unlocked.items() if isinstance(unlocked, dict) else ()):
        if k in ACH_INDEX and isinstance(v, (int, float)) and not isinstance(v, bool):
            out["unlocked"][k] = float(v)
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    for k in out["stats"]:
        v = stats.get(k)
        if k in LIST_STATS:
            out["stats"][k] = [str(x)[:40] for x in v][-LIST_KEPT:] if isinstance(v, list) else []
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            out["stats"][k] = v
    return out


def ach_progress(stats, stat):
    if stat == "hours":
        return stats["uptime_seconds"] / 3600.0
    if stat in LIST_STATS:
        return len(stats[stat])
    return stats[stat]


def clean_layout(data):
    """{element name: [dx, dy]} from a saved layout.json. Junk is dropped, distances are limited, and zero offsets are not kept."""
    raw = data.get("offsets") if isinstance(data, dict) else None
    out = {}
    for key, val in (raw.items() if isinstance(raw, dict) else ()):
        if not isinstance(key, str) or not 0 < len(key) <= 40 or len(out) >= 80:
            continue
        if not (isinstance(val, (list, tuple)) and len(val) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in val)):
            continue
        dx, dy = (max(-LAYOUT_MAX, min(LAYOUT_MAX, int(v))) for v in val)
        if dx or dy:
            out[key] = [dx, dy]
    return out


def shifted(xy, dx, dy):
    """An element's xy (x, y or x0, y0, x1, y1) moved by dx, dy."""
    return tuple(v + (dx if i % 2 == 0 else dy) for i, v in enumerate(xy))


def clean_settings(cfg):
    """Validated settings: whether an overheating Pi turns itself off (and at what temperature, after how long)."""
    if not isinstance(cfg, dict):
        raise ValueError("settings must be a JSON object")
    return {"overheat_off": bool(cfg.get("overheat_off", False)),
            "overheat_temp": _num(cfg.get("overheat_temp", 85), 70, 95, "overheat_temp"),
            "overheat_seconds": _num(cfg.get("overheat_seconds", 60), 10, 600, "overheat_seconds"),
            "achievements": bool(cfg.get("achievements", True))}


def _clock(value, what):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(value).strip())
    if not m:
        raise ValueError("%s must be a time like 22:30" % what)
    return int(m.group(1)) * 60 + int(m.group(2))


def clean_display(cfg):
    """Validated display settings: {dim, night: None | {from, to, dim}, idle: None | {minutes, dim}}."""
    if not isinstance(cfg, dict):
        raise ValueError("display settings must be a JSON object")
    out = {"dim": _num(cfg.get("dim", 1.0), 0.05, 1.0, "dim"), "night": None, "idle": None}
    night = cfg.get("night")
    if night:
        if not isinstance(night, dict):
            raise ValueError("night must be an object")
        _clock(night.get("from"), "night.from")
        _clock(night.get("to"), "night.to")
        out["night"] = {"from": str(night["from"]).strip(), "to": str(night["to"]).strip(),
                        "dim": _num(night.get("dim", 0.3), 0.05, 1.0, "night.dim")}
    idle = cfg.get("idle")
    if idle:
        if not isinstance(idle, dict):
            raise ValueError("idle must be an object")
        out["idle"] = {"minutes": _num(idle.get("minutes", 5), 1, 240, "idle.minutes"),
                       "dim": _num(idle.get("dim", 0.25), 0.05, 1.0, "idle.dim")}
    return out


def night_active(night, lt):
    """Is the local time `lt` (a time.struct_time) inside the night window? Windows may cross midnight."""
    if not night:
        return False
    now = lt.tm_hour * 60 + lt.tm_min
    a, b = _clock(night["from"], "from"), _clock(night["to"], "to")
    return (a <= now < b) if a <= b else (now >= a or now < b)


def effective_dim(cfg, lt, idle_seconds):
    """(brightness 0.05-1, idle_dimmed): the dimmest of the manual setting, the night window and idle dimming."""
    dim, idle_on = cfg["dim"], False
    if night_active(cfg["night"], lt):
        dim = min(dim, cfg["night"]["dim"])
    if cfg["idle"] and idle_seconds >= cfg["idle"]["minutes"] * 60:
        dim, idle_on = min(dim, cfg["idle"]["dim"]), True
    return dim, idle_on


_dim_luts = {}


def apply_dim(img, factor):
    """Scale the brightness of an RGB image (a lookup table: about a millisecond)."""
    if factor >= 0.99:
        return img
    key = round(factor, 2)
    if key not in _dim_luts:
        _dim_luts[key] = [int(i * key) for i in range(256)] * 3
    return img.point(_dim_luts[key])


def warning_text(low_power, temp):
    """The banner text for the current problems (empty when there are none)."""
    parts = []
    if low_power:
        parts.append("LOW POWER")
    if temp is not None and temp >= THERMAL_SLOW_C:
        parts.append("HOT %dC" % round(temp))
    return "  ".join(parts)


def draw_banner(img, text):
    """A red label at the top centre, in front of everything: the same on every theme so it cannot be missed."""
    d = ImageDraw.Draw(img)
    font = _font(13, True)
    w = int(d.textlength(text, font=font)) + 18
    x0 = (img.width - w) // 2
    d.rounded_rectangle((x0, 18, x0 + w, 36), 6, fill=(190, 30, 30), outline=(255, 255, 255), width=1)
    d.text((img.width // 2, 27), text, font=font, fill=(255, 255, 255), anchor="mm")


def draw_toast(img, text, theme):
    """A small label at the bottom centre of the screen (the new theme's name, and so on)."""
    d = ImageDraw.Draw(img)
    bg, fg, acc = _hex(theme["bg"]), _hex(theme["fg"]), _hex(theme["accent"])
    font = _font(16, True)
    w = int(d.textlength(text, font=font)) + 28
    x0, y0 = (img.width - w) // 2, 276
    d.rounded_rectangle((x0, y0, x0 + w, y0 + 26), 10, fill=_mixc(bg, (0, 0, 0), 0.45), outline=acc, width=2)
    d.text((img.width // 2, y0 + 13), text, font=font, fill=fg, anchor="mm")


DISCLAIMER_FILE = os.path.join(THEME_DIR, "disclaimer.json")
DISCLAIMER_TEXT = ("For authorized security testing, research and education only. Only use this on networks and "
                   "devices you own or have explicit permission to test. You are responsible for complying with "
                   "all applicable laws.")


def draw_notice(img, text, theme):
    """A one-time full-panel notice the user must tap away, drawn the same way as the calibration prompt."""
    d = ImageDraw.Draw(img)
    bg, fg, acc = _hex(theme["bg"]), _hex(theme["fg"]), _hex(theme["accent"])
    d.rectangle((16, 56, 464, 264), fill=_mixc(bg, (0, 0, 0), 0.35), outline=acc, width=2)
    d.text((240, 78), "Before you start", font=_font(20, True), fill=fg, anchor="mm")
    y = 108
    for line in textwrap.wrap(text, 46):
        d.text((240, y), line, font=_font(13), fill=fg, anchor="mm")
        y += 19
    d.text((240, 242), "tap anywhere to continue", font=_font(13, True), fill=acc, anchor="mm")


class ThemeManager(plugins.Plugin):
    __author__ = "theme_manager contributors"
    __version__ = "2.7.0"
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
        self._toast = None
        self._notice = None
        self._ach = clean_achievements(None)
        self._ach_lock = threading.Lock()
        self._ach_dirty = False
        self._ach_loaded = False
        self._ach_saved = 0
        self._ach_last = 0
        self._settings = clean_settings({})
        self._settings_mtime = 0
        self._layout = {}
        self._radar = []
        self._radar_at = 0
        self._radar_lock = threading.Lock()
        self._hot_since = 0
        self._shutdown_at = 0
        self._snooze_until = 0
        self._try_until = 0
        self._warn = ""
        self._last_low = 0
        self._temp = None
        self._next_power = 0
        self._last_swipe = 0
        self._last_touch = 0
        self._display_cfg = clean_display({})
        self._display_mtime = 0
        self._dim = 1.0
        self._idle_dimmed = False
        self._started = time.time()
        self._swallow = False
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
        self._stat("themes", mark=name)
        if persist:
            self._try_until = 0
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

    def try_theme(self, theme, seconds):
        """Show a theme (saved or not) for a while, then go back to the active one. Nothing is written to disk, so a
        bad idea can never be left on the screen."""
        clean = _clean(theme)
        seconds = max(TRY_MIN_S, min(TRY_MAX_S, float(seconds)))
        with self._lock:
            self._theme = clean
            self._trans = None
            self._mood = None
        self._apply_web(clean)
        self._apply_faces(clean)
        self._try_until = time.time() + seconds
        self._wake.set()
        if self._view:
            try:
                self._view.update(force=True)
            except Exception as e:
                logging.debug("[theme_manager] refresh failed: %s", e)
        logging.info("[theme_manager] trying a theme for %d s (back to %s afterwards)", seconds, self._active)
        return seconds

    def _end_try(self):
        self._try_until = 0
        try:
            self._apply(self._active)
        except KeyError:                       # the saved theme was deleted meanwhile
            self._apply("default")
        self.toast("back to " + self._active)
        self._refresh_now()

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
            m = os.path.getmtime(DISPLAY_FILE)
        except OSError:
            m = 0
        if m != self._display_mtime:
            self._load_display()
        try:
            m = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            m = 0
        if m != self._settings_mtime:
            self._load_settings()
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
                off = mgr._layout.get(_key)
                home = _elem.xy
                if off:
                    try:
                        _elem.xy = shifted(home, off[0], off[1])
                    except Exception:
                        off = None
                try:
                    _orig(canvas, drawer)
                    mgr._capture(_key, _elem, before, canvas)
                finally:
                    if off:
                        _elem.xy = home

            elem.draw = wrapped
            elem._tm_wrapped = True
            self._wrapped.append(elem)

    def _capture(self, key, elem, before, canvas):
        """Remember which pixels the element just drew (and, for the face, where it is)."""
        try:
            changed = ImageChops.logical_and(ImageChops.logical_xor(before, canvas), canvas)
            box = changed.getbbox()
            if box:
                self._building["layers"][key] = (changed.crop(box).convert("L"), box)
            if key == "face":
                self._building["face"] = (elem.value, tuple(elem.xy))
        except Exception as e:
            logging.debug("[theme_manager] capture %s: %s", key, e)

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
        if self._warn:
            draw_banner(img, self._warn)
        menu = self._menu
        if menu is not None:
            if menu["mode"] == "adjust":
                region = ctx["layers"].get(menu["adjust"])
                menu["box"] = region[1] if region else None
            if menu.get("tab") == "system" and menu["mode"] == "list":
                self._fill_status(menu)
            elif menu.get("tab") == "crack" and menu["mode"] == "list":
                self._sync_crack_menu(menu)
            elif menu.get("tab") == "radar" and menu["mode"] == "list":
                self._sync_radar_menu(menu)
            draw_menu(img, menu, self._theme)
        toast = self._toast
        if toast is not None:
            draw_toast(img, toast[0], self._theme)
        if self._notice:
            draw_notice(img, self._notice, self._theme)
        return rotate(apply_dim(img, self._dim), self._rot)

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
        tab = tab if tab in TAB_NAMES else "themes"
        with self._menu_lock:
            self._menu = {"mode": mode, "tab": tab, "page": 0, "tab_scroll": TAB_NAMES.index(tab),
                          "pages": {t: 0 for t in TAB_NAMES}, "confirm": None, "awards_on": self._settings["achievements"],
                          "awards": [a[0] for a in ACHIEVEMENTS] if self._settings["achievements"] else [], "layout": [], "layout_info": {},
                          "crack": [], "crack_info": {}, "radar": [], "radar_info": {},
                          "award_info": {r["id"]: r for r in self.award_rows()}, "plugins": self._plugin_names(),
                          "on": set(plugins.loaded), "busy": set(), "failed": set(), "step": 0, "raw": [], "names": list(themes),
                          "colors": {n: t for n, t in themes.items()}, "active": self._active,
                          "until": now + (CALIB_TIMEOUT if mode == "calib" else MENU_TIMEOUT)}
        self._sync_layout_menu(self._menu)
        self._sync_crack_menu(self._menu)
        self._sync_radar_menu(self._menu)
        self._wake.set()
        self._refresh_now()

    def _sync_crack_menu(self, menu):
        rows = crack_rows()
        summary = crack_summary(rows)
        info = {"__summary__": {"kind": "summary", "text": _crack_summary_text(summary)}}
        order = ["__summary__"]
        for r in rows:
            info[r["file"]] = dict(r, kind="row")
            order.append(r["file"])
        menu["crack"] = order
        menu["crack_info"] = info

    def _sync_radar_menu(self, menu):
        rows, age = self.radar_rows()
        info = {"__summary__": {"kind": "summary", "text": _radar_summary_text(rows, age)}}
        order = ["__summary__"]
        for r in rows:
            info[r["mac"]] = dict(r, kind="row")
            order.append(r["mac"])
        menu["radar"] = order
        menu["radar_info"] = info

    def _sync_layout_menu(self, menu):
        rows = self.layout_rows()
        menu["layout"] = [r["key"] for r in rows]
        menu["layout_info"] = {r["key"]: (r["dx"], r["dy"]) for r in rows}
        if menu.get("adjust"):
            menu["offset"] = tuple(self._layout.get(menu["adjust"], (0, 0)))

    def close_menu(self):
        with self._menu_lock:
            self._menu = None
        self._refresh_now()

    # ---- achievements
    def _load_achievements(self):
        try:
            with open(ACHIEVEMENTS_FILE) as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            data = None
        self._ach = clean_achievements(data)
        self._ach_loaded = True
        if data is None:      # first run: start from what is already on disk, and unlock those without fanfare
            for stat, count in (("handshakes", _count_handshakes),):
                try:
                    self._ach["stats"][stat] = int(count())
                except (ValueError, OSError):
                    pass
            self._check_achievements(silent=True)
            self._save_achievements()

    def _save_achievements(self):
        try:
            os.makedirs(THEME_DIR, exist_ok=True)
            with self._ach_lock:
                write_json(ACHIEVEMENTS_FILE, self._ach, indent=1)
            self._ach_dirty = False
            self._ach_saved = time.time()
        except OSError as e:
            logging.warning("[theme_manager] could not save achievements: %s", e)

    def _stat(self, name, add=None, at_least=None, mark=None):
        """Change one statistic (add to it, raise it to a value, or add a name to a list) and check for new achievements."""
        if not self._settings["achievements"]:
            return
        with self._ach_lock:
            stats = self._ach["stats"]
            if add is not None:
                stats[name] += add
            elif at_least is not None:
                if at_least <= stats[name]:
                    return
                stats[name] = at_least
            elif mark is not None:
                if mark in stats[name]:
                    return
                stats[name] = (stats[name] + [mark])[-LIST_KEPT:]
            self._ach_dirty = True
        self._check_achievements()

    def _check_achievements(self, silent=False):
        new = []
        with self._ach_lock:
            for aid, name, desc, stat, goal in ACHIEVEMENTS:
                if aid not in self._ach["unlocked"] and ach_progress(self._ach["stats"], stat) >= goal:
                    self._ach["unlocked"][aid] = time.time()
                    new.append(name)
        if not new:
            return
        self._save_achievements()
        if silent:
            return
        logging.info("[theme_manager] achievement unlocked: %s", ", ".join(new))
        self.toast("\u2605 %s%s" % (new[0], " (+%d more)" % (len(new) - 1) if len(new) > 1 else ""), seconds=4)
        self._refresh_now()

    def award_rows(self):
        """One dict per achievement: id, name, desc, progress, goal, unlocked (time or None)."""
        with self._ach_lock:
            return [{"id": aid, "name": name, "desc": desc, "goal": goal, "progress": ach_progress(self._ach["stats"], stat),
                     "unlocked": self._ach["unlocked"].get(aid)} for aid, name, desc, stat, goal in ACHIEVEMENTS]

    def _tick_achievements(self, now):
        if not self._settings["achievements"]:
            self._ach_last = 0
            return
        if self._ach_last and now - self._ach_last < 1:      # once a second is plenty
            return
        dt = min(now - self._ach_last, 30) if self._ach_last else 0
        self._ach_last = now
        with self._ach_lock:
            self._ach["stats"]["uptime_seconds"] += dt
            self._ach_dirty = self._ach_dirty or dt > 0
        self._stat("days", mark=time.strftime("%Y-%m-%d", time.localtime(now)))
        if time.localtime(now).tm_hour == 3:
            self._stat("night_owl", at_least=1)
        self._check_achievements()
        if self._ach_dirty and now - self._ach_saved > 300:
            self._save_achievements()

    # ---- layout (moving things on the screen)
    def _load_layout(self):
        try:
            with open(LAYOUT_FILE) as fp:
                self._layout = clean_layout(json.load(fp))
        except FileNotFoundError:
            self._layout = {}
        except (ValueError, OSError) as e:
            logging.warning("[theme_manager] layout.json: %s", e)

    def _save_layout(self):
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(LAYOUT_FILE, {"offsets": self._layout})

    def _redraw_ui(self):
        try:
            if self._view:
                self._view.update(force=True)
        except Exception as e:
            logging.debug("[theme_manager] layout redraw: %s", e)
        self._refresh_now()

    def set_offset(self, key, dx, dy, count=True):
        """Put one element at dx, dy from where pwnagotchi draws it (0, 0 puts it back). Returns the stored offset."""
        if not isinstance(key, str) or not 0 < len(key) <= 40:
            raise ValueError("element name")
        dx, dy = (max(-LAYOUT_MAX, min(LAYOUT_MAX, int(v))) for v in (dx, dy))
        if dx or dy:
            if key not in self._layout and len(self._layout) >= 80:
                raise ValueError("too many moved elements")
            self._layout[key] = [dx, dy]
        else:
            self._layout.pop(key, None)
        self._save_layout()
        if count:
            self._stat("layout_moves", add=1)
        self._redraw_ui()
        return [dx, dy]

    def reset_layout(self):
        self._layout = {}
        self._save_layout()
        self._redraw_ui()

    def layout_rows(self):
        """[{key, box, dx, dy}] for every element on the screen now, plus any moved element that is not drawn at the moment."""
        ctx = self._ctx or {"layers": {}}
        rows = {k: {"key": k, "box": list(region[1]), "dx": self._layout.get(k, (0, 0))[0], "dy": self._layout.get(k, (0, 0))[1]}
                for k, region in ctx["layers"].items()}
        for k, (dx, dy) in self._layout.items():
            rows.setdefault(k, {"key": k, "box": None, "dx": dx, "dy": dy})
        return sorted(rows.values(), key=lambda r: ((r["box"] or [0, 999])[1], (r["box"] or [0, 0])[0], r["key"]))

    # ---- settings (overheating auto-off, achievements)
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as fp:
                cfg = clean_settings(json.load(fp))
            self._settings_mtime = os.path.getmtime(SETTINGS_FILE)
        except FileNotFoundError:
            cfg, self._settings_mtime = clean_settings({}), 0
        except (ValueError, OSError) as e:
            logging.warning("[theme_manager] settings.json: %s", e)
            return
        self._settings = cfg
        if cfg["achievements"] and not self._ach_loaded:
            self._load_achievements()
        if not cfg["overheat_off"]:
            self._hot_since = self._shutdown_at = 0

    def save_settings(self, cfg):
        """Validate and store new settings (the web editor and the touch menu use this)."""
        self._settings = clean_settings(cfg)
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(SETTINGS_FILE, self._settings)
        self._settings_mtime = os.path.getmtime(SETTINGS_FILE)
        if self._settings["achievements"] and not self._ach_loaded:
            self._load_achievements()
        if not self._settings["overheat_off"]:
            self._hot_since = self._shutdown_at = 0
        return self._settings

    def _toggle_overheat(self):
        on = not self._settings["overheat_off"]
        self.save_settings(dict(self._settings, overheat_off=on))
        self.toast("auto-off when hot: %s (%d C)" % ("ON" if on else "OFF", self._settings["overheat_temp"]))
        self._set_warning(time.time())
        self._refresh_now()

    def _check_overheat(self, temp, now):
        """With the option on: if the CPU stays at or above the limit long enough, count down 30 s on screen and turn the
        Pi off (a touch cancels and snoozes it). Cooling down cancels it too."""
        s = self._settings
        if not s["overheat_off"] or temp is None or now < self._snooze_until:
            self._hot_since = 0
            return
        if temp >= s["overheat_temp"]:
            self._hot_since = self._hot_since or now
            if not self._shutdown_at and now - self._hot_since >= s["overheat_seconds"]:
                self._shutdown_at = now + OVERHEAT_GRACE_S
                logging.critical("[theme_manager] CPU at %.0f C for %d s: turning the Pi off in %d s unless you touch the screen",
                                 temp, s["overheat_seconds"], OVERHEAT_GRACE_S)
        else:
            self._hot_since = 0
            if self._shutdown_at and temp < s["overheat_temp"] - 3:
                self._shutdown_at = 0
                logging.warning("[theme_manager] the CPU cooled down to %.0f C: not turning off", temp)
                self._set_warning(now)

    def _countdown(self, now):
        if now >= self._shutdown_at:
            self._shutdown_at = 0
            logging.critical("[theme_manager] overheating: turning the Pi off now")
            self._set_warning(now)
            self._do_system("shutdown")
        else:
            self._set_warning(now)

    def _cancel_overheat(self, now):
        self._shutdown_at = 0
        self._hot_since = 0
        self._snooze_until = now + OVERHEAT_SNOOZE_S
        logging.warning("[theme_manager] overheating shutdown cancelled by a touch (quiet for %d min)", OVERHEAT_SNOOZE_S // 60)
        self.toast("shutdown cancelled", now=now)
        self._set_warning(now)

    # ---- brightness: manual dim, night window, idle dimming
    def _load_display(self):
        try:
            with open(DISPLAY_FILE) as fp:
                cfg = clean_display(json.load(fp))
            self._display_mtime = os.path.getmtime(DISPLAY_FILE)
        except FileNotFoundError:
            cfg = clean_display({})
            self._display_mtime = 0
        except (ValueError, OSError) as e:
            logging.warning("[theme_manager] display.json: %s", e)
            return
        self._display_cfg = cfg
        self._update_dim(time.time())

    def _update_dim(self, now):
        idle = now - max(self._last_touch, self._started)
        dim, idle_on = effective_dim(self._display_cfg, time.localtime(now), idle)
        self._idle_dimmed = idle_on
        if abs(dim - self._dim) > 0.005:
            self._dim = dim
            self._refresh_now()

    def save_display(self, cfg):
        """Validate and store brightness settings (the web editor uses this). Returns the stored settings."""
        cfg = clean_display(cfg)
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(DISPLAY_FILE, cfg)
        self._display_mtime = os.path.getmtime(DISPLAY_FILE)
        self._display_cfg = cfg
        self._update_dim(time.time())
        self._refresh_now()
        return cfg

    def _cycle_dim(self):
        """The System tab's dim button: 100% -> 60% -> 30% -> 100%."""
        cur = self._display_cfg["dim"]
        nxt = DIM_STEPS[(min(range(len(DIM_STEPS)), key=lambda i: abs(DIM_STEPS[i] - cur)) + 1) % len(DIM_STEPS)]
        self._display_cfg = dict(self._display_cfg, dim=nxt)
        try:
            write_json(DISPLAY_FILE, self._display_cfg)
            self._display_mtime = os.path.getmtime(DISPLAY_FILE)
        except OSError as e:
            logging.warning("[theme_manager] could not save display.json: %s", e)
        self._update_dim(time.time())
        self._refresh_now()

    def toast(self, text, seconds=TOAST_S, now=None):
        self._toast = (str(text)[:30], (time.time() if now is None else now) + seconds)

    def menu_tick(self, now):
        if self._try_until and now >= self._try_until:
            self._end_try()
        if self._toast is not None and now > self._toast[1]:
            self._toast = None
            self._refresh_now()
        m = self._menu
        if m is not None and now > m["until"]:
            self.close_menu()
        elif m is not None and m.get("confirm") and now > m["confirm"][1]:
            m["confirm"] = None
            self._refresh_now()

    def on_tap(self, rx, ry, now):
        """A finished tap at raw touch coordinates."""
        if self._notice:
            self._notice = None
            self._refresh_now()
            return
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
        menu["until"] = now + (ADJUST_TIMEOUT if menu["mode"] == "adjust" else MENU_TIMEOUT)
        for (x0, y0, x1, y1), (act, arg) in menu_hits(menu):
            if x0 <= x <= x1 and y0 <= y <= y1:
                pages = max(1, -(-len(menu_items(menu)) // MENU_ROWS))
                if act not in ("power", "mode", "resetall"):
                    menu["confirm"] = None
                if act == "tab":
                    menu["pages"][menu["tab"]] = menu["page"]
                    menu["tab"] = arg
                    menu["page"] = menu["pages"][arg]
                elif act == "tabscroll":
                    menu["tab_scroll"] = (menu.get("tab_scroll", 0) + arg) % len(TAB_NAMES)
                elif act == "resetall":
                    ask = menu.get("confirm")
                    if ask and ask[0] == "resetall" and now <= ask[1]:
                        menu["confirm"] = None
                        self.reset_layout()
                        self._sync_layout_menu(menu)
                        return
                    menu["confirm"] = ("resetall", now + CONFIRM_S)
                elif act == "adjust":
                    menu.update(mode="adjust", adjust=arg, step_px=menu.get("step_px", 1))
                    self._sync_layout_menu(menu)
                    menu["until"] = now + ADJUST_TIMEOUT
                    menu["box"] = next((tuple(r["box"]) for r in self.layout_rows() if r["key"] == arg and r["box"]), None)
                elif act in ("nudge", "step", "reset1", "done"):
                    key = menu["adjust"]
                    cur = self._layout.get(key, [0, 0])
                    if act == "nudge":
                        self.set_offset(key, cur[0] + arg[0] * menu["step_px"], cur[1] + arg[1] * menu["step_px"])
                    elif act == "reset1":
                        self.set_offset(key, 0, 0, count=False)
                    elif act == "step":
                        menu["step_px"] = LAYOUT_STEPS[(LAYOUT_STEPS.index(menu["step_px"]) + 1) % len(LAYOUT_STEPS)]
                    else:
                        menu.update(mode="list", adjust=None, box=None)
                    self._sync_layout_menu(menu)
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
                elif act == "dim":
                    self._cycle_dim()
                    return
                elif act == "overheat":
                    self._toggle_overheat()
                    return
                elif act == "award":
                    info = menu["award_info"].get(arg)
                    if info:
                        self.toast(info["desc"], seconds=3, now=now)
                        self._refresh_now()
                    return
                elif act == "crackrow":
                    info = menu["crack_info"].get(arg)
                    if info and info["kind"] == "row":
                        msgs = {"cracked": "%s: %s" % (info["name"], info["password"]), "invalid": "invalid capture",
                                "uploaded": "uploaded, not cracked yet", "queued": "waiting to upload",
                                "unknown": "status unknown (wpa-sec plugin not active)"}
                        self.toast(msgs.get(info["status"], "?"), seconds=4, now=now)
                        self._refresh_now()
                    return
                elif act == "radrow":
                    info = menu["radar_info"].get(arg)
                    if info and info["kind"] == "row":
                        msg = "%s: %s, %d clients, %d dBm" % (info["name"], info["encryption"], info["clients"], info["rssi"])
                        if info["captured"]:
                            msg += " (already have a handshake)"
                        self.toast(msg, seconds=4, now=now)
                        self._refresh_now()
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
        if menu["mode"] == "adjust":
            return     # taps beside the popup do nothing, so the element being moved stays in view
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
        self._tick_achievements(now)
        if self._shutdown_at:
            self._countdown(now)
        if now >= self._next_temp:
            self._next_temp = now + 5
            self._update_dim(now)
            try:
                temp = cpu_temp()
            except (OSError, ValueError):
                temp = None
            self._temp = temp
            self._check_overheat(temp, now)
            self._set_warning(now)
            if temp is not None:
                new = heat_factor(temp, self._heat)
                if new != self._heat:
                    logging.warning("[theme_manager] CPU at %.0f C: animation %s", temp,
                                    "paused" if new is None else "slowed down" if new > 1 else "back to normal")
                    self._heat = new
                    if new != 1.0:
                        self._stat("hot_events", add=1)
                    self._wake.set()
        if now >= self._next_power:
            self._next_power = now + 2
            try:
                if _power_state() == "LOW":
                    self._last_low = now
            except Exception:
                pass
            self._set_warning(now)
        if now >= self._next_guard:
            self._next_guard = now + GUARD_S
            try:
                self._check_gps()
            except Exception as e:
                logging.debug("[theme_manager] gps guard: %s", e)

    def _set_warning(self, now):
        """Show or hide the red banner for low power / high temperature (a theme can switch it off)."""
        low = self._last_low > 0 and now - self._last_low < WARN_HOLD_S
        text = warning_text(low, self._temp) if self._theme.get("warnings", True) else ""
        if self._shutdown_at:
            text = "TOO HOT: OFF IN %ds (touch to cancel)" % max(0, int(self._shutdown_at - now + 0.999))
        if text != self._warn:
            self._warn = text
            self._refresh_now()

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
        menu["dim"] = self._display_cfg["dim"]
        menu["overheat"] = self._settings["overheat_off"]
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

    def on_swipe(self, first, last, now):
        """A clearly sideways swipe on the bare screen changes theme: left = next, right = previous."""
        if self._menu is not None or self._touch_m is None or now - self._last_swipe < 0.8:
            return
        x0, y0 = to_screen(self._touch_m, *first)
        x1, y1 = to_screen(self._touch_m, *last)
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) < SWIPE_PX or abs(dy) * 2 > abs(dx):
            return
        names = list(self._all())
        idx = names.index(self._active) if self._active in names else 0
        name = names[(idx + (-1 if dx > 0 else 1)) % len(names)]
        self._last_swipe = now
        self._stat("swipes", add=1)
        self.toast(name, now=now)
        try:
            self._apply(name, persist=True)
        except KeyError:
            pass

    def feed(self, etype, code, value, now):
        """One input event from the touch controller."""
        if etype == EV_ABS and code in (ABS_X, ABS_Y):
            self._abs[code] = value
        elif etype == EV_KEY and code == BTN_TOUCH:
            if value:
                if self._shutdown_at:
                    self._cancel_overheat(now)
                self._down = (now, [])
                self._swallow = self._idle_dimmed
                self._last_touch = now
                if self._idle_dimmed:
                    self._update_dim(now)          # wake up at once
            elif self._down:
                t0, samples = self._down
                self._down = None
                if not samples:
                    return
                if self._swallow:                  # the touch that woke the screen is only a wake-up
                    self._swallow = False
                    return
                head, tail = samples[:3], samples[-3:]
                first = tuple(sorted(p[i] for p in head)[len(head) // 2] for i in (0, 1))
                last = tuple(sorted(p[i] for p in tail)[len(tail) // 2] for i in (0, 1))
                if abs(last[0] - first[0]) + abs(last[1] - first[1]) >= SWIPE_RAW:
                    if now - t0 <= SWIPE_MAX_S:
                        self.on_swipe(first, last, now)
                elif now - t0 <= TAP_MAX_S:
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

    def _maybe_show_disclaimer(self):
        """The very first time this plugin ever runs, log the disclaimer and show it on screen until tapped away."""
        if os.path.exists(DISCLAIMER_FILE):
            return
        logging.warning("[theme_manager] %s", DISCLAIMER_TEXT)
        try:
            os.makedirs(THEME_DIR, exist_ok=True)
            write_json(DISCLAIMER_FILE, {"shown": time.time()})
        except OSError as e:
            logging.debug("[theme_manager] could not save disclaimer.json: %s", e)
        self._notice = DISCLAIMER_TEXT

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
        self._load_display()
        self._load_settings()
        self._load_layout()
        self._maybe_show_disclaimer()
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
        self._stat("handshakes", add=1)
        self._event_until = time.time() + HANDSHAKE_FLASH
        self._wake.set()

    def on_wifi_update(self, agent, access_points):
        """pwnagotchi calls this with every network it currently sees, each time it looks. We only ever read it, to
        rank and display; nothing here feeds back into what gets attacked."""
        try:
            captured = {r["bssid"] for r in crack_rows() if r.get("bssid")}
            rows = []
            for ap in access_points:
                mac = (ap.get("mac") or "").lower()
                rows.append({"mac": mac, "name": ap.get("hostname") or "(hidden)", "channel": ap.get("channel", 0),
                             "rssi": ap.get("rssi", -100), "clients": len(ap.get("clients") or []),
                             "encryption": ap.get("encryption") or "?", "captured": mac.replace(":", "") in captured,
                             "score": _ap_score(ap, captured)})
            rows.sort(key=lambda r: -r["score"])
            with self._radar_lock:
                self._radar = rows[:RADAR_MAX]
                self._radar_at = time.time()
        except Exception as e:
            logging.debug("[theme_manager] wifi update: %s", e)

    def radar_rows(self):
        """(rows, age in seconds since the last scan, or None before the first one)."""
        with self._radar_lock:
            rows, at = list(self._radar), self._radar_at
        return rows, (time.time() - at if at else None)

    def on_unload(self, ui):
        self._running = False
        if self._ach_dirty:
            self._save_achievements()
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

        if path == "api/achievements":
            return jsonify({"enabled": self._settings["achievements"], "achievements": self.award_rows()})

        if path == "api/settings" and request.method != "POST":
            return jsonify({"settings": self._settings, "display": self._display_cfg,
                            "limits": {"overheat_temp": [70, 95], "overheat_seconds": [10, 600]}})

        if path == "api/layout" and request.method != "POST":
            return jsonify({"rows": self.layout_rows(), "max": LAYOUT_MAX})

        if path == "api/cracking":
            rows = crack_rows()
            return jsonify({"summary": crack_summary(rows), "rows": rows[:200], "wpa_sec": _wpa_db_status() is not None})

        if path == "api/radar":
            rows, age = self.radar_rows()
            return jsonify({"rows": rows, "age": age})

        if path == "api/backup":
            self._stat("backups", add=1)
            return Response(make_backup(), mimetype="application/zip",
                            headers={"Content-Disposition": "attachment; filename=theme-manager-backup.zip"})

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
                if path == "api/restore":
                    upload = request.files.get("backup")
                    if upload is None:
                        return jsonify({"ok": False, "error": "choose a backup file"}), 400
                    report = restore_backup(upload.read(BACKUP_MAX_BYTES + 1), request.form.get("overwrite") == "1")
                    return jsonify(dict(report, ok=True))
                if path == "api/faces":
                    pack = str(request.form.get("pack", "")).strip()
                    uploads = request.files.getlist("files")[:40]
                    if not uploads:
                        return jsonify({"ok": False, "error": "choose some images"}), 400
                    report = {"added": [], "skipped": [], "invalid": []}
                    for f in uploads:
                        try:
                            result = store_face(pack, f.filename or "", f.read(FACE_MAX_BYTES + 1), True)
                            report["added"].append("%s (%s)" % (f.filename, result))
                        except ValueError as e:
                            report["invalid"].append(str(e))
                    if report["added"]:
                        self._stat("face_uploads", add=1)
                    return jsonify(dict(report, ok=bool(report["added"])))
                if path == "api/settings":
                    if "display" in data:
                        clean_display(data["display"])       # check both halves before saving either
                    if "settings" in data and isinstance(data["settings"], dict):
                        clean_settings(dict(self._settings, **data["settings"]))
                    if "display" in data:
                        self.save_display(data["display"])
                    if "settings" in data:
                        if not isinstance(data["settings"], dict):
                            raise ValueError("settings must be a JSON object")
                        self.save_settings(dict(self._settings, **data["settings"]))
                    return jsonify({"ok": True, "settings": self._settings, "display": self._display_cfg})
                if path == "api/layout":
                    if data.get("reset"):
                        self.reset_layout()
                    else:
                        self.set_offset(data.get("key"), data.get("dx", 0), data.get("dy", 0))
                    return jsonify({"ok": True, "rows": self.layout_rows()})
                if path == "api/faces/delete":
                    return jsonify({"ok": delete_pack(data.get("pack", ""))})
                if path == "api/try":
                    seconds = self.try_theme(data.get("theme", {}), data.get("seconds", 30))
                    return jsonify({"ok": True, "seconds": seconds})
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
            return render_template_string(PAGE.replace("SCENE_KINDS_JS", json.dumps(list(SCENE_KINDS))))
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
<button id="apply">Apply to screen</button><button id="try" title="show it on the screen for 30 seconds, then go back">Try 30 s</button><button id="save">Save</button>
<button id="export">Export</button><button id="import">Import</button><button id="del" class="d">Delete</button>
<input type="file" id="file" accept=".json,application/json" hidden></div>
<div class="bar" id="backup"><span style="color:var(--dim)">Backup</span>
<a id="dl" download="theme-manager-backup.zip"><button type="button">Download all my themes and faces</button></a>
<button id="restore" type="button">Restore from a backup</button><label class="ck"><input type="checkbox" id="over"> replace what is already there</label>
<input type="file" id="bfile" accept=".zip,application/zip" hidden></div>
<div id="tabs" class="tabs"></div>
<div id="panel" class="ed"></div>
</div>
{% raw %}<script>
let CSRF=document.querySelector('meta[name="csrf_token"]').content;
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
 stars:{density:[.05,1,.05,.5],speed:[0,30,.5,3],color:1},
 scene:{kind:'kind',strength:[0,1,.05,1],speed:[0,30,.5,3]}};
const KINDS=SCENE_KINDS_JS;
const ANIM=['pulse','rainbow','glitch','rain','stars','noise'];
const MOODS=['look_r','sleep','awake','bored','intense','cool','happy','grateful','excited','motivated','demotivated','smart','lonely','sad','angry','friend','broken','debug','upload','handshake'];
const HOLDERS=['{name}','{time}','{date}','{cpu}','{temp}','{mem}','{uptime}','{ip}','{mode}','{gps}','{lat}','{lon}','{sats}','{handshakes}','{cracked}','{session}','{power}','{battery}'];
const TABS=['Colors','Effects','Text','Elements','Moods','Faces','JSON','Layout','Awards','Cracking','Radar','Settings'];
let S={active:'',themes:{}},sel='',cur={},info={elements:[],entities:[],packs:{}},tab='Colors',mood='sad',pvMood=null,busy=false,dirty=false,pvErr=false,timer=null;
const say=t=>$('msg').textContent=t||'';
/* After the plugin restarts (or the browser loses its session) the page's token is stale: fetch a fresh one and retry once. */
async function newToken(){try{const h=await(await fetch(location.pathname,{cache:'no-store'})).text();const m=h.match(/name="csrf_token" content="([^"]+)"/);if(m){CSRF=m[1];return true}}catch(e){}return false}
async function send(p,opts,retry){const r=await fetch(base+'/api/'+p,Object.assign({method:'POST'},opts,{headers:Object.assign({'X-CSRFToken':CSRF},opts.headers||{})}));
 if(r.status===400&&retry){const t=await r.clone().text();if(/CSRF/i.test(t)&&await newToken())return send(p,opts,false)}return r}
const post=(p,b)=>send(p,{headers:{'Content-Type':'application/json'},body:JSON.stringify(b)},true);
const postForm=(p,fd)=>send(p,{body:fd},true);
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
   if(on){const o={type};for(const[k,d]of Object.entries(params)){if(Array.isArray(d))o[k]=d[3];else if(d==='kind')o[k]=KINDS[0]}l.push(o)}
   else{const i=l.findIndex(e=>e.type===type);if(i>=0)l.splice(i,1)}touch();panel()}));
  if(have){const sub=E('div',{class:'sub'});
   for(const[k,d]of Object.entries(params))sub.append(Array.isArray(d)?slider(k,d,have[k]??d[3],v=>{have[k]=v;touch()}):d==='kind'?
    E('div',{class:'row'},field('scenery',select(KINDS,have.kind,v=>{have.kind=v;touch()}))):
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
 const pname=E('input',{type:'text',id:'packname',maxlength:32,value:cur.face_pack||'',placeholder:'pack name'});
 const files=E('input',{type:'file',id:'facefiles',multiple:'multiple',accept:'image/png,image/gif,image/jpeg,image/webp'});
 p.append(E('h2',{},'Add or replace faces'),E('p',{style:'color:var(--dim);margin:0 0 8px'},'Choose images named after moods (happy.png, sad.png, angry.gif, default.png ...). They are resized to fit the screen; a gif keeps its animation.'),
  E('div',{class:'row'},field('pack name',pname),field('images',files),E('button',{id:'faceupload',onclick:async()=>{
    const pack=pname.value.trim();if(!pack||!files.files.length)return say('give the pack a name and choose some images');
    const fd=new FormData();fd.append('pack',pack);for(const f of files.files)fd.append('files',f);
    const j=await(await postForm('faces',fd)).json();
    say((j.added||[]).length+' saved'+((j.invalid||[]).length?', '+j.invalid.length+' not used: '+j.invalid[0]:'')+(j.error?j.error:''));
    await refresh(true);if((j.added||[]).length){cur.face_pack=pack;touch()}panel()}},'Upload'),
   cur.face_pack?E('button',{class:'d',id:'facedelete',onclick:async()=>{if(!confirm('Delete the face pack "'+cur.face_pack+'" and all its images?'))return;
    const j=await(await post('faces/delete',{pack:cur.face_pack})).json();say(j.ok?'deleted the pack':'could not delete it');cur.face_pack=undefined;touch();await refresh(true);panel()}},'Delete this pack'):null));
 return p}
function panelJson(){prune(cur);const ta=E('textarea',{id:'json',spellcheck:'false',value:JSON.stringify(cur,null,2)});
 ta.oninput=()=>{try{const o=normalize(JSON.parse(ta.value));ta.classList.remove('bad');cur=o;schedule()}catch(e){ta.classList.add('bad')}};
 const url=E('input',{type:'text',id:'url',placeholder:'https://github.com/.../theme.json',style:'flex:1;min-width:220px'});
 return E('div',{},E('p',{style:'color:var(--dim);margin:0 0 8px'},'Full theme JSON. Changes apply to the preview as you type.'),ta,
  E('div',{class:'row'},url,E('button',{id:'importurl',onclick:()=>importUrl(url.value)},'Import from a link')))}
async function importUrl(u){u=u.trim();
 if(!/^https:\/\//i.test(u))return say('use a https:// link');
 const g=u.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)\/blob\/(.+)$/i);if(g)u='https://raw.githubusercontent.com/'+g[1]+'/'+g[2]+'/'+g[3];
 try{const r=await fetch(u);if(!r.ok)return say('could not download it (HTTP '+r.status+')');
  cur=normalize(JSON.parse(await r.text()));$('name').value=(u.split('/').pop()||'theme').replace(/\.json.*$/i,'').replace(/[^A-Za-z0-9_\- ]/g,'_').slice(0,32);
  panel();overlay();schedule();say('imported from the link: check the preview, then Save')}catch(e){say('could not read a theme from that link')}}
/* ---- the screen itself: layout, awards, settings (not part of a theme) ---- */
let lay={rows:[],max:200},layStep=1;
async function loadLayout(){try{lay=await(await fetch(base+'/api/layout')).json()}catch(e){}}
/* Clicks apply at once to the local copy and go to the device one after another, so quick clicks add up instead of overwriting each other. */
let layQ=Promise.resolve(),layPending=0;
function nudge(key,dx,dy,abs){const r=lay.rows.find(x=>x.key===key);if(!r)return layQ;
 if(abs){r.dx=dx;r.dy=dy}else{r.dx+=dx;r.dy+=dy}
 const want=[r.dx,r.dy];layPending++;panel();
 layQ=layQ.then(async()=>{let j={};try{j=await(await post('layout',{key,dx:want[0],dy:want[1]})).json()}catch(e){}
  layPending--;if(!j.ok)say(j.error||'could not move it');
  if(!layPending){if(j.ok)lay.rows=j.rows;else await loadLayout();panel();setTimeout(preview,500)}});
 return layQ}
function panelLayout(){const p=E('div');
 p.append(E('p',{style:'color:var(--dim);margin:0 0 8px'},'Move things on the screen. Every element is nudged by the step you choose; the preview shows the result. This is not part of a theme: it stays the same for all themes. On the device itself you can do the same from the touch menu (Layout tab).'));
 p.append(E('div',{class:'row'},field('step',select([[1,'1 px'],[5,'5 px'],[10,'10 px']],layStep,v=>{layStep=parseInt(v)})),
  E('button',{class:'d',id:'layreset',onclick:async()=>{if(!confirm('Put everything back where it was?'))return;const j=await(await post('layout',{reset:true})).json();if(j.ok){lay.rows=j.rows;panel();setTimeout(preview,500)}}},'Reset all')));
 const list=E('div',{class:'ent'});
 for(const r of lay.rows){const moved=r.dx||r.dy;
  list.append(E('div',{class:'erow'+(moved?' set':''),'data-key':r.key},E('span',{class:'ename'},r.key),
   E('button',{class:'lx-',onclick:()=>nudge(r.key,-layStep,0)},'X -'),E('button',{class:'lx+',onclick:()=>nudge(r.key,layStep,0)},'X +'),
   E('button',{class:'ly-',onclick:()=>nudge(r.key,0,-layStep)},'Y -'),E('button',{class:'ly+',onclick:()=>nudge(r.key,0,layStep)},'Y +'),
   E('span',{class:'inh'},'x '+(r.dx>0?'+':'')+r.dx+'  y '+(r.dy>0?'+':'')+r.dy),
   moved?E('button',{class:'x',onclick:()=>nudge(r.key,0,0,true)},'reset'):null))}
 if(!lay.rows.length)list.append(E('p',{style:'color:var(--dim)'},'Nothing is on the screen yet.'));
 p.append(list);return p}
let awards={enabled:true,achievements:[]};
async function loadAwards(){try{awards=await(await fetch(base+'/api/achievements')).json()}catch(e){}}
function panelAwards(){const p=E('div');
 if(!awards.enabled){p.append(E('p',{style:'color:var(--dim)'},'Achievements are switched off (Settings tab).'));return p}
 const done=awards.achievements.filter(a=>a.unlocked!==null).length;
 p.append(E('p',{style:'color:var(--dim);margin:0 0 8px'},done+' of '+awards.achievements.length+' unlocked. They also show on the device: touch menu, Awards tab.'));
 for(const a of awards.achievements){const d=a.unlocked!==null;const pct=d?100:Math.round(100*Math.min(a.progress,a.goal)/a.goal);
  p.append(E('div',{class:'tl award'+(d?' done':''),'data-id':a.id,style:d?'border-color:var(--acc)':''},
   E('b',{},(d?'★ ':'')+a.name),E('span',{style:'color:var(--dim)'},'  '+a.desc),
   E('div',{class:'gbar',style:'background:linear-gradient(90deg,var(--acc) '+pct+'%,var(--bg) '+pct+'%);height:8px;margin:6px 0 0'}),
   E('small',{style:'color:var(--dim)'},d?'unlocked '+new Date(a.unlocked*1000).toLocaleDateString():Math.floor(Math.min(a.progress,a.goal))+' / '+a.goal)))}
 return p}
let crack={summary:{total:0,cracked:0,queued:0,uploaded:0,invalid:0,unknown:0},rows:[],wpa_sec:false};
async function loadCracking(){try{crack=await(await fetch(base+'/api/cracking')).json()}catch(e){}}
function panelCracking(){const p=E('div'),s=crack.summary;
 p.append(E('p',{style:'color:var(--dim);margin:0 0 10px'},crack.wpa_sec?'From the wpa-sec plugin\\'s own upload/crack tracking. Read-only: nothing here changes what gets attacked.':
  'The wpa-sec plugin is not tracking uploads, so only what has actually been cracked is known. Handshakes otherwise show as \\'unknown\\'.'));
 p.append(E('div',{class:'wpa-stats',style:'display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;margin-bottom:12px'},
  [['cracked','Cracked'],['queued','Queued'],['uploaded','Uploaded'],['invalid','Invalid'],['total','Total']].map(([k,l])=>
   E('div',{class:'card',style:'text-align:center;cursor:default'},E('div',{style:'font-size:22px'},String(s[k])),E('small',{style:'color:var(--dim)'},l)))));
 if(!crack.rows.length){p.append(E('p',{style:'color:var(--dim)'},'No handshakes yet.'));return p}
 const PILL={cracked:['PWND',1],uploaded:['WAIT',0],queued:['NEW',0],invalid:['BAD',0],unknown:['?',0]};
 for(const r of crack.rows){const[label,done]=PILL[r.status]||['?',0];
  p.append(E('div',{class:'erow set',style:done?'border-color:var(--acc)':''},
   E('span',{class:'ename',style:'width:170px'},r.name||'(hidden)'),
   E('span',{class:'inh',style:'flex:1'},r.status==='cracked'?r.password:(r.bssid||'')),
   E('span',{style:'padding:2px 10px;border-radius:10px;font-size:11px;background:'+(done?'var(--acc)':'transparent')+';border:1px solid var(--acc);color:'+(done?'var(--bg)':'var(--text)')},label)))}
 return p}
let radar={rows:[],age:null};
async function loadRadar(){try{radar=await(await fetch(base+'/api/radar')).json()}catch(e){}}
function panelRadar(){const p=E('div');
 p.append(E('p',{style:'color:var(--dim);margin:0 0 10px'},'Networks pwnagotchi currently sees, ranked by signal and client count (a rough guess at which ones are worth the time). '+
  'Display only: nothing here changes what actually gets attacked. Also on the device: touch menu, Radar tab.'+
  (radar.age==null?' No scan yet.':radar.age>120?' Last scan '+Math.round(radar.age/60)+' min ago.':'')));
 if(!radar.rows.length){p.append(E('p',{style:'color:var(--dim)'},'No networks seen yet.'));return p}
 for(const r of radar.rows){
  p.append(E('div',{class:'erow'+(r.captured?'':' set'),style:r.captured?'opacity:.55':''},
   E('span',{class:'ename',style:'width:170px'},r.name),
   E('span',{class:'inh',style:'flex:1'},'ch'+r.channel+'  '+r.rssi+'dBm  '+r.encryption+(r.captured?'  (have a handshake)':'')),
   E('span',{style:'padding:2px 10px;border-radius:10px;font-size:11px;border:1px solid var(--acc);background:'+(r.clients&&!r.captured?'var(--acc)':'transparent')+';color:'+(r.clients&&!r.captured?'var(--bg)':'var(--text)')},r.clients+' STA')))}
 return p}
let cfg={settings:{},display:{dim:1,night:null,idle:null},limits:{}};
async function loadSettings(){try{cfg=await(await fetch(base+'/api/settings')).json()}catch(e){}}
async function saveSettings(){const j=await(await post('settings',{settings:cfg.settings,display:cfg.display})).json();
 if(j.ok){cfg.settings=j.settings;cfg.display=j.display;say('settings saved')}else say(j.error||'could not save the settings')}
function panelSettings(){const p=E('div'),s=cfg.settings,d=cfg.display;
 const num=(v,cb,mn,mx,st)=>E('input',{type:'number',min:mn,max:mx,step:st||1,value:v,oninput:e=>{const x=parseFloat(e.target.value);if(!isNaN(x))cb(clamp(x,mn,mx))}});
 p.append(E('h2',{},'Overheating'),E('div',{class:'row'},
  check('switch the Pi off when it stays too hot',s.overheat_off,on=>{s.overheat_off=on;panel()}),
  field('above (°C)',num(s.overheat_temp,v=>s.overheat_temp=v,70,95)),
  field('for (seconds)',num(s.overheat_seconds,v=>s.overheat_seconds=v,10,600))),
  E('p',{style:'color:var(--dim);margin:0'},'A warning with a countdown shows on the screen first, and a touch cancels it (then it stays quiet for 10 minutes).'));
 p.append(E('h2',{},'Achievements'),check('keep track of achievements',s.achievements,on=>{s.achievements=on}));
 p.append(E('h2',{},'Brightness'),E('div',{class:'row'},slider('brightness',[5,100,5],Math.round(d.dim*100),v=>{d.dim=v/100})));
 const nightOn=!!d.night,idleOn=!!d.idle;
 p.append(E('div',{class:'row'},check('night mode',nightOn,on=>{d.night=on?{from:'22:00',to:'07:00',dim:.3}:null;panel()}),
  nightOn?[field('from',E('input',{type:'text',size:5,value:d.night.from,oninput:e=>d.night.from=e.target.value})),
   field('to',E('input',{type:'text',size:5,value:d.night.to,oninput:e=>d.night.to=e.target.value})),
   slider('dim to',[5,100,5],Math.round(d.night.dim*100),v=>{d.night.dim=v/100})]:null));
 p.append(E('div',{class:'row'},check('dim when not touched',idleOn,on=>{d.idle=on?{minutes:5,dim:.25}:null;panel()}),
  idleOn?[field('after (minutes)',num(d.idle.minutes,v=>d.idle.minutes=v,1,240)),slider('dim to',[5,100,5],Math.round(d.idle.dim*100),v=>{d.idle.dim=v/100})]:null));
 p.append(E('div',{class:'row'},E('button',{id:'setsave',onclick:saveSettings},'Save settings')));
 return p}
const PANELS={Colors:panelColors,Effects:panelEffects,Text:panelText,Elements:panelElements,Moods:panelMoods,Faces:panelFaces,JSON:panelJson,Layout:panelLayout,Awards:panelAwards,Cracking:panelCracking,Radar:panelRadar,Settings:panelSettings};
function panel(){const p=$('panel');p.innerHTML='';p.append(PANELS[tab]());
 const t=$('tabs');t.innerHTML='';for(const n of TABS)t.append(E('button',{class:n===tab?'on':'',onclick:async()=>{tab=n;pickKey=null;$('pick').innerHTML='';$('pick').className='';pvMood=n==='Moods'?mood:null;if(n==='Elements'||n==='Moods'){try{info.entities=await(await fetch(base+'/api/entities')).json()}catch(e){}}if(n==='Layout')await loadLayout();if(n==='Awards')await loadAwards();if(n==='Cracking')await loadCracking();if(n==='Radar')await loadRadar();if(n==='Settings')await loadSettings();panel();overlay();schedule()}},n))}

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
let tryTimer=null;
$('try').onclick=async()=>{const r=await post('try',{theme:prune(clone(cur)),seconds:30});const j=await r.json();
 if(!j.ok)return say(j.error||'this theme cannot be shown');
 let left=Math.round(j.seconds);clearInterval(tryTimer);
 say('showing this theme on the screen for '+left+' s, then back to the saved one (Apply keeps it)');
 const tick=()=>{if(left<=0){clearInterval(tryTimer);$('try').textContent='Try 30 s';return}$('try').textContent='back in '+left+' s';left--};
 tick();tryTimer=setInterval(tick,1000)};
$('apply').onclick=async()=>{clearInterval(tryTimer);$('try').textContent='Try 30 s';const n=$('name').value.trim();const ex=S.themes[n];
 if(ex&&ex.builtin){if(!same(cur,ex))return say('built-in themes can\'t be changed: type a new name, Save, then Apply');}
 else{if(!nameOk(n))return say('give the theme a name first');if(!(ex&&same(cur,ex))&&!await saveAs(n))return}
 const r=await(await post('apply',{name:n})).json();say(r.ok?'applied '+n+' to the screen':r.error);sel=n;await refresh()};
$('del').onclick=async()=>{const r=await(await post('delete',{name:sel})).json();say(r.ok?'deleted '+sel:r.error);if(r.ok){sel='';await refresh()}};
$('export').onclick=()=>{const n=($('name').value.trim()||'theme');const a=E('a',{href:URL.createObjectURL(new Blob([JSON.stringify(prune(clone(cur)),null,2)],{type:'application/json'})),download:n+'.json'});document.body.append(a);a.click();a.remove()};
$('import').onclick=()=>$('file').click();
$('file').onchange=async e=>{const f=e.target.files[0];if(!f)return;
 try{cur=normalize(JSON.parse(await f.text()));$('name').value=f.name.replace(/\.json$/i,'').replace(/[^A-Za-z0-9_\- ]/g,'_').slice(0,32);
  panel();overlay();schedule();say('imported: check the preview, then Save')}catch(err){say('not a valid theme file')}e.target.value=''};
$('dl').href=base+'/api/backup';
$('restore').onclick=()=>$('bfile').click();
$('bfile').onchange=async e=>{const f=e.target.files[0];if(!f)return;const fd=new FormData();fd.append('backup',f);fd.append('overwrite',$('over').checked?'1':'0');
 try{const r=await postForm('restore',fd);const j=await r.json();
  if(!j.ok)say(j.error||'could not restore that file');
  else{say('restored '+j.added.length+', skipped '+j.skipped.length+(j.invalid.length?', could not use '+j.invalid.length+' ('+j.invalid[0]+')':''));await refresh()}}
 catch(err){say('could not restore that file')}e.target.value=''};
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
    elif cmd in ("dim", "night", "idle") and len(a) >= 2:
        try:
            cfg = clean_display(json.load(open(DISPLAY_FILE))) if os.path.exists(DISPLAY_FILE) else clean_display({})
            if cmd == "dim" and len(a) == 2:
                cfg["dim"] = float(a[1]) / 100
            elif cmd == "night" and a[1] == "off":
                cfg["night"] = None
            elif cmd == "night" and len(a) == 4:
                cfg["night"] = {"from": a[1], "to": a[2], "dim": float(a[3]) / 100}
            elif cmd == "idle" and a[1] == "off":
                cfg["idle"] = None
            elif cmd == "idle" and len(a) == 3:
                cfg["idle"] = {"minutes": float(a[1]), "dim": float(a[2]) / 100}
            else:
                raise ValueError("wrong arguments, see: theme_manager.py --help")
            cfg = clean_display(cfg)
        except ValueError as e:
            sys.exit("cannot set %s: %s" % (cmd, e))
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(DISPLAY_FILE, cfg)
        print(json.dumps(cfg))
    elif cmd == "overheat":
        try:
            if len(a) not in (2, 3, 4) or a[1] not in ("on", "off"):
                raise ValueError("usage: overheat on|off [TEMPERATURE [SECONDS]]")
            cfg = clean_settings(json.load(open(SETTINGS_FILE))) if os.path.exists(SETTINGS_FILE) else clean_settings({})
            cfg["overheat_off"] = a[1] == "on"
            if len(a) >= 3:
                cfg["overheat_temp"] = float(a[2])
            if len(a) == 4:
                cfg["overheat_seconds"] = float(a[3])
            cfg = clean_settings(cfg)
        except ValueError as e:
            sys.exit("cannot set overheat: %s" % e)
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(SETTINGS_FILE, cfg)
        print(json.dumps(cfg))
    elif cmd == "achievements" and len(a) == 2 and a[1] in ("on", "off"):
        cfg = clean_settings(json.load(open(SETTINGS_FILE))) if os.path.exists(SETTINGS_FILE) else clean_settings({})
        cfg["achievements"] = a[1] == "on"
        os.makedirs(THEME_DIR, exist_ok=True)
        write_json(SETTINGS_FILE, cfg)
        print(json.dumps(cfg))
    elif cmd == "layout" and len(a) == 2 and a[1] in ("show", "reset"):
        if a[1] == "reset":
            write_json(LAYOUT_FILE, {"offsets": {}})
        try:
            print(json.dumps(clean_layout(json.load(open(LAYOUT_FILE)))))
        except (OSError, ValueError):
            print("{}")
    elif cmd == "cracking" and len(a) == 1:
        print(json.dumps(crack_summary()))
    elif cmd == "cracking" and len(a) == 2 and a[1] == "list":
        for r in crack_rows():
            extra = ": %s" % r["password"] if r["status"] == "cracked" else ""
            print("%-8s %-24s %s%s" % (r["status"], r["name"] or "(hidden)", r["bssid"] or "?", extra))
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
