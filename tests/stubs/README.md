Minimal stand-ins for the parts of pwnagotchi that `theme_manager.py` imports, so the tests run on any machine with
just `numpy` and `Pillow`. They are only used by the tests and by `tools/`. On a real pwnagotchi the real package is used.
