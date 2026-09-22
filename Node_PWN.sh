#!/usr/bin/env bash
# Installs (or removes) the node_pwn companion plugin on a pwnagotchi you want to run as a "node" -- a unit whose
# capture stats the theme_manager plugin on your main unit can find on the network and use to avoid double-attacking
# the same handshake. Meant for a second (or third...) small unit, e.g. a Pi Zero W, that already runs pwnagotchi;
# this does not install pwnagotchi itself.
#
#   sudo ./Node_PWN.sh                 install node_pwn and enable it
#   sudo ./Node_PWN.sh --restart       ...and restart pwnagotchi afterwards
#   sudo ./Node_PWN.sh --uninstall     remove node_pwn and disable it
#
# Options: --no-config     do not touch config.toml
# PWN_DIR=/some/dir overrides /etc/pwnagotchi (useful for testing).
set -euo pipefail

PWN_DIR="${PWN_DIR:-/etc/pwnagotchi}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG=1 RESTART=0 UNINSTALL=0

for arg in "$@"; do
    case "$arg" in
        --no-config)   CONFIG=0 ;;
        --restart)     RESTART=1 ;;
        --uninstall)   UNINSTALL=1 ;;
        -h|--help)     sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

PLUGINS="$PWN_DIR/custom-plugins"
CONFIG_FILE="$PWN_DIR/config.toml"

set_enabled() {   # set_enabled true|false : make sure [main.plugins.node_pwn] has enabled = <value>
    python3 - "$CONFIG_FILE" "$1" <<'PY'
import re, sys
path, value = sys.argv[1], sys.argv[2]
text = open(path).read()
block = re.search(r"^\[main\.plugins\.node_pwn\][ \t]*\n((?:(?!\[).*\n?)*)", text, re.M)
if not block:
    if value == "true":
        text = text.rstrip("\n") + "\n\n[main.plugins.node_pwn]\nenabled = true\n"
else:
    body = block.group(1)
    if re.search(r"^enabled\s*=", body, re.M):
        body = re.sub(r"^enabled\s*=.*$", "enabled = " + value, body, flags=re.M)
    else:
        body = "enabled = " + value + "\n" + body
    text = text[:block.start(1)] + body + text[block.end(1):]
open(path, "w").write(text)
PY
}

backup_config() {
    if [ -f "$CONFIG_FILE" ] && [ ! -f "$CONFIG_FILE.bak-node-pwn" ]; then
        cp "$CONFIG_FILE" "$CONFIG_FILE.bak-node-pwn"
        echo "  backed up config.toml to config.toml.bak-node-pwn"
    fi
}

restart_service() {
    if [ "$RESTART" = 1 ]; then
        if command -v systemctl >/dev/null 2>&1; then
            echo "restarting pwnagotchi ..."
            systemctl restart pwnagotchi
        else
            echo "systemctl not found: restart pwnagotchi yourself" >&2
        fi
    else
        echo "Restart pwnagotchi to load it:  sudo systemctl restart pwnagotchi"
    fi
}

if [ "$UNINSTALL" = 1 ]; then
    echo "Removing node_pwn from $PWN_DIR"
    rm -f "$PLUGINS/node_pwn.py"
    if [ "$CONFIG" = 1 ] && [ -f "$CONFIG_FILE" ]; then
        backup_config
        set_enabled false
        echo "  disabled it in config.toml"
    fi
    restart_service
    exit 0
fi

[ -f "$SRC/node_pwn.py" ] || { echo "cannot find node_pwn.py next to Node_PWN.sh: run it from a full copy of the repository" >&2; exit 1; }

echo "Installing node_pwn into $PWN_DIR"
mkdir -p "$PLUGINS" 2>/dev/null || { echo "cannot write to $PWN_DIR: run with sudo" >&2; exit 1; }
install -m 644 "$SRC/node_pwn.py" "$PLUGINS/node_pwn.py"
echo "  plugin installed"

if [ "$CONFIG" = 1 ]; then
    if [ -f "$CONFIG_FILE" ]; then
        backup_config
        set_enabled true
        echo "  enabled it in config.toml"
    else
        echo "  no $CONFIG_FILE yet: add this yourself once it exists:" >&2
        printf '\n[main.plugins.node_pwn]\nenabled = true\n' >&2
    fi
fi

echo
echo "Done. This unit is now a node: on your main unit, open the theme manager's web editor -> Nodes tab -> Scan,"
echo "and it should show up (both units need to be on the same network)."
restart_service
