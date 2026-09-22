"""node_pwn: a tiny companion plugin that turns this pwnagotchi into a "node" the theme_manager plugin on another
pwnagotchi (the "main" unit) can find on the same network and pull capture stats from, so a group of units working
together do not all attack the same handshake twice.

It does exactly one thing: answers `GET /plugins/node_pwn/api/info` on this unit's own web UI (the same port
pwnagotchi's web UI already uses, nothing new to open) with this unit's identity and the BSSIDs it has already
captured. It never touches what this unit attacks, never talks to any other node on its own, and never phones home
anywhere off your own network -- the main unit has to come and ask it, over plain HTTP, on whatever network you
already joined both units to (your own Wi-Fi, or a hotspot the main unit runs).

Install with Node_PWN.sh, or by hand: drop this file in /etc/pwnagotchi/custom-plugins/ and enable it:

    [main.plugins.node_pwn]
    enabled = true
"""
import glob
import logging
import os
import re
import time

import pwnagotchi.plugins as plugins

__author__ = "theme_manager contributors"
__version__ = "1.0.0"
__license__ = "GPL3"
__description__ = "Answers a small status API so another unit running theme_manager can find this one and see what it has already captured."

BSSID_RE = re.compile(r"[0-9a-fA-F]{12}")


def _handshake_dir():
    override = os.environ.get("NODE_PWN_HANDSHAKES")   # for testing: a real pwnagotchi never sets this
    if override:
        return override
    try:
        import pwnagotchi
        return pwnagotchi.config["bettercap"]["handshakes"]
    except Exception:
        return "/etc/pwnagotchi/handshakes"


def node_bssids(handshake_dir=None):
    """Bare (no colons), lowercase BSSIDs this unit has a capture for, read straight from filenames --
    the same `ESSID_BSSID.pcapng` naming bettercap and the grid plugin already use."""
    out = []
    try:
        for f in glob.glob(os.path.join(handshake_dir or _handshake_dir(), "*.pcapng")):
            stem = os.path.splitext(os.path.basename(f))[0]
            tail = stem.rsplit("_", 1)[-1]
            if BSSID_RE.fullmatch(tail):
                out.append(tail.lower())
    except Exception as e:
        logging.debug("[node_pwn] listing handshakes: %s", e)
    return out


def node_info(started, mac_path="/sys/class/net/wlan0/address"):
    try:
        import pwnagotchi
        name = pwnagotchi.config["main"]["name"]
    except Exception:
        name = os.uname().nodename
    try:
        mac = open(mac_path).read().strip()
    except Exception:
        mac = ""
    bssids = node_bssids()
    return {"node": "node_pwn", "version": __version__, "name": name, "mac": mac,
            "handshakes": len(bssids), "bssids": bssids, "uptime": round(time.time() - started)}


class NodePwn(plugins.Plugin):
    __author__ = __author__
    __version__ = __version__
    __license__ = __license__
    __description__ = __description__

    def __init__(self):
        self._started = time.time()

    def on_loaded(self):
        logging.info("[node_pwn] loaded: reachable at /plugins/node_pwn/api/info")

    def on_webhook(self, path, request):
        from flask import jsonify
        if (path or "") != "api/info":
            return jsonify({"error": "not found"}), 404
        return jsonify(node_info(self._started))
