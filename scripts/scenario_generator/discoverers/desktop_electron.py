"""Electron desktop-app discoverer.

Finds entry points declared in Electron desktop applications for the
`desktop_electron` software type:

- `ipcMain.on(<channel>, (event, ...args) => { ... })` — emits one
  IPC_HANDLER EntryPoint per channel. `ipcMain.on` registers a
  fire-and-forget receiver; the walker reasons about scenarios at the
  channel boundary.
- `ipcMain.handle(<channel>, (event, ...args) => { ... })` — emits
  one IPC_HANDLER EntryPoint per channel. `ipcMain.handle` is the
  invoke/handle (request-response) variant. Distinguished by the
  `style: "handle"` metadata field.
- `ipcMain.once(<channel>, ...)` and `ipcMain.removeAllListeners(...)`
  variants are also recognised (rare in practice but valid surfaces).
- `BrowserWindow` constructor instantiations — emit one BOOT_PATH
  EntryPoint per construction site. A BrowserWindow is the
  renderer-process spawn point; the walker traces what UI surface
  comes up.
- `app.on('ready', ...)` and `app.whenReady().then(...)` — emit one
  BOOT_PATH EntryPoint per ready callback. Electron's lifecycle is
  rooted at the `ready` event; everything else hangs off it.

Regex-based heuristic (no Babel/TypeScript AST). Deterministic at
every step: files sorted, matches iterated in source order, output
dedup'd and sorted before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ipcMain.on / .handle / .once / .removeAllListeners — capture the
# channel name (first quoted string arg) and the method that was
# called on ipcMain. The handler function is anonymous in most
# Electron code; we don't try to extract its name.
_IPC_MAIN_RE = re.compile(
    r"\bipcMain\s*\.\s*(?P<method>on|handle|once|removeAllListeners|removeHandler|removeListener)"
    r"\s*\(\s*['\"](?P<channel>[^'\"]+)['\"]",
)

# new BrowserWindow({...}) — capture position; the symbol is "BrowserWindow"
# (a generic boot marker) plus the offset into the file as line metadata.
_BROWSER_WINDOW_RE = re.compile(
    r"\bnew\s+BrowserWindow\s*\(",
)

# app.on('ready', ...) or app.whenReady().then(...). Both root the
# application lifecycle. We emit BOOT_PATH per call site so a project
# with multiple windows behind a single ready handler is correctly
# attributed.
_APP_READY_RE = re.compile(
    r"\bapp\s*\.\s*(?:on\s*\(\s*['\"]ready['\"]|whenReady\s*\(\s*\)\s*\.\s*then\s*\()",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "node_modules",
        "dist",
        "out",
        "build",
        "release",
        ".cache",
        ".webpack",
        ".vite",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Electron main-process files rarely exceed this.


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

    Checking absolute parts would mis-skip every fixture under
    `tests/fixtures/...`.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_sources(repo_root: Path) -> list[Path]:
    """Sorted list of JS / TS source files, skip-dir filtered."""
    out: list[Path] = []
    for ext in ("*.js", "*.mjs", "*.cjs", "*.ts", "*.tsx"):
        for p in repo_root.rglob(ext):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Electron IPC handlers and window/app boot points.

    `languages` is advisory — the detector gated dispatch via the
    Electron fingerprint (`"electron":` in package.json plus
    `BrowserWindow` / `app.on('ready'` in JS/TS source).
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_sources(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) ipcMain.* — each call site is an IPC_HANDLER.
        for m in _IPC_MAIN_RE.finditer(text):
            method = m.group("method")
            channel = m.group("channel")
            line = _line_of(text, m.start())
            # The symbol is the channel name itself — that's what the
            # renderer process invokes by name, so it's the natural
            # entry-point identifier.
            found.append(
                EntryPoint(
                    kind=EntryPointKind.IPC_HANDLER,
                    file=rel,
                    line=line,
                    symbol=channel,
                    type_origin="desktop_electron",
                    metadata={
                        "element": "ipc_main",
                        "method": method,
                        "channel": channel,
                        "style": "handle" if method == "handle" else "on",
                        "framework": "electron",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) `new BrowserWindow(...)` → BOOT_PATH.
        for m in _BROWSER_WINDOW_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="BrowserWindow",
                    type_origin="desktop_electron",
                    metadata={
                        "element": "browser_window",
                        "framework": "electron",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 3) app.on('ready', ...) / app.whenReady().then(...) → BOOT_PATH.
        for m in _APP_READY_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="app.ready",
                    type_origin="desktop_electron",
                    metadata={
                        "element": "app_ready",
                        "framework": "electron",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind). Two BrowserWindow constructions
    # on the same line would be deduped (rare).
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
