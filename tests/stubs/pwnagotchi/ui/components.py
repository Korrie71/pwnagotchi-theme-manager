"""Same drawing behaviour as pwnagotchi's widgets (text, labeled value, line)."""
from textwrap import TextWrapper


class Widget:
    def __init__(self, xy, color=0):
        self.xy = xy
        self.color = color


class Line(Widget):
    def __init__(self, xy, color=0, width=1):
        super().__init__(xy, color)
        self.width = width

    def draw(self, canvas, drawer):
        drawer.line(self.xy, fill=self.color, width=self.width)


class Text(Widget):
    def __init__(self, value="", position=(0, 0), font=None, color=0, wrap=False, max_length=0, png=False):
        super().__init__(position, color)
        self.value, self.font, self.wrap, self.png = value, font, wrap, png
        self.wrapper = TextWrapper(width=max_length, replace_whitespace=False) if wrap else None

    def draw(self, canvas, drawer):
        if self.value is not None:
            text = "\n".join(self.wrapper.wrap(str(self.value))) if self.wrap else str(self.value)
            drawer.text(self.xy, text, font=self.font, fill=self.color)


class LabeledValue(Widget):
    def __init__(self, label, value="", position=(0, 0), label_font=None, text_font=None, color=0, label_spacing=5):
        super().__init__(position, color)
        self.label, self.value = label, value
        self.label_font, self.text_font, self.label_spacing = label_font, text_font, label_spacing

    def draw(self, canvas, drawer):
        pos = self.xy
        drawer.text(pos, self.label, font=self.label_font, fill=self.color)
        drawer.text((pos[0] + self.label_spacing + 5 * len(self.label), pos[1]), str(self.value),
                    font=self.text_font, fill=self.color)
