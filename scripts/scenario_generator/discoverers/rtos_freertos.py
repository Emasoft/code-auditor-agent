"""FreeRTOS discoverer.

Finds the canonical entry points exposed by a FreeRTOS application:

- `xTaskCreate(<fn>, "name", stack, params, priority, handle)` -> RTOS_TASK
  one entry per call, with metadata `{name, stack, priority}` from the
  call arguments. The task function (first argument) is the symbol.
- `vTaskStartScheduler()` -> BOOT_PATH for the kernel launch site. The
  containing function name (typically `main`) is the reported symbol.

`type_origin` is hard-coded to `"rtos_freertos"`. The discoverer scans
`*.c` files (FreeRTOS apps are overwhelmingly C; C++ wrappers are rare
enough that the cost of also scanning .cpp would buy little). Skip-dirs
are computed RELATIVE to repo_root so fixtures living under
`tests/fixtures/...` are not silently dropped.

Output is sorted by (file, line, symbol, kind) -- required for
byte-identical goldens across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "rtos_freertos"

# xTaskCreate(<fn>, "<name>", <stack>, <params>, <priority>, <handle>)
# The signature is fixed at 6 arguments; we capture the first 5 we need
# (function, name, stack depth, ignored params, priority). The trailing
# handle pointer is ignored. DOTALL lets the call span lines.
_XTASKCREATE_RE = re.compile(
    r"\bxTaskCreate\s*\(\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r'"(?P<name>[^"]*)"\s*,\s*'
    r"(?P<stack>[^,]+?)\s*,\s*"
    r"(?P<params>[^,]+?)\s*,\s*"
    r"(?P<priority>[^,]+?)\s*,\s*"
    r"(?P<handle>[^)]+?)\)",
    re.DOTALL,
)

# vTaskStartScheduler() -- typically the last call in main(). We only
# need the call site to report BOOT_PATH; the containing function name
# is recovered by a backward scan for the nearest preceding function
# definition.
_VTASKSTART_RE = re.compile(r"\bvTaskStartScheduler\s*\(\s*\)\s*;")

# Function definition pattern -- used to find the symbol enclosing a
# vTaskStartScheduler() call. We grep for `<rettype> <name>(...)` with a
# trailing `{` somewhere on the next non-empty content. The pattern is
# deliberately loose (no full C parser) -- it just needs to find the
# nearest preceding identifier that looks like a function name.
_FUNC_DEF_RE = re.compile(
    r"^\s*(?:static\s+|inline\s+|extern\s+)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*\s+)+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)

# Comment patterns -- used to pull a one-line docstring from immediately
# preceding `//` or `/* ... */` blocks. Matches firmware_arduino's
# convention so the walker's intent hints look consistent across types.
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
        ".pio",
        ".pioenvs",
        ".piolibdeps",
    }
)

CONTENT_PREVIEW_BYTES = 131072  # 128KB


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
    """Sorted *.c files under repo_root with skip-dirs filtered.

    Skip-dir filtering uses path components RELATIVE to repo_root --
    checking absolute parts would mis-skip every fixture whose
    repo_root happens to live under a directory named "tests/" (i.e.
    this plugin's own test fixtures).
    """
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
    "main" if no enclosing function is identifiable -- this is the
    realistic default for vTaskStartScheduler() call sites.
    """
    enclosing = "main"
    for fm in _FUNC_DEF_RE.finditer(text):
        if fm.start() < offset:
            enclosing = fm.group("name")
        else:
            break
    return enclosing


def _comment_before(text: str, offset: int) -> str:
    """Pull a one-line doc summary from comments immediately preceding `offset`.

    Walks backwards over contiguous `//` / `*` lines plus a single
    `/* ... */` block. Returns the first non-empty extracted line. Kept
    short so the walker uses it as an intent hint, not a paragraph.
    """
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
    """Find FreeRTOS entry points. Deterministic order.

    Gated on `"c"` being present in the detected language list --
    mirrors the language gate used by linux_kernel_module. FreeRTOS
    apps without any .c files don't really exist; if the gate misfires
    we silently return nothing.
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

        # ---- xTaskCreate(...) -> RTOS_TASK --------------------------------
        for m in _XTASKCREATE_RE.finditer(text):
            fn = m.group("fn")
            name = m.group("name")
            stack = m.group("stack").strip()
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
                        "name": name,
                        "stack": stack,
                        "priority": priority,
                        "creator": "xTaskCreate",
                    },
                    docstring=_comment_before(text, m.start()),
                )
            )

        # ---- vTaskStartScheduler() -> BOOT_PATH ---------------------------
        for m in _VTASKSTART_RE.finditer(text):
            enclosing = _enclosing_function(text, m.start())
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=enclosing,
                    type_origin=TYPE_ORIGIN,
                    metadata={"trigger": "vTaskStartScheduler"},
                    docstring=_comment_before(text, m.start()),
                )
            )

    # Dedup by (file, line, symbol, kind) -- the same task entry function
    # registered twice (e.g. once per env) should be two entries because
    # the line numbers differ; the dedup is only a safety net against an
    # accidental double match at the same site.
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
