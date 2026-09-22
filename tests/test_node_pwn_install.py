"""Node_PWN.sh: installs the node_pwn companion plugin, is safe to run twice, uninstalls cleanly. Uses a scratch folder."""
import filecmp
import os
import re
import shutil
import subprocess
import tempfile

from _util import ROOT, finish, ok

SCRIPT = os.path.join(ROOT, "Node_PWN.sh")
CONFIG = """[main]
name = "example"

[main.plugins.grid]
enabled = true
"""


def run(pwn_dir, *args):
    env = dict(os.environ, PWN_DIR=pwn_dir)
    return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True)


def fresh(config=CONFIG):
    d = tempfile.mkdtemp(prefix="node-pwn-install-")
    if config is not None:
        open(os.path.join(d, "config.toml"), "w").write(config)
    return d


def blocks(pwn_dir):
    return re.findall(r"^\[main\.plugins\.node_pwn\]\nenabled = (\w+)", open(os.path.join(pwn_dir, "config.toml")).read(), re.M)


# ---------------------------------------------------------------- a normal install
d = fresh()
r = run(d)
ok("install succeeds", r.returncode == 0, r.stderr.strip()[:200])
ok("the plugin is installed and identical to the repository copy",
   filecmp.cmp(os.path.join(ROOT, "node_pwn.py"), os.path.join(d, "custom-plugins", "node_pwn.py"), shallow=False))
ok("it is enabled in the config", blocks(d) == ["true"], blocks(d))
ok("the rest of the config is untouched", CONFIG in open(os.path.join(d, "config.toml")).read())
ok("the original config was backed up", open(os.path.join(d, "config.toml.bak-node-pwn")).read() == CONFIG)
ok("it says how to restart", "systemctl restart pwnagotchi" in r.stdout)
ok("it points you at the Nodes tab", "Nodes tab" in r.stdout)

# ---------------------------------------------------------------- running it again
r = run(d)
ok("a second run succeeds and adds no second config block", r.returncode == 0 and blocks(d) == ["true"], blocks(d))
ok("the backup is only made once (it still holds the original)", open(os.path.join(d, "config.toml.bak-node-pwn")).read() == CONFIG)

# ---------------------------------------------------------------- existing config variations
d2 = fresh(CONFIG + "\n[main.plugins.node_pwn]\nenabled = false\n\n[ui]\nfps = 0\n")
run(d2)
text = open(os.path.join(d2, "config.toml")).read()
ok("a disabled entry is switched on, and later sections survive", blocks(d2) == ["true"] and "[ui]\nfps = 0" in text, text[-80:])
d4 = fresh(None)
r = run(d4)
ok("with no config.toml it still installs and tells you what to add", r.returncode == 0 and "[main.plugins.node_pwn]" in r.stderr
   and os.path.isfile(os.path.join(d4, "custom-plugins", "node_pwn.py")))
d5 = fresh()
run(d5, "--no-config")
ok("--no-config leaves config.toml alone", open(os.path.join(d5, "config.toml")).read() == CONFIG and not os.path.exists(os.path.join(d5, "config.toml.bak-node-pwn")))

# ---------------------------------------------------------------- uninstall
r = run(d, "--uninstall")
ok("uninstall succeeds and removes the plugin", r.returncode == 0 and not os.path.exists(os.path.join(d, "custom-plugins", "node_pwn.py")))
ok("...disables it in the config", blocks(d) == ["false"], blocks(d))
ok("uninstalling something that is not installed is fine", run(fresh(), "--uninstall").returncode == 0)

# ---------------------------------------------------------------- misuse
ok("an unknown option is refused", run(fresh(), "--bogus").returncode == 2)
ok("--help prints usage", "Node_PWN.sh" in run(fresh(), "--help").stdout)
lonely = tempfile.mkdtemp()
shutil.copy(SCRIPT, lonely)
r = subprocess.run(["bash", os.path.join(lonely, "Node_PWN.sh")], env=dict(os.environ, PWN_DIR=fresh()), capture_output=True, text=True)
ok("running it away from the repository explains what is missing", r.returncode == 1 and "full copy" in r.stderr)

finish()
