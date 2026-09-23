"""The doctor: what looks wrong on a unit, worked out from the log, the kernel messages, the service and the disk."""
import time

from PIL import Image

from _util import Panel, T, finish, new_manager, ok, sandbox

sandbox()
NOW = time.mktime(time.strptime("2026-05-01 12:00:00", "%Y-%m-%d %H:%M:%S"))


def line(ago, level, msg):
    return "[%s,123] [%s] [Thread-9 (x)] : %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - ago)), level, msg)


def titles(res):
    return [i["title"] for i in res["items"]]


ok("a healthy unit has nothing to report", T.diagnose(NOW) == {"status": "ok", "items": [], "checked_at": NOW})

# ---------------------------------------------------------------- the log
text = "\n".join([line(60, "INFO", "all fine"), "Traceback (most recent call last):", '  File "x.py", line 1', line(2 * 3600, "ERROR", "[old] ancient")])
ok("old lines, other levels and traceback bodies are not counted", T.diagnose(NOW, log_text=text)["status"] == "ok")
ok("_log_events keeps only what is inside the window", len(T._log_events(text, NOW)) == 1)

bt = "\n".join(line(30 * i, "ERROR", "[bt-tether] Connection failed: NAP/PAN setup incomplete") for i in range(1, 4))
r = T.diagnose(NOW, log_text=bt)
ok("repeated bt-tether failures are named, with what to do", titles(r) == ["bt-tether cannot connect"] and "phone" in r["items"][0]["hint"] and r["status"] == "warn", r)
ok("...but two failures are just noise", T.diagnose(NOW, log_text="\n".join(bt.splitlines()[:2]))["status"] == "ok")

pw = "\n".join(line(20 * i, "ERROR", "main loop exception (HTTPConnectionPool(host='127.0.0.1', port=8666): Read timed out. (read timeout=20.0))") for i in range(1, 3))
r = T.diagnose(NOW, log_text=pw)
ok("pwngrid-peer timing out is a bad one, and is not also reported as a generic plugin error", titles(r) == ["pwngrid-peer is not answering"] and r["status"] == "bad", r)

many = "\n".join(line(10 * i, "ERROR", "[flaky] boom %d" % i) for i in range(1, 7))
ok("a plugin that keeps logging errors is named", titles(T.diagnose(NOW, log_text=many)) == ["flaky keeps logging errors"])
ok("...but a few errors are not enough", T.diagnose(NOW, log_text="\n".join(many.splitlines()[:4]))["status"] == "ok")

# ---------------------------------------------------------------- the kernel, the service, the disk
drv = ["[ 8519.88] ieee80211 phy0: brcmf_proto_bcdc_query_dcmd: brcmf_proto_bcdc_msg failed w/status -110"] * 5
r = T.diagnose(NOW, dmesg_lines=drv)
ok("a stuck WiFi driver says only a reboot fixes it", titles(r) == ["the WiFi driver is timing out"] and "reboot" in r["items"][0]["hint"] and r["status"] == "bad")
ok("...a few driver errors are not a diagnosis", T.diagnose(NOW, dmesg_lines=drv[:3])["status"] == "ok")
ok("other kernel noise is ignored", T.diagnose(NOW, dmesg_lines=["[ 1.0] Bluetooth: Unexpected continuation frame"] * 20)["status"] == "ok")

ok("a crash loop is the headline", titles(T.diagnose(NOW, restarts=5, service_age=40)) == ["pwnagotchi keeps restarting"])
ok("...one recent restart is only a note", T.diagnose(NOW, restarts=1, service_age=60)["status"] == "warn")
ok("...old restarts are not news", T.diagnose(NOW, restarts=5, service_age=7200)["status"] == "ok")
ok("an unknown service age is not a finding", T.diagnose(NOW, restarts=5, service_age=None)["status"] == "ok")

ok("a nearly full disk is bad", T.diagnose(NOW, disk_free=0.02)["status"] == "bad")
ok("a filling disk is a warning", T.diagnose(NOW, disk_free=0.08)["status"] == "warn")
ok("a roomy disk is fine", T.diagnose(NOW, disk_free=0.5)["status"] == "ok")

everything = T.diagnose(NOW, log_text=bt + "\n" + pw, dmesg_lines=drv, restarts=5, service_age=10, disk_free=0.02)
ok("several problems are all listed, and the worst sets the status", len(everything["items"]) == 5 and everything["status"] == "bad")

# ---------------------------------------------------------------- the real sources fail soft
ins = T._doctor_inputs()
ok("the real sources always give a complete answer, even where they cannot be read", set(ins) == {"log_text", "dmesg_lines", "restarts", "service_age", "disk_free"})
ok("...that diagnose accepts", T.diagnose(**ins)["status"] in ("ok", "warn", "bad"))

# ---------------------------------------------------------------- the manager: cached, refreshed in the background
tm, ui, els = new_manager()
calls = []
real = T.diagnose
T.diagnose = lambda **kw: (calls.append(1), {"status": "warn", "items": [{"level": "warn", "title": "x", "detail": "d", "hint": "h"}], "checked_at": 1})[1]
T._doctor_inputs, keep = (lambda: {}), T._doctor_inputs
ok("the doctor has not run before anyone asks", tm._doctor[1] is None)
r1 = tm.doctor()
r2 = tm.doctor()
ok("its answer is cached for a few seconds, not recomputed per call", len(calls) == 1 and r1 is r2)
tm.doctor(force=True)
ok("...unless you ask it to check again", len(calls) == 2)

# ---------------------------------------------------------------- the touch menu
finger = Panel(tm)
finger.calibrate()
tm._doctor = (0, None)
tm.open_menu("list", "system")
ok("the System tab has a doc button", any(a == ("doctor", None) for _, a in T.menu_hits(tm._menu)))
tm._toast = None
finger.tap_rect(finger.hit("doctor"))
ok("tapping it before the first check says to wait, not a blank popup", tm._menu["mode"] == "list" and tm._toast and "checking" in tm._toast[0], tm._toast)
import time as _t
end = _t.time() + 3
while tm._doctor[1] is None and _t.time() < end:
    _t.sleep(0.02)
ok("...and the check happens in the background", tm._doctor[1] is not None and tm._doctor[1]["status"] == "warn")
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
tm._menu["doctor"] = tm._doctor[1]
finger.tap_rect(finger.hit("doctor"))
ok("tapping it again opens the doctor", tm._menu["mode"] == "doctor")
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("...and it draws, with a problem listed", True)
tm._menu["doctor"] = {"status": "ok", "items": [], "checked_at": 1}
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("...and draws the all-good case", True)
tm._menu["doctor"] = {"status": "bad", "items": [{"level": "bad", "title": "t" * 30, "detail": "d" * 60, "hint": "h" * 200}] * 6, "checked_at": 1}
T.draw_menu(Image.new("RGB", (480, 320)), tm._menu, tm._theme)
ok("...and copes with too many, too-long findings", True)
finger.tap_rect(finger.hit("doctorclose"))
ok("close returns to the System tab", tm._menu["mode"] == "list" and tm._menu["tab"] == "system")
T.diagnose, T._doctor_inputs = real, keep

# ---------------------------------------------------------------- the web API
try:
    import flask
except ImportError:
    finish()
import json
app = flask.Flask(__name__)
with app.test_request_context("/api/doctor"):
    j = json.loads(tm.on_webhook("api/doctor", flask.request).get_data())
ok("api/doctor answers with the same shape", j["status"] in ("ok", "warn", "bad") and isinstance(j["items"], list))

finish()
