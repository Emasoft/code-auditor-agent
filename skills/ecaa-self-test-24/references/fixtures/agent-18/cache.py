# ruff: noqa
# Intentionally contains the bugs each detector should catch.
_CACHE = {}

def store(key, value):
    _CACHE[key] = value


def get(key):
    return _CACHE.get(key)
