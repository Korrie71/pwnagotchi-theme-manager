"""Text placeholders: {ip} {gps} {handshakes} {cracked} {session} {power} {battery} {mode} and friends."""
import os
import re
import tempfile
import threading
import time

from _util import T, finish, new_manager, ok, sandbox

sandbox()

# ---------------------------------------------------------------- values read from the system
hs = tempfile.mkdtemp()
for f in ("a.pcap", "b.pcapng", "c.pcap", "notes.txt", "d.pcap.bak"):
    open(os.path.join(hs, f), "w").write("x")
open(os.path.join(hs, "wpa-sec.cracked.potfile"), "w").write("aa:bb:Net1:pw1\ncc:dd:Net2:pw2\n\n")
open(os.path.join(hs, "cracked.pwncrack.potfile"), "w").write("x:aa:y:Net3:pw3\n")
T._handshake_dir = lambda: hs
T._slow.clear()
ok("{handshakes} counts pcap and pcapng files only", T._expand("{handshakes}") == "3", T._expand("{handshakes}"))
ok("{cracked} counts the non-empty potfile lines", T._expand("{cracked}") == "3", T._expand("{cracked}"))
ip = T._expand("{ip}")
ok("{ip} is a dotted IPv4 address, or 'no ip'", bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip)) or ip == "no ip", ip)
ok("{power} is OK, LOW or n/a", T._expand("{power}") in ("OK", "LOW", "n/a"), T._expand("{power}"))
battery = T._expand("{battery}")
ok("{battery} is a percentage or n/a", battery == "n/a" or battery.endswith("%"), battery)
ok("unknown placeholders are kept, {{ }} are literal braces", T._expand("{nope} {{x}}") == "{nope} {x}")
ok("format specs work", len(T._expand("[{ip:>20}]")) >= 22)
for token in ("time", "date", "name", "cpu", "temp", "mem", "uptime", "ip", "handshakes", "cracked", "power", "battery"):
    value = T._expand("{%s}" % token)
    assert value and not value.startswith("{"), (token, value)
ok("every built-in placeholder expands to something", True)
import pwnagotchi
pwnagotchi.config = {"main": {"name": "testbot"}}
T._stats["t"] = 0
ok("{name} is the name from pwnagotchi's config", T._expand("{name}") == "testbot")
pwnagotchi.config = None
T._stats["t"] = 0
ok("...or the machine's hostname when there is no config", T._expand("{name}") == os.uname().nodename)
empty = tempfile.mkdtemp()
T._handshake_dir = lambda: empty
T._slow.clear()
ok("empty folder: counts are 0", T._expand("{handshakes} {cracked}") == "0 0")
T._handshake_dir = lambda: os.path.join(empty, "does-not-exist")
T._slow.clear()
ok("missing folder: a '?' instead of an error", T._expand("{handshakes} {cracked}") == "? ?")
T._handshake_dir = lambda: hs

# ---------------------------------------------------------------- caching and laziness
counter = {"n": 0}
orig = T.PROVIDERS["ip"]
T.PROVIDERS["ip"] = (15, lambda: (counter.__setitem__("n", counter["n"] + 1), "1.2.3.4")[1])
T._slow.clear()
for _ in range(200):
    T._expand("{ip} {ip}")
ok("a slow value is read once per cache period, not once per frame", counter["n"] == 1, counter["n"])
T.PROVIDERS["ip"] = orig
T._slow.clear()
asked = {"n": 0}
T.STAT_SOURCE = lambda key: (asked.__setitem__("n", asked["n"] + 1), None)[1]
for _ in range(50):
    T._expand("plain {time} text")
ok("a line that does not use a live value never asks for one", asked["n"] == 0)
T.STAT_SOURCE = None
start = time.perf_counter()
for _ in range(2000):
    T._expand("{time} {ip} {handshakes} {cpu} {temp}")
per_call = (time.perf_counter() - start) / 2000
ok("expanding five placeholders is cheap (< 0.05 ms)", per_call < 5e-5, "%.3f ms" % (per_call * 1000))

