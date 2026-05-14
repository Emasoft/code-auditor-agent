"""Flutter mobile-app discoverer.

Finds entry points in Flutter applications for the `mobile_flutter`
software type — two surface areas are recognised:

- Named-route registrations in a `MaterialApp(routes: {...})`
  (or `CupertinoApp(routes: {...})`) constructor: each `'/foo': ...`
  key is one screen, emitted as UI_ROUTE with metadata `{route_name,
  screen_class}` where `screen_class` is the Dart identifier on the
  right of the arrow (e.g. `HomeScreen()` → `HomeScreen`).
- `Navigator.pushNamed(context, '/foo')` and the related
  `Navigator.pushReplacementNamed`, `Navigator.popAndPushNamed`,
  `Navigator.pushNamedAndRemoveUntil`. Each call site is one
  UI_EVENT_HANDLER EntryPoint — the call dispatches navigation, so
  the walker can reason about which routes are reachable from where.

The discoverer reads `.dart` files only; the manifest (`pubspec.yaml`)
is consulted by the detector, not here. Regex-based heuristic
(Dart has no stdlib AST in Python), deterministic at every step.

Two notes on what is NOT recognised here:

1. `onGenerateRoute: (settings) { ... }` — dynamic route builders.
   Adding this requires walking the function body, which is out of
   scope for v1; the named-route table covers the static-declared
   surface area that most apps use.
2. `GoRouter` / `auto_route` package routes — third-party routers
   with their own DSL. They warrant separate framework-variant
   discoverers (`mobile_flutter_gorouter.py` etc.) following the
   TYPE_ORIGIN dispatch convention.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match a `routes:` argument inside a `MaterialApp(...)` /
# `CupertinoApp(...)` constructor, capturing the dict body up to the
# matching closing brace at the same nesting depth. Regex can't count
# braces, so we approximate by capturing up to the FIRST `}` followed
# by the closing `)` of the app constructor — works for the common
# shape `routes: { '/a': ..., '/b': ... }`.
_ROUTES_BLOCK_RE = re.compile(
    r"(?:MaterialApp|CupertinoApp)\s*\([^)]*?routes\s*:\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)

# Within a routes-dict body, match `'/path': (context) => SomeWidget(`
# or `'/path': (BuildContext context) => SomeWidget(` etc. The screen
# class is the identifier immediately after the arrow and before the
# opening paren. We deliberately allow ANY widget shape (not just
# `SomeWidget()`) so wrapped forms like `=> const HomeScreen()` or
# `=> SafeArea(child: HomeScreen())` capture the IDENTIFIER nearest
# to the arrow — that's the entry-point screen.
_ROUTE_ENTRY_RE = re.compile(
    r"['\"](?P<path>/[^'\"]*)['\"]\s*:\s*"
    r"\([^)]*\)\s*=>\s*(?:const\s+)?"
    r"(?P<widget>[A-Z][A-Za-z0-9_]*)",
)

# Match `Navigator.pushNamed(context, '/foo')` and the four common
# variants. The path is the SECOND positional argument when present;
# `pushNamedAndRemoveUntil` takes the path as the second arg followed
# by a predicate, so the same `'second-quoted-arg'` rule works for all
# four.
_NAV_PUSH_RE = re.compile(
    r"Navigator\s*\.\s*"
    r"(?P<method>pushNamed|pushReplacementNamed|popAndPushNamed|pushNamedAndRemoveUntil)"
    r"\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*,\s*"
    r"['\"](?P<path>/[^'\"]*)['\"]",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".dart_tool",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "out",
        ".cache",
        ".pub-cache",
        ".pub",
        "node_modules",
        "vendor",
        "__pycache__",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "examples_dev",
        "samples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Dart source files rarely exceed this


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES bytes, UTF-8 with replace."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dir check against RELATIVE parts only.

    Same reasoning as every other discoverer — checking absolute parts
    would mis-skip fixtures under `tests/fixtures/...`.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_dart_files(repo_root: Path) -> list[Path]:
    """Sorted list of .dart files, skip-dir filtered."""
    out: list[Path] = []
    for p in repo_root.rglob("*.dart"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Flutter screens and navigation call sites.

    `languages` is advisory — the detector gated dispatch via the
    Flutter fingerprint (`flutter:` in pubspec.yaml). If pubspec
    matched, we run regardless of the language list (the language
    detector maps `.dart` to "dart" which is in the list, but we
    don't gate on it to keep behaviour symmetric with the other
    mobile-* discoverers).
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_dart_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) Named-route table entries inside MaterialApp/CupertinoApp.
        for block_match in _ROUTES_BLOCK_RE.finditer(text):
            body = block_match.group("body")
            body_start = block_match.start("body")
            for entry_match in _ROUTE_ENTRY_RE.finditer(body):
                route = entry_match.group("path")
                widget = entry_match.group("widget")
                abs_offset = body_start + entry_match.start()
                line = _line_of(text, abs_offset)
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_ROUTE,
                        file=rel,
                        line=line,
                        symbol=widget,
                        type_origin="mobile_flutter",
                        metadata={
                            "element": "named_route",
                            "route": route,
                            "screen_class": widget,
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

        # 2) Navigator.push*Named() call sites.
        for m in _NAV_PUSH_RE.finditer(text):
            method = m.group("method")
            route = m.group("path")
            line = _line_of(text, m.start())
            symbol = f"{method}:{route}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_EVENT_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="mobile_flutter",
                    metadata={
                        "element": "navigator_push",
                        "method": method,
                        "route": route,
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind) + sort.
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, ep.kind.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(key=lambda e: (e.sort_key(), e.kind.value))
    return unique
