"""Firefox browser extension discoverer (MV2 + MV3).

Finds entry points for the `browser_ext_firefox` software type. Firefox
WebExtensions share most of the manifest shape with Chrome, but with two
key differences the discoverer must handle:

- MV2 still ships: `background.scripts` (a list of JS files) is the
  MV2-only form; MV3's `background.service_worker` works on Firefox
  too. We pick whichever the manifest declares.
- The `browser.*` namespace replaces `chrome.*` in API calls. The
  discoverer scans for `browser.runtime.*.addListener(...)` instead of
  `chrome.runtime.*.addListener(...)`.

Other manifest fields recognised:
- `browser_action.default_popup` (MV2) or `action.default_popup` (MV3)
- `content_scripts[].js`
- `options_ui.page`

Each manifest-derived entry point is one EntryPoint with `metadata.surface`
distinguishing background, content script, popup, options page. Each
runtime-listener call is one IPC_HANDLER EntryPoint.

The manifest is parsed via `json.loads`. Line numbers are recovered by
searching for the relevant key in the raw text — Firefox manifests are
hand-written and the keys are unique enough that substring search is
reliable. JS handler discovery is regex-based; `_strip_js_comments` is
applied first so commented-out example calls aren't picked up as live
listeners.

Deterministic at every step.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match `browser.runtime.<API>.addListener(...)`. Pinned to the
# `browser` namespace (the WebExtensions standard one); the
# `chrome.runtime.*` polyfill alias is recognised separately when a
# Firefox manifest uses it for cross-browser compat.
_ON_MESSAGE_RE = re.compile(
    r"\b(?P<ns>browser|chrome)\s*\.\s*runtime\s*\.\s*"
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


CONTENT_PREVIEW_BYTES = 131072

_JS_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts")


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dir check against RELATIVE parts only.

    Same reasoning as every sibling discoverer — fixtures live under
    `tests/fixtures/...` and we must NOT walk the absolute path or we'd
    mis-skip via the parent `tests/` directory.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _key_line(text: str, key: str) -> int:
    """Best-effort line number of the first `"<key>":` occurrence."""
    needle = f'"{key}"'
    idx = text.find(needle)
    if idx < 0:
        return 1
    return _line_of(text, idx)


def _strip_js_comments(text: str) -> str:
    """Blank out JS comments while preserving offsets (line numbers stay correct)."""
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


def _discover_manifest(manifest_path: Path, repo_root: Path) -> list[EntryPoint]:
    """Pull declarative entry points from a Firefox manifest (MV2 or MV3)."""
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
    mv = data.get("manifest_version")

    # 1) Background entries — MV2: background.scripts (list); MV3: service_worker.
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
                    type_origin="browser_ext_firefox",
                    metadata={
                        "surface": "background_service_worker",
                        "script": sw,
                        "manifest_version": mv,
                    },
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )
        bg_scripts = bg.get("scripts")
        if isinstance(bg_scripts, list):
            # MV2 may list multiple background scripts — emit one entry
            # per file so the walker can reason about each independently.
            line = _key_line(text, "scripts")
            for idx, script in enumerate(bg_scripts):
                if not isinstance(script, str) or not script:
                    continue
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.BOOT_PATH,
                        file=rel,
                        line=line,
                        symbol=f"background.scripts[{idx}]:{script}",
                        type_origin="browser_ext_firefox",
                        metadata={
                            "surface": "background_scripts",
                            "script": script,
                            "manifest_version": mv,
                        },
                        docstring="",
                        intended_behaviour_sources=(rel,),
                    )
                )

    # 2) content_scripts[].js
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
                        type_origin="browser_ext_firefox",
                        metadata={
                            "surface": "content_script",
                            "script": jsfile,
                            "matches": list(matches_tuple),
                        },
                        docstring="",
                        intended_behaviour_sources=(rel,),
                    )
                )

    # 3) browser_action.default_popup (MV2) and action.default_popup (MV3).
    for action_key in ("browser_action", "action"):
        action = data.get(action_key)
        if not isinstance(action, dict):
            continue
        popup = action.get("default_popup")
        if isinstance(popup, str) and popup:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=_key_line(text, "default_popup"),
                    symbol=f"{action_key}.default_popup:{popup}",
                    type_origin="browser_ext_firefox",
                    metadata={
                        "surface": f"{action_key}_popup",
                        "html": popup,
                    },
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )

    # 4) options_ui.page — Firefox-style options HTML.
    options_ui = data.get("options_ui")
    if isinstance(options_ui, dict):
        page = options_ui.get("page")
        if isinstance(page, str) and page:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=_key_line(text, "options_ui"),
                    symbol=f"options_ui.page:{page}",
                    type_origin="browser_ext_firefox",
                    metadata={"surface": "options_ui", "html": page},
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )

    return found


def _discover_listeners(js_path: Path, repo_root: Path) -> list[EntryPoint]:
    """Find browser.runtime.* (and chrome.runtime.* polyfill) addListener calls."""
    text = _read(js_path)
    if not text:
        return []
    if "browser.runtime" not in text and "chrome.runtime" not in text:
        return []
    rel = str(js_path.relative_to(repo_root))
    stripped = _strip_js_comments(text)
    found: list[EntryPoint] = []
    for m in _ON_MESSAGE_RE.finditer(stripped):
        ns = m.group("ns")
        api = m.group("api")
        line = _line_of(stripped, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.IPC_HANDLER,
                file=rel,
                line=line,
                symbol=f"{ns}.runtime.{api}",
                type_origin="browser_ext_firefox",
                metadata={
                    "surface": "runtime_listener",
                    "api": f"{ns}.runtime.{api}",
                    "external": api.endswith("External"),
                    "namespace": ns,
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Firefox extension entry points. Deterministic order."""
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

    # 2) Scan every JS file for browser.runtime listeners.
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
