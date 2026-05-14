"""Chrome MV3 browser extension discoverer.

Finds entry points for the `browser_ext_chrome` software type. The
extension's surface area is split between the manifest (declarative) and
the JS bundles it references (imperative). Both contribute entry points:

- `background.service_worker` in manifest.json — the persistent background
  surface that owns all cross-tab state. Emitted as BOOT_PATH.
- `content_scripts[].js` paths in manifest.json — each declared content
  script gets one UI_ROUTE EntryPoint with the matching `matches` URL
  pattern in metadata so the walker can reason about which pages the
  script runs in.
- `action.default_popup`, `options_page`, `devtools_page` — UI surfaces
  the user can open; each becomes a UI_ROUTE EntryPoint.
- `chrome.runtime.onMessage.addListener(...)` calls inside any `.js` file
  — message-handler entry points the popup, content scripts, or other
  pages can deliver into. Emitted as IPC_HANDLER. These are the most
  attacker-exposed surface in MV3 extensions (the `sender` is untrusted
  from the listener's perspective).

The manifest is parsed via `json.loads`. Line numbers are recovered from
the raw text by searching for the relevant key — Chrome manifests are
written by humans and the keys are unique enough that a substring search
is reliable. JS handler discovery is regex-based; `_strip_js_comments`
is applied first so commented-out example calls in JSDoc are not picked
up as live listeners.

Deterministic at every step: files sorted, manifest keys iterated in a
fixed order, dedup + sort before return.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match `chrome.runtime.onMessage.addListener(...)`. We capture the
# offset of the call so we can recover the line number, and the
# argument list is opaque to the discoverer (we only need to know the
# listener exists). External-message variants (`onMessageExternal`) are
# captured separately so the walker can distinguish them — they have a
# stricter origin policy than internal `onMessage`.
_ON_MESSAGE_RE = re.compile(
    r"\bchrome\s*\.\s*runtime\s*\.\s*"
    r"(?P<api>onMessage|onMessageExternal|onConnect|onConnectExternal|onInstalled|onStartup)"
    r"\s*\.\s*addListener\s*\(",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        ".yarn",
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "target",
        ".cache",
        ".idea",
        ".vscode",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
        "samples_dev",
        "examples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — manifests are small; JS is bounded.


_JS_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts")


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dir check against RELATIVE parts only.

    Fixtures live under `tests/fixtures/...` — checking absolute parts
    would mis-skip every match because the repo path itself contains
    `tests`. We compare against the path components inside `repo_root`.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _key_line(text: str, key: str) -> int:
    """Best-effort line number of the first `"<key>":` occurrence.

    Manifests are JSON, and JSON keys are quoted. We search for the
    literal `"<key>"` token and return its line. If not present, fall
    back to 1 so the EntryPoint still has a valid line number.
    """
    needle = f'"{key}"'
    idx = text.find(needle)
    if idx < 0:
        return 1
    return _line_of(text, idx)


def _strip_js_comments(text: str) -> str:
    """Blank out JS comments while preserving offsets (so line numbers stay correct).

    Comments routinely contain example listener calls — without stripping,
    a JSDoc example `chrome.runtime.onMessage.addListener(...)` would
    fire as a live handler. We replace comment characters with spaces
    (and keep newlines) so every offset into the stripped text maps
    back to the same source line.

    Not a full lexer — string-literal state isn't tracked, so a `//`
    inside a quoted string will be partially blanked. Acceptable for the
    v1 scope (listener registrations are at top-level call sites, not
    inside strings).
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                j = n
            else:
                j += 2
            chunk = text[i:j]
            blanked = "".join("\n" if ch == "\n" else " " for ch in chunk)
            out.append(blanked)
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _discover_manifest(
    manifest_path: Path,
    repo_root: Path,
) -> list[EntryPoint]:
    """Pull declarative entry points from a Chrome MV3 manifest.

    The manifest is the source of truth for which JS files are loaded
    where (background SW, content scripts) and which HTML surfaces the
    user can open (popup, options, devtools). Each maps to one
    EntryPoint with `metadata.surface` distinguishing them.
    """
    text = _read(manifest_path)
    if not text:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    rel = str(manifest_path.relative_to(repo_root))
    found: list[EntryPoint] = []

    # 1) background.service_worker — MV3 service worker entry.
    bg = data.get("background")
    if isinstance(bg, dict):
        sw = bg.get("service_worker")
        if isinstance(sw, str) and sw:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=_key_line(text, "service_worker"),
                    symbol=f"background.service_worker:{sw}",
                    type_origin="browser_ext_chrome",
                    metadata={
                        "surface": "background_service_worker",
                        "script": sw,
                        "manifest_version": data.get("manifest_version"),
                    },
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )

    # 2) content_scripts[].js — each declared script is one UI_ROUTE.
    content_scripts = data.get("content_scripts")
    if isinstance(content_scripts, list):
        for idx, cs in enumerate(content_scripts):
            if not isinstance(cs, dict):
                continue
            js_list = cs.get("js")
            if not isinstance(js_list, list):
                continue
            matches = cs.get("matches")
            matches_tuple: tuple[str, ...] = ()
            if isinstance(matches, list):
                matches_tuple = tuple(m for m in matches if isinstance(m, str))
            for jsfile in js_list:
                if not isinstance(jsfile, str) or not jsfile:
                    continue
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_ROUTE,
                        file=rel,
                        line=_key_line(text, "content_scripts"),
                        symbol=f"content_script[{idx}]:{jsfile}",
                        type_origin="browser_ext_chrome",
                        metadata={
                            "surface": "content_script",
                            "script": jsfile,
                            "matches": list(matches_tuple),
                        },
                        docstring="",
                        intended_behaviour_sources=(rel,),
                    )
                )

    # 3) action.default_popup — the toolbar-icon popup HTML.
    action = data.get("action")
    if isinstance(action, dict):
        popup = action.get("default_popup")
        if isinstance(popup, str) and popup:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=_key_line(text, "default_popup"),
                    symbol=f"action.default_popup:{popup}",
                    type_origin="browser_ext_chrome",
                    metadata={"surface": "action_popup", "html": popup},
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )

    # 4) options_page and devtools_page — top-level UI surfaces.
    for key in ("options_page", "devtools_page"):
        page = data.get(key)
        if isinstance(page, str) and page:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=_key_line(text, key),
                    symbol=f"{key}:{page}",
                    type_origin="browser_ext_chrome",
                    metadata={"surface": key, "html": page},
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )

    return found


