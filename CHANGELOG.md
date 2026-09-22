# Changelog

## 2.11.0

**Location memory.** The Cracking dashboard now shows where a handshake was captured, if pwnagotchi's own `gps`
plugin saved a location for it (a `.gps.json` file it already writes next to the capture; nothing new to turn on).
Tap a located handshake to see its coordinates, or open it on OpenStreetMap from the web editor. A new "Located"
count in the summary. This does not draw its own map (`webgpsmap` already does); it just ties a location to a
specific capture's status.

**Attack modes.** Aggressive (normal), Passive recon (deauth and association off immediately, no restart), and Home
defense (passive, plus a warning if a new device starts broadcasting one of your whitelisted network names, a sign
of a rogue access point). A button on the System tab, a selector in the web editor's Settings tab, and
`theme_manager.py mode`.

**Installable web editor.** A manifest and icon, so a phone can add it to the home screen and open it like an app.

**Fixed:** the on-screen toast for a status message used to get cut off at a fixed 30 characters, sometimes mid-word
(present since the handshake-quality feature); it now shortens gracefully with an ellipsis, fitted to the screen. A
local `import io` inside the web API's face-image handler shadowed the module-level one, which would have broken it.

## 2.10.0

**Sprites.** A handful of scenes now have a small animal wandering through them, the way a Flipper Zero's dolphin
turns up in its own UI: a dolphin leaping in `ocean`, a fox trotting through `forest`, a scorpion patrolling
`desert` (now animated), and a penguin waddling through `winter`. Not every scene, just these four, so it stays a
surprise rather than clutter.

## 2.9.0

**Removed the Radar.** The network-ranking tab and its API/editor tab are gone. It was harmless (display-only,
never touched what got attacked) but not worth the screen space it took from other tabs.

## 2.8.0

**Handshake quality.** Each capture in the Cracking dashboard now also gets a local quality guess, without waiting
for wpa-sec: a full handshake, a PMKID (crackable without a client), a partial capture, or empty (likely junk). It's
a best-effort look at the raw EAPOL bytes, not a full parser. Shown when you tap a row, in the web editor, and as a
new "Junk" count in the summary. `cracking list` prints it as a second column.

## 2.7.1

Fixed a JS syntax error (a double-escaped apostrophe in the Cracking tab's text) that broke the entire web editor,
not just that tab: no theme cards, no preview, nothing. Shipped in 2.6.0, only in code paths the Python test suite
can't reach; added real-browser tests for the Cracking and Radar tabs so this class of bug is caught before release.

## 2.7.0

**Touch menu:** the tab bar now scrolls (`<`/`>`) instead of cramming every tab into a fixed width; each tab keeps a
comfortable, readable size no matter how many features get added.

**Legal notice.** The first time the plugin ever runs it shows a one-time notice on the screen (authorized use only)
and logs it once; tap anywhere to dismiss it. See the Legal section in the README.

## 2.6.0

**Radar.** A new **Radar** tab in the touch menu and the web editor ranks the networks pwnagotchi currently sees:
signal, client count and encryption combine into a rough "worth attacking" score (a network already cracked, or
WPA3-only, ranks lower). Tap one for its channel, signal and client count. Display only: it reads the same
`on_wifi_update` data pwnagotchi already collects and never changes what actually gets attacked. Web API: `api/radar`.

## 2.5.0

**Cracking dashboard.** A new **Crack** tab in the touch menu and the web editor lists every captured handshake,
newest first, with a status pill: cracked (tap it for the password), uploaded, queued or rejected, read from the
`wpa-sec` plugin's own database and potfile. A summary line up top shows the totals. New placeholders `{queued}`,
`{uploaded}` and `{invalid}`. It only reads that data; nothing here changes what gets attacked or uploaded.
CLI: `cracking` (JSON summary) and `cracking list`.

## 2.4.1

- Removed the two "passwords cracked" achievements (Safe Cracker, Locksmith), so there are 19. Saved progress that still
  mentions them is cleaned up on load. The `{cracked}` text placeholder is unchanged.

## 2.4.0

**Themes with scenery.** A new `scene` effect paints a landscape behind the text: mountains with snow caps, a sunset
sea, pine forests, dunes and cacti, northern lights, a volcano with lava, snowy hills, spring meadows, a beach with palms,
autumn trees, a halloween moon, christmas pines, a ringed planet, a Star Trek console, a neon city, a vaporwave sun and
grid, a blood moon and pixel hills. 19 of the built-in themes now have one (`mountain`, `ice`, `ocean`, `forest`,
`desert`, `aurora`, `volcano`, `winter`, `spring`, `summer`, `autumn`, `halloween`, `christmas`, `space`, `startrek`,
`cyberpunk`, `vaporwave`, `blood`, `gameboy`). Snow, waves, embers, leaves, fireflies, bats, aurora curtains and warp
streaks move; a frame costs 3-6 ms (aurora 15 ms). Available in the web editor (Effects tab) and in your own themes.

**Docs:** a [display setup guide](docs/DISPLAY-SETUP.md) for 3.5" ILI9486 screens, including installing a missing
`tft35a.dtbo`.

## 2.3.0

**New themes** (14 new ones, 27 built in): `startrek` (with a `{stardate}` placeholder), the seasons `spring`, `summer`,
`autumn`, `winter`, the landscapes `mountain`, `ocean`, `forest`, `desert`, `aurora`, `volcano`, and `halloween`,
`christmas` and `space`. `blood` got a brighter accent so its bars are readable.

**Achievements.** 19 of them (handshakes, running time, days used, themes tried, night owl, swiping,
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