# ---------------------------------------------------------------- values that need pwnagotchi's live state
tm, ui, els = new_manager()
T.STAT_SOURCE = tm._live_stat


class Agent:
    mode = "auto"


tm._view._agent = Agent()
ok("{gps} is n/a until there is data", T._expand("{gps} {lat} {lon} {sats}") == "n/a - - -")
tm._gps = {"Latitude": 52.123456, "Longitude": 4.654321, "NumSatellites": 9, "FixQuality": "1"}
ok("{gps} with a fix", T._expand("{gps}") == "FIX 9sat")
ok("{lat} and {lon} have 5 decimals", T._expand("{lat} {lon}") == "52.12346 4.65432")
ok("{sats}", T._expand("{sats}") == "9")
tm._gps = {"Latitude": 0.0, "Longitude": 0.0, "NumSatellites": 3, "FixQuality": "0"}
ok("no fix: 'no fix', '-', and the satellites it can see", T._expand("{gps}|{lat}|{sats}") == "no fix|-|3")
tm._gps = {"Latitude": "garbage", "Longitude": None}
ok("garbage GPS values do not raise", T._expand("{gps} {lat}") == "no fix -")
ok("{session} is the first number of the 'N (total)' text", T._expand("{session}") == "4")
ui._agent = Agent()
tm._view = type("V", (), {"get": lambda self, k: None, "_agent": Agent()})()
ok("{session} is 0 before anything is captured", T._expand("{session}") == "0")
ok("{mode} is AUTO", T._expand("{mode}") == "AUTO")
tm._view._agent.mode = "manual"
ok("{mode} is MANU in manual mode", T._expand("{mode}") == "MANU")
tm._gps_wanted = 0
tm._gps_evt.clear()
T._expand("{gps}")
ok("asking for GPS after a quiet spell wakes the refresher at once", tm._gps_evt.is_set())

# ---------------------------------------------------------------- the GPS refresher
fetched = []


class GpsAgent:
    mode = "auto"

    def session(self):
        fetched.append(1)
        return {"gps": {"Latitude": 1.0, "Longitude": 2.0, "NumSatellites": 5}}


tm._view = type("V", (), {"get": lambda self, k: None, "_agent": GpsAgent()})()
tm._gps = None
tm._running = True
tm._gps_wanted = time.time()
tm._gps_evt.set()
thread = threading.Thread(target=tm._gps_loop, daemon=True)
thread.start()
time.sleep(0.6)
ok("it fetches while something is showing GPS values", fetched and tm._gps and tm._gps["NumSatellites"] == 5)
tm._gps_wanted = time.time() - 100
count = len(fetched)
tm._gps_evt.set()
time.sleep(0.4)
ok("...and stops when nothing is", len(fetched) == count)
tm._running = False
tm._gps_evt.set()
thread.join(3)
ok("the refresher stops on shutdown", not thread.is_alive())


class BrokenAgent:
    def session(self):
        raise RuntimeError("bettercap is down")


tm._view = type("V", (), {"get": lambda self, k: None, "_agent": BrokenAgent()})()
tm._running = True
tm._gps_wanted = time.time()
tm._gps_evt.set()
thread = threading.Thread(target=tm._gps_loop, daemon=True)
thread.start()
time.sleep(0.5)
ok("a failing bettercap is survived (GPS just reads n/a)", thread.is_alive() and tm._gps is None)
tm._running = False
tm._gps_evt.set()
thread.join(30)

# ---------------------------------------------------------------- themes using them
def text_theme(token):
    return T._clean({"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff",
                     "text": [{"text": "{%s}" % token, "x": 0, "y": 0}]})


for token in ("ip", "mode", "gps", "lat", "lon", "sats", "handshakes", "cracked", "session", "power", "battery", "time", "cpu"):
    assert T.is_animated(text_theme(token)), token
ok("a text line with a live placeholder makes the theme refresh", True)
ok("...once a second", T.frame_interval(text_theme("ip"), 1.0) == 1.0)
ok("{name} and {date} do not", not T.is_animated(text_theme("name")) and not T.is_animated(text_theme("date")))

finish()
