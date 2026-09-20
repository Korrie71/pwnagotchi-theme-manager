"""install.sh: installs, is safe to run twice, never overwrites your files, uninstalls cleanly. Uses a scratch folder."""
import filecmp
import os
import re
import shutil
import subprocess
import tempfile

from _util import ROOT, finish, ok

SCRIPT = os.path.join(ROOT, "install.sh")
CONFIG = """[main]
name = "example"

[main.plugins.grid]
enabled = true

[personality]
channels = []
"""


def run(pwn_dir, *args):
    env = dict(os.environ, PWN_DIR=pwn_dir)
    return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True)


def fresh(config=CONFIG):
    d = tempfile.mkdtemp(prefix="tm-install-")
    if config is not None:
        open(os.path.join(d, "config.toml"), "w").write(config)
    return d


def blocks(pwn_dir):
    return re.findall(r"^\[main\.plugins\.theme_manager\]\nenabled = (\w+)", open(os.path.join(pwn_dir, "config.toml")).read(), re.M)


# ---------------------------------------------------------------- a normal install
d = fresh()
r = run(d)
ok("install succeeds", r.returncode == 0, r.stderr.strip()[:200])
ok("the plugin is installed and identical to the repository copy",
   filecmp.cmp(os.path.join(ROOT, "theme_manager.py"), os.path.join(d, "custom-plugins", "theme_manager.py"), shallow=False))
ok("the guide is installed where the web editor serves it", filecmp.cmp(os.path.join(ROOT, "docs/THEMES.md"), os.path.join(d, "themes", "README.md"), shallow=False))
ok("example themes and face packs are added", os.path.isfile(os.path.join(d, "themes", "sunset.json"))
   and os.path.isfile(os.path.join(d, "themes", "faces", "blob", "happy.png")) and os.path.isfile(os.path.join(d, "themes", "faces", "make_face_packs.py")))
ok("the plugin is enabled in the config", blocks(d) == ["true"], blocks(d))
ok("the rest of the config is untouched", CONFIG in open(os.path.join(d, "config.toml")).read())
ok("the original config was backed up", open(os.path.join(d, "config.toml.bak-theme-manager")).read() == CONFIG)
ok("it says how to restart", "systemctl restart pwnagotchi" in r.stdout)

# ---------------------------------------------------------------- running it again
open(os.path.join(d, "themes", "sunset.json"), "w").write('{"mine": true}')
open(os.path.join(d, "themes", "mytheme.json"), "w").write("{}")
r = run(d)
ok("a second run succeeds and adds no second config block", r.returncode == 0 and blocks(d) == ["true"], blocks(d))
ok("your edited theme is never overwritten", open(os.path.join(d, "themes", "sunset.json")).read() == '{"mine": true}')
ok("your own themes are left alone", os.path.isfile(os.path.join(d, "themes", "mytheme.json")))
ok("the backup is only made once (it still holds the original)", open(os.path.join(d, "config.toml.bak-theme-manager")).read() == CONFIG)

# ---------------------------------------------------------------- existing config variations
d2 = fresh(CONFIG + "\n[main.plugins.theme_manager]\nenabled = false\n\n[ui]\nfps = 0\n")
run(d2)
text = open(os.path.join(d2, "config.toml")).read()
ok("a disabled entry is switched on, and later sections survive", blocks(d2) == ["true"] and "[ui]\nfps = 0" in text, text[-80:])
d3 = fresh(CONFIG + "\n[main.plugins.theme_manager]\nspeed = 3\n")
run(d3)
ok("an entry without 'enabled' gets one", "enabled = true" in open(os.path.join(d3, "config.toml")).read() and "speed = 3" in open(os.path.join(d3, "config.toml")).read())
d4 = fresh(None)
r = run(d4)
ok("with no config.toml it still installs and tells you what to add", r.returncode == 0 and "[main.plugins.theme_manager]" in r.stderr
   and os.path.isfile(os.path.join(d4, "custom-plugins", "theme_manager.py")))
d5 = fresh()
run(d5, "--no-config")
ok("--no-config leaves config.toml alone", open(os.path.join(d5, "config.toml")).read() == CONFIG and not os.path.exists(os.path.join(d5, "config.toml.bak-theme-manager")))
d6 = fresh()
run(d6, "--no-examples")
ok("--no-examples skips example themes and face packs", not os.path.exists(os.path.join(d6, "themes", "sunset.json")) and not os.path.exists(os.path.join(d6, "themes", "faces", "blob")))
ok("...but still installs the plugin and guide", os.path.isfile(os.path.join(d6, "custom-plugins", "theme_manager.py")) and os.path.isfile(os.path.join(d6, "themes", "README.md")))

# ---------------------------------------------------------------- uninstall
r = run(d, "--uninstall")
ok("uninstall succeeds and removes the plugin", r.returncode == 0 and not os.path.exists(os.path.join(d, "custom-plugins", "theme_manager.py")))
ok("...disables it in the config", blocks(d) == ["false"], blocks(d))
ok("...and keeps your themes", os.path.isfile(os.path.join(d, "themes", "mytheme.json")))
r = run(d, "--uninstall", "--purge")
ok("--purge deletes the themes folder too", not os.path.exists(os.path.join(d, "themes")))
ok("uninstalling something that is not installed is fine", run(fresh(), "--uninstall").returncode == 0)

# ---------------------------------------------------------------- misuse
ok("an unknown option is refused", run(fresh(), "--bogus").returncode == 2)
ok("--help prints usage", "install.sh" in run(fresh(), "--help").stdout)
ro = tempfile.mkdtemp()
os.chmod(ro, 0o555)
if os.geteuid() != 0:      # root can write anywhere, so this can only be checked as a normal user
    r = run(os.path.join(ro, "nested"))
    ok("an unwritable target gives a clear message", r.returncode == 1 and "sudo" in r.stderr, r.stderr.strip()[:100])
os.chmod(ro, 0o755)
lonely = tempfile.mkdtemp()
shutil.copy(SCRIPT, lonely)
r = subprocess.run(["bash", os.path.join(lonely, "install.sh")], env=dict(os.environ, PWN_DIR=fresh()), capture_output=True, text=True)
ok("running it away from the repository explains what is missing", r.returncode == 1 and "full copy" in r.stderr)

finish()
