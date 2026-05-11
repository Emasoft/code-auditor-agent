"""Linux kernel module discoverer.

Finds the canonical entry points exposed by an out-of-tree Linux kernel
module (`obj-m` style — i.e. the units that the type-detection registry
labels `linux_kernel_module`):

- `module_init(<symbol>);`  → MODULE_INIT — inner symbol is the entry
- `module_exit(<symbol>);`  → MODULE_EXIT
- `struct file_operations <var> = { ... };` blocks:
    * `.unlocked_ioctl = <fn>` → IOCTL_HANDLER
    * `.read | .write | .open | .release | .mmap | .poll = <fn>` →
      SYSCALL_HANDLER (metadata `op` carries the fops member name)
- `EXPORT_SYMBOL(<fn>)` / `EXPORT_SYMBOL_GPL(<fn>)` → IPC_HANDLER

`type_origin` is hard-coded to `"linux_kernel_module"`. The walker is
type-blind and reads only the EntryPoint schema fields; type knowledge
is crystallised into the metadata dict.

Heuristic, not AST-perfect, but deterministic. The discoverer greps for
the literal macro/struct-member spellings used in idiomatic kernel code
and skips `tests/`, `examples/`, and `Documentation/` so out-of-tree
example modules don't pollute the scan.

Output is sorted by (file, line, symbol) — required for byte-identical
goldens across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regex contracts
#
# All patterns operate on a UTF-8 string read from a *.c file. They are
# anchored loosely (no leading `^\s*` requirement) because kernel macros
# often appear after a closing brace of the previous function on the same
# line. Trailing semicolons / commas are tolerated where idiomatic.
# ---------------------------------------------------------------------------

# module_init(<symbol>) and module_exit(<symbol>)
_MODULE_INIT_RE = re.compile(r"\bmodule_init\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)")
_MODULE_EXIT_RE = re.compile(r"\bmodule_exit\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)")

# EXPORT_SYMBOL(<fn>) and EXPORT_SYMBOL_GPL(<fn>) — share one regex.
_EXPORT_SYMBOL_RE = re.compile(r"\bEXPORT_SYMBOL(?:_GPL)?\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)")

# struct file_operations <var> = { ... };
# Notes:
# - `static`/`const` qualifiers are optional, in any order.
# - Body is captured up to the matching closing brace + optional semicolon.
#   We rely on the body not containing nested `{...}` blocks at the top
#   level (kernel fops initialisers never do; they are flat designated
#   initialisers).
# - DOTALL so the body can span lines.
_FOPS_RE = re.compile(
    r"\b(?:(?:static|const)\s+){0,2}struct\s+file_operations\s+"
    r"(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{(?P<body>[^}]*)\}",
    re.DOTALL,
)

# Inside a fops body: `.member = symbol,` — one entry. The trailing
# comma is optional (last member often omits it).
_FOPS_MEMBER_RE = re.compile(r"\.\s*(?P<op>[a-z_][a-z0-9_]*)\s*=\s*(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*[,}\n]")

# fops members that map to SYSCALL_HANDLER. `.unlocked_ioctl` is special:
# it maps to IOCTL_HANDLER. Other members like `.owner = THIS_MODULE`,
# `.llseek = ...`, `.compat_ioctl = ...`, etc. are silently ignored at
# the walker level (they are not adversarial entry points the walker
# reasons about). Keeping the syscall set narrow keeps the golden small
# and the families list predictable.
_SYSCALL_OPS: frozenset[str] = frozenset(
    {
        "read",
        "write",
        "open",
        "release",
        "mmap",
        "poll",
    }
)

# Directories to skip — out-of-tree kernel module repos almost always
# bundle a `tests/` or `examples/` dir plus a `Documentation/` snippet
# tree imported from upstream. None of these are real entry points.
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
    }
)

# 128 KiB preview is enough for any single .c kernel module file we
# realistically scan. Larger files are truncated; the walker's report
# documents this in its limitations section.
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
    """Sorted list of *.c files under `repo_root`, with skip-dirs filtered.

    Deterministic: paths are sorted alphabetically before the scan loop.

    Skip-dir filtering uses path components RELATIVE to `repo_root` — this
    matters because callers may pass an absolute path whose own parents
    happen to contain a name we'd otherwise skip (e.g. fixtures living
    under `tests/`). A `parts` check on the full absolute path would
    silently drop every fixture file in that case.
    """
    out: list[Path] = []
    for p in repo_root.rglob("*.c"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            # rglob can return symlinked paths outside repo_root in
            # pathological setups — skip them rather than crash.
            continue
        # The filename itself is the last part; only DIRECTORY components
        # (everything except the final element) participate in the skip
        # check.
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find kernel-module entry points. Deterministic order.

    `languages` is the language list emitted by the language detector. We
    require `"c"` to be present — otherwise this isn't really a kernel
    module and we silently return nothing. This mirrors the language
    gate that the FastAPI discoverer uses.
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

        # ---- module_init(<sym>) → MODULE_INIT ------------------------------
        for m in _MODULE_INIT_RE.finditer(text):
            sym = m.group("sym")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="linux_kernel_module",
                    metadata={"macro": "module_init"},
                )
            )

        # ---- module_exit(<sym>) → MODULE_EXIT ------------------------------
        for m in _MODULE_EXIT_RE.finditer(text):
            sym = m.group("sym")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_EXIT,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="linux_kernel_module",
                    metadata={"macro": "module_exit"},
                )
            )

        # ---- struct file_operations <var> = { ... }; → IOCTL + SYSCALL ----
        for fops_match in _FOPS_RE.finditer(text):
            fops_var = fops_match.group("var")
            body = fops_match.group("body")
            body_start = fops_match.start("body")
            for member_match in _FOPS_MEMBER_RE.finditer(body):
                op = member_match.group("op")
                fn = member_match.group("fn")
                # Position in the original text — needed for the line
                # number reported on the EntryPoint.
                abs_offset = body_start + member_match.start()
                line = _line_of(text, abs_offset)

                if op == "unlocked_ioctl":
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.IOCTL_HANDLER,
                            file=rel,
                            line=line,
                            symbol=fn,
                            type_origin="linux_kernel_module",
                            metadata={"op": op, "fops_var": fops_var},
                        )
                    )
                elif op in _SYSCALL_OPS:
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.SYSCALL_HANDLER,
                            file=rel,
                            line=line,
                            symbol=fn,
                            type_origin="linux_kernel_module",
                            metadata={"op": op, "fops_var": fops_var},
                        )
                    )
                # Other fops members (.owner, .llseek, .compat_ioctl, ...)
                # are intentionally ignored — they aren't entry points the
                # walker reasons about and listing them would just inflate
                # the scenario count without raising coverage.

        # ---- EXPORT_SYMBOL / EXPORT_SYMBOL_GPL → IPC_HANDLER --------------
        for m in _EXPORT_SYMBOL_RE.finditer(text):
            sym = m.group("sym")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.IPC_HANDLER,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="linux_kernel_module",
                    metadata={"macro": "EXPORT_SYMBOL"},
                )
            )

    # Dedup by (file, line, symbol, kind) — the same symbol can legitimately
    # appear as both a fops member and an EXPORT_SYMBOL (rare but valid for
    # helpers reused by other modules). Including `kind` in the key keeps
    # both kinds when they coexist at the same site.
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, ep.kind.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    # Deterministic sort. Tiebreaker on kind so two entries that hash to the
    # same (file, line, symbol) still order identically across runs.
    unique.sort(key=lambda e: (e.sort_key(), e.kind.value))
    return unique
