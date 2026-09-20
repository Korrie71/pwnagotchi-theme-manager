"""Repository hygiene: links and images exist, example data is valid, and nothing personal has slipped in."""
import glob
import json
import os
import re
import subprocess

from _util import ROOT, T, finish, ok
from PIL import Image

read = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()  # noqa: E731

# ---------------------------------------------------------------- docs
readme = read("README.md")
targets = re.findall(r'(?:\]\(|src=")((?:docs|faces|themes|tests|tools)/[^)"\s]+)', readme)
missing = [t for t in targets if not os.path.exists(os.path.join(ROOT, t))]
ok("every file the README links to or shows exists (%d)" % len(set(targets)), targets and not missing, missing)
for name in ("LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "install.sh", "docs/THEMES.md"):
    ok("%s exists" % name, os.path.isfile(os.path.join(ROOT, name)))
ok("the changelog mentions the plugin's current version", re.search(r"__version__ = \"([\d.]+)\"", read("theme_manager.py")).group(1) in read("CHANGELOG.md"))
guide = read("docs/THEMES.md")
tokens = set(re.findall(r"`\{(\w+)\}`", guide))
ok("the guide documents every placeholder the plugin knows",
   {"name", "time", "date", "cpu", "temp", "mem", "uptime", "ip", "mode", "gps", "lat", "lon", "sats", "handshakes", "cracked", "session", "power", "battery"} <= tokens)
ok("the guide documents brightness, warnings, swipe, try and backup",
   all(w in guide for w in ("display.json", "warnings", "Swipe", "Try 30 s", "Download all my themes", "Import from a link")))
effects = set(T.EFFECTS)
ok("...and every effect", all("`%s`" % e in guide for e in effects), [e for e in effects if "`%s`" % e not in guide])
ok("...and every mood", all("`%s`" % m in guide for m in T.MOODS), [m for m in T.MOODS if "`%s`" % m not in guide])

# ---------------------------------------------------------------- data
for path in sorted(glob.glob(os.path.join(ROOT, "themes", "*.json"))):
    try:
        T._clean(json.load(open(path)))
        good = True
    except Exception as e:  # noqa: BLE001
        good = False
        print("   ", path, e)
    ok("theme file %s is valid" % os.path.basename(path), good)
for pack in sorted(glob.glob(os.path.join(ROOT, "faces", "*/"))):
    files = glob.glob(pack + "*")
    bad = []
    for f in files:
        mood = os.path.splitext(os.path.basename(f))[0]
        im = Image.open(f)
        if im.size != (240, 90) or (mood not in T.MOODS and mood != "default"):
            bad.append(os.path.basename(f))
    ok("face pack %s: %d images, all 240x90 and named after a mood" % (os.path.basename(pack.rstrip("/")), len(files)), files and not bad, bad)
big = [p for p in glob.glob(os.path.join(ROOT, "docs", "images", "*")) if os.path.getsize(p) > 3_500_000]
ok("no README image is huge", not big, big)

# ---------------------------------------------------------------- nothing personal or secret
tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.split() \
    if os.path.isdir(os.path.join(ROOT, ".git")) else [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True) if os.path.isfile(p)]
text_files = [f for f in tracked if f.endswith((".py", ".md", ".json", ".sh", ".yml", ".yaml", ".txt", ".html")) and "__pycache__" not in f]
problems = []
for f in text_files:
    body = read(f)
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.-]+", body):
        if "noreply" not in m.group(0) and not m.group(0).endswith(("@example.com", "@users.noreply.github.com")):
            problems.append((f, "email", m.group(0)))
    for m in re.finditer(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", body):
        problems.append((f, "MAC address", m.group(0)))
    for m in re.finditer(r"\b192\.168\.\d+\.\d+\b|\b10\.\d+\.\d+\.\d+\b", body):
        problems.append((f, "private IP", m.group(0)))
    for m in re.finditer(r"gh[pousr]_[A-Za-z0-9]{20,}|api_key\s*=\s*\"[^\"]+\"|password\s*=\s*\"[^\"]+\"", body):
        problems.append((f, "secret", m.group(0)[:20]))
ok("no emails, MAC addresses, private IPs or tokens in %d tracked text files" % len(text_files), not problems, problems[:3])
ok("the shipped plugin has no debug or test-only hooks", "api/tap" not in read("theme_manager.py") and "tracemalloc" not in read("theme_manager.py"))
ok("the plugin's author line is neutral", '__author__ = "theme_manager contributors"' in read("theme_manager.py"))

finish()
