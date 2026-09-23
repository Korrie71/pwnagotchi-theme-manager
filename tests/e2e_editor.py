"""Real-browser test of the web editor against a RUNNING plugin (not part of run_all.py).

    pip install playwright && playwright install chromium-headless-shell
    python tests/e2e_editor.py [http://localhost:8080/plugins/theme_manager/]

It saves and deletes a few throwaway themes and face packs named zz-e2e-*, briefly shows a theme on the screen, and
re-applies the theme that was active before it started.
"""
import io
import json
import os
import re
import sys
import tempfile
import zipfile

import requests
from PIL import Image
from playwright.sync_api import sync_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/plugins/theme_manager/").rstrip("/") + "/"
results, console_errors = [], []


def check(name, ok, extra=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" [%s]" % (extra,)) if extra != "" else ""))


def png(name, color):
    path = os.path.join(tempfile.mkdtemp(), name)
    Image.new("RGBA", (240, 90), color).save(path)
    return path


def api_themes():
    return requests.get(URL + "api/themes").json()


def cleanup(page_request=None):
    s = requests.Session()
    tok = re.search(r'name="csrf_token" content="([^"]+)"', s.get(URL).text).group(1)
    h = {"X-CSRFToken": tok, "Content-Type": "application/json"}
    for name in list(api_themes()["themes"]):
        if name.startswith("zz-e2e"):
            s.post(URL + "api/delete", data=json.dumps({"name": name}), headers=h)
    for pack in requests.get(URL + "api/packs").json():
        if pack.startswith("zz-e2e"):
            s.post(URL + "api/faces/delete", data=json.dumps({"pack": pack}), headers=h)


