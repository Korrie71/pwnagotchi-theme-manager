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

del os.environ["NODE_PWN_HANDSHAKES"]
finish()
