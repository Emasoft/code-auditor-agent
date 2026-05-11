"""mylib — example library package for the library_python discoverer fixture."""

from mylib.core import MyClass, public_api

__all__ = ["public_api", "MyClass"]


def _private() -> None:
    """Private helper — must NOT appear as a library export."""
    return None
