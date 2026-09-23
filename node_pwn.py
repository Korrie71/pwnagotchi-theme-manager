"""node_pwn: a tiny companion plugin that turns this pwnagotchi into a "node" the theme_manager plugin on another
pwnagotchi (the "main" unit) can find and pull capture stats from, so a group of units working together do not all
attack the same handshake twice.

Two independent ways to be found, so it works whether or not the two units ever share a network:

  - Over pwnagotchi's own local mesh (pwngrid): this unit's identity and captured BSSIDs ride along in the same
    WiFi-beacon-frame advertisement pwnagotchi already broadcasts to let two nearby units notice each other. No
    network, no association, no config -- just ordinary WiFi radio range, the same "ESP-NOW style" direct-broadcast
    idea, built on hardware this unit already has active. This is the main path, and needs nothing from you.
  - `GET /plugins/node_pwn/api/info` on this unit's own web UI, for when both units *are* reachable over IP (the
    same network, a VPN, a forwarded port) -- the main unit's theme_manager still supports finding a node this way
    too.

Either way this only ever answers; it never talks to any other node on its own, never touches what this unit
attacks, and never phones home anywhere off your own radio/network.

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
__version__ = "1.1.0"
__license__ = "GPL3"
__description__ = "Answers a small status API, and advertises over pwnagotchi's own mesh, so another unit running theme_manager can find this one and see what it has already captured -- on the same network or not."

BSSID_RE = re.compile(r"[0-9a-fA-F]{12}")
MESH_KEY = "node_pwn"
MESH_MAX_BSSIDS = 25       # a WiFi beacon frame is not a big pipe -- keep this unit's slice of it small
MESH_PUSH_INTERVAL = 60    # seconds between routine pushes; a new handshake also pushes right away


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


def _identity(mac_path="/sys/class/net/wlan0/address"):
    try:
        import pwnagotchi
        name = pwnagotchi.config["main"]["name"]
    except Exception:
        name = os.uname().nodename
    try:
        mac = open(mac_path).read().strip()
    except Exception:
        mac = ""
    return name, mac


def node_info(started, mac_path="/sys/class/net/wlan0/address"):
    name, mac = _identity(mac_path)
    bssids = node_bssids()
    return {"node": "node_pwn", "version": __version__, "name": name, "mac": mac,
            "handshakes": len(bssids), "bssids": bssids, "uptime": round(time.time() - started)}


def mesh_payload(mac_path="/sys/class/net/wlan0/address"):
    """The compact version of node_info() that actually fits in a mesh advertisement: capped BSSID list, no
    uptime/version noise the other unit does not need for this."""
    name, mac = _identity(mac_path)
    bssids = node_bssids()
    return {"name": name, "mac": mac, "n": len(bssids), "b": bssids[-MESH_MAX_BSSIDS:]}


class NodePwn(plugins.Plugin):
    __author__ = __author__
    __version__ = __version__
    __license__ = __license__
    __description__ = __description__

    def __init__(self):
        self._started = time.time()
        self._last_mesh_push = 0

    def on_loaded(self):
        logging.info("[node_pwn] loaded: reachable at /plugins/node_pwn/api/info and over the local mesh")

    def _push_mesh(self):
        try:
            import pwnagotchi.grid as grid
            grid.set_advertisement_data({MESH_KEY: mesh_payload()})
            self._last_mesh_push = time.time()
        except Exception as e:
            logging.debug("[node_pwn] mesh push: %s", e)

    def on_ready(self, agent):
        self._push_mesh()

    def on_handshake(self, agent, filename, ap, sta):
        self._push_mesh()   # a capture changed what we have to offer: worth advertising right away

    def on_epoch(self, agent, epoch, epoch_data):
        if time.time() - self._last_mesh_push >= MESH_PUSH_INTERVAL:
            self._push_mesh()

    def on_webhook(self, path, request):
        from flask import jsonify
        if (path or "") != "api/info":
            return jsonify({"error": "not found"}), 404
        return jsonify(node_info(self._started))
