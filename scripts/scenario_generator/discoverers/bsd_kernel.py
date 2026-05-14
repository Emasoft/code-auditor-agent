"""FreeBSD / OpenBSD kernel discoverer.

Finds canonical entry points in BSD kernel modules and kernel-tree
sources. The fingerprint matches files under `sys/kern/**` or
`sys/dev/**` with at least one of `MOD_LOAD` / `DEVMETHOD` /
`DECLARE_MODULE` present.

Entry-point kinds emitted:

- `DECLARE_MODULE(<name>, <data>, <subsystem>, <order>)` →
  MODULE_INIT — the canonical FreeBSD module-registration macro.
  Symbol is the first argument (module name).
- `DEV_MODULE(<name>, <evh>, <arg>)` → MODULE_INIT — the convenience
  wrapper used by character-device drivers. Symbol is the first arg.
- `MODULE_DEPEND(<mod>, <dep>, <vmin>, <vpref>, <vmax>)` →
  IPC_HANDLER — declares a runtime dependency on another module.
  Symbol is `<mod>__depends_on__<dep>` so the scenario IDs stay
  unique even when multiple deps are declared on the same module.
- `SYSCTL_PROC(...)` / `SYSCTL_INT(...)` / `SYSCTL_LONG(...)` /
  `SYSCTL_UINT(...)` → SYSCALL_HANDLER — sysctl tree entries are the
  BSD equivalent of a userspace-reachable kernel knob; the walker
  reasons about them as syscall-shaped surfaces. Symbol is the
  sysctl OID name (3rd argument).
- `MODULE_VERSION(<mod>, <vnum>)` → MODULE_INIT marker with
  `metadata.macro=MODULE_VERSION`.

Output is sorted by `(file, line, symbol, kind)`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regex contracts
# ---------------------------------------------------------------------------

# DECLARE_MODULE(name, data, subsystem, order); — FreeBSD canonical module
# declaration. `data` is typically a `moduledata_t` struct; we don't
# parse it. Captured: module name.
_DECLARE_MODULE_RE = re.compile(r"\bDECLARE_MODULE\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*,")

# DEV_MODULE(name, evh, arg); — character-device wrapper macro.
_DEV_MODULE_RE = re.compile(r"\bDEV_MODULE\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*,")

# MODULE_DEPEND(mod, dep, vmin, vpref, vmax);
_MODULE_DEPEND_RE = re.compile(
    r"\bMODULE_DEPEND\s*\(\s*(?P<mod>[A-Za-z_][A-Za-z0-9_]*)\s*,"
    r"\s*(?P<dep>[A-Za-z_][A-Za-z0-9_]*)\s*,"
)

# MODULE_VERSION(mod, vnum);
_MODULE_VERSION_RE = re.compile(r"\bMODULE_VERSION\s*\(\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*,")

# SYSCTL_<TYPE>(parent, nbr, name, access, ...) — the 3rd positional
# argument is the OID symbol. We accept any uppercase ASCII suffix.
_SYSCTL_RE = re.compile(
    r"\bSYSCTL_(?P<type>[A-Z_]+)\s*\(\s*"
    r"[^,]+,\s*[^,]+,\s*(?P<sym>[A-Za-z_][A-Za-z0-9_]*)\s*,"
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
        "obj",
        "compile",
        "doc",
        "docs",
        "share",
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


def _iter_c_files(repo_root: Path) -> list[Path]:
    """Sorted *.c files under repo_root with skip-dirs filtered.

    Skip-dir filtering is RELATIVE to repo_root — fixtures under
    `tests/fixtures/...` are scanned even though `tests` would be in
    other discoverers' skip sets.
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
    """Find FreeBSD/OpenBSD kernel entry points. Deterministic order.

    Requires `c` in the language list — BSD kernels are C-only at the
    granularity we care about here.
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

        # ---- DECLARE_MODULE(<sym>, ...) → MODULE_INIT --------------------
        for m in _DECLARE_MODULE_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="bsd_kernel",
                    metadata={"macro": "DECLARE_MODULE"},
                )
            )

        # ---- DEV_MODULE(<sym>, ...) → MODULE_INIT ------------------------
        for m in _DEV_MODULE_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="bsd_kernel",
                    metadata={"macro": "DEV_MODULE"},
                )
            )

        # ---- MODULE_DEPEND(<mod>, <dep>, ...) → IPC_HANDLER --------------
        for m in _MODULE_DEPEND_RE.finditer(text):
            mod = m.group("mod")
            dep = m.group("dep")
            sym = f"{mod}__depends_on__{dep}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.IPC_HANDLER,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="bsd_kernel",
                    metadata={"macro": "MODULE_DEPEND", "module": mod, "depends_on": dep},
                )
            )

        # ---- MODULE_VERSION(<sym>, ...) → MODULE_INIT (version marker) ---
        for m in _MODULE_VERSION_RE.finditer(text):
            sym = m.group("sym")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="bsd_kernel",
                    metadata={"macro": "MODULE_VERSION"},
                )
            )

        # ---- SYSCTL_<TYPE>(parent, nbr, <sym>, ...) → SYSCALL_HANDLER ---
        for m in _SYSCTL_RE.finditer(text):
            sym = m.group("sym")
            sysctl_type = m.group("type")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.SYSCALL_HANDLER,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=sym,
                    type_origin="bsd_kernel",
                    metadata={"macro": f"SYSCTL_{sysctl_type}"},
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
