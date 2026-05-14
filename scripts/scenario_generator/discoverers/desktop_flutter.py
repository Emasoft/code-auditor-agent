"""Flutter desktop-app discoverer.

Finds entry points in Flutter applications targeting the desktop
platforms (windows / linux / macos) for the `desktop_flutter`
software type. Distinct from `mobile_flutter` only by the deployment
target — the source-code surface is identical, so the discoverer
shape mirrors the mobile_flutter discoverer:

- Named-route registrations inside `MaterialApp(routes: {...})` (or
  `CupertinoApp(routes: {...})`) — each `'/path': ...` key is one
  screen, emitted as UI_ROUTE with metadata
  `{route_name, screen_class}` where `screen_class` is the Dart
  identifier on the right of the arrow.
- `Navigator.pushNamed(context, '/path')` and the related
  `pushReplacementNamed`, `popAndPushNamed`, `pushNamedAndRemoveUntil`
  call sites — each is one UI_EVENT_HANDLER EntryPoint.

The fingerprint disambiguates desktop_flutter from mobile_flutter via
the presence of platform keywords (windows, linux, macos) in
pubspec.yaml. The discoverer itself reads only .dart files; the
manifest is consulted by the detector.

Regex-based heuristic (Dart has no stdlib AST in Python).
Deterministic at every step: files sorted, matches iterated in source
order, output dedup'd and sorted before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match a `routes:` argument inside a `MaterialApp(...)` /
# `CupertinoApp(...)` constructor, capturing the dict body up to the
# matching closing brace at the same nesting depth. Regex can't count
# braces, so we approximate by capturing up to the FIRST `}` followed
# by the rest of the app constructor — works for the common shape.
_ROUTES_BLOCK_RE = re.compile(
    r"(?:MaterialApp|CupertinoApp)\s*\([^)]*?routes\s*:\s*\{(?P<body>.*?)\}",
    re.DOTALL,
)

# Within a routes-dict body, match `'/path': (context) => SomeWidget(`
# or `'/path': (BuildContext context) => SomeWidget(` etc. The screen
# class is the identifier immediately after the arrow and before the
# opening paren.
_ROUTE_ENTRY_RE = re.compile(
    r"['\"](?P<path>/[^'\"]*)['\"]\s*:\s*"
    r"\([^)]*\)\s*=>\s*(?:const\s+)?"
    r"(?P<widget>[A-Z][A-Za-z0-9_]*)",
)

# Match `Navigator.pushNamed(context, '/path')` and four common
# variants. The path is the SECOND positional argument when present.
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Dart source files rarely exceed this.


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

    Absolute parts would mis-skip every fixture under
    `tests/fixtures/...`.
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
    """Find Flutter desktop screens and navigation call sites.

    `languages` is advisory — the detector gated dispatch via the
    Flutter fingerprint (`flutter:` in pubspec.yaml + platform
    keywords). The discoverer body mirrors mobile_flutter; what
    differs between the two types is the SCENARIO surface (suspend/
    resume relevance, hardware-back-button absence, etc.) which the
    family registry expresses, not the discoverer.
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
                        type_origin="desktop_flutter",
                        metadata={
                            "element": "named_route",
                            "route": route,
                            "screen_class": widget,
                            "framework": "flutter",
                            "platform": "desktop",
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
                    type_origin="desktop_flutter",
                    metadata={
                        "element": "navigator_push",
                        "method": method,
                        "route": route,
                        "framework": "flutter",
                        "platform": "desktop",
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
