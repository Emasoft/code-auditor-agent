"""React Native mobile-app discoverer.

Finds entry points in React Native applications for the
`mobile_reactnative` software type — two surface areas are recognised:

- `Stack.Screen` / `Tab.Screen` / `Drawer.Screen` registrations from
  the `@react-navigation/*` navigators. Each `<Stack.Screen name="X"
  component={Y} />` JSX element is one UI_ROUTE EntryPoint with
  metadata `{navigator, route_name, component}`.
- `AppRegistry.registerComponent('Name', () => RootComponent)` calls
  — the React Native root binding that hooks the JS bundle to the
  native host (`MainApplication.java` on Android, `AppDelegate.m` on
  iOS). Each call is one BOOT_PATH EntryPoint.

Regex-based heuristic (no AST for TSX/JSX in stdlib). Deterministic
across runs: files sorted, matches iterated in source order, output
dedup'd and sorted.

Two notes on what is NOT recognised here:

1. `react-router-native` / `wouter-native` routes — third-party
   routers with their own DSL. They warrant separate framework-variant
   discoverers under the TYPE_ORIGIN dispatch convention.
2. Programmatic `navigation.navigate('X')` call sites — those are
   transition events, not registrations. Adding them would mean
   walking the call graph; the registration table covers the
   surface area, the walker traces from there.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match a JSX element like `<Stack.Screen name="Foo" component={Bar} />`
# or `<Tab.Screen name='Foo' component={Bar}>...</Tab.Screen>`.
# We capture the navigator namespace (Stack|Tab|Drawer|...), the route
# `name`, and the `component={...}` identifier. Attribute order is
# variable in real code, so we use two lookaheads — one for `name=`,
# one for `component=` — rather than locking them in sequence.
_SCREEN_TAG_RE = re.compile(
    r"<(?P<navigator>[A-Z][A-Za-z0-9_]*)\.Screen\b"
    r"(?P<attrs>[^>]*?)"
    r"/?>"
)
_NAME_ATTR_RE = re.compile(r'\bname\s*=\s*(?P<quote>["\'])(?P<name>[^"\']+)(?P=quote)')
_COMPONENT_ATTR_RE = re.compile(r"\bcomponent\s*=\s*\{\s*(?P<component>[A-Za-z_][A-Za-z0-9_]*)\s*\}")

# Match `AppRegistry.registerComponent('Name', () => RootComponent)`.
# The factory callback may use either `() => X` or `function() { return X }`;
# v1 covers the arrow form, which is the convention in every RN template.
_REGISTER_COMPONENT_RE = re.compile(
    r"AppRegistry\s*\.\s*registerComponent\s*\(\s*"
    r"(?P<quote>['\"])(?P<app_name>[^'\"]+)(?P=quote)\s*,\s*"
    r"\(\s*\)\s*=>\s*(?P<component>[A-Za-z_][A-Za-z0-9_]*)"
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        ".yarn",
        ".expo",
        ".expo-shared",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "out",
        "ios/Pods",
        "android/.gradle",
        "android/app/build",
        ".cache",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — RN entry files rarely exceed this


_SOURCE_EXTS: tuple[str, ...] = (".tsx", ".jsx", ".ts", ".js")


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


def _iter_source_files(repo_root: Path) -> list[Path]:
    """Sorted list of .tsx/.jsx/.ts/.js files, skip-dir filtered."""
    out: list[Path] = []
    for ext in _SOURCE_EXTS:
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find React Native screens and root-component registrations.

    `languages` is advisory — the detector gated dispatch via the RN
    fingerprint (`"react-native":` in package.json + `app.json` glob).
    Running unconditionally on the source-file glob set keeps the
    behaviour symmetric with the other mobile-* discoverers.
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_source_files(repo_root):
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter: skip files that don't even mention the
        # patterns. Saves regex work on every utility/helper file.
        if "Screen" not in text and "AppRegistry" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) <Navigator.Screen name="..." component={...} /> tags.
        for tag_match in _SCREEN_TAG_RE.finditer(text):
            navigator = tag_match.group("navigator")
            attrs = tag_match.group("attrs")
            name_m = _NAME_ATTR_RE.search(attrs)
            component_m = _COMPONENT_ATTR_RE.search(attrs)
            if name_m is None or component_m is None:
                continue
            route_name = name_m.group("name")
            component = component_m.group("component")
            line = _line_of(text, tag_match.start())
            symbol = f"{navigator}.Screen:{route_name}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="mobile_reactnative",
                    metadata={
                        "element": "navigator_screen",
                        "navigator": navigator,
                        "route_name": route_name,
                        "component": component,
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) AppRegistry.registerComponent('X', () => Y) — RN root binding.
        for reg_match in _REGISTER_COMPONENT_RE.finditer(text):
            app_name = reg_match.group("app_name")
            component = reg_match.group("component")
            line = _line_of(text, reg_match.start())
            symbol = f"AppRegistry:{app_name}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="mobile_reactnative",
                    metadata={
                        "element": "app_registry",
                        "app_name": app_name,
                        "root_component": component,
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
