#!/usr/bin/env bash
# Installs (or removes) the theme manager plugin on a pwnagotchi.
#
#   sudo ./install.sh                 install the plugin, the guide, example themes and face packs, and enable it
#   sudo ./install.sh --restart       ...and restart pwnagotchi afterwards
#   sudo ./install.sh --uninstall     remove the plugin and disable it (your themes are kept)
#   sudo ./install.sh --uninstall --purge   ...and delete /etc/pwnagotchi/themes too
#
# Options: --no-examples   skip the example themes and face packs
#          --no-config     do not touch config.toml
# PWN_DIR=/some/dir overrides /etc/pwnagotchi (useful for testing).
set -euo pipefail

PWN_DIR="${PWN_DIR:-/etc/pwnagotchi}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES=1 CONFIG=1 RESTART=0 UNINSTALL=0 PURGE=0

for arg in "$@"; do
    case "$arg" in
        --no-examples) EXAMPLES=0 ;;
        --no-config)   CONFIG=0 ;;
        --restart)     RESTART=1 ;;
        --uninstall)   UNINSTALL=1 ;;
        --purge)       PURGE=1 ;;
        -h|--help)     sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

PLUGINS="$PWN_DIR/custom-plugins"
THEMES="$PWN_DIR/themes"
CONFIG_FILE="$PWN_DIR/config.toml"

set_enabled() {   # set_enabled true|false : make sure [main.plugins.theme_manager] has enabled = <value>
    python3 - "$CONFIG_FILE" "$1" <<'PY'
import re, sys
path, value = sys.argv[1], sys.argv[2]
text = open(path).read()
block = re.search(r"^\[main\.plugins\.theme_manager\][ \t]*\n((?:(?!\[).*\n?)*)", text, re.M)
if not block:
    if value == "true":
        text = text.rstrip("\n") + "\n\n[main.plugins.theme_manager]\nenabled = true\n"
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
    if [ -f "$CONFIG_FILE" ] && [ ! -f "$CONFIG_FILE.bak-theme-manager" ]; then
        cp "$CONFIG_FILE" "$CONFIG_FILE.bak-theme-manager"
        echo "  backed up config.toml to config.toml.bak-theme-manager"
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
    echo "Removing the theme manager from $PWN_DIR"
    rm -f "$PLUGINS/theme_manager.py"
    if [ "$CONFIG" = 1 ] && [ -f "$CONFIG_FILE" ]; then
        backup_config
        set_enabled false
        echo "  disabled it in config.toml"
    fi
    if [ "$PURGE" = 1 ]; then
        rm -rf "$THEMES"
        echo "  deleted $THEMES"
    else
        echo "  your themes are kept in $THEMES (use --purge to delete them)"
    fi
    restart_service
    exit 0
fi

for f in theme_manager.py docs/THEMES.md; do
    [ -f "$SRC/$f" ] || { echo "cannot find $f next to install.sh: run it from a full copy of the repository" >&2; exit 1; }
done

echo "Installing the theme manager into $PWN_DIR"
mkdir -p "$PLUGINS" "$THEMES/faces" 2>/dev/null || { echo "cannot write to $PWN_DIR: run with sudo" >&2; exit 1; }
install -m 644 "$SRC/theme_manager.py" "$PLUGINS/theme_manager.py"
install -m 644 "$SRC/docs/THEMES.md" "$THEMES/README.md"
echo "  plugin and guide installed"

if [ "$EXAMPLES" = 1 ]; then
    for f in "$SRC"/themes/*.json; do
        [ -e "$THEMES/$(basename "$f")" ] || install -m 644 "$f" "$THEMES/"
    done
    for pack in "$SRC"/faces/*/; do
        [ -e "$THEMES/faces/$(basename "$pack")" ] || cp -r "$pack" "$THEMES/faces/"
    done
    install -m 644 "$SRC/faces/make_face_packs.py" "$THEMES/faces/make_face_packs.py"
    chmod -R a+rX "$THEMES"
    echo "  example themes and face packs added (existing files are never overwritten)"
fi

if [ "$CONFIG" = 1 ]; then
    if [ -f "$CONFIG_FILE" ]; then
        backup_config
        set_enabled true
        echo "  enabled it in config.toml"
    else
        echo "  no $CONFIG_FILE yet: add this yourself once it exists:" >&2
        printf '\n[main.plugins.theme_manager]\nenabled = true\n' >&2
    fi
fi

echo
echo "Done. Then open http://<pi-address>:8080/plugins/theme_manager/ or double tap the screen."
restart_service
