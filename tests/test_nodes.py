"""Node scanning and pairing: finding other units running node_pwn on the network, and remembering the ones you
pair with so their capture stats stick around between scans."""
import http.server
import json
import os
import threading
import time

from _util import Panel, T, finish, new_manager, ok, sandbox

sandbox()


def make_handler(body_bytes, status=200):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/plugins/node_pwn/api/info":
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body_bytes)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass
    return H


def fake_node(info, status=200):
    srv = http.server.HTTPServer(("127.0.0.1", 0), make_handler(json.dumps(info).encode(), status))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "127.0.0.1:%d" % srv.server_address[1]


NODE_A = {"node": "node_pwn", "version": "1.0.0", "name": "node-a", "mac": "02:00:00:00:00:01",
          "handshakes": 2, "bssids": ["aabbccddeeff", "112233445566"], "uptime": 40}
NODE_B = {"node": "node_pwn", "version": "1.0.0", "name": "node-b", "mac": "02:00:00:00:00:02",
          "handshakes": 0, "bssids": [], "uptime": 5}

srv_a, addr_a = fake_node(NODE_A)
srv_b, addr_b = fake_node(NODE_B)
srv_other, addr_other = fake_node({"node": "something_else"})            # not a node_pwn unit
srv_nomac, addr_nomac = fake_node({"node": "node_pwn", "mac": "", "name": "no-mac"})   # a mac read failure
addr_closed = "127.0.0.1:1"                                              # nothing listens on a privileged port here

# ---------------------------------------------------------------- _probe_node
ok("probes a real node_pwn endpoint", T._probe_node(addr_a) == dict(NODE_A, ip=addr_a))
ok("rejects a JSON body that is not from node_pwn", T._probe_node(addr_other) is None)
ok("rejects a node_pwn reply with no mac (nothing stable to key it on)", T._probe_node(addr_nomac) is None)
ok("a closed port is just not found, no exception", T._probe_node(addr_closed) is None)
ok("a host:port string and separate host/port both work", T._probe_node("127.0.0.1", port=int(addr_a.split(":")[1])) == dict(NODE_A, ip="127.0.0.1"))

# ---------------------------------------------------------------- scan_for_nodes: concurrent, only real nodes
found = T.scan_for_nodes(hosts=[addr_a, addr_b, addr_other, addr_nomac, addr_closed, "127.0.0.1:2", "127.0.0.1:3"])
ok("finds exactly the real node_pwn endpoints", sorted(f["mac"] for f in found) == ["02:00:00:00:00:01", "02:00:00:00:00:02"], found)
ok("an empty pool returns nothing and does not crash", T.scan_for_nodes(hosts=[]) == [])

# ---------------------------------------------------------------- persistence
ok("nothing saved yet loads as empty", T._load_nodes() == {})
T._save_nodes({"02:00:00:00:00:01": dict(NODE_A, ip="127.0.0.1")})
ok("a saved pairing loads back", T._load_nodes()["02:00:00:00:00:01"]["name"] == "node-a")
ok("a missing/corrupt file loads as empty, not a crash", (open(os.path.join(T.THEME_DIR, "nodes.json"), "w").write("not json"), T._load_nodes())[1] == {})

# ---------------------------------------------------------------- the manager: scan, pair, unpair
sandbox()
tm, ui, els = new_manager()
tm._settings = T.clean_settings({})
tm._display_cfg = T.clean_display({})
ok("nothing found or paired yet", tm.node_rows() == ([], []))

tm.scan_nodes(hosts=[addr_a, addr_b, addr_other])
paired, foundrows = tm.node_rows()
ok("a scan populates the found list, nothing paired by itself", paired == [] and sorted(f["mac"] for f in foundrows) == ["02:00:00:00:00:01", "02:00:00:00:00:02"])

ok("pairing an unknown mac fails cleanly", tm.pair_node("02:00:00:00:00:99") is False)
ok("pairing a mac from the last scan works", tm.pair_node("02:00:00:00:00:01") is True)
paired, foundrows = tm.node_rows()
ok("it moves from found to paired", len(paired) == 1 and paired[0]["mac"] == "02:00:00:00:00:01")
ok("...and found no longer repeats an already-paired node", all(f["mac"] != "02:00:00:00:00:01" for f in foundrows))
ok("pairing is saved to disk", T._load_nodes().get("02:00:00:00:00:01", {}).get("name") == "node-a")

# a second manager instance (e.g. after a restart) picks up the pairing from disk
tm2, ui2, els2 = new_manager()
tm2._settings = T.clean_settings({})
tm2._display_cfg = T.clean_display({})
paired2, _ = tm2.node_rows()
ok("pairing survives a restart (loaded from nodes.json)", len(paired2) == 1 and paired2[0]["mac"] == "02:00:00:00:00:01")

