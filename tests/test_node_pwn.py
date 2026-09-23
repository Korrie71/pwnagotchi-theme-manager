"""node_pwn: the tiny status API a node exposes so the main unit's theme_manager can find it and see what it has
already captured."""
import json
import os
import tempfile
import time

import flask

from _util import finish, ok, sandbox

sandbox()
import node_pwn as N  # noqa: E402
import pwnagotchi.grid as G  # noqa: E402

app = flask.Flask(__name__)


def touch(d, name):
    open(os.path.join(d, name), "w").write("x")


# ---------------------------------------------------------------- bssids from filenames
d = tempfile.mkdtemp()
touch(d, "CoffeeShop_aabbccddeeff.pcapng")
touch(d, "GuestWifi_112233445566.pcapng")
touch(d, "(hidden)_aabbccddeeff.pcapng")   # same bssid again, dedup is the caller's job, not this function's
touch(d, "not-a-capture.txt")
touch(d, "justbssidnounderscore.pcapng")   # no essid separator: the tail after rsplit is not 12 hex chars, skipped
bssids = N.node_bssids(d)
ok("reads bssids from ESSID_BSSID.pcapng filenames", set(bssids) >= {"aabbccddeeff", "112233445566"}, bssids)
ok("bssids are lowercase", all(b == b.lower() for b in bssids))
ok("a file that is not a capture is ignored", len(bssids) == 3, bssids)
ok("an empty or missing folder does not crash it", N.node_bssids(os.path.join(d, "nope")) == [])

# ---------------------------------------------------------------- node_info
os.environ["NODE_PWN_HANDSHAKES"] = d
fake_mac = os.path.join(d, "address")
open(fake_mac, "w").write("02:00:00:00:00:2a\n")
info = N.node_info(time.time() - 5, mac_path=fake_mac)
ok("identifies itself", info["node"] == "node_pwn" and info["version"] == N.__version__)
ok("reports its handshake count and bssids consistently", info["handshakes"] == len(info["bssids"]) == 3)
ok("reads its mac from the given file", info["mac"] == "02:00:00:00:00:2a")
ok("uptime is a small non-negative number", 0 <= info["uptime"] < 60, info["uptime"])
ok("a missing mac file does not crash it", N.node_info(time.time(), mac_path=os.path.join(d, "nope"))["mac"] == "")

# ---------------------------------------------------------------- the plugin, end to end through on_webhook
plugin = N.NodePwn()
with app.test_request_context("/api/info", method="GET"):
    r = plugin.on_webhook("api/info", flask.request)
body = json.loads(r.get_data())
ok("on_webhook answers api/info with the same shape node_info returns", body["node"] == "node_pwn" and body["handshakes"] == 3)

with app.test_request_context("/api/nope", method="GET"):
    r2 = plugin.on_webhook("api/nope", flask.request)
status = r2[1] if isinstance(r2, tuple) else r2.status_code
ok("an unknown path is a 404, not a crash", status == 404)

# ---------------------------------------------------------------- mesh_payload: the compact version for a beacon
big = tempfile.mkdtemp()
for i in range(30):
    touch(big, "Net%d_%012x.pcapng" % (i, i))
payload = N.mesh_payload(mac_path=fake_mac)
ok("reports its full count even when the bssid list itself is capped", payload["n"] == 3)   # still points at `d`, not `big`
os.environ["NODE_PWN_HANDSHAKES"] = big
payload = N.mesh_payload(mac_path=fake_mac)
ok("caps the bssid list to keep the beacon payload small", payload["n"] == 30 and len(payload["b"]) == N.MESH_MAX_BSSIDS, len(payload["b"]))
ok("name and mac are in the compact payload too", payload["mac"] == "02:00:00:00:00:2a" and payload["name"])
os.environ["NODE_PWN_HANDSHAKES"] = d

# ---------------------------------------------------------------- pushing to the mesh (over pwnagotchi's own grid)
pushed = []
G.set_advertisement_data = lambda data: pushed.append(data)
plugin2 = N.NodePwn()
plugin2.on_ready(None)
ok("on_ready pushes a mesh advertisement right away", len(pushed) == 1)
ok("...keyed so it does not collide with pwnagotchi's own advertisement fields", list(pushed[0].keys()) == [N.MESH_KEY])
ok("...carrying this unit's identity and captures", pushed[0][N.MESH_KEY]["mac"] and pushed[0][N.MESH_KEY]["n"] == 3)

plugin2.on_handshake(None, "x.pcapng", {}, {})
ok("a new handshake pushes again immediately, no throttle", len(pushed) == 2)

plugin2.on_epoch(None, 1, {})
ok("a routine epoch does not push again right after a push (throttled)", len(pushed) == 2)
plugin2._last_mesh_push = time.time() - N.MESH_PUSH_INTERVAL - 1
plugin2.on_epoch(None, 2, {})
ok("...but does once the interval has passed", len(pushed) == 3)

G.set_advertisement_data = lambda data: (_ for _ in ()).throw(RuntimeError("mesh is down"))
plugin2.on_handshake(None, "x.pcapng", {}, {})
ok("a mesh push failure (pwngrid not running, say) does not crash the plugin", True)

del os.environ["NODE_PWN_HANDSHAKES"]
finish()
