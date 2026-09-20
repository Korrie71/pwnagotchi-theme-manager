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
Built-in theme names (default, paper, matrix, amber, cyberpunk, vaporwave, blood, ice, gameboy, rainbow)
can't be saved over or deleted, but you can copy them under a new name.

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

Placeholders: `{name}` (pwnagotchi name), `{time}` (HH:MM:SS), `{date}`, `{cpu}` (load %),
`{temp}` (CPU temperature), `{mem}` (RAM used %), `{uptime}`. Unknown placeholders are printed as they are.
Lines with `{time}`, `{cpu}`, `{temp}`, `{mem}`, `{uptime}` or `scroll` make the theme animated.
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

| tab | what it does |
|---|---|
| Colors | four color pickers, gradient on/off with from/to pickers and direction, animation fps |
| Effects | checkbox per effect with sliders for its settings |
| Text | edit each text line, insert placeholders, **drag the green boxes on the preview** to position lines |
| Elements | color per UI element, "rainbow" option |
| Moods | pick a mood, set overrides, preview it, or show it on the real screen for 15 seconds |
| Faces | choose a face pack, scale, offset, tint, see every face in the pack |
| JSON | the whole theme as text, changes apply as you type (red border = invalid JSON) |

Buttons: **Save** stores the theme under the name in the box (built-in themes can't be overwritten: type a new name),
**Apply to screen** saves if needed and makes it the active theme, **Export** downloads the JSON,
**Import** loads a JSON file into the editor (press Save to keep it), **Delete** removes a custom theme.

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

## Troubleshooting

- **Theme not in the list:** run `validate` on the file. Invalid themes are skipped and the reason is written to
  `/etc/pwnagotchi/log/pwnagotchi.log` (search for `theme_manager`).
- **Screen stays plain black/white:** the `theme_manager` plugin isn't enabled. Check `[main.plugins.theme_manager]`
  has `enabled = true` in `/etc/pwnagotchi/config.toml`, then `sudo systemctl restart pwnagotchi`.
- **Animation stutters:** lower `fps`, remove `rain`, `noise` or `glow`.
- **Back to normal:** `set default`, or delete `/etc/pwnagotchi/themes/active.json` and restart.
