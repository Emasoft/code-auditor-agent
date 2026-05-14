"""Linux kernel tree discoverer.

Finds canonical entry points in a full Linux kernel source tree (the
in-tree style — MAINTAINERS file at the top, arch/ subtree, drivers/
subtree). This is distinct from `linux_kernel_module`, which targets a
single out-of-tree module.

Entry-point kinds emitted:

- `module_init(<sym>)` / `module_exit(<sym>)` → MODULE_INIT / MODULE_EXIT
- `SYSCALL_DEFINE<N>(<name>, ...)` → SYSCALL_HANDLER (the macro
  expands to `sys_<name>`; we use the bare name from the macro args)
- `EXPORT_SYMBOL(<fn>)` / `EXPORT_SYMBOL_GPL(<fn>)` → IPC_HANDLER
- `early_initcall(<fn>)` / `core_initcall(<fn>)` /
  `subsys_initcall(<fn>)` / `arch_initcall(<fn>)` / `late_initcall(<fn>)`
  → BOOT_PATH (the staged init levels that the kernel runs at boot)

The discoverer scans only `*.c` files; the kernel uses C exclusively
for these entry points. Output is sorted by `(file, line, symbol, kind)`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regex contracts
# ---------------------------------------------------------------------------

_MODULE_INIT_RE = re.compile(r"\bmodule_init\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)")
_MODULE_EXIT_RE = re.compile(r"\bmodule_exit\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)")
_EXPORT_SYMBOL_RE = re.compile(r"\bEXPORT_SYMBOL(?:_GPL)?\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)")

# SYSCALL_DEFINE0..6(<name>, ...) — the kernel's standard syscall macro.
# Argument count appears as the suffix digit; we keep both the bare name
# (used as the symbol) and the arity (metadata).
_SYSCALL_DEFINE_RE = re.compile(r"\bSYSCALL_DEFINE(?P<arity>[0-6])\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\b")

# initcall levels — staged boot init macros. Order in the tuple is the
# canonical run order at boot but the discoverer is agnostic to it.
_INITCALL_LEVELS: tuple[str, ...] = (
    "early_initcall",
    "pure_initcall",
    "core_initcall",
    "postcore_initcall",
    "arch_initcall",
    "subsys_initcall",
    "fs_initcall",
    "rootfs_initcall",
    "device_initcall",
    "late_initcall",
)
_INITCALL_RE = re.compile(
    r"\b(?P<level>" + "|".join(_INITCALL_LEVELS) + r")\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)


# ---------------------------------------------------------------------------
# Skip-dirs / preview / IO helpers
# ---------------------------------------------------------------------------

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
        "tools",
        "scripts",
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

# 128 KiB preview — kernel .c files can be large; 128 KB covers the
# meaningful preamble + entry-point declarations in essentially every
# real kernel file.
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

    Uses path components RELATIVE to `repo_root` for the skip check, so
    fixtures under `tests/fixtures/...` are scanned even though `tests`
    is in the skip set of other discoverers.
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


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Linux kernel tree entry points. Deterministic order.

    Requires `c` in the language list — kernel trees are C-only at this
    level of granularity.
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

        # ---- module_init(<sym>) → MODULE_INIT ----------------------------
        for m in _MODULE_INIT_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="linux_kernel_tree",
                    metadata={"macro": "module_init"},
                )
            )

        # ---- module_exit(<sym>) → MODULE_EXIT ----------------------------
        for m in _MODULE_EXIT_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_EXIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="linux_kernel_tree",
                    metadata={"macro": "module_exit"},
                )
            )

        # ---- SYSCALL_DEFINE<N>(<name>, ...) → SYSCALL_HANDLER ------------
        for m in _SYSCALL_DEFINE_RE.finditer(text):
            sym = m.group("sym")
            arity = m.group("arity")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.SYSCALL_HANDLER,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="linux_kernel_tree",
                    metadata={"macro": f"SYSCALL_DEFINE{arity}", "arity": int(arity)},
                )
            )

        # ---- EXPORT_SYMBOL{,_GPL} → IPC_HANDLER --------------------------
        for m in _EXPORT_SYMBOL_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.IPC_HANDLER,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="linux_kernel_tree",
                    metadata={"macro": "EXPORT_SYMBOL"},
                )
            )

        # ---- *_initcall(<fn>) → BOOT_PATH --------------------------------
        for m in _INITCALL_RE.finditer(text):
            sym = m.group("sym")
            level = m.group("level")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="linux_kernel_tree",
                    metadata={"macro": level},
                )
            )

    # Dedup by (file, line, symbol, kind) so a helper that legitimately
    # appears as both initcall + EXPORT_SYMBOL keeps both kinds.
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
