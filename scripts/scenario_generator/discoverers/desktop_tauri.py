"""Tauri desktop-app discoverer.

Finds entry points declared in Tauri desktop applications for the
`desktop_tauri` software type. Tauri splits a desktop app across a
Rust backend (src-tauri/) and a JavaScript/TypeScript frontend; the
Rust backend exposes commands invoked from the frontend via the
`#[tauri::command]` attribute, which is the canonical IPC surface
the walker reasons about.

Entry-point kinds emitted:

- `#[tauri::command]` on a Rust function → IPC_HANDLER per function.
  The function name is the command channel; the symbol IS the
  function name and the metadata field `command` mirrors it for
  walker consumption.
- `tauri::Builder::default().invoke_handler(tauri::generate_handler![...])`
  references — the bracketed identifier list inside
  `generate_handler!` enumerates the commands the app exposes. We
  do NOT emit separate EntryPoints for these (they would duplicate
  the per-function entries above) but the discoverer is robust to
  the macro syntax so it doesn't accidentally trip over commas.

Regex-based heuristic (no Rust AST in the runtime). Deterministic at
every step: files sorted, matches iterated in source order, output
dedup'd and sorted before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# #[tauri::command]
# (possibly with parens for args: #[tauri::command(rename_all = "snake_case")])
# followed by a Rust function declaration. We capture the function
# name; the optional `async` keyword is tolerated.
_TAURI_COMMAND_RE = re.compile(
    r"#\[\s*tauri::command\s*(?:\([^)]*\))?\s*\]\s*"
    r"(?:pub\s+(?:\([^)]*\)\s+)?)?"
    r"(?:async\s+)?fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "node_modules",
        "target",  # Rust build dir
        "dist",
        "out",
        "build",
        ".cache",
        ".tauri",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Tauri command files rarely exceed this.


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


def _iter_rust_files(repo_root: Path) -> list[Path]:
    """Sorted list of .rs files, skip-dir filtered.

    Tauri commands always live in Rust source under `src-tauri/`. We
    don't restrict to that subtree (some projects use workspaces or
    custom layouts), but skip-dirs keep us out of build artefacts.
    """
    out: list[Path] = []
    for p in repo_root.rglob("*.rs"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find #[tauri::command] functions. Deterministic order.

    `languages` is advisory — the detector gated dispatch via the
    Tauri fingerprint (tauri.conf.json plus #[tauri::command]
    annotations in .rs sources). We run on .rs files regardless.
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_rust_files(repo_root):
        text = _read(path)
        if not text:
            continue
        # Cheap gate — must contain the macro literal somewhere before
        # we run the heavier regex. Avoids parsing non-Tauri Rust.
        if "tauri::command" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        for m in _TAURI_COMMAND_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.IPC_HANDLER,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="desktop_tauri",
                    metadata={
                        "element": "tauri_command",
                        "command": name,
                        "framework": "tauri",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol).
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(key=lambda e: e.sort_key())
    return unique
