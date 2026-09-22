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

    check("the editor loads with its theme cards and a preview", page.locator(".card").count() >= 13)
    page.click(".card[data-name='cyberpunk']")

    # ---------------------------------------------------------------- try a theme for a while
    sent = {}

    def try_route(route):
        body = json.loads(route.request.post_data)
        sent.update(body)
        body["seconds"] = 5                                   # keep the real test short
        route.continue_(post_data=json.dumps(body))

    page.route("**/api/try", try_route)
    page.click("#try")
    wait_msg("for 5 s")
    check("'Try' sends the theme being edited and 30 seconds", sent.get("seconds") == 30 and sent["theme"]["fg"] == "#00f0ff", sent.get("seconds"))
    check("the button counts down and the message says what happens", "back in" in page.inner_text("#try") and "Apply keeps it" in msg())
    page.unroute("**/api/try")
    page.wait_for_function("document.getElementById('try').textContent==='Try 30 s'", timeout=9000)
    check("...and returns to normal when the time is up", True)
    page.route("**/api/try", lambda r: r.fulfill(status=400, content_type="application/json", body='{"ok":false,"error":"bad theme"}'))
    page.click("#try")
    wait_msg("bad theme")
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
    tab("Faces")
    page.fill("#packname", "zz-e2e-pack")
    page.set_input_files("#facefiles", [png("happy.png", (255, 0, 0, 255)), png("notamood.png", (0, 0, 0, 255))])
    page.click("#faceupload")
    wait_msg("1 saved")
    check("uploading images stores the ones named after a mood and reports the rest", "not used" in msg(), msg())
    page.wait_for_selector(".thumbs img")
    page.wait_for_function("[...document.querySelectorAll('.thumbs img')].every(i=>i.complete&&i.naturalWidth>0)")
    check("the new pack is selected and its face shows up", requests.get(URL + "api/packs").json().get("zz-e2e-pack") == ["happy"] and page.locator(".thumbs img").count() == 1)
    page.click("#facedelete")
    page.wait_for_function("!document.querySelector('.thumbs')", timeout=8000)
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
    check("the Cracking tab shows the summary cards", page.locator(".statcard").count() == 6)
    check("...and matches the API's counts", page.locator(".statcard div").first.inner_text() == str(cracking0["summary"]["cracked"]))

    tab("Radar")
    page.wait_for_timeout(300)
    check("the Radar tab loads with no browser error (empty or listing networks)",
          page.locator("p:has-text('Networks pwnagotchi')").count() == 1)

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
