"""Zephyr RTOS firmware discoverer.

Finds the canonical entry points exposed by a Zephyr application
(`prj.conf` + CMakeLists.txt + `**/*.c`):

- `K_THREAD_DEFINE(<tid>, <stack>, <entry>, ...);` → RTOS_TASK — the
  `<entry>` symbol is the thread body. The `<tid>` and `<stack>` size
  are kept on `metadata`.
- `K_WORK_DEFINE(<work>, <handler>);` → EVENT_LISTENER — work-queue
  handler runs from the system workqueue or a dedicated worker thread.
- `SYS_INIT(<fn>, <level>, <prio>);` → BOOT_PATH — pre-main init hook.
- `int main(void)` → MAIN_FUNCTION — Zephyr's cooperative main entry.

`type_origin` is hard-coded to `"firmware_zephyr"`. The walker is
type-blind and reads only the EntryPoint schema fields; type knowledge
is crystallised into the metadata dict.

Heuristic, not AST-perfect, but deterministic. Output is sorted by
`(file, line, symbol, kind)` — required for byte-identical goldens.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# K_THREAD_DEFINE(name, stack_size, entry, p1, p2, p3, prio, options, delay)
# The first three arguments are what the walker reasons about; everything
# after that is policy metadata. DOTALL lets multi-line invocations match.
_K_THREAD_DEFINE_RE = re.compile(
    r"\bK_THREAD_DEFINE\s*\(\s*"
    r"(?P<tid>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<stack>[^,]+?)\s*,\s*"
    r"(?P<entry>[A-Za-z_][A-Za-z0-9_]*)\s*,",
    re.DOTALL,
)

# K_WORK_DEFINE(work, handler) — the standard top-level work-item macro.
_K_WORK_DEFINE_RE = re.compile(
    r"\bK_WORK_DEFINE\s*\(\s*"
    r"(?P<work>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*\)",
)

# SYS_INIT(fn, level, prio) — Zephyr's pre-main init registry.
_SYS_INIT_RE = re.compile(
    r"\bSYS_INIT\s*\(\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<level>[A-Z_][A-Z0-9_]*)\s*,\s*"
    r"(?P<prio>[^)]+?)\s*\)",
    re.DOTALL,
)

# int main(void) at column 0 — Zephyr applications expose main as a
# normal C entry. Whitespace before `int` is tolerated for indented
# class-method-style sketches, but `\s*` at the start prevents matching
# `static int main(void)` (which Zephyr does not use).
_MAIN_RE = re.compile(r"^\s*int\s+main\s*\(\s*void\s*\)\s*\{", re.MULTILINE)


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
        "build",
        "dist",
        "out",
        "bin",
        "obj",
        # Zephyr's build directories — west generates these.
        "zephyr",
        "modules",
        # Per-app workspace caches.
        ".west",
        "twister-out",
        # Tests / fixtures bundled in nested example apps.
        "tests",
        "test",
        "samples",
        "sample",
        "examples",
        "example",
        "doc",
        "docs",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "samples_dev",
        "examples_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128 KiB is plenty for Zephyr app .c files


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
    """Sorted list of *.c files under `repo_root`, with skip-dirs filtered.

    Skip-dir filtering uses path components RELATIVE to `repo_root` — this
    matters because fixtures live under `tests/fixtures/...` and an
    absolute-`parts` check would silently drop every file in the fixture.
    """
    out: list[Path] = []
    for p in repo_root.rglob("*.c"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        # Only DIRECTORY parts participate in the skip check (the
        # filename itself is the last element).
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Zephyr entry points. Deterministic order.

    `languages` is the language list emitted by the language detector.
    We require `"c"` to be present — otherwise this isn't really a Zephyr
    application and we silently return nothing.
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

        # ---- K_THREAD_DEFINE → RTOS_TASK ----------------------------------
        for m in _K_THREAD_DEFINE_RE.finditer(text):
            tid = m.group("tid")
            stack = m.group("stack").strip()
            entry = m.group("entry")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RTOS_TASK,
                    file=rel,
                    line=line,
                    symbol=entry,
                    type_origin="firmware_zephyr",
                    metadata={
                        "macro": "K_THREAD_DEFINE",
                        "thread_id": tid,
                        "stack": stack,
                    },
                )
            )

        # ---- K_WORK_DEFINE → EVENT_LISTENER -------------------------------
        for m in _K_WORK_DEFINE_RE.finditer(text):
            work = m.group("work")
            handler = m.group("handler")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=handler,
                    type_origin="firmware_zephyr",
                    metadata={"macro": "K_WORK_DEFINE", "work": work},
                )
            )

        # ---- SYS_INIT → BOOT_PATH -----------------------------------------
        for m in _SYS_INIT_RE.finditer(text):
            fn = m.group("fn")
            level = m.group("level")
            prio = m.group("prio").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin="firmware_zephyr",
                    metadata={
                        "macro": "SYS_INIT",
                        "level": level,
                        "priority": prio,
                    },
                )
            )

        # ---- int main(void) → MAIN_FUNCTION -------------------------------
        for m in _MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="firmware_zephyr",
                    metadata={"role": "zephyr_main"},
                )
            )

    # Dedup by (file, line, symbol, kind) — two distinct K_WORK_DEFINEs of
    # the same handler are two entries; the same handler appearing in a
    # header included from two .c files is one entry. Including `kind`
    # in the key keeps RTOS_TASK and EVENT_LISTENER distinct when a
    # symbol is somehow both (rare but valid).
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, ep.kind.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    # Deterministic sort. Tiebreaker on kind so two entries that hash to
    # the same (file, line, symbol) still order identically across runs.
    unique.sort(key=lambda e: (e.sort_key(), e.kind.value))
    return unique
