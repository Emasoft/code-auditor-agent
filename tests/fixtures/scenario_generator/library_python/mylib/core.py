"""Core module — exposes the public surface of mylib.

This module has no `__all__`, so every public top-level callable in it
qualifies as a library export.
"""

from __future__ import annotations


def public_api(value: str) -> str:
    """Transform `value` into the library's canonical form.

    Exposed at the package level via mylib/__init__.py.
    """
    return value.strip()


class MyClass:
    """A simple value object exposed by mylib.

    Instances carry a name and a numeric weight.
    """

    def __init__(self, name: str, weight: int = 0) -> None:
        self.name = name
        self.weight = weight

    def describe(self) -> str:
        """Return a short human-readable description.

        Note: this is an INSTANCE method, not a top-level def — it must
        be skipped by the discoverer.
        """
        return f"{self.name} ({self.weight})"


def _private_helper(text: str) -> str:
    """Underscore-prefixed helper — must NOT appear as a library export."""
    return text.lower()


def another_public(items: list[str]) -> list[str]:
    """A public callable that is NOT listed in mylib.__init__.__all__.

    Per rule 3, the discoverer must still emit it from core.py because
    core.py itself has no __all__; the __all__ filter only applies to
    the module that defines it (the package's __init__.py).
    """
    return [s.strip() for s in items if s]
