loaded = {}
database = {}


class Plugin:
    """Like pwnagotchi's: every subclass is instantiated and registered when its class is created."""
    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        loaded[cls.__module__.split(".")[0]] = cls()


def toggle_plugin(name, enable=True):
    raise RuntimeError("stub: the tests replace this")


def on(event_name, *args, **kwargs):
    pass


def one(plugin_name, event_name, *args, **kwargs):
    pass
