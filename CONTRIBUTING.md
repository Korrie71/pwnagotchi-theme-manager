# Contributing

Thanks for helping! Themes, face packs, bug reports and code are all welcome.

## Please keep your private details out

Never paste screenshots, logs or config files that show your **device name, network names (SSIDs), MAC addresses, IP
addresses, GPS coordinates or API keys**. Your pwnagotchi's real screen shows several of these, so:

- For screenshots of themes, use `python tools/make_screenshots.py`, which draws made-up data.
- In bug reports, blank out or replace anything personal in the log lines you paste.
- Commit with a neutral identity if you would rather not use your own (`git config user.name` / `user.email`).

## Share a theme

1. Make it in the web editor, or with `theme_manager.py new NAME`, and check it with `theme_manager.py validate FILE.json`.
2. Open an issue with the "Theme submission" template and attach the JSON, or send a pull request that adds it to
   [`themes/`](themes). Use only made-up text in it (no names, addresses or coordinates).
3. Themes that use a face pack need the pack folder too (240x90 images named after moods, see
   [docs/THEMES.md](docs/THEMES.md)).

## Report a bug

Open an issue with the "Bug report" template. The most useful things are what you did, what you expected, the
`theme_manager` lines from `/etc/pwnagotchi/log/pwnagotchi.log`, and your pwnagotchi version.

## Change the code

```bash
pip install numpy pillow
python tests/run_all.py
```

- The tests run without a Raspberry Pi, using the stand-in pwnagotchi in `tests/stubs`. Please add a test for what you
  change, and make sure `python tests/run_all.py` passes.
- The plugin is a single file (`theme_manager.py`) on purpose: pwnagotchi loads plugins as single files, and that keeps
  installing it to one copy.
- Things the tests cannot cover need a real device: the framebuffer output, the touch controller, and the web editor
  in a browser. Say in your pull request what you tried on real hardware.
- `python tools/make_screenshots.py` and `python tools/make_demo.py` regenerate the README images.
- Keep the shipped plugin free of debug hooks and personal data. `tests/test_repo.py` checks this.
