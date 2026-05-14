"""Baremetal firmware discoverer (no RTOS, no SDK).

Finds the canonical entry points exposed by a pure baremetal Cortex-M /
ARM / RISC-V firmware:

- `void Reset_Handler(void)` → RESET_PATH — the C-side reset entry the
  asm startup branches into.
- `int main(void)` → MAIN_FUNCTION — the firmware's main loop.
- `void _start(void)` → BOOT_PATH — alternative startup symbol used by
  some baremetal toolchains (newlib + crt0 stub or hand-rolled).
- `void __attribute__((interrupt)) <Name>(void)` → ISR_VECTOR — any
  function with the GCC `interrupt` attribute is a real vector-table
  entry. The `<Name>` is the ISR symbol (e.g. `SysTick_Handler`,
  `HardFault_Handler`).
- `void __attribute__((naked)) <Name>(void)` → ISR_VECTOR with metadata
  `attr=naked` — naked functions on baremetal are almost always vector
  handlers that manage their own prologue/epilogue.

`type_origin` is hard-coded to `"firmware_baremetal"`. The walker is
type-blind and reads only the EntryPoint schema fields; type knowledge
is crystallised into the metadata dict.

Heuristic, not AST-perfect, but deterministic. Output is sorted by
`(file, line, symbol, kind)` — required for byte-identical goldens.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# void Reset_Handler(void) — column-zero. `void` return is mandatory by
# the ARM EABI ABI for Reset_Handler.
_RESET_HANDLER_RE = re.compile(
    r"^\s*void\s+Reset_Handler\s*\(\s*void\s*\)\s*\{",
    re.MULTILINE,
)

# int main(void) — column-zero, void-arg. Baremetal firmware never uses
# the hosted `int main(int, char**)` form.
_MAIN_RE = re.compile(r"^\s*int\s+main\s*\(\s*void\s*\)\s*\{", re.MULTILINE)

# void _start(void) — newlib / crt0 entry. Some baremetal toolchains
# expose _start as the linker-script ENTRY() target instead of
# Reset_Handler. We emit both when both are present.
_START_RE = re.compile(r"^\s*void\s+_start\s*\(\s*void\s*\)\s*\{", re.MULTILINE)

# void __attribute__((interrupt)) <Name>(void) { — the GCC ISR attribute.
# Whitespace between `__attribute__` and the parens is tolerated, and the
# inner `((interrupt))` may also be `((interrupt("IRQ")))` on AVR/ARM-V7M
# — we only need the keyword.
_INTERRUPT_FN_RE = re.compile(
    r"^\s*void\s+"
    r"__attribute__\s*\(\s*\(\s*interrupt"
    r"[^)]*\)\s*\)\s+"  # may have ((interrupt("IRQ"))) on some archs
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*void\s*\)\s*\{",
    re.MULTILINE,
)

# void __attribute__((naked)) <Name>(void) { — naked baremetal handlers.
_NAKED_FN_RE = re.compile(
    r"^\s*void\s+"
    r"__attribute__\s*\(\s*\(\s*naked\s*\)\s*\)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*void\s*\)\s*\{",
    re.MULTILINE,
)


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


CONTENT_PREVIEW_BYTES = 131072  # 128 KiB — baremetal firmware files almost never exceed this


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

    Skip-dir filtering uses path components RELATIVE to `repo_root` so
    fixtures under `tests/fixtures/...` aren't dropped.
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
    """Find baremetal firmware entry points. Deterministic order.

    `languages` is the language list emitted by the language detector.
    We require `"c"` to be present.
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

        # ---- void Reset_Handler(void) → RESET_PATH ------------------------
        for m in _RESET_HANDLER_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RESET_PATH,
                    file=rel,
                    line=line,
                    symbol="Reset_Handler",
                    type_origin="firmware_baremetal",
                    metadata={"role": "reset_vector"},
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
                    type_origin="firmware_baremetal",
                    metadata={"role": "baremetal_main"},
                )
            )

        # ---- void _start(void) → BOOT_PATH --------------------------------
        for m in _START_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="_start",
                    type_origin="firmware_baremetal",
                    metadata={"role": "crt0_entry"},
                )
            )

        # ---- __attribute__((interrupt)) → ISR_VECTOR ----------------------
        for m in _INTERRUPT_FN_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.ISR_VECTOR,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="firmware_baremetal",
                    metadata={"attr": "interrupt"},
                )
            )

        # ---- __attribute__((naked)) → ISR_VECTOR --------------------------
        for m in _NAKED_FN_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.ISR_VECTOR,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="firmware_baremetal",
                    metadata={"attr": "naked"},
                )
            )

    # Dedup by (file, line, symbol, kind) — the same handler declared in
    # multiple translation units would otherwise duplicate; we keep one
    # entry per (file, line) source location.
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