# ---------------------------------------------------------------- refresh: online/offline, updated stats, and the shared bssid set
srv_a.shutdown()   # node-a goes offline
srv_a.server_close()
tm.refresh_paired_nodes()
paired, _ = tm.node_rows()
ok("an unreachable paired node is marked offline, not dropped", len(paired) == 1 and paired[0]["online"] is False)
ok("a node teammate's bssids do not count while it is offline", tm.all_node_bssids() == set())

tm.pair_node("02:00:00:00:00:02")   # node-b (still up) also paired
tm.refresh_paired_nodes()
ok("an online paired node's bssids feed the shared 'a teammate already has this' set", tm.all_node_bssids() == set())  # node-b has none
srv_b.shutdown()
srv_b.server_close()

ok("unpairing removes it and is saved", tm.unpair_node("02:00:00:00:00:01") is True and "02:00:00:00:00:01" not in T._load_nodes())
ok("unpairing something not paired is a clean no-op", tm.unpair_node("02:00:00:00:00:01") is False)

srv_other.shutdown()
srv_other.server_close()
srv_nomac.shutdown()
srv_nomac.server_close()

# ---------------------------------------------------------------- the touch menu
sandbox()
tm3, ui3, els3 = new_manager()
tm3._settings = T.clean_settings({})
tm3._display_cfg = T.clean_display({})
finger = Panel(tm3)
finger.calibrate()


def wait_scan(tm, seconds=3):
    end = time.time() + seconds
    while tm._menu and tm._menu.get("nodes_scanning") and time.time() < end:
        time.sleep(0.02)


tm3.open_menu("list", "nodes")
ok("the nodes tab opens with nothing yet", tm3._menu["tab"] == "nodes" and len(tm3._menu["nodes"]) == 1)
T.draw_menu(__import__("PIL.Image", fromlist=["Image"]).new("RGB", (480, 320)), tm3._menu, tm3._theme)
ok("...and draws the empty-state hint without crashing", True)

srv_c, addr_c = fake_node({"node": "node_pwn", "version": "1.0.0", "name": "node-c", "mac": "02:00:00:00:00:03",
                            "handshakes": 5, "bssids": ["aabbccddeeff"], "uptime": 20})
real_scan = T.scan_for_nodes
T.scan_for_nodes = lambda **kw: real_scan(hosts=[addr_c])   # keep on_tap's real thread/sync flow, fake the network

scan_hit = next(r for r, a in T.menu_hits(tm3._menu) if a == ("scan", None))
finger.tap_rect(scan_hit)
ok("tapping scan marks it busy and keeps the menu open", tm3._menu is not None and tm3._menu["nodes_scanning"] is True)
wait_scan(tm3)
ok("when done, the found node shows up", any(r[1] == ("noderow", "f:02:00:00:00:00:03") for r in T.menu_hits(tm3._menu)))

pair_hit = next(r for r, a in T.menu_hits(tm3._menu) if a == ("noderow", "f:02:00:00:00:00:03"))
tm3._toast = None
finger.tap_rect(pair_hit)
ok("tapping a found row pairs it", tm3._toast and "paired with node-c" in tm3._toast[0], tm3._toast)
ok("it now shows up as paired", any(r[1] == ("noderow", "p:02:00:00:00:00:03") for r in T.menu_hits(tm3._menu)))
ok("...and it is actually saved", "02:00:00:00:00:03" in T._load_nodes())

paired_hit = next(r for r, a in T.menu_hits(tm3._menu) if a == ("noderow", "p:02:00:00:00:00:03"))
tm3._toast = None
finger.tap_rect(paired_hit)
ok("tapping a paired row shows its details and asks to tap again", tm3._toast and "tap again to unpair" in tm3._toast[0], tm3._toast)
ok("...and does not unpair yet", "02:00:00:00:00:03" in T._load_nodes())
finger.tap_rect(paired_hit)
ok("tapping it again unpairs it", "02:00:00:00:00:03" not in T._load_nodes())
ok("...and it goes back to being just a found candidate (still in the last scan) instead of vanishing",
   any(a == ("noderow", "f:02:00:00:00:00:03") for _, a in T.menu_hits(tm3._menu)))

finger.tap_rect(finger.hit("tab", "themes"))
ok("the other tabs stay reachable", tm3._menu["tab"] == "themes")

T.scan_for_nodes = real_scan
srv_c.shutdown()
srv_c.server_close()
finish()
