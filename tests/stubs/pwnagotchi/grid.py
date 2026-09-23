"""Stand-in for pwnagotchi's real grid.py: a thin client for the local pwngrid-peer mesh API. Tests replace
whichever of these they need."""


def set_advertisement_data(data):
    raise RuntimeError("stub: the tests replace this")


def get_advertisement_data():
    raise RuntimeError("stub: the tests replace this")


def peers():
    raise RuntimeError("stub: the tests replace this")
