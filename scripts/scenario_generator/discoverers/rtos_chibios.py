"""ChibiOS/RT discoverer.

Finds the canonical entry points exposed by a ChibiOS application:

- `THD_FUNCTION(<name>, arg) { ... }` -> RTOS_TASK
  one entry per macro-style function definition. The first argument
  (name) is the symbol; the surrounding macro is what the ChibiOS
  scheduler expands into the actual thread entry point. Metadata
  records the macro form so consumers know it's not an ordinary
  C function.
- `chThdCreateStatic(<wa>, <wa_size>, <prio>, <fn>, <arg>)` ->
  EVENT_LISTENER. The created site for each thread. The symbol is the
  function passed (which the THD_FUNCTION macro produced). Metadata
  carries the working-area variable + priority. EVENT_LISTENER is used
  here for the launch (creation event) -- the RTOS_TASK is the entry
  function definition itself, the EVENT_LISTENER is the registration
  point. Two distinct entry-point kinds for the two semantic events.
- `chSysInit()` -> BOOT_PATH for the kernel init site. The containing
  function (typically `main`) is the reported symbol.

`type_origin` is hard-coded to `"rtos_chibios"`. The discoverer scans
`*.c` files only -- ChibiOS apps are C; THD_FUNCTION is a C macro that
declares a normal-looking function with a fixed signature.

Skip-dir filtering uses RELATIVE parts. Output is sorted by
(file, line, symbol, kind) so goldens are byte-identical.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "rtos_chibios"

# THD_FUNCTION(<name>, <arg>) { ... }
# ChibiOS macro that declares the thread entry function. The first
# argument is the function name; the second is the user argument
# parameter name. We capture both for the metadata.
_THD_FUNCTION_RE = re.compile(
    r"\bTHD_FUNCTION\s*\(\s*"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<arg>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\{",
)

# chThdCreateStatic(<wa>, <wa_size>, <prio>, <fn>, <arg>)
# 5 positional arguments. The 4th (fn) is the thread entry; the 1st
# (wa) is the working-area buffer. DOTALL for multi-line calls.
_CH_THD_CREATE_RE = re.compile(
    r"\bchThdCreateStatic\s*\(\s*"
    r"(?P<wa>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<wa_size>[^,]+?)\s*,\s*"
    r"(?P<priority>[^,]+?)\s*,\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"[^)]+\)",
    re.DOTALL,
)

# chSysInit() -- ChibiOS kernel init call. Always present in a real app.
_CH_SYS_INIT_RE = re.compile(r"\bchSysInit\s*\(\s*\)\s*;")

_FUNC_DEF_RE = re.compile(
    r"^\s*(?:static\s+|inline\s+|extern\s+)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*\s+)+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)

_LINE_COMMENT_RE = re.compile(r"^\s*(?://+|\*)\s?(?P<text>.*?)\s*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*(?P<text>.*?)\*/", re.DOTALL)

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "out",
        "bin",
        "obj",
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "Documentation",
        "doc",
        "docs",
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
        "ChibiOS",  # vendored ChibiOS tree mirror
        "chibios",
    }
)

CONTENT_PREVIEW_BYTES = 131072


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path`. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _iter_c_files(repo_root: Path) -> list[Path]:
    """Sorted *.c files under repo_root with skip-dirs filtered (REL parts)."""
    out: list[Path] = []
    for p in repo_root.rglob("*.c"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        out.append(p)
    out.sort()
    return out


def _enclosing_function(text: str, offset: int) -> str:
    """Name of the function whose body contains `offset`. Default "main"."""
    enclosing = "main"
    for fm in _FUNC_DEF_RE.finditer(text):
        if fm.start() < offset:
            enclosing = fm.group("name")
        else:
            break
    return enclosing


def _comment_before(text: str, offset: int) -> str:
    """First non-empty line of comments immediately preceding `offset`."""
    line_start = text.rfind("\n", 0, offset) + 1
    lines: list[str] = []
    cursor = line_start - 1
    while cursor > 0:
        prev_line_start = text.rfind("\n", 0, cursor) + 1
        prev_line = text[prev_line_start:cursor]
        stripped = prev_line.strip()
        if not stripped:
            break
        if stripped.startswith(("//", "*")):
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


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find ChibiOS entry points. Deterministic order.

    Gated on `"c"` being present in the detected language list. ChibiOS
    is a C RTOS; a repo with no C source is configuration-only.
    """
    if "c" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_c_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # ---- THD_FUNCTION(<name>, <arg>) { ... } -> RTOS_TASK -------------
        for m in _THD_FUNCTION_RE.finditer(text):
            name = m.group("name")
            arg = m.group("arg")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RTOS_TASK,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "arg": arg,
                        "macro": "THD_FUNCTION",
                    },
                    docstring=_comment_before(text, m.start()),
                )
            )

        # ---- chThdCreateStatic(...) -> EVENT_LISTENER ---------------------
        for m in _CH_THD_CREATE_RE.finditer(text):
            wa = m.group("wa")
            wa_size = m.group("wa_size").strip()
            priority = m.group("priority").strip()
            fn = m.group("fn")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "wa": wa,
                        "wa_size": wa_size,
                        "priority": priority,
                        "creator": "chThdCreateStatic",
                    },
                    docstring=_comment_before(text, m.start()),
                )
            )

        # ---- chSysInit() -> BOOT_PATH ------------------------------------
        for m in _CH_SYS_INIT_RE.finditer(text):
            enclosing = _enclosing_function(text, m.start())
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=enclosing,
                    type_origin=TYPE_ORIGIN,
                    metadata={"trigger": "chSysInit"},
                    docstring=_comment_before(text, m.start()),
                )
            )

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
