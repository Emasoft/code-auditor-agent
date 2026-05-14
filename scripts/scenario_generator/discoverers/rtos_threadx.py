"""Azure RTOS ThreadX discoverer.

Finds the canonical entry points exposed by a ThreadX application:

- `tx_thread_create(&<thread>, "<name>", <entry_fn>, ...)` -> RTOS_TASK
  one entry per call. The entry function (third argument) is the
  reported symbol. Metadata captures thread struct, name, and any
  priority/stack info that fits in a short regex pass.
- `tx_kernel_enter()` -> BOOT_PATH for the RTOS launch site. The
  containing function is reported as the symbol (typically `main`).

`type_origin` is hard-coded to `"rtos_threadx"`. The discoverer scans
`*.c` files only (ThreadX projects rarely use C++; tx_user.h is
header-only configuration, no entry points live in it).

Skip-dir filtering uses RELATIVE parts. Output is sorted by
(file, line, symbol, kind) so goldens are byte-identical.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "rtos_threadx"

# tx_thread_create(&<thread>, "<name>", <entry>, <input>, <stack_ptr>,
#                  <stack_size>, <prio>, <preempt_thresh>,
#                  <time_slice>, <auto_start>)
# 10 positional arguments. We capture (thread, name, entry, stack_size,
# prio) for metadata. DOTALL so multi-line calls match.
_TX_THREAD_CREATE_RE = re.compile(
    r"\btx_thread_create\s*\(\s*"
    r"&\s*(?P<thread>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r'"(?P<name>[^"]*)"\s*,\s*'
    r"(?P<entry>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"[^,]+,\s*"  # input
    r"[^,]+,\s*"  # stack_ptr
    r"(?P<stack_size>[^,]+?)\s*,\s*"
    r"(?P<priority>[^,]+?)\s*,\s*"
    r"[^,]+,\s*"  # preempt_thresh
    r"[^,]+,\s*"  # time_slice
    r"[^)]+\)",  # auto_start
    re.DOTALL,
)

# tx_kernel_enter() -- ThreadX's scheduler entry point. Idiomatic
# applications call it once from main() after tx_application_define.
_TX_KERNEL_ENTER_RE = re.compile(r"\btx_kernel_enter\s*\(\s*\)\s*;")

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
        "threadx",  # vendored ThreadX tree mirror
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
    """Return the name of the function whose body contains `offset`.

    Walks the file's function-definition matches and returns the name
    of the last one whose opening `{` precedes `offset`. Falls back to
    "main" -- the realistic default for tx_kernel_enter() sites.
    """
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
    """Find ThreadX entry points. Deterministic order.

    Gated on `"c"` being present in the detected language list. A
    ThreadX repo with no .c files is configuration-only and has
    nothing the walker can reason about.
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

        # ---- tx_thread_create(...) -> RTOS_TASK ---------------------------
        for m in _TX_THREAD_CREATE_RE.finditer(text):
            thread = m.group("thread")
            name = m.group("name")
            entry = m.group("entry")
            stack_size = m.group("stack_size").strip()
            priority = m.group("priority").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RTOS_TASK,
                    file=rel,
                    line=line,
                    symbol=entry,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "thread": thread,
                        "name": name,
                        "stack_size": stack_size,
                        "priority": priority,
                        "creator": "tx_thread_create",
                    },
                    docstring=_comment_before(text, m.start()),
                )
            )

        # ---- tx_kernel_enter() -> BOOT_PATH -------------------------------
        for m in _TX_KERNEL_ENTER_RE.finditer(text):
            enclosing = _enclosing_function(text, m.start())
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=enclosing,
                    type_origin=TYPE_ORIGIN,
                    metadata={"trigger": "tx_kernel_enter"},
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
