# Changelog

## 2.3.0

**New themes** (14 new ones, 27 built in): `startrek` (with a `{stardate}` placeholder), the seasons `spring`, `summer`,
`autumn`, `winter`, the landscapes `mountain`, `ocean`, `forest`, `desert`, `aurora`, `volcano`, and `halloween`,
`christmas` and `space`. `blood` got a brighter accent so its bars are readable.

**Achievements.** 21 of them (handshakes, cracked passwords, running time, days used, themes tried, night owl, swiping,
moving things, the heat guard, face uploads, backups), a message when one unlocks, an **Awards** tab in the touch menu and
in the editor. A first run starts from what is already on the device. Off switch in Settings or `achievements off`.

**Overheating auto-off** (optional). Above a temperature you choose for a time you choose, a countdown shows on the screen
and the Pi shuts down unless you touch it. `Hot-off` button on the System tab, Settings tab, or `overheat on 85 60`.

**Move things on the screen.** A **Layout** tab in the touch menu: tap an element and a box and a small popup with
`X -` `X +` `Y -` `Y +` (1, 5 or 10 pixel steps), `reset` and `done` appear. The web editor has a Layout tab too, and
`layout show|reset` works on the command line. Moves are saved in `layout.json` and apply to every theme.

**Web editor:** new Layout, Awards and Settings tabs (overheating auto-off, achievements, brightness, night mode and idle
dimming).

**Under the hood:** the page counter in the menu now sits on the `>` button; a Flask-based API test; 500+ automated checks.

## 2.2.0

**On the screen**
- **Swipe** sideways on the bare screen to change theme; the new theme's name shows for a moment
- **Night mode and dimming:** a `dim` button on the System tab (100/60/30 %), a night window, and idle dimming where the
  first touch only wakes the screen. Settings in `display.json`, CLI: `dim`, `night`, `idle`
- **Warning banner** for low power (under-voltage) and heat (75 C and up); a theme can turn it off with `"warnings": false`

**Web editor**
- **Try 30 s:** show the theme being edited on the real screen, then go back by itself (nothing is saved)
- **Import from a link** (github.com page links are converted to the raw file)
- **Backup and restore** of all themes and face packs as one zip, with strict checks on what is restored
- **Upload face images** per mood in the browser (resized, gifs keep their animation) and delete packs
- Recovers by itself when the session is lost after pwnagotchi restarts

**Under the hood**
- A text line without a string `text` is rejected; `THEME_MANAGER_DIR` can point the plugin at another folder (for testing)
- 380+ automated checks plus a real-browser test of the editor (`tests/e2e_editor.py`)

## 2.1.0

- **System tab: `refresh`.** Flashes the panel and writes the whole screen again, to clear a garbled or stuck display
- **Thermal guard.** Animation runs at half rate above 75 C and pauses above 80 C, and resumes 3 degrees lower
- **GPS watchdog.** If bettercap keeps a GPS device that no longer exists (unplugged, or renumbered `ttyACM0` to
  `ttyACM1`) it spins a whole CPU core and heats the Pi. The plugin now notices, resets bettercap's GPS module and
  brings it back when the device returns
- Guide: use the stable `/dev/serial/by-id/...` name for a USB GPS receiver

## 2.0.0 - first public release

**Themes**
- Full-color themes for the `waveshare35lcd` display: ink, background and bar colors, gradients
- Effects: glow, scanlines, vignette, film grain, pulse, rainbow, glitch, matrix rain, twinkling stars, border
- Per-element colors: face, name, status, stats and any plugin's on-screen items, or `rainbow`
- Custom text lines with scrolling marquees and live placeholders: `{name}` `{time}` `{date}` `{cpu}` `{temp}` `{mem}`
  `{uptime}` `{ip}` `{mode}` `{gps}` `{lat}` `{lon}` `{sats}` `{handshakes}` `{cracked}` `{session}` `{power}` `{battery}`
- Mood-reactive themes: overrides per mood with smooth blending, and a flash on new handshakes
- Face packs: PNG or GIF faces per mood, in color or tinted by the theme
- Built-in themes and two example themes; two example face packs and a generator to make your own

**Web editor** at `/plugins/theme_manager/`
- Live preview, sliders for every effect, gradient picker, JSON editor, import and export
- Drag text lines on the preview; click a part of the screen to recolor it
- Element colors per mood, face pack chooser

**Touch menu**
- Double tap the screen; four-tap calibration on first use
- Themes tab, Plugins tab (switch plugins on and off, saved to `config.toml`), System tab (status, restart, reboot,
  shutdown, AUTO/MANU, each needing a second tap)

**Under the hood**
- Only changed screen rows are written; static parts cached; animation backs off under load
- Memory use stays flat under heavy web use
- Works when enabled or disabled live from pwnagotchi's plugin page
- `install.sh` (install, uninstall, safe to run twice) and a test suite that runs without a Raspberry Pi
