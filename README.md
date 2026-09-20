# pwnagotchi theme manager

A theme engine for [pwnagotchi](https://pwnagotchi.org) on a **3.5" framebuffer LCD** (`waveshare35lcd`, 480x320).
Pwnagotchi draws in black and white; this plugin turns that into full-color themes, live.

## Features

- **Colors and gradients** for ink, background and the top/bottom bars
- **Effects:** glow, scanlines, vignette, film grain, pulse, rainbow, glitch, matrix rain, twinkling stars, border
- **Per-element colors:** face, name, status, stats and any plugin's on-screen items each get their own color
- **Custom text lines** with placeholders (`{name}`, `{time}`, `{cpu}`, `{temp}`...) and scrolling marquees
- **Mood-reactive themes:** colors and effects follow pwnagotchi's face (sad, angry, happy...), with smooth blending and a flash on new handshakes
- **Face packs:** replace the text face with PNG or GIF images per mood, in color or tinted by the theme
- **Web editor** with live preview: sliders, gradient picker, drag-to-place text, click a part of the preview to recolor it, import/export
- **Touch menu:** double tap the screen to switch themes, or to enable/disable pwnagotchi plugins on the fly
- Themes are small JSON files you can share

## Requirements

- pwnagotchi 2.9.x (jayofelony fork)
- Python packages pwnagotchi already ships: Pillow, numpy, Flask
- Optional, for the touch menu: a touchscreen that shows up under `/dev/input` (for example an ADS7846/XPT2046 controller)

## Install

```bash
sudo cp theme_manager.py /etc/pwnagotchi/custom-plugins/
sudo mkdir -p /etc/pwnagotchi/themes/faces
sudo cp docs/THEMES.md /etc/pwnagotchi/themes/README.md      # the guide shown in the web editor
sudo cp themes/*.json /etc/pwnagotchi/themes/                # optional example themes
sudo cp -r faces/blob faces/outline /etc/pwnagotchi/themes/faces/   # optional example face packs
```

Enable it in `/etc/pwnagotchi/config.toml`:

```toml
[main.plugins.theme_manager]
enabled = true
```

Then `sudo systemctl restart pwnagotchi`.

## Use

- **Web editor:** `http://<pi-address>:8080/plugins/theme_manager/`
- **CLI** (use pwnagotchi's Python):

```bash
P="sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py"
$P list                  # themes, * = active
$P set matrix            # switch theme (applies within seconds)
$P new mytheme           # create a template to edit
$P validate FILE.json
$P mood sad 20           # preview a mood for 20 seconds
```

**Touch menu:** double tap the screen (two quick taps in about the same place). The first time you are asked to tap four
`+` marks in the corners to calibrate. Then the **Themes** tab switches theme with one tap, and the **Plugins** tab lists every
installed plugin with an `ON`/`OFF` switch that takes effect immediately and is saved to `config.toml`. A plugin that
fails to load shows `ERR` and is set back to disabled. `close`, a tap outside the menu, or 20 seconds of nothing closes it.
It costs nothing while idle: one thread sleeps until the screen is touched.

The full guide to writing themes (every field, effect, placeholder and mood) is in [docs/THEMES.md](docs/THEMES.md).

## How it works

Pwnagotchi renders a 1-bit canvas. The plugin wraps the display's `render()` and recolors each frame, and wraps each UI
element's `draw()` to learn which pixels belong to which element. Only changed screen rows are written to the
framebuffer, static parts are cached, and animation slows down when the system is busy.

## Notes

- Enabling or disabling the plugin from pwnagotchi's plugin page works live.
- The touch menu reads raw touch events itself and needs no extra Python packages. The calibration is stored in
  `/etc/pwnagotchi/themes/touch.json`; delete it (or use the menu's `calibrate` button) to redo it.
- Pwnagotchi rewrites `config.toml` from memory when a plugin is toggled. The touch menu keeps `personality.channels` exactly as
  it is on disk; toggling from the web plugin page does not, so check that line if you rely on `channels = []`.
- The web accent color of pwnagotchi's own UI follows the active theme.

## License

GPL-3.0, see [LICENSE](LICENSE).
