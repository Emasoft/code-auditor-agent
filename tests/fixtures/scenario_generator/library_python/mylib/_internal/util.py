"""Internal-only helpers — never exported by mylib."""

from __future__ import annotations


def secret(token: str) -> str:
    """A public-looking callable that lives in an _internal subtree.

    The library_python discoverer MUST skip the entire `_internal/`
    subtree, so this function must NOT show up as a library export.
    """
    return token[::-1]
