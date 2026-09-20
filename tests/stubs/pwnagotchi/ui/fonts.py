import os
from PIL import ImageFont

_DIRS = ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/", "/Library/Fonts/")
Bold = BoldSmall = BoldBig = Medium = Small = Huge = None


def _font(name, size):
    for d in _DIRS:
        p = os.path.join(d, name + ".ttf")
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def setup(bold, bold_small, medium, huge, bold_big, small):
    global Bold, BoldSmall, Medium, Huge, BoldBig, Small
    Small, Medium = _font("DejaVuSansMono", small), _font("DejaVuSansMono", medium)
    BoldSmall, Bold = _font("DejaVuSansMono-Bold", bold_small), _font("DejaVuSansMono-Bold", bold)
    BoldBig, Huge = _font("DejaVuSansMono-Bold", bold_big), _font("DejaVuSansMono-Bold", huge)
