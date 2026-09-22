# Making your own pwnagotchi themes

The theme manager recolors the pwnagotchi screen (480x320, the 3.5" display) and can add
effects, animations and your own text. A theme is one small JSON file.

## Quick start

1. Web editor: open `http://<pi-ip>:8080/plugins/theme_manager/`, pick a theme, edit it with the tabs
   (Colors, Effects, Text, Elements, Moods, Faces, JSON), type a name, press **Save**, then **Apply to screen**.
   The preview updates live. See "The web editor" below.
2. Or by hand: `sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py new mytheme`
   creates `/etc/pwnagotchi/themes/mytheme.json`. Edit it, check it, apply it:

```
sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py validate /etc/pwnagotchi/themes/mytheme.json
sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py set mytheme
```

The file name (without `.json`) is the theme name: letters, digits, `_`, `-` and spaces, max 32.
Saved files are picked up live. If you edit the active theme's file, re-apply it (or save it from the web page).
Built-in theme names can't be saved over or deleted, but you can copy them under a new name. They are `default`, `paper`,
`matrix`, `amber`, `cyberpunk`, `vaporwave`, `blood`, `ice`, `gameboy`, `rainbow`, and the newer ones: `startrek`
(a bridge console with a stardate), `lcars` (a ship's-computer instrument panel, no viewscreen), the seasons `spring`,
`summer`, `autumn` and `winter`, the landscapes `mountain`, `ocean`, `forest`, `desert`, `aurora` and `volcano`, and
`halloween`, `christmas` and `space`.

## How it works (read this once)

Pwnagotchi draws its screen in 1 bit: every pixel is either "ink" or "paper". The theme engine
turns that into color afterwards. A theme chooses the ink and paper colors, adds backgrounds and effects,
draws extra text, and can color **individual UI elements** (face, name, status, ...) separately:
the plugin notices which pixels each element drew. Color images (face packs) are drawn on top of the result.

## Full example

```json
{
  "description": "my neon theme",
  "bg": "#0d0221",
  "fg": "#00f0ff",
  "accent": "#ff2a6d",
  "web": "#ff2a6d",
  "fps": 8,
  "gradient": {"from": "#0d0221", "to": "#2a0845", "direction": "vertical"},
  "effects": [
    {"type": "glow", "radius": 3, "strength": 0.8},
    {"type": "glitch", "interval": 5},
    "scanlines"
  ],
  "text": [
    {"text": "// {name} //", "x": 10, "y": 262, "size": 12, "bold": true, "color": "#ff2a6d"},
    {"text": "STAY LOW ::: ", "x": 10, "y": 278, "size": 11, "scroll": true, "speed": 45, "width": 290}
  ],
  "faces": {"HAPPY": "(^o^)", "SAD": "(T_T)"}
}
```

## Top-level fields

| field | required | meaning |
|---|---|---|
| `bg` | yes | paper color, `#rrggbb` |
| `fg` | yes | ink color (text, face, lines) |
| `accent` | yes | ink color for the top bar (above the line at y=14) and bottom bar (below y=300). Same as `fg` = no change |
| `web` | yes | accent color of the pwnagotchi web UI |
| `description` | no | short note, max 120 chars |
| `fps` | no | animation speed 1-10, default 5. Higher looks smoother and uses more CPU |
| `gradient` | no | replaces the flat `bg`: `{"from", "to", "direction": "vertical"\|"horizontal"}`. Keep `fg` readable against both ends |
| `effects` | no | list of effects, see below. Written as `"name"` or `{"type": "name", ...}` |
| `text` | no | list of custom text lines (max 20), see below |
| `elements` | no | color per UI element, e.g. `{"face": "#ff2a6d", "status": "rainbow"}`, see "Element colors" |
| `mood` | no | overrides that apply while pwnagotchi is in a mood, see "Moods" |
| `face_pack`, `face_scale`, `face_offset`, `face_tint` | no | picture faces, see "Face packs" |
| `faces` | no | replace face strings live, e.g. `"HAPPY": "(^o^)"`. Keys are the names in pwnagotchi's `faces.py` (LOOK_R, SLEEP, AWAKE, BORED, HAPPY, SAD, ...) |

Colors are always 6-digit hex like `#00ff41`.

## Effects

Effects are applied in a fixed order, no matter how you list them. Numbers outside the allowed range are clamped.

| type | animated | options (default) | what it does |
|---|---|---|---|
| `glow` | no | `radius` 0-12 (3), `strength` 0-1 (0.8) | soft halo around ink |
| `scanlines` | no | `strength` 0-1 (0.35) | darkens every second row, CRT look |
| `vignette` | no | `strength` 0-1 (0.6) | darkens the corners |
| `border` | no | `size` 1-64 (2), `color` | frame around the screen |
| `noise` | yes | `strength` 0-1 (0.3) | film grain |
| `pulse` | yes | `speed` 0-30 (3), `strength` 0-1 (0.5) | ink brightness breathes |
| `rainbow` | yes | `speed` 0-30 (2) | ink cycles through all hues (overrides `fg` and `accent`) |
| `glitch` | yes | `interval` 0.5-60 seconds (4) | short bursts of shifted rows and color split |
| `rain` | yes | `density` 0.01-1 (0.5), `speed` 0-30 (8), `color` | falling characters behind the UI |
| `stars` | yes | `density` 0.01-1 (0.5), `speed` 0-30 (3), `color` | twinkling stars behind the UI |
| `scene` | some | `kind` (required), `strength` 0-1 (1), `speed` 0-30 (3) | scenery painted behind everything, see below |

### Scenery

`{"type": "scene", "kind": "mountains"}` paints a landscape on the background, on top of the gradient and behind the
ink, so text and the face stay readable. The still picture is drawn once and cached; a few scenes also have a light
moving layer. `strength` fades the scenery toward the plain background, `speed` scales the movement.

| kind | what it shows | moves |
|---|---|---|
| `mountains` | sun over three ridges with snow caps and pines | light snow |
| `glacier` | icy peaks | snow |
| `ocean` | a low sun over the sea | waves, a leaping dolphin |
| `forest` | moon over layers of pines | fireflies, a trotting fox |
| `desert` | big sun, dunes and cacti | a patrolling scorpion |
| `aurora` | dark peaks under northern lights | swaying curtains |
| `volcano` | a cone with lava rivers | embers, glowing crater |
| `winter` | moon, snowy hills and pines | snowfall, a waddling penguin |
| `spring` | sun, clouds, meadow with flowers | |
| `summer` | sun over the sea, beach and palms | waves |
| `autumn` | hills with bare trees and orange leaves | falling leaves |
| `halloween` | big moon, a dead tree, gravestones | bats |
| `christmas` | pines with stars and snow | blinking lights, snow |
| `space` | nebulae and a ringed planet | |
| `startrek` | console bars along the edges and a planet | warp streaks, an occasional ship flying past |
| `lcars` | a ship's-computer instrument panel: stacked rounded blocks, no viewscreen | |
| `city` | a neon skyline | |
| `vaporwave` | striped sun over a grid | the grid glides |
| `bloodmoon` | a red moon and a dead tree | |
| `pixel` | blocky hills and clouds in handheld greens | |

A few scenes (`ocean`, `forest`, `desert`, `winter`, `startrek`, `aurora`) also have a small animal or ship passing
through, the way a Flipper Zero's dolphin turns up in its own UI — not every scene, just a handful, so it stays a
nice surprise rather than clutter. `ocean` also gets an occasional whale, much rarer than its dolphin.

Combine it with the other effects: stars over a night scene, `vignette` to darken the edges. The web editor has a
"scene" checkbox with a kind dropdown under Effects.

Animated effects redraw the screen `fps` times per second. Themes without them only redraw when pwnagotchi does.

## Custom text lines

```json
{"text": "{name} {time}", "x": 10, "y": 278, "size": 12, "bold": false,
 "color": "#ffffff", "align": "left", "scroll": false, "speed": 40, "width": 300}
```

| field | default | meaning |
|---|---|---|
| `text` | required | the text, up to 200 chars. Placeholders below |
| `x`, `y` | 0 | top-left position in pixels. The screen is 480 wide, 320 high |
| `size` | 12 | font size 6-64 (DejaVu Sans Mono) |
| `bold` | false | bold font |
| `color` | theme `fg` | `#rrggbb` |
| `align` | left | `left`, `center` or `right`: which side of `x` the text sits on |
| `scroll` | false | marquee. Scrolls inside a box `width` pixels wide starting at `x` |
| `speed` | 40 | scroll speed, pixels per second |
| `width` | 300 | scroll box width 10-480 |

Placeholders are replaced with live values (unknown ones are printed as they are):

| placeholder | value |
|---|---|
| `{name}` | pwnagotchi name |
| `{time}` `{date}` | `HH:MM:SS`, `YYYY-MM-DD` |
| `{cpu}` `{temp}` `{mem}` `{uptime}` | load %, CPU temperature, RAM used %, uptime |
| `{ip}` | IPv4 address of the connection that carries your default route (or the first interface with an address) |
| `{mode}` | `AUTO` or `MANU` |
| `{gps}` | `FIX 9sat`, `no fix`, or `n/a` when there is no GPS data |
| `{lat}` `{lon}` `{sats}` | latitude and longitude (5 decimals, `-` without a fix), number of satellites |
| `{handshakes}` | handshake files in the handshakes folder |
| `{cracked}` | cracked passwords (lines in the `*.potfile` files in that folder) |
| `{session}` | handshakes captured this session |
| `{power}` | `OK` or `LOW` (the Pi's undervoltage flag) |
| `{battery}` | battery percentage if the system reports one, else `n/a` |
| `{stardate}` | a made-up stardate from the calendar, like `26264.4` |
| `{queued}` `{uploaded}` `{invalid}` | handshakes waiting to upload, uploaded, or rejected by wpa-sec (`n/a` without the `wpa-sec` plugin) |

`{gps}`, `{lat}`, `{lon}` and `{sats}` need pwnagotchi's `gps` plugin (which turns on bettercap's GPS module). `{queued}`,
`{uploaded}` and `{invalid}` need pwnagotchi's own `wpa-sec` plugin, which uploads handshakes and downloads cracked
passwords; without it they read `n/a` and the Crack tab shows every handshake as "unknown".
Values that are slow to read (`{ip}`, `{handshakes}`, `{cracked}`, `{battery}`, `{queued}`, `{uploaded}`, `{invalid}`) are cached for a few seconds, and a value
is only read at all if a text line uses it. Lines with any live placeholder (everything except `{name}` and `{date}`) or
`scroll` make the theme redraw once a second (or at `fps` for scrolling text).
Use `{{` and `}}` for literal braces.

### Where is free space?

Pwnagotchi's own items sit here (approximately): channel/APS/uptime in the top bar (y 0-14),
the face at about (110, 100), the status message at (80, 200), and PWND/mode in the bottom bar (y 300+).
The Age plugin uses the lower right (x 319+, y 225-290). The lower left (x 10-300, y 255-296) is normally free.
Custom text is drawn over everything else, so check the preview. Your layout may differ (see `tweak_view`).

## Element colors

`elements` maps a UI element name to a color (`#rrggbb`) or `"rainbow"`. Elements you don't list use `fg`
(or `accent` in the top and bottom bars). Names of pwnagotchi's own elements:

`channel`, `aps`, `uptime`, `line1`, `line2` (the two bar lines), `face`, `friend_face`, `friend_name`,
`name`, `status`, `shakes`, `mode`.

Plugins add their own (on this Pi: `Age`, `AgeStatus`, `Points`, `Progress`, `Strength`, `SkyHigh`, `bt-status`,
`bt-detail`, `pass`). The **Elements** tab lists every name that exists right now, and you can type any other name.

In the web editor you never need to type a name: **click the part on the preview** (a dotted box appears over each
element) and its color square, "rainbow" switch and "reset" button show up right under the preview. The same colors
are available as one row per element in the Elements tab. Moving a color square assigns that color at once; "reset"
sends the element back to the theme color (it then shows "theme color").

```json
"elements": {"face": "#00f0ff", "name": "#ff2a6d", "status": "#fcee0a", "shakes": "#ff2a6d"}
```

Where two elements overlap, a pixel takes the color of the element drawn first. Custom `text` lines are
drawn over everything and have their own color.

## Moods

Pwnagotchi's face changes with its state. A theme can react: `mood` maps a mood name to overrides that apply
while the face shows that mood. Colors blend smoothly over 0.6 seconds when the mood changes.

```json
"mood": {
  "sad":       {"fg": "#5b7cff", "elements": {"face": "#5b7cff"}},
  "angry":     {"fg": "#ff3030", "effects": [{"type": "glitch", "interval": 1.5}]},
  "handshake": {"fg": "#39ff14", "effects": [{"type": "glow", "radius": 6, "strength": 1}]}
}
```

An override can contain `bg`, `fg`, `accent`, `gradient`, `elements` (merged with the theme's) and `effects`
(added to the theme's; the same effect type replaces the theme's).

Moods: `look_r`, `sleep`, `awake`, `bored`, `intense`, `cool`, `happy`, `grateful`, `excited`, `motivated`,
`demotivated`, `smart`, `lonely`, `sad`, `angry`, `friend`, `broken`, `debug`, `upload`, and `handshake`.
`handshake` is special: it is a 4 second flash when a new handshake is captured. The mood is found from the
face pwnagotchi is showing (`look_l` counts as `look_r`; `look_r_happy` and `look_l_happy` count as `happy`).
If two moods share a face string in your face config (`happy` and `grateful` do by default), the first one wins.

Try a mood without waiting for it: use **show on screen** in the Moods tab, or

```
sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py mood sad 20   # 20 seconds
sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py mood off
```

## Face packs

A face pack replaces the text face `(◕‿‿◕)` with an image per mood. Put a folder in
`/etc/pwnagotchi/themes/faces/<packname>/` with files named after moods:
`happy.png`, `sad.png`, `angry.png`, ... (same names as the moods above, without `handshake`).
A file named `default.png` is used for moods you didn't draw. If neither exists, the normal text face is shown.

- **PNG** with transparency, or **GIF** for animation (frame durations are respected). If both exist for a mood, the GIF wins.
- The face is drawn where pwnagotchi's own face is. The example packs are 240x90 pixels with the face centered.
- Themes: `"face_pack": "blob"`, `"face_scale": 1.5` (0.25-4, pixel-exact scaling), `"face_offset": [-10, 28]` (moves the
  picture, in pixels), `"face_tint": true`.
- `face_tint` turns the image into a one-color stencil that is painted with the `face` element color. Use it with white
  line-art (pack `outline`): then the moods' `elements.face` colors recolor the face. Without it, the image keeps its own colors.
- Two example packs are included: `blob` (colored, with a blinking `awake.gif`) and `outline` (white, for tinting).
  `faces/make_face_packs.py` generates them; copy and edit it to make your own, or draw your own PNGs.

## The web editor

`http://<pi-ip>:8080/plugins/theme_manager/`. The picture at the top is a live preview of your current screen with the
theme you are editing. Animated themes animate. Changes are only sent to the screen with **Apply to screen**.

The page has a manifest and icon, so on a phone you can add it to your home screen (share/menu -> "Add to Home
Screen") and open it like an app, with its own icon instead of a browser tab.

| tab | what it does |
|---|---|
| Colors | four color pickers, gradient on/off with from/to pickers and direction, animation fps |
| Effects | checkbox per effect with sliders for its settings |
| Text | edit each text line, insert placeholders, **drag the green boxes on the preview** to position lines |
| Elements | one row per screen element with a color square, "rainbow" and "reset"; **click a part of the preview to pick it** |
| Moods | pick a mood, set overrides (including per-element colors, also clickable on the preview), preview it, or show it on the real screen for 15 seconds |
| Faces | choose a face pack, scale, offset, tint, see every face in the pack |
| JSON | the whole theme as text, changes apply as you type (red border = invalid JSON) |

Buttons: **Save** stores the theme under the name in the box (built-in themes can't be overwritten: type a new name),
**Apply to screen** saves if needed and makes it the active theme, **Export** downloads the JSON,
**Import** loads a JSON file into the editor (press Save to keep it), **Delete** removes a custom theme.

**Try 30 s** shows the theme you are editing on the real screen for 30 seconds and then goes back to the saved one
(the button counts down). Nothing is saved, so a bad idea can never be left on the screen; **Apply to screen** keeps it.

Under the **JSON** tab, **Import from a link** loads a theme from a `https://` link (a github.com page link is turned into
the raw file automatically); check the preview, then Save. Under the **Faces** tab you can **upload face images**: name
each file after a mood (`happy.png`, `sad.png`, `default.png`, animated `awake.gif` ...), choose a pack name, and they are
resized to fit and stored in that pack (max 1 MB each; `Delete this pack` removes it again). At the bottom of the page,
**Download all my themes and faces** makes a backup zip and **Restore from a backup** puts one back (existing themes are
kept unless you tick "replace what is already there"; built-in names and anything that is not a theme or face are ignored).

If the editor loses its session (for example after pwnagotchi restarts) it fetches a new one by itself and carries on.

## Touch menu

Double tap the screen (two quick taps in about the same place) and a menu with all your themes appears. Tap a theme
to switch to it, `<` and `>` change page, `close` (or a tap outside the menu, or 20 seconds of nothing) closes it.
The active theme has a dot. Each row shows the theme's background, ink and bar colors.

The first time, the menu asks for a quick **touch calibration**: tap the four `+` marks in the corners. The touch
controller reports raw numbers, so this teaches the plugin where your screen is. It only needs doing once and is saved in
`/etc/pwnagotchi/themes/touch.json`. Use the `calibrate` button in the menu (or delete `touch.json`) to redo it.

The menu has seven tabs. **Themes** switches theme. **Plugins** lists every installed plugin with an `ON`/`OFF` switch: tap a
row to enable or disable that plugin right away, exactly like the switch on the web plugin page (the change is saved in
`config.toml` and lasts after a reboot). While a plugin is switching the row shows `...`; enabling one can take a few
seconds. `theme_manager` itself is never listed, so you can't switch off the menu from the menu. Pwnagotchi rewrites
`config.toml` when a plugin is toggled; the plugin keeps your `personality.channels` line exactly as it was on disk.
A plugin that cannot be loaded (for example because its file has an error) shows `ERR` and is set back to disabled.

**System** shows CPU temperature and load, RAM, IP address, GPS status, uptime, power state, battery, and your handshake
and cracked-password counts, refreshed every second. Below it are the buttons `Mode`, `restart`, `reboot` and
`shutdown`, and `refresh` at the bottom left. Each one asks for a **second tap** ("tap again", within 4 seconds) before it does anything, and any other
tap cancels it. `restart` restarts pwnagotchi in the current mode, `Mode` restarts it in the other mode (AUTO or MANU),
`reboot` and `shutdown` do what they say. They call the same pwnagotchi functions as the web UI's buttons, except that
`restart` and `Mode` leave bettercap running, so the Wi-Fi driver is not reloaded.

`Hot-off` switches the overheating auto-off on and off (see "Keeping it cool").

`refresh` needs no confirmation: it flashes the panel black and writes the whole screen again. Use it when the display
looks garbled or stuck (the plugin normally sends only the rows that changed, so a glitch on the panel can otherwise
stay until that spot changes). `dim` cycles the brightness 100% / 60% / 30% (see "Brightness and night mode").

**Awards** lists the achievements (see "Achievements"): a star and `done` for the ones you have, `n/goal` for the rest.
Tap a row to see what it asks for.

**Layout** lists everything on the screen so you can move it (see "Moving things on the screen").

**Crack** is a cracking dashboard: a summary line (cracked / queued / invalid, from the `wpa-sec` plugin if it is
installed and enabled) followed by every captured handshake, newest first, each with a colored status pill: `PWND`
(cracked, tap it to see the password), `WAIT` (uploaded, not cracked yet), `NEW` (waiting to upload), `BAD` (wpa-sec
rejected it) or `?` (wpa-sec isn't tracking it). Nothing here changes what gets attacked; it only reads the same
sqlite database and potfile the `wpa-sec` plugin already keeps. The web editor has the same information in its
Cracking tab, plus a **Map** tab: an OpenStreetMap view (loaded only when you open the tab) pinning every handshake
that has a saved location, with a plain list and per-row "open on OpenStreetMap" links if the map itself cannot load.
This does not replace `webgpsmap` (which maps every access point it sees); it only ties a location to your own
captures. `theme_manager.py cracking` prints the summary as JSON, `cracking list` prints every row.

**Radar** is a sonar-style display of nearby networks: a rotating sweep line with a fading trail, and a blip for each
network bettercap currently sees. Distance from the centre reflects signal strength (closer = stronger); each device
gets a bearing derived from its MAC address, since there is no real direction data, so it stays in the same spot
between scans instead of jumping around. Tap a blip for its name, encryption, client count, signal and whether you
already have a handshake for it (shown dimmed and ranked lower). Like the Cracking tab, this is purely a display: it
never changes what pwnagotchi decides to attack. The web editor's Radar tab shows the same sweep, redrawn live.

Each handshake also gets a **quality** guess, worked out locally from the capture itself instead of waiting for
wpa-sec: a full handshake, a PMKID (crackable without a client ever connecting), only a partial capture, or empty
(likely junk, e.g. a deauth that never got a reply). It's a best-effort look at the raw bytes, not a full parser, so
an unusual network can occasionally fool it. Tapping a row that hasn't been cracked yet mentions it; the web editor
shows it next to each row, and counts junk captures in its own stat card. `cracking list` prints it as a second column.

If pwnagotchi's own `gps` plugin is enabled, it already saves a `<handshake>.gps.json` file next to each capture that
had a fix. The dashboard reads that (nothing new to turn on): tap a located handshake to see its coordinates, the web
editor shows a **map** link straight to OpenStreetMap for it, and the summary counts how many are located. This
project doesn't draw its own map (`webgpsmap` already does that well); it just ties a location to a specific
capture's crack status.

**Swipe:** on the bare screen (no menu open), swipe sideways to change theme: left goes to the next theme, right to the
previous one, and the new theme's name shows for a moment. It needs the calibration, and only clearly sideways swipes
count, so taps, vertical swipes and slow drags are ignored.

It costs nothing while idle: one small thread sleeps until the screen is touched. Menu and calibration screens are drawn
with the active theme's colors, so custom themes get a matching menu automatically.

If nothing happens, check `journalctl`-style output in `/etc/pwnagotchi/log/pwnagotchi.log` for `theme_manager`:
`touch menu ready on /dev/input/eventN` means the touch reader is running, `double tap: opening the theme menu` means
the gesture was recognised. No touchscreen found means the menu is simply disabled.

## Moving things on the screen

Every element pwnagotchi draws (the face, the name, the status text, the counters, the lines, and the items other plugins
add) can be moved. On the device: double tap, open the **Layout** tab, tap an element and a box appears around it with a
small popup: `X -` `X +` `Y -` `Y +` move it one step, `step` cycles 1, 5 and 10 pixels, `reset` puts that element back and
`done` returns to the list. Taps outside the popup do nothing, so the element stays in view while you place it. `clear`
on the list puts everything back (it asks for a second tap). In the web editor, the **Layout** tab does the same with
buttons.

Moves are saved in `/etc/pwnagotchi/themes/layout.json`, apply to every theme, and are limited to 200 pixels. The
element is drawn at the new spot, so its colors, glow and effects go with it. Pwnagotchi's own layout is never changed.
`theme_manager.py layout show` prints what is moved and `layout reset` puts it all back.

## Achievements

A small set of achievements to unlock: handshakes captured (1, 10, 50, 100, 500), hours of running
time, different days used, themes tried, running at 3 in the morning, swiping to change theme, moving something on the
screen, the heat guard stepping in, uploading a face, and downloading a backup. A message shows on the screen when
one unlocks. The **Awards** tab of the touch menu and of the web editor show them all with their progress.

Progress is kept in `/etc/pwnagotchi/themes/achievements.json`. The first time, it starts from the handshakes already on the device (those unlock without a message). Switch it all off in the web editor
(Settings tab) or with `theme_manager.py achievements off`: nothing is counted or written then.

## Attack modes

A button on the System tab (next to `Hot-off`), and a selector at the top of the web editor's Settings tab, switch
between three modes:

- **Aggressive** is normal pwnagotchi behavior: nothing is changed.
- **Passive recon** turns deauthentication and association off immediately, no restart needed (it edits
  pwnagotchi's own running configuration; switching back to Aggressive puts it back exactly as it was, even if you
  had deauth or association off already for some other reason).
- **Home defense** does the same as Passive, and also watches for a new device broadcasting one of the network
  names in your `whitelist` (`main.whitelist` in `config.toml`) that it has not seen before, a common sign of a
  rogue or evil-twin access point. The first device seen for a whitelisted name is learned quietly; a second,
  different one triggers a warning on the screen and in the log. It needs at least one entry in your whitelist to
  have anything to watch. This is read-only otherwise: it never sends anything.

`theme_manager.py mode` prints the current mode, `mode passive` (or `aggressive`, `home`) sets it.

## Brightness and night mode

The panel has no backlight control, so the plugin dims the picture itself. Set it with the `dim` button on the System tab,
or with the command line (settings live in `/etc/pwnagotchi/themes/display.json` and are picked up within a second):

```bash
P="sudo /opt/.pwn/bin/python3 /etc/pwnagotchi/custom-plugins/theme_manager.py"
$P dim 60                 # brightness, 5-100 %
$P night 22:00 07:00 30   # 30 % between 22:00 and 07:00 (the window may cross midnight)
$P night off
$P idle 5 25              # 25 % after 5 minutes without a touch
$P idle off
```

The screen uses the dimmest of the three that apply. With idle dimming on, the first touch only wakes the screen (it is
not treated as a tap, so you cannot press a button by accident on a dark screen).

## Warnings on the screen

A red banner at the top centre says **LOW POWER** while the Pi reports under-voltage (it stays for 10 seconds after the last
reading) and **HOT nnC** from 75 C up. It is the same on every theme so it cannot be missed. A theme can switch it off
with `"warnings": false`.

## Keeping it cool

The plugin protects the Pi from overheating in two ways, with nothing to configure, and can optionally shut it down:

- **Thermal guard.** Above 75 C the animation runs at half rate, and above 80 C it pauses (the screen still redraws
  whenever pwnagotchi itself changes something). It resumes 3 degrees below where it slowed down, so it does not flap.
  A line in the log says when it slows down or resumes. The Pi 5 starts throttling on its own at 85 C.
- **GPS watchdog.** If a USB GPS receiver is unplugged, or gets a new name (`ttyACM0` becomes `ttyACM1` after a
  reboot), bettercap keeps spinning on the dead file handle and uses a whole CPU core, which heats the Pi. Every 30
  seconds the plugin looks for that situation, resets bettercap's GPS module the same way pwnagotchi's `gps` plugin
  starts it, and switches it on again when the device is back.

To make the name stable in the first place, point the `gps` plugin at the `/dev/serial/by-id/...` path instead of
`/dev/ttyACM0` (`ls /dev/serial/by-id/` shows it). It always leads to the same receiver, whatever number it gets.

- **Auto-off (optional, off by default).** If the Pi stays above a temperature for a while, it shuts itself down to protect
  the hardware. Turn it on with the `Hot-off` button on the System tab, in the Settings tab of the web editor, or with
  `theme_manager.py overheat on 85 60` (off at 85 C after 60 seconds; the temperature can be 70-95 C and the time 10-600
  seconds). It only acts when the temperature has stayed at or above the limit for the whole time you set. Then the
  screen shows **TOO HOT: OFF IN nn s (touch to cancel)**, counting down from 30 seconds. A touch cancels it (it then stays
  quiet for 10 minutes), and so does the Pi cooling down 3 degrees below the limit.

If the Pi still runs hot, the biggest help is hardware: an active cooler or a fan on the Pi 5's fan connector.
`{temp}` on a text line, or the System tab, shows the temperature.

## Tips

- Keep `fg` and `bg` far apart in brightness, otherwise the text is unreadable.
- With `gradient`, test both ends of it. Text can vanish where the gradient reaches the ink color.
- `glow` on a bright `bg` looks muddy. Use it on dark themes.
- Cost: a frame takes about 5-12 ms on the Pi 5. Only changed screen rows are sent to the display, static parts are
  cached, and animation slows itself down when the Pi is busy (load above 3.5). Themes that only have a clock or
  `glitch` redraw once per second (or only during a glitch burst). `rain`, `stars`, `noise`, `pulse`, `rainbow` and
  `scroll` text and GIF faces run at `fps` (GIFs at most 10 per second); lower `fps` if the Pi runs hot.
- The web preview shows your current screen frame with the theme applied, and animates for animated themes.
- Face pack images are cached and re-read when the pack folder changes.
- Share a theme by copying its JSON file (and its face pack folder, if it uses one). Import by putting a `.json` file into `/etc/pwnagotchi/themes/`.

## The first-run notice

The first time the plugin ever runs it shows a legal notice on the screen (authorized use only) and logs it once;
tap anywhere to dismiss it. It remembers that it was shown in `disclaimer.json`, so it never appears again after that
(delete that file to see it once more, for example after resetting the device for someone else).

## Troubleshooting

- **Theme not in the list:** run `validate` on the file. Invalid themes are skipped and the reason is written to
  `/etc/pwnagotchi/log/pwnagotchi.log` (search for `theme_manager`).
- **Screen stays plain black/white:** the `theme_manager` plugin isn't enabled. Check `[main.plugins.theme_manager]`
  has `enabled = true` in `/etc/pwnagotchi/config.toml`, then `sudo systemctl restart pwnagotchi`.
- **Animation stutters:** lower `fps`, remove `rain`, `noise` or `glow`.
- **Back to normal:** `set default`, or delete `/etc/pwnagotchi/themes/active.json` and restart.
