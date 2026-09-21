# Setting up the 3.5" ILI9486 screen

How to get a generic 3.5" GPIO/SPI TFT (480x320, ILI9486 controller, XPT2046/ADS7846 touch) working with pwnagotchi,
including what to do when `tft35a.dtbo` is missing. Tested on a Raspberry Pi 4 with the jayofelony pwnagotchi image; the
same steps apply to other Pis, but the framebuffer may get another number (`/dev/fb0` instead of `/dev/fb1`).

**The key point:** setting `type = "waveshare35lcd"` in pwnagotchi is *not* enough. Linux must first set up the LCD as an
ILI9486 framebuffer. The chain that works is:

```
tft35a overlay  ->  ILI9486 kernel driver  ->  /dev/fb1  ->  480x320 RGB565  ->  pwnagotchi waveshare35lcd
```

If the screen stays completely white, check that chain first (step 7) before you touch pwnagotchi, its rotation or any theme.

## 1. Check whether the overlay exists

```bash
ls -l /boot/overlays/tft35a*
```

If you see `tft35a.dtbo` (and maybe `tft35a-overlay.dtb`), go to step 3. Otherwise continue with step 2.

## 2. Install `tft35a.dtbo` if it is missing

The overlay comes from the GoodTFT [LCD-show](https://github.com/goodtft/LCD-show) repository (`usr/tft35a-overlay.dtb`).
Copy only that file. Running their full `LCD35-show` installer also rewrites boot, display and X11 settings that
pwnagotchi does not need. (It is a compiled device-tree file from a third party: only use it if you are comfortable
with that source.)

```bash
cd /tmp
git clone --depth 1 https://github.com/goodtft/LCD-show.git
sudo cp LCD-show/usr/tft35a-overlay.dtb /boot/overlays/tft35a-overlay.dtb
sudo cp LCD-show/usr/tft35a-overlay.dtb /boot/overlays/tft35a.dtbo
ls -l /boot/overlays/tft35a*
rm -rf /tmp/LCD-show
```

On newer images the overlays folder may be `/boot/firmware/overlays/` instead. Use whichever exists.

## 3. Enable SPI and load the overlay

The boot configuration is `/boot/firmware/config.txt` on newer images, `/boot/config.txt` on older ones:

```bash
sudo nano /boot/firmware/config.txt
```

Make sure these two lines are present and **not** commented out with `#`:

```
dtparam=spi=on
dtoverlay=tft35a:rotate=270
```

Save with `CTRL+O`, `ENTER`, `CTRL+X`, then `sudo reboot`.

## 4. Check that the framebuffer exists

```bash
ls -l /dev/fb*
cat /proc/fb
```

You want a new framebuffer (here `/dev/fb1`) and a line like `1 fb_ili9486`. If neither appears, the kernel side is not
working yet: fix that before anything else.

Check the size and color depth:

```bash
for f in /sys/class/graphics/fb*; do
    echo "---- $f ----"
    cat "$f/name" "$f/virtual_size" "$f/bits_per_pixel" 2>/dev/null
done
```

The TFT should show `fb_ili9486`, `480,320` and `16` (16-bit RGB565).

More checks, if something is off:

```bash
sudo dmesg | grep -Ei "ili9486|fb_ili|spi|fbtft|tft"        # the driver loading
sudo dtoverlay -l                                            # the overlay is loaded
sudo cat /proc/device-tree/soc/spi@7e204000/tft35a@0/compatible | xxd    # should say ilitek,ili9486
```

The LCD sits on `spi0.0`, the touch controller on `spi0.1`.

## 5. Check the touchscreen

```bash
cat /proc/bus/input/devices     # look for "ADS7846 Touchscreen"
ls -l /dev/input/
```

The XPT2046 chip is handled by Linux's ADS7846 driver and shows up as an event device, for example `/dev/input/event0`.
The theme manager's touch menu finds it by itself (see the main README for calibration).

## 6. Configure pwnagotchi

```bash
sudo nano /etc/pwnagotchi/config.toml
```

```toml
[ui.display]
enabled = true
rotation = 180
type = "waveshare35lcd"
```

Then `sudo systemctl restart pwnagotchi` (or reboot) and check `systemctl status pwnagotchi` says `active (running)`.

### Two different rotations

Do not mix them up:

| setting | where | value that worked |
|---|---|---|
| panel rotation | `dtoverlay=tft35a:rotate=270` in `config.txt` | 270 |
| pwnagotchi UI rotation | `rotation` in `config.toml` | 180 |

If the picture is upside down or sideways, change one of them and reboot; 90 was tried during testing and 180 was the final
working value for the UI.

## 7. If the screen stays white

1. `cat /proc/fb`: is `fb_ili9486` there? If not, go back to steps 2 and 3 (overlay file, `dtparam=spi=on`, the
   `dtoverlay` line, and that both are in the file your image really uses).
2. `ls /dev/fb*`: does the TFT's framebuffer exist?
3. `sudo dmesg | grep -Ei "ili9486|fbtft"`: any errors from the driver?
4. Only when all three are fine, look at pwnagotchi's `rotation` and `type`.

## 8. Then install the theme manager

With the screen working, follow the [installation steps](../README.md#install) to get themes, the touch menu and the rest.
