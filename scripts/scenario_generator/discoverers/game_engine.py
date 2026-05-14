"""Custom C++ game engine discoverer.

Finds entry points for a hand-rolled C++ game engine — i.e. a project
that does NOT use Unity, Unreal, or Godot but does carry the standard
`class Renderer` / `SceneGraph` / `ShaderCompiler` building blocks the
fingerprint registers under `game_engine`.

Recognised shapes (each becomes one EntryPoint):

- `int main(...)` in a `.cpp` file                 → MAIN_FUNCTION
- `<Class>::update(float ...)` definitions         → MAIN_FUNCTION
  (per-frame tick on the engine / scene root)
- `<Class>::render()` definitions                   → MAIN_FUNCTION
  (frame submission to the renderer)
- `<Class>::onKey*(...)` / `<Class>::onMouse*(...)` → EVENT_LISTENER
  (input callbacks)
- `<Class>::on*Event(...)` / `<Class>::handle*(...)` → EVENT_LISTENER

The discoverer is regex-based; the walker reads only the universal
EntryPoint schema fields, with engine-specific context in `metadata`.

type_origin is hard-coded to `"game_engine"`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `int main(...)` at the top level of a .cpp file. `argc`/`argv`
# parameter list is tolerated; void/no-arg `main()` is also matched.
_MAIN_RE = re.compile(
    r"^\s*(?:int|void)\s+main\s*\((?P<args>[^)]*)\)\s*\{?",
    re.MULTILINE,
)

# `<Class>::update(float ...)` or `<Class>::Update(...)` definitions —
# the per-frame tick. We accept both lowercase and PascalCase variants.
_UPDATE_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_:<>\*\&\s]*\s+)?"
    r"(?P<cls>[A-Za-z_][A-Za-z0-9_]*)::(?P<name>[Uu]pdate|[Tt]ick|[Ss]tep)\s*"
    r"\((?P<params>[^)]*)\)\s*\{",
    re.MULTILINE,
)

# `<Class>::render()` definitions — frame submission.
_RENDER_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_:<>\*\&\s]*\s+)?"
    r"(?P<cls>[A-Za-z_][A-Za-z0-9_]*)::(?P<name>[Rr]ender|[Dd]raw|[Pp]resent)\s*"
    r"\((?P<params>[^)]*)\)\s*\{",
    re.MULTILINE,
)

# Input callbacks: `<Class>::onKeyDown(...)`, `::onMouseDown(...)`,
# `::onPointerMove(...)`, `::handleInput(...)`, `::on*Event(...)`.
_INPUT_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_:<>\*\&\s]*\s+)?"
    r"(?P<cls>[A-Za-z_][A-Za-z0-9_]*)::"
    r"(?P<name>(?:on|handle|process)[A-Z][A-Za-z0-9_]*)\s*"
    r"\((?P<params>[^)]*)\)\s*\{",
    re.MULTILINE,
)

_LINE_COMMENT_RE = re.compile(r"^\s*//+\s?(?P<text>.*?)\s*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*(?P<text>.*?)\*/", re.DOTALL)

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
        "build",
        "dist",
        "out",
        "obj",
        "bin",
        "third_party",
        "thirdparty",
        "external",
        "extern",
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

# Engine markers we use to gate scanning — if a .cpp / .h file does not
# mention any of these (or include one of the engine's own headers),
# we skip it. This prevents an unrelated CLI tool living next to the
# engine source from being scraped for spurious entry points.
_ENGINE_MARKERS: tuple[str, ...] = (
    "class Renderer",
    "SceneGraph",
    "ShaderCompiler",
    "class Engine",
    "GameEngine",
)

CONTENT_PREVIEW_BYTES = 262144  # 256KB — engine source files trend larger.


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES bytes, UTF-8 with replace."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _comment_before(text: str, offset: int) -> str:
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
            m = _LINE_COMMENT_RE.match(prev_line)
            if m:
                lines.insert(0, m.group("text").strip())
            cursor = prev_line_start - 1
            continue
        if stripped.endswith("*/"):
            block_search = text.rfind("/*", 0, cursor)
            if block_search != -1:
                block = text[block_search : cursor + 1]
                bm = _BLOCK_COMMENT_RE.search(block)
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


def _project_uses_engine_markers(repo_root: Path, source_files: list[Path]) -> bool:
    """Return True when any source file contains one of the engine markers.

    The discoverer is type-blind: it'll happily scan an unrelated C++
    project if asked, but the dispatcher only calls us when the
    `game_engine` fingerprint matched — so this is a belt-and-braces
    check for safety, not a substitute for the fingerprint gate.
    """
    del repo_root
    for path in source_files:
        text = _read(path)
        if any(m in text for m in _ENGINE_MARKERS):
            return True
    return False


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find custom C++ engine entry points. Deterministic order.

    Runs whenever `cpp` or `c` is present in `languages`.
    """
    if "cpp" not in languages and "c" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    source_files: list[Path] = []
    for ext in (".cpp", ".cc", ".cxx", ".h", ".hpp"):
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            try:
                rel_parts = p.relative_to(repo_root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            source_files.append(p)
    source_files.sort()

    if not _project_uses_engine_markers(repo_root, source_files):
        return []

    for path in source_files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) `int main(...)` — top-level program entry.
        for m in _MAIN_RE.finditer(text):
            args = m.group("args").strip()
            line = _line_of(text, m.start())
            metadata = {
                "callback": "main",
                "framework": "custom_engine",
            }
            if args:
                metadata["args"] = args
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="game_engine",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

        # 2) `<Class>::update(...)` / `tick(...)` / `step(...)`.
        for m in _UPDATE_RE.finditer(text):
            cls = m.group("cls")
            name = m.group("name")
            params = m.group("params").strip()
            line = _line_of(text, m.start())
            metadata = {
                "callback": name,
                "class": cls,
                "framework": "custom_engine",
                "role": "tick",
            }
            if params:
                metadata["params"] = params
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol=f"{cls}::{name}",
                    type_origin="game_engine",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

        # 3) `<Class>::render(...)` / `draw(...)` / `present(...)`.
        for m in _RENDER_RE.finditer(text):
            cls = m.group("cls")
            name = m.group("name")
            params = m.group("params").strip()
            line = _line_of(text, m.start())
            metadata = {
                "callback": name,
                "class": cls,
                "framework": "custom_engine",
                "role": "render",
            }
            if params:
                metadata["params"] = params
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol=f"{cls}::{name}",
                    type_origin="game_engine",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

        # 4) Input callbacks — `<Class>::on<Event>(...)` and friends.
        for m in _INPUT_RE.finditer(text):
            cls = m.group("cls")
            name = m.group("name")
            params = m.group("params").strip()
            line = _line_of(text, m.start())
            # Filter false-positives: methods called `onload` /
            # `onunload` aren't input handlers in the engine sense.
            lower = name.lower()
            if lower in ("onload", "onunload", "oninit", "onshutdown"):
                kind = EntryPointKind.BOOT_PATH
            else:
                kind = EntryPointKind.EVENT_LISTENER
            metadata = {
                "callback": name,
                "class": cls,
                "framework": "custom_engine",
                "role": "input",
            }
            if params:
                metadata["params"] = params
            found.append(
                EntryPoint(
                    kind=kind,
                    file=rel,
                    line=line,
                    symbol=f"{cls}::{name}",
                    type_origin="game_engine",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
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
