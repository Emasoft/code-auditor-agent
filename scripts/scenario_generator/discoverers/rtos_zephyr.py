"""Zephyr (RTOS variant) discoverer.

Distinct from any future firmware_zephyr discoverer: this module
emphasises the threading constructs that justify the rtos_zephyr type
in the registry. Zephyr applications can match BOTH rtos_zephyr and
firmware_zephyr (the fingerprints are not in conflict), so emit
type_origin = "rtos_zephyr" only and let any firmware-variant
discoverer that ships later own its own EntryPoints.

Patterns detected:

- `K_THREAD_DEFINE(<tid>, <stack>, <fn>, ...)` -> RTOS_TASK
  one entry per macro invocation, symbol = thread entry function.
  Metadata: `{tid, stack, entry}`.
- `K_WORK_DEFINE(<sym>, <handler>)` -> EVENT_LISTENER
  one entry per work item, symbol = work handler function.
  Metadata: `{work, handler}`.
- `SYS_INIT(<fn>, <level>, <prio>)` -> BOOT_PATH
  one entry per system init hook, symbol = the init function.
  Metadata: `{level, priority}`.

`type_origin` is hard-coded to `"rtos_zephyr"`. The discoverer scans
both `*.c` AND `*.h` files (Zephyr drivers commonly place macro
invocations in headers via initialiser macros). Skip-dir filtering
uses RELATIVE parts.

Output is sorted by (file, line, symbol, kind) -- byte-identical
across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "rtos_zephyr"

# K_THREAD_DEFINE(<tid>, <stack>, <fn>, <p1>, <p2>, <p3>, <prio>, <opts>, <delay>)
# The macro takes 9 positional arguments. We only need (tid, stack, fn,
# prio); the rest are kept as opaque metadata. DOTALL so multi-line.
_K_THREAD_DEFINE_RE = re.compile(
    r"\bK_THREAD_DEFINE\s*\(\s*"
    r"(?P<tid>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<stack>[^,]+?)\s*,\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"[^,]+,\s*"  # p1
    r"[^,]+,\s*"  # p2
    r"[^,]+,\s*"  # p3
    r"(?P<priority>[^,]+?)\s*,\s*"
    r"[^,]+,\s*"  # opts
    r"[^)]+\)",  # delay
    re.DOTALL,
)

# K_WORK_DEFINE(<sym>, <handler>) -- 2 positional arguments. The handler
# is what the workqueue invokes when the work item is submitted.
_K_WORK_DEFINE_RE = re.compile(
    r"\bK_WORK_DEFINE\s*\(\s*"
    r"(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*\)",
)

# SYS_INIT(<fn>, <level>, <prio>) -- 3 positional arguments. Captures
# the Zephyr "called at <level> with <prio>" boot hook.
_SYS_INIT_RE = re.compile(
    r"\bSYS_INIT\s*\(\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<level>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<priority>[^)]+?)\)",
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
        "zephyr",  # vendored zephyr tree mirror; never the app's own code
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


def _iter_source_files(repo_root: Path) -> list[Path]:
    """Sorted .c and .h files under repo_root. Skip-dirs filtered by REL parts."""
    out: list[Path] = []
    for ext in (".c", ".h"):
        for p in repo_root.rglob(f"*{ext}"):
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
    """Find Zephyr-as-RTOS entry points. Deterministic order.

    Gated on `"c"` being present. Zephyr applications without C source
    are not realistic; a Kconfig-only repo is build configuration, not
    an application, and has nothing for the walker to reason about.
    """
    if "c" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_source_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # ---- K_THREAD_DEFINE(...) -> RTOS_TASK ----------------------------
        for m in _K_THREAD_DEFINE_RE.finditer(text):
            tid = m.group("tid")
            stack = m.group("stack").strip()
            fn = m.group("fn")
            priority = m.group("priority").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RTOS_TASK,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "tid": tid,
                        "stack": stack,
                        "priority": priority,
                        "macro": "K_THREAD_DEFINE",
                    },
                    docstring=_comment_before(text, m.start()),
                )
            )

        # ---- K_WORK_DEFINE(<sym>, <handler>) -> EVENT_LISTENER ------------
        for m in _K_WORK_DEFINE_RE.finditer(text):
            work = m.group("sym")
            handler = m.group("handler")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=handler,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "work": work,
                        "handler": handler,
                        "macro": "K_WORK_DEFINE",
                    },
                    docstring=_comment_before(text, m.start()),
                )
            )

        # ---- SYS_INIT(<fn>, <level>, <prio>) -> BOOT_PATH -----------------
        for m in _SYS_INIT_RE.finditer(text):
            fn = m.group("fn")
            level = m.group("level")
            priority = m.group("priority").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "level": level,
                        "priority": priority,
                        "macro": "SYS_INIT",
                    },
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
