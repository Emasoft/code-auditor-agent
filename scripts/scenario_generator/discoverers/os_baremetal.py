"""Custom OS / hobby kernel (bare-metal) discoverer.

Finds canonical entry points in a bare-metal kernel project — typical
shape: an `*.ld` linker script + a hand-rolled bootloader (`boot.s` /
`start.s` / `entry.s`) + a C kernel with `kernel_main` and a sprinkling
of ISR handlers wired into a vector table.

Entry-point kinds emitted:

- `kernel_main` / `kmain` / `_kernel_start` definitions in C →
  BOOT_PATH — the high-level kernel entry the bootloader jumps to.
- `_start` / `Reset_Handler` / `_entry` definitions in C →
  BOOT_PATH — low-level entry / reset vector implemented in C.
- `__attribute__((interrupt))` function definitions in C →
  ISR_VECTOR — explicit ISR markers.
- Functions whose name ends in `_isr`, `_irq_handler`, or
  `_interrupt_handler` in C → ISR_VECTOR — common naming for
  interrupt service routines in hobby kernels.
- Assembly labels named `_start:`, `_entry:`, `kernel_entry:`,
  `Reset_Handler:` in `*.s` / `*.S` files → BOOT_PATH.
- Assembly labels matching `*_isr:` / `*_irq:` in `*.s` / `*.S` →
  ISR_VECTOR.

`metadata.lang` distinguishes `c` vs `asm` entries so the walker can
treat them differently if needed. Output is sorted by
`(file, line, symbol, kind)`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regex contracts
# ---------------------------------------------------------------------------

# C function DEFINITION for one of the well-known kernel-entry names.
# Accepts any return type, including `void __attribute__((noreturn))`
# combos that are idiomatic for bare-metal kernels.
_KERNEL_ENTRY_NAMES: tuple[str, ...] = (
    "kernel_main",
    "kmain",
    "_kernel_start",
    "kernel_start",
    "kernel_entry",
)
_LOW_ENTRY_NAMES: tuple[str, ...] = (
    "_start",
    "Reset_Handler",
    "_entry",
    "_reset",
    "reset_handler",
)

# Match a C function definition. The capture group `sym` is the
# function name. We match a permissive return-type prefix that can
# include attributes and qualifiers, then the name, then `(`, then any
# parameter list, then `{` on the same or next line.
_C_DEF_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*\s+|\*\s*|__attribute__\s*\(\([^)]*\)\)\s+){1,6}"
    r"(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{",
)

# Detect functions decorated with __attribute__((interrupt)) on the
# same logical declaration. We scan the 200 bytes preceding the `(` of
# the function name. The actual symbol comes from `_C_DEF_RE` above —
# this regex is only used as an "is this an interrupt-handler?" test.
_INTERRUPT_ATTR_RE = re.compile(r"__attribute__\s*\(\s*\(\s*interrupt\s*(?:\([^)]*\))?\s*\)\s*\)")

# ISR-suffix naming convention. Matches the full function-name suffix.
_ISR_SUFFIX_RE = re.compile(r"_(?:isr|irq_handler|interrupt_handler|irqh)\Z", re.IGNORECASE)

# Assembly labels. Matches `<name>:` at start of line (idiomatic),
# tolerating leading whitespace for indented labels.
_ASM_LABEL_RE = re.compile(r"^[ \t]*(?P<sym>[A-Za-z_\.][A-Za-z0-9_\.]*)\s*:", re.MULTILINE)

# Well-known boot-label names in assembly.
_BOOT_ASM_NAMES: frozenset[str] = frozenset(
    {
        "_start",
        "_entry",
        "kernel_entry",
        "Reset_Handler",
        "_reset",
        "reset_handler",
        "kernel_main",
        "kmain",
    }
)

# ISR-suffix detection for asm labels — same rule as for C, but ALSO
# allow the canonical `*_handler` suffix that's more common in vector
# tables than in C names.
_ASM_ISR_SUFFIX_RE = re.compile(r"_(?:isr|irq|irqh|handler)\Z", re.IGNORECASE)


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
        "doc",
        "docs",
        "Documentation",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
        "samples_dev",
        "examples_dev",
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


def _iter_files(repo_root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """Sorted files matching any of `suffixes` under `repo_root`.

    Skip-dir filtering is RELATIVE to repo_root — fixtures under
    `tests/fixtures/...` are scanned even though `tests` would be in
    other discoverers' skip sets.
    """
    out: list[Path] = []
    for suffix in suffixes:
        for p in repo_root.rglob(f"*{suffix}"):
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


def _scan_c_file(rel: str, text: str, found: list[EntryPoint]) -> None:
    """Scan a single C source for kernel-main / reset-handler / ISR defs."""
    kernel_set = frozenset(_KERNEL_ENTRY_NAMES)
    low_set = frozenset(_LOW_ENTRY_NAMES)

    for m in _C_DEF_RE.finditer(text):
        sym = m.group("sym")
        line = _line_of(text, m.start())
        # Look at the matched preamble for an `interrupt` attribute.
        preamble = m.group(0)
        has_interrupt_attr = bool(_INTERRUPT_ATTR_RE.search(preamble))

        if has_interrupt_attr:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.ISR_VECTOR,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="os_baremetal",
                    metadata={"lang": "c", "marker": "__attribute__((interrupt))"},
                )
            )
            continue

        if sym in kernel_set:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="os_baremetal",
                    metadata={"lang": "c", "role": "kernel_entry"},
                )
            )
        elif sym in low_set:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="os_baremetal",
                    metadata={"lang": "c", "role": "reset_vector"},
                )
            )
        elif _ISR_SUFFIX_RE.search(sym):
            found.append(
                EntryPoint(
                    kind=EntryPointKind.ISR_VECTOR,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="os_baremetal",
                    metadata={"lang": "c", "marker": "suffix"},
                )
            )


def _scan_asm_file(rel: str, text: str, found: list[EntryPoint]) -> None:
    """Scan an assembly source for boot-label / ISR-label definitions."""
    for m in _ASM_LABEL_RE.finditer(text):
        sym = m.group("sym")
        line = _line_of(text, m.start())

        # Skip local labels (start with `.`) and labels that look like
        # data-section directives — they're not entry points.
        if sym.startswith("."):
            continue

        if sym in _BOOT_ASM_NAMES:
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="os_baremetal",
                    metadata={"lang": "asm", "role": "boot_label"},
                )
            )
        elif _ASM_ISR_SUFFIX_RE.search(sym):
            found.append(
                EntryPoint(
                    kind=EntryPointKind.ISR_VECTOR,
                    file=rel,
                    line=line,
                    symbol=sym,
                    type_origin="os_baremetal",
                    metadata={"lang": "asm", "marker": "suffix"},
                )
            )


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find bare-metal kernel entry points. Deterministic order.

    Bare-metal kernels are predominantly C + ASM. We don't strictly
    require either language flag to be set — the linker-script
    fingerprint plus the file scan is enough; the language tuple is
    advisory.
    """
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_files(repo_root, (".c",)):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        _scan_c_file(rel, text, found)

    for path in _iter_files(repo_root, (".s", ".S", ".asm")):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        _scan_asm_file(rel, text, found)

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
