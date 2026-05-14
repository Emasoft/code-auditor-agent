"""Godot engine discoverer.

Finds Godot lifecycle and input callbacks across `.gd` (GDScript) files
under the project tree. C# Godot scripts (`.cs`) are also scanned when
they exist — Godot supports a mono / .NET runtime where the same
callback set is exposed under PascalCase names.

Recognised GDScript callbacks (each becomes one EntryPoint):

- `func _ready()`               → BOOT_PATH      (called once on tree entry)
- `func _enter_tree()`          → BOOT_PATH      (called when the node enters the tree)
- `func _exit_tree()`           → BOOT_PATH      (called when the node leaves the tree)
- `func _init()`                → BOOT_PATH      (object constructor)
- `func _process(delta)`        → MAIN_FUNCTION  (per-frame tick)
- `func _physics_process(delta)` → MAIN_FUNCTION (fixed-step physics tick)
- `func _input(event)`          → EVENT_LISTENER (input event hook)
- `func _unhandled_input(event)` → EVENT_LISTENER (input fallback)
- `func _unhandled_key_input(event)` → EVENT_LISTENER (keyboard fallback)
- `func _gui_input(event)`      → EVENT_LISTENER (UI input hook on Control nodes)
- `func _notification(what)`    → EVENT_LISTENER (godot internal notifications)

For the C# / .NET variant, the same callbacks exist as `_Ready()`,
`_Process(double)`, `_Input(InputEvent)`, etc. They are matched by the
PascalCase form.

Each callback is reported with its parent class hint (`extends Node`,
`extends Node2D`, etc.) when available, surfaced via metadata.

type_origin is hard-coded to `"game_godot"`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `extends <ClassName>` at the top of a GDScript file.
_EXTENDS_RE = re.compile(r"^\s*extends\s+(?P<base>[A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

# Map callback names → EntryPointKind. Snake_case for GDScript,
# PascalCase for the C# Godot variant.
_GD_CALLBACK_KIND: dict[str, EntryPointKind] = {
    "_ready": EntryPointKind.BOOT_PATH,
    "_init": EntryPointKind.BOOT_PATH,
    "_enter_tree": EntryPointKind.BOOT_PATH,
    "_exit_tree": EntryPointKind.BOOT_PATH,
    "_process": EntryPointKind.MAIN_FUNCTION,
    "_physics_process": EntryPointKind.MAIN_FUNCTION,
    "_input": EntryPointKind.EVENT_LISTENER,
    "_unhandled_input": EntryPointKind.EVENT_LISTENER,
    "_unhandled_key_input": EntryPointKind.EVENT_LISTENER,
    "_gui_input": EntryPointKind.EVENT_LISTENER,
    "_notification": EntryPointKind.EVENT_LISTENER,
}

_CS_CALLBACK_KIND: dict[str, EntryPointKind] = {
    "_Ready": EntryPointKind.BOOT_PATH,
    "_EnterTree": EntryPointKind.BOOT_PATH,
    "_ExitTree": EntryPointKind.BOOT_PATH,
    "_Process": EntryPointKind.MAIN_FUNCTION,
    "_PhysicsProcess": EntryPointKind.MAIN_FUNCTION,
    "_Input": EntryPointKind.EVENT_LISTENER,
    "_UnhandledInput": EntryPointKind.EVENT_LISTENER,
    "_UnhandledKeyInput": EntryPointKind.EVENT_LISTENER,
    "_GuiInput": EntryPointKind.EVENT_LISTENER,
    "_Notification": EntryPointKind.EVENT_LISTENER,
}

# GDScript callback: `func _ready() -> void:` or `func _process(delta):`.
_GD_CALLBACK_NAMES_RE = "|".join(re.escape(n) for n in _GD_CALLBACK_KIND)
_GD_CALLBACK_RE = re.compile(
    r"^\s*func\s+(?P<name>" + _GD_CALLBACK_NAMES_RE + r")\s*\((?P<args>[^)]*)\)",
    re.MULTILINE,
)

# C# Godot callback: `public override void _Ready() { ... }`.
_CS_CALLBACK_NAMES_RE = "|".join(re.escape(n) for n in _CS_CALLBACK_KIND)
_CS_CALLBACK_RE = re.compile(
    r"^\s*(?:public\s+|protected\s+|private\s+|internal\s+)*"
    r"(?:override\s+|virtual\s+|sealed\s+)*"
    r"void\s+(?P<name>" + _CS_CALLBACK_NAMES_RE + r")\s*\((?P<args>[^)]*)\)",
    re.MULTILINE,
)

_GD_COMMENT_RE = re.compile(r"^\s*#+\s?(?P<text>.*?)\s*$")
_CS_LINE_COMMENT_RE = re.compile(r"^\s*//+\s?(?P<text>.*?)\s*$")
_CS_BLOCK_COMMENT_RE = re.compile(r"/\*(?P<text>.*?)\*/", re.DOTALL)

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        ".vscode",
        ".godot",  # Godot 4 auto-generated cache
        ".import",  # Godot 3 auto-generated imports
        "addons",  # third-party plugins — out of scope
        "build",
        "dist",
        "out",
        "obj",
        "bin",
        "tests",
        "test",
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

CONTENT_PREVIEW_BYTES = 131072  # 128KB


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _gd_comment_before(text: str, offset: int) -> str:
    """Pull a short doc summary from `#` comments before `offset`."""
    line_start = text.rfind("\n", 0, offset) + 1
    cursor = line_start - 1
    lines: list[str] = []
    while cursor > 0:
        prev_line_start = text.rfind("\n", 0, cursor) + 1
        prev_line = text[prev_line_start:cursor]
        stripped = prev_line.strip()
        if not stripped:
            break
        if stripped.startswith("#"):
            m = _GD_COMMENT_RE.match(prev_line)
            if m:
                lines.insert(0, m.group("text").strip())
            cursor = prev_line_start - 1
            continue
        break
    for ln in lines:
        if ln:
            return ln
    return ""


def _cs_comment_before(text: str, offset: int) -> str:
    """Pull a short doc summary from C-style comments before `offset`."""
    line_start = text.rfind("\n", 0, offset) + 1
    cursor = line_start - 1
    lines: list[str] = []
    while cursor > 0:
        prev_line_start = text.rfind("\n", 0, cursor) + 1
        prev_line = text[prev_line_start:cursor]
        stripped = prev_line.strip()
        if not stripped:
            break
        if stripped.startswith("//"):
            m = _CS_LINE_COMMENT_RE.match(prev_line)
            if m:
                lines.insert(0, m.group("text").strip())
            cursor = prev_line_start - 1
            continue
        if stripped.endswith("*/"):
            block_search = text.rfind("/*", 0, cursor)
            if block_search != -1:
                block = text[block_search : cursor + 1]
                bm = _CS_BLOCK_COMMENT_RE.search(block)
                if bm:
                    body = bm.group("text").strip()
                    for ln in body.splitlines():
                        s = ln.strip().lstrip("*").strip()
                        if s:
                            lines.insert(0, s)
                            break
            break
        break
    for ln in lines:
        if ln:
            return ln
    return ""


def _extends_base(text: str) -> str:
    """Return the `extends <Name>` value from a GDScript file, "" if absent."""
    m = _EXTENDS_RE.search(text)
    return m.group("base") if m else ""


def _is_godot_cs(text: str) -> bool:
    """Heuristic: is this `.cs` file using the Godot mono runtime?"""
    return "using Godot" in text or "Godot.Node" in text or "Godot.Sprite" in text


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Godot lifecycle / input callbacks. Deterministic order.

    Runs whenever `gdscript` or `csharp` is present in `languages`.
    """
    if "gdscript" not in languages and "csharp" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # 1) GDScript files
    if "gdscript" in languages:
        gd_files: list[Path] = []
        for p in repo_root.rglob("*.gd"):
            if not p.is_file():
                continue
            try:
                rel_parts = p.relative_to(repo_root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            gd_files.append(p)
        gd_files.sort()

        for path in gd_files:
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            base = _extends_base(text)
            for m in _GD_CALLBACK_RE.finditer(text):
                name = m.group("name")
                kind = _GD_CALLBACK_KIND.get(name)
                if kind is None:
                    continue
                args = m.group("args").strip()
                line = _line_of(text, m.start())
                metadata: dict[str, str] = {
                    "callback": name,
                    "language": "gdscript",
                    "framework": "godot",
                }
                if base:
                    metadata["extends"] = base
                if args:
                    metadata["args"] = args
                found.append(
                    EntryPoint(
                        kind=kind,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="game_godot",
                        metadata=metadata,
                        docstring=_gd_comment_before(text, m.start()),
                        intended_behaviour_sources=(),
                    )
                )

    # 2) C# / .NET Godot files (only when Godot.Node / using Godot present).
    if "csharp" in languages:
        cs_files: list[Path] = []
        for p in repo_root.rglob("*.cs"):
            if not p.is_file():
                continue
            try:
                rel_parts = p.relative_to(repo_root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            cs_files.append(p)
        cs_files.sort()

        for path in cs_files:
            text = _read(path)
            if not text:
                continue
            if not _is_godot_cs(text):
                continue
            rel = str(path.relative_to(repo_root))
            for m in _CS_CALLBACK_RE.finditer(text):
                name = m.group("name")
                kind = _CS_CALLBACK_KIND.get(name)
                if kind is None:
                    continue
                args = m.group("args").strip()
                line = _line_of(text, m.start())
                metadata = {
                    "callback": name,
                    "language": "csharp",
                    "framework": "godot",
                }
                if args:
                    metadata["args"] = args
                found.append(
                    EntryPoint(
                        kind=kind,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="game_godot",
                        metadata=metadata,
                        docstring=_cs_comment_before(text, m.start()),
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by (file, line, symbol, kind).
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
