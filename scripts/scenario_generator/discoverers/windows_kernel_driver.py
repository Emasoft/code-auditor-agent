"""Windows kernel-mode driver discoverer.

Finds canonical entry points in Windows kernel-mode drivers (WDM /
KMDF). The fingerprint matches a `.inf` install file at repo root plus
`DriverEntry` / `WdfDriverEntry` somewhere in the C/C++ sources.

Entry-point kinds emitted:

- `(NTSTATUS|VOID) DriverEntry(...)` → BOOT_PATH — the driver's
  one-and-only entry point at load time. Symbol is `DriverEntry`.
- `WdfDriverCreate(...)` callsite → BOOT_PATH for KMDF drivers —
  symbol is `DriverEntry` (the caller), `metadata.framework=kmdf`.
- `IRP_MJ_<NAME>` dispatch-table assignments
  (`DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = MyDispatch`)
  → IOCTL_HANDLER when the IRP is DEVICE_CONTROL or
  INTERNAL_DEVICE_CONTROL; SYSCALL_HANDLER for READ/WRITE/CREATE/CLOSE;
  IPC_HANDLER for the rest. `metadata.irp` carries the major-function
  name.
- `IO_COMPLETION_ROUTINE <Name>;` declarations → EVENT_LISTENER —
  these are async I/O completion callbacks invoked by the kernel
  when an IRP finishes.

Output is sorted by `(file, line, symbol, kind)`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regex contracts
# ---------------------------------------------------------------------------

# DriverEntry signature — Windows kernel-mode drivers' load entry. We
# match the function DEFINITION (with an opening `{` somewhere after
# the parameter list) to avoid forward declarations in headers.
_DRIVER_ENTRY_RE = re.compile(
    r"\b(?:NTSTATUS|VOID|DRIVER_INITIALIZE)\s+DriverEntry\s*\([^)]*\)\s*(?:\n|\r|\s)*\{",
    re.MULTILINE,
)

# WdfDriverCreate callsite — present in KMDF drivers inside DriverEntry.
# We use this as a framework hint rather than a separate entry point.
_WDF_DRIVER_CREATE_RE = re.compile(r"\bWdfDriverCreate\s*\(")

# IRP major-function dispatch-table assignment.
#   DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = MyDispatch;
# Tolerant of arbitrary leading whitespace and `pDriverObject` /
# `Driver->...` / `Driver.MajorFunction[...]` variants used by some
# code styles. The `IRP_MJ_<NAME>` token is captured; the handler
# symbol on the right of `=` is captured up to a `;` or `,`.
_IRP_DISPATCH_RE = re.compile(
    r"->\s*MajorFunction\s*\[\s*(?P<irp>IRP_MJ_[A-Z_]+)\s*\]\s*=\s*"
    r"(?:&\s*)?(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*[;,]"
)

# Forward-declared completion routines:
#   IO_COMPLETION_ROUTINE MyRoutine;
# Function-pointer typedef matches a single identifier followed by `;`.
_IO_COMPLETION_ROUTINE_RE = re.compile(r"\bIO_COMPLETION_ROUTINE\s+(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*;")

# Sets of IRP major codes mapped to kind. Order in the tuples doesn't
# matter; we just check membership.
_IRP_IOCTL: frozenset[str] = frozenset({"IRP_MJ_DEVICE_CONTROL", "IRP_MJ_INTERNAL_DEVICE_CONTROL"})
_IRP_SYSCALL: frozenset[str] = frozenset(
    {
        "IRP_MJ_CREATE",
        "IRP_MJ_CLOSE",
        "IRP_MJ_READ",
        "IRP_MJ_WRITE",
        "IRP_MJ_CLEANUP",
    }
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
        "x64",
        "x86",
        "Debug",
        "Release",
        "samples",
        "sample",
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


def _iter_c_cpp_files(repo_root: Path) -> list[Path]:
    """Sorted *.c / *.cpp / *.cxx files under repo_root with skip-dirs filtered.

    Windows kernel-mode drivers are predominantly C; some KMDF drivers
    mix in `.cpp` for utility code. We scan both extensions for safety.
    """
    out: list[Path] = []
    for pattern in ("*.c", "*.cpp", "*.cxx"):
        for p in repo_root.rglob(pattern):
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


def _irp_kind(irp: str) -> EntryPointKind:
    """Map an IRP_MJ_* major code to the appropriate EntryPointKind."""
    if irp in _IRP_IOCTL:
        return EntryPointKind.IOCTL_HANDLER
    if irp in _IRP_SYSCALL:
        return EntryPointKind.SYSCALL_HANDLER
    return EntryPointKind.IPC_HANDLER


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Windows kernel driver entry points. Deterministic order.

    Requires `c` or `cpp` in the language list. KMDF allows mixed C/C++
    sources, so either is acceptable.
    """
    if "c" not in languages and "cpp" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_c_cpp_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # ---- DriverEntry → BOOT_PATH -------------------------------------
        for m in _DRIVER_ENTRY_RE.finditer(text):
            # Framework hint: is there a WdfDriverCreate inside this file?
            framework = "kmdf" if _WDF_DRIVER_CREATE_RE.search(text) else "wdm"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol="DriverEntry",
                    type_origin="windows_kernel_driver",
                    metadata={"framework": framework, "role": "load"},
                )
            )

        # ---- MajorFunction[IRP_MJ_*] dispatch → IOCTL/SYSCALL/IPC --------
        for m in _IRP_DISPATCH_RE.finditer(text):
            irp = m.group("irp")
            fn = m.group("fn")
            kind = _irp_kind(irp)
            found.append(
                EntryPoint(
                    kind=kind,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=fn,
                    type_origin="windows_kernel_driver",
                    metadata={"irp": irp},
                )
            )

        # ---- IO_COMPLETION_ROUTINE <sym>; → EVENT_LISTENER --------------
        for m in _IO_COMPLETION_ROUTINE_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="windows_kernel_driver",
                    metadata={"callback": "IO_COMPLETION_ROUTINE"},
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