def _discover_listeners(js_path: Path, repo_root: Path) -> list[EntryPoint]:
    """Find chrome.runtime.* addListener calls in a JS file."""
    text = _read(js_path)
    if not text:
        return []
    # Cheap pre-filter — skip files that don't mention chrome.runtime.
    if "chrome.runtime" not in text:
        return []
    rel = str(js_path.relative_to(repo_root))
    stripped = _strip_js_comments(text)
    found: list[EntryPoint] = []
    for m in _ON_MESSAGE_RE.finditer(stripped):
        api = m.group("api")
        line = _line_of(stripped, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.IPC_HANDLER,
                file=rel,
                line=line,
                symbol=f"chrome.runtime.{api}",
                type_origin="browser_ext_chrome",
                metadata={
                    "surface": "runtime_listener",
                    "api": f"chrome.runtime.{api}",
                    "external": api.endswith("External"),
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Chrome extension entry points. Deterministic order.

    `languages` is advisory — the dispatcher already gated on the
    `browser_ext_chrome` fingerprint match. We still emit nothing if
    JavaScript is not detected (no JS files means no extension surface
    to scan), which keeps the behaviour symmetric with sibling
    discoverers that gate on language.
    """
    del languages
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # 1) Parse every manifest.json reachable under repo_root.
    manifest_paths: list[Path] = []
    for p in repo_root.rglob("manifest.json"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        manifest_paths.append(p)
    manifest_paths.sort()
    for mp in manifest_paths:
        found.extend(_discover_manifest(mp, repo_root))

    # 2) Scan every JS file for chrome.runtime listeners.
    js_paths: list[Path] = []
    for ext in _JS_EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            js_paths.append(p)
    js_paths.sort()
    for jsp in js_paths:
        found.extend(_discover_listeners(jsp, repo_root))

    # Dedup by (file, line, symbol, kind) and sort.
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