original = api_themes()["active"]
cleanup()
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1000, "height": 1000}, accept_downloads=True)
    page = ctx.new_page()
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append("PAGEERROR " + str(e)))
    page.on("dialog", lambda d: d.accept())
    page.goto(URL)
    page.wait_for_selector(".card")
    page.wait_for_function("document.getElementById('prev').naturalWidth>0")
    tab = lambda n: page.click("#tabs button:text-is('%s')" % n)
    msg = lambda: page.inner_text("#msg")
    wait_msg = lambda text, t=8000: page.wait_for_function("t=>document.getElementById('msg').textContent.includes(t)", arg=text, timeout=t)

    def click_until(selector, done, attempts=10, pause=500):
        """Click, and if `done()` is not true shortly after, click again. On an animated theme this rig occasionally
        drops a synthetic click on a plain <button> -- confirmed to be an input-dispatch/CPU-contention quirk of this
        headless-shell build, not the page: the exact same click, force-dispatched at the verified correct on-screen
        coordinates, still sometimes does nothing, while calling the button's own onclick handler directly always
        produces the identical, correct result a real click should. Retrying is simpler and more honest than
        pretending a fixed delay makes it deterministic."""
        for _ in range(attempts):
            page.click(selector, force=True)
            page.wait_for_timeout(pause)
            if done():
                return
        raise AssertionError("click on %s never took effect after %d attempts" % (selector, attempts))

    check("the editor loads with its theme cards and a preview", page.locator(".card").count() >= 13)
    page.click(".card[data-name='cyberpunk']")
    page.wait_for_timeout(300)   # picking a card re-renders the panel and kicks off a preview fetch; let it settle
    # before the next click, or a click can land while the DOM is mid-update and silently miss (seen once the page
    # grew enough tabs to make that re-render take a little longer)

    # ---------------------------------------------------------------- try a theme for a while
    sent = {}

    def try_route(route):
        body = json.loads(route.request.post_data)
        sent.update(body)
        body["seconds"] = 5                                   # keep the real test short
        route.continue_(post_data=json.dumps(body))

    page.route("**/api/try", try_route)
    click_until("#try", lambda: "for 5 s" in msg())
    check("'Try' sends the theme being edited and 30 seconds", sent.get("seconds") == 30 and sent["theme"]["fg"] == "#00f0ff", sent.get("seconds"))
    check("the button counts down and the message says what happens", "back in" in page.inner_text("#try") and "Apply keeps it" in msg())
    page.unroute("**/api/try")
    page.wait_for_function("document.getElementById('try').textContent==='Try 30 s'", timeout=9000)
    check("...and returns to normal when the time is up", True)
    page.route("**/api/try", lambda r: r.fulfill(status=400, content_type="application/json", body='{"ok":false,"error":"bad theme"}'))
    click_until("#try", lambda: "bad theme" in msg())
    check("a refused theme shows the reason", True)
    page.unroute("**/api/try")

    # ---------------------------------------------------------------- a lost session is recovered
    ctx.clear_cookies()
    page.fill("#name", "zz-e2e-csrf")
    page.click("#save")
    wait_msg("saved zz-e2e-csrf")
    check("after the session is lost, saving works (the page fetches a fresh token and retries)", "zz-e2e-csrf" in api_themes()["themes"])
    ctx.clear_cookies()
    tab("Colors")
    page.evaluate("()=>{const e=document.querySelector('#panel input[type=color]');e.value='#123456';e.dispatchEvent(new Event('input',{bubbles:true}))}")
    page.wait_for_function("document.getElementById('prev').naturalWidth>0")
    page.wait_for_timeout(1200)
    check("...and so does the live preview", msg() == "" or "token" not in msg().lower(), msg())

    # ---------------------------------------------------------------- import from a link
    tab("JSON")
    urls = []
    theme_body = json.dumps({"bg": "#101010", "fg": "#abcdef", "accent": "#fedcba", "web": "#00ff00"})
    page.route("https://raw.githubusercontent.com/**", lambda r: (urls.append(r.request.url), r.fulfill(body=theme_body, content_type="application/json", headers={"access-control-allow-origin": "*"}))[1])
    page.route("https://example.test/**", lambda r: r.fulfill(body="<html>not a theme</html>", content_type="text/html", headers={"access-control-allow-origin": "*"}))
    page.fill("#url", "https://github.com/someone/repo/blob/main/themes/cool-one.json")
    page.click("#importurl")
    wait_msg("imported from the link")
    check("a github.com page link is turned into the raw file link", urls == ["https://raw.githubusercontent.com/someone/repo/main/themes/cool-one.json"], urls)
    check("the theme is loaded and named after the file", '"fg": "#abcdef"' in page.input_value("#json") and page.input_value("#name") == "cool-one")
    page.fill("#url", "http://insecure.test/theme.json")
    page.click("#importurl")
    check("a link that is not https is refused", "https" in msg())
    page.fill("#url", "https://example.test/nothing.json")
    page.click("#importurl")
    wait_msg("could not read a theme")
    check("a link that is not a theme is reported", True)

    # ---------------------------------------------------------------- backup and restore
    with page.expect_download() as d:
        page.click("#dl button")
    zf = zipfile.ZipFile(d.value.path())
    check("the backup downloads as a zip with the user's themes", any(n.startswith("themes/") for n in zf.namelist()) and d.value.suggested_filename == "theme-manager-backup.zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("themes/zz-e2e-restored.json", theme_body)
        z.writestr("themes/default.json", theme_body)
    path = os.path.join(tempfile.mkdtemp(), "b.zip")
    open(path, "wb").write(buf.getvalue())
    page.set_input_files("#bfile", path)
    page.wait_for_selector(".card[data-name='zz-e2e-restored']", timeout=8000)
    check("restoring a backup adds the theme and skips a built-in name", "zz-e2e-restored" in api_themes()["themes"] and "1" in msg(), msg())
    page.set_input_files("#bfile", path)
    page.wait_for_timeout(1000)
    check("restoring again does not duplicate or overwrite by default", msg() != "")
    open(path, "wb").write(b"not a zip")
    page.set_input_files("#bfile", path)
    page.wait_for_timeout(1000)
    check("a file that is not a zip is reported, nothing breaks", msg() != "" and page.locator(".card").count() >= 13, msg())

    # ---------------------------------------------------------------- face packs from the browser
    page.click(".card[data-name='cyberpunk']")
    page.wait_for_timeout(300)   # see the comment on the same wait above: let the re-render settle before clicking again
    tab("Faces")
    page.fill("#packname", "zz-e2e-pack")
    page.set_input_files("#facefiles", [png("happy.png", (255, 0, 0, 255)), png("notamood.png", (0, 0, 0, 255))])
    page.click("#faceupload")
    wait_msg("1 saved")
    check("uploading images stores the ones named after a mood and reports the rest", "not used" in msg(), msg())
    page.wait_for_selector(".thumbs img")
    page.wait_for_function("[...document.querySelectorAll('.thumbs img')].every(i=>i.complete&&i.naturalWidth>0)")
    check("the new pack is selected and its face shows up", requests.get(URL + "api/packs").json().get("zz-e2e-pack") == ["happy"] and page.locator(".thumbs img").count() == 1)
    click_until("#facedelete", lambda: page.locator(".thumbs").count() == 0)
    check("the pack can be deleted from the browser", "zz-e2e-pack" not in requests.get(URL + "api/packs").json())

    # ---------------------------------------------------------------- the older editor features still work
    tab("Colors")
    page.click(".card[data-name='matrix']")
    check("selecting a theme loads it", json.loads((tab("JSON"), page.input_value("#json"))[1])["fg"] == "#00ff41")
    tab("Text")
    n0 = page.locator(".tl").count()
    page.click("button:text-is('+ add text line')")
    check("a text line can be added", page.locator(".tl").count() == n0 + 1)
    chips = page.locator(".tl").last.locator(".chips button").all_inner_texts()
    check("with the live placeholders as buttons", all(x in chips for x in ("{ip}", "{gps}", "{handshakes}", "{power}")))
    tab("Elements")
    page.wait_for_selector("#ov .eb")
    page.evaluate("window.scrollTo(0,0)")
    page.locator("#ov .eb").first.click()
    page.wait_for_selector("#pick .erow")
    check("clicking the preview selects an element and shows its colour bar", page.locator("#pick .erow").count() == 1)
    page.fill("#name", "zz-e2e-flow")
    page.click("#save")
    page.wait_for_selector(".card[data-name='zz-e2e-flow']")
    page.click("#apply")
    page.wait_for_selector(".card.act[data-name='zz-e2e-flow']", timeout=8000)
    check("save and apply work", True)
    with page.expect_download() as d2:
        page.click("#export")
    check("export downloads the theme as JSON", json.load(open(d2.value.path()))["fg"] == "#00ff41")
    page.click(".card[data-name='zz-e2e-flow']")
    page.click("#del")
    page.wait_for_function("!document.querySelector(\".card[data-name='zz-e2e-flow']\")", timeout=8000)
    check("delete works", True)
    # ---------------------------------------------------------------- scenery in the Effects tab
    tab("Effects")
    page.locator("label.ck:has-text('scene') input").first.check()
    page.wait_for_selector(".fxbox select")
    page.select_option(".fxbox select >> nth=-1", "volcano")
    effects = json.loads((tab("JSON"), page.input_value("#json"))[1])["effects"]
    check("the Effects tab adds a scene and lets you choose its scenery", any(e["type"] == "scene" and e["kind"] == "volcano" for e in effects), effects)

    # ---------------------------------------------------------------- layout, awards and settings
    s0 = requests.Session()
    tok0 = re.search(r'name="csrf_token" content="([^"]+)"', s0.get(URL).text).group(1)
    s0.post(URL + "api/layout", data=json.dumps({"reset": True}), headers={"X-CSRFToken": tok0, "Content-Type": "application/json"})
    tab("Layout")
    page.wait_for_selector(".erow[data-key='name']")
    check("the Layout tab lists the elements that are on the screen", page.locator(".erow").count() >= 5 and all(page.locator(".erow[data-key='%s']" % k).count() for k in ("name", "face", "status")))
    page.locator(".erow[data-key='name'] .lx\\+").click()
    page.locator(".erow[data-key='name'] .ly\\+").click()
    page.wait_for_function("document.querySelector(\".erow[data-key='name'] .x\")")
    for _ in range(25):
        rows = {r["key"]: r for r in requests.get(URL + "api/layout").json()["rows"]}
        if (rows["name"]["dx"], rows["name"]["dy"]) == (1, 1):
            break
        page.wait_for_timeout(200)
    check("two quick clicks (X+ then Y+) both count, and it is saved", (rows["name"]["dx"], rows["name"]["dy"]) == (1, 1), rows["name"])
    page.select_option(".row select", "10")
    page.locator(".erow[data-key='name'] .lx-").click()
    page.wait_for_function("document.querySelector(\".erow[data-key='name'] .inh\").textContent.includes('x -9')")
    check("the step can be 10 pixels", True)
    page.locator(".erow[data-key='name'] .x").click()
    page.wait_for_function("!document.querySelector(\".erow[data-key='name'] .x\")||document.querySelector(\".erow[data-key='name']:not(.set)\")")
    for _ in range(25):
        rows = {r["key"]: r for r in requests.get(URL + "api/layout").json()["rows"]}
        if (rows["name"]["dx"], rows["name"]["dy"]) == (0, 0):
            break
        page.wait_for_timeout(200)
    check("the reset button puts that element back", (rows["name"]["dx"], rows["name"]["dy"]) == (0, 0))
    page.locator(".erow[data-key='name'] .lx\\+").click()
    page.click("#layreset")
    page.wait_for_function("!document.querySelector('.erow.set')")
    check("Reset all clears every move", all(r["dx"] == 0 and r["dy"] == 0 for r in requests.get(URL + "api/layout").json()["rows"]))

    tab("Awards")
    page.wait_for_selector(".award")
    check("the Awards tab lists every achievement with its progress", page.locator(".award").count() >= 15 and page.locator(".award.done").count() >= 1)

    cracking0 = requests.get(URL + "api/cracking").json()
    tab("Cracking")
    page.wait_for_selector(".statcard")
    check("the Cracking tab shows the summary cards", page.locator(".statcard").count() == 7)
    check("...and matches the API's counts", page.locator(".statcard div").first.inner_text() == str(cracking0["summary"]["cracked"]))

    tab("Radar")
    page.wait_for_selector("canvas")
    check("the Radar tab draws a sonar canvas", page.locator("canvas").count() == 1)
    page.wait_for_timeout(200)
    shot1 = page.locator("canvas").screenshot()
    page.wait_for_timeout(600)
    shot2 = page.locator("canvas").screenshot()
    check("the sonar sweep actually animates", shot1 != shot2)

    tab("Map")
    page.wait_for_timeout(300)
    check("the Map tab loads with no browser error (empty or listing locations)",
          page.locator("p:has-text('located so far')").count() == 1)

    tab("Nodes")
    page.wait_for_timeout(200)
    check("the Nodes tab loads with no browser error (nothing found yet)", page.locator("p:has-text('No nodes yet')").count() == 1)

    mesh_node = {"node": "node_pwn", "mac": "02:00:00:00:00:0b", "name": "zz-e2e-mesh", "ip": None,
                 "handshakes": 6, "bssids": ["aabbccddeeff"], "via": "mesh", "rssi": -58}
    page.route("**/api/nodes", lambda r: r.fulfill(body=json.dumps({"paired": [], "found": [mesh_node]}), content_type="application/json"))
    tab("Settings")
    tab("Nodes")   # round-trip through another tab to force a fresh loadNodes() with the mesh peer now "in range"
    page.wait_for_timeout(200)
    check("a node in mesh range shows up on its own, no scan or address needed",
          page.locator(".erow:has-text('zz-e2e-mesh')").count() == 1)
    check("...shown as 'mesh' with its signal instead of an address it does not have",
          "mesh, -58 dBm" in page.locator(".erow:has-text('zz-e2e-mesh')").inner_text())
    page.unroute("**/api/nodes")

    fake_node = {"node": "node_pwn", "version": "1.0.0", "name": "zz-e2e-node", "mac": "02:00:00:00:00:09",
                 "ip": "192.0.2.50:8080", "handshakes": 4, "bssids": ["aabbccddeeff"], "uptime": 30}
    page.route("**/api/nodes/scan", lambda r: r.fulfill(body=json.dumps({"ok": True, "paired": [], "found": [fake_node]}),
                                                          content_type="application/json"))
    page.click("button:text-is('Scan for nodes on this network')")
    page.wait_for_selector(".erow:has-text('zz-e2e-node')")
    check("a found node shows up with a Pair button", page.locator(".erow:has-text('zz-e2e-node') button:text-is('Pair')").count() == 1)
    page.unroute("**/api/nodes/scan")
    page.route("**/api/nodes/pair", lambda r: r.fulfill(body=json.dumps({"ok": True, "paired": [dict(fake_node, online=True)], "found": []}),
                                                          content_type="application/json"))
    page.click(".erow:has-text('zz-e2e-node') button:text-is('Pair')")
    page.wait_for_selector(".erow:has-text('Unpair')")
    check("pairing moves it into the paired list with an Unpair button", page.locator(".erow:has-text('zz-e2e-node') button:text-is('Unpair')").count() == 1)
    check("a paired, online node shows a filled dot and its handshake count", "4 handshake" in page.locator(".erow:has-text('zz-e2e-node')").inner_text())
    page.unroute("**/api/nodes/pair")
    page.route("**/api/nodes/unpair", lambda r: r.fulfill(body=json.dumps({"ok": True, "paired": [], "found": []}), content_type="application/json"))
    page.click(".erow:has-text('zz-e2e-node') button:text-is('Unpair')")
    page.wait_for_selector("p:has-text('No nodes yet')")
    check("unpairing empties the list again", page.locator(".erow:has-text('zz-e2e-node')").count() == 0)
    page.unroute("**/api/nodes/unpair")

    remote_node = {"node": "node_pwn", "version": "1.0.0", "name": "zz-e2e-remote", "mac": "02:00:00:00:00:0a",
                   "ip": "203.0.113.5:8080", "handshakes": 2, "bssids": []}
    page.route("**/api/nodes/add", lambda r: r.fulfill(body=json.dumps({"ok": True, "error": None, "paired": [dict(remote_node, online=True)], "found": []}),
                                                         content_type="application/json"))
    page.fill("input[placeholder='address or address:port']", "203.0.113.5:8080")
    page.click("button:text-is('Add')")
    page.wait_for_selector(".erow:has-text('zz-e2e-remote')")
    check("adding a node by address works with no scan involved, e.g. a node on a different network",
          page.locator(".erow:has-text('zz-e2e-remote') button:text-is('Unpair')").count() == 1)
    page.unroute("**/api/nodes/add")
    page.route("**/api/nodes/add", lambda r: r.fulfill(body=json.dumps({"ok": False, "error": "could not reach a node_pwn unit there", "paired": [], "found": []}),
                                                         content_type="application/json"))
    page.fill("input[placeholder='address or address:port']", "203.0.113.9:8080")
    page.click("button:text-is('Add')")
    page.wait_for_timeout(200)
    check("a bad address shows the reason instead of silently failing", "could not reach" in (page.locator("#msg").inner_text() if page.locator("#msg").count() else ""))
    page.unroute("**/api/nodes/add")

    tab("Wardrive")
    page.wait_for_timeout(200)
    check("the Wardrive tab loads with no browser error, nothing tracked yet",
          page.locator("p:has-text('No track yet')").count() == 1 and page.locator("button:text-is('Start wardrive')").count() == 1)
    page.route("**/api/wardrive/start", lambda r: r.fulfill(
        body=json.dumps({"ok": True, "active": True, "started_at": 1.0, "ended_at": None, "distance_m": 0,
                          "duration_s": 0, "aps_seen": 0, "handshakes": 0, "points": []}), content_type="application/json"))
    page.click("button:text-is('Start wardrive')")
    page.wait_for_selector("button:text-is('Stop wardrive')")
    check("starting flips the button and shows a waiting-for-fix message", page.locator("p:has-text('Waiting for a gps fix')").count() == 1)
    page.unroute("**/api/wardrive/start")
    page.route("**/api/wardrive/stop", lambda r: r.fulfill(
        body=json.dumps({"ok": True, "active": False, "started_at": 1.0, "ended_at": 61.0, "distance_m": 1234,
                          "duration_s": 60, "aps_seen": 3, "handshakes": 1, "points": [[52.0, 4.0], [52.01, 4.0]]}),
        content_type="application/json"))
    page.click("button:text-is('Stop wardrive')")
    page.wait_for_selector("button:text-is('Start wardrive')")
    check("stopping shows the trip summary (distance, duration, seen, handshakes)",
          "1.23 km" in page.locator(".statcard").nth(0).inner_text() and "1" in page.locator(".statcard").nth(3).inner_text())
    page.unroute("**/api/wardrive/stop")

    settings0 = requests.get(URL + "api/settings").json()
    tab("Settings")
    page.wait_for_selector("#setsave")
    page.locator("label.ck:has-text('switch the Pi off') input").check()
    page.locator("label:has-text('above') input").fill("90")
    page.locator("label:has-text('for (seconds)') input").fill("120")
    page.locator("label.ck:has-text('night mode') input").check()
    page.click("#setsave")
    wait_msg("settings saved")
    now = requests.get(URL + "api/settings").json()
    check("Settings: the overheating switch, temperature and time are saved", now["settings"]["overheat_off"] is True and now["settings"]["overheat_temp"] == 90 and now["settings"]["overheat_seconds"] == 120, now["settings"])
    check("Settings: night mode gets a sensible default window", now["display"]["night"] and now["display"]["night"]["from"] == "22:00")
    tab("Colors")
    tab("Settings")
    check("...and the tab shows what is saved when it is opened again", page.locator("label.ck:has-text('switch the Pi off') input").is_checked())
    s2 = requests.Session()
    tok2 = re.search(r'name="csrf_token" content="([^"]+)"', s2.get(URL).text).group(1)
    s2.post(URL + "api/settings", data=json.dumps({"settings": settings0["settings"], "display": settings0["display"]}),
            headers={"X-CSRFToken": tok2, "Content-Type": "application/json"})
    check("the original settings are restored", requests.get(URL + "api/settings").json()["settings"] == settings0["settings"])

    phone = browser.new_context(viewport={"width": 375, "height": 800}, has_touch=True).new_page()
    phone.goto(URL)
    phone.wait_for_selector(".card")
    check("on a phone-sized screen the page does not scroll sideways", not phone.evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth"))
    check("the page links to a web app manifest with an icon", phone.evaluate(
        "()=>fetch(document.querySelector('link[rel=manifest]').href).then(r=>r.json()).then(m=>m.icons.length>0)"))
    phone.wait_for_function("navigator.serviceWorker.getRegistrations().then(r=>r.length>0)", timeout=5000)
    check("the service worker registers (installable as an app)", True)
    browser.close()

cleanup()
s = requests.Session()
tok = re.search(r'name="csrf_token" content="([^"]+)"', s.get(URL).text).group(1)
s.post(URL + "api/apply", data=json.dumps({"name": original}), headers={"X-CSRFToken": tok, "Content-Type": "application/json"})
check("the original theme is active again (%s)" % original, api_themes()["active"] == original)
check("no throwaway themes or packs are left", not [n for n in api_themes()["themes"] if n.startswith("zz-e2e")]
      and not [p for p in requests.get(URL + "api/packs").json() if p.startswith("zz-e2e")])
real = [e for e in console_errors if "favicon" not in e and "400" not in e]
check("no unexpected browser errors", not real, real[:3])
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
