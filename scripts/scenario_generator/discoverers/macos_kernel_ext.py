"""macOS kernel extension (KEXT) discoverer.

Finds canonical entry points in macOS kernel extensions — IOKit-based
C++ drivers. The fingerprint matches an `Info.plist` somewhere under a
`*.kext/` bundle plus C++ sources using `IOService` or
`OSDeclareDefaultStructors`.

Entry-point kinds emitted:

- `OSDefineMetaClassAndStructors(<Class>, IOService)` → MODULE_INIT —
  the canonical class registration; this is what the kernel loads when
  the kext is matched against an IOKit personality.
- `OSDeclareDefaultStructors(<Class>)` declarations → MODULE_INIT
  (header-side mirror).
- `bool <Class>::init(...)` definitions → MODULE_INIT
- `bool <Class>::start(IOService *provider)` definitions → BOOT_PATH —
  the IOKit equivalent of "driver came up against this provider".
- `void <Class>::stop(IOService *provider)` definitions → MODULE_EXIT
- `bool <Class>::free(...)` definitions → MODULE_EXIT
- `IOReturn <Class>::message(UInt32 type, IOService *provider, ...)`
  definitions → EVENT_LISTENER — IOKit's event-callback for messages
  from provider services.

`metadata.class` carries the IOService subclass name; `metadata.method`
carries the method name verbatim. Output is sorted by
`(file, line, symbol, kind)`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regex contracts
# ---------------------------------------------------------------------------

# OSDefineMetaClassAndStructors(<Class>, <Super>);
_OS_DEFINE_RE = re.compile(
    r"\bOSDefineMetaClassAndStructors\s*\(\s*(?P<cls>[A-Za-z_][A-Za-z0-9_]*)\s*,"
    r"\s*(?P<super>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)

# OSDeclareDefaultStructors(<Class>); — header-side mirror.
_OS_DECLARE_RE = re.compile(r"\bOSDeclareDefaultStructors\s*\(\s*(?P<cls>[A-Za-z_][A-Za-z0-9_]*)\s*\)")

# IOService method definitions. Match the SIGNATURE that defines the
# method on a class (not a forward declaration in a header). We accept
# any return type, any qualifiers (`virtual`/`override`/...), and any
# parameter list. The trailing `{` proves it's a definition.
#
# Each method pattern captures (cls, method) explicitly and is paired
# with its own EntryPointKind / metadata in `discover()`.


def _method_regex(method: str) -> re.Pattern[str]:
    """Build the per-method definition regex.

    Done as a function rather than `.format()` because the regex body
    contains literal `{1,6}` and `{` repetition / brace tokens that
    would otherwise need to be escaped — clearer to interpolate
    `method` via f-string where it's a plain identifier.
    """
    return re.compile(
        rf"\b(?P<cls>[A-Za-z_][A-Za-z0-9_]*)\s*::\s*(?P<method>{method})\s*\([^)]*\)"
        r"(?:\s*(?:const|override|noexcept|throw\s*\([^)]*\)))*"
        r"\s*\{"
    )


_METHOD_INIT_RE = _method_regex("init")
_METHOD_START_RE = _method_regex("start")
_METHOD_STOP_RE = _method_regex("stop")
_METHOD_FREE_RE = _method_regex("free")
_METHOD_MESSAGE_RE = _method_regex("message")


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
        "DerivedData",
        "build",
        "Build",
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


def _iter_sources(repo_root: Path) -> list[Path]:
    """Sorted *.cpp / *.cxx / *.cc / *.mm / *.h / *.hpp files under repo_root.

    KEXTs are C++ with Objective-C++ glue allowed; declarations live in
    headers and definitions in implementation files. We scan both so
    the OSDeclareDefaultStructors lookups in headers are included.

    Skip-dir filtering is RELATIVE to repo_root — fixtures under
    `tests/fixtures/...` are scanned even though `tests` would be in
    other discoverers' skip sets.
    """
    out: list[Path] = []
    for pattern in ("*.cpp", "*.cxx", "*.cc", "*.mm", "*.h", "*.hpp"):
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


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find macOS KEXT entry points. Deterministic order.

    Requires `cpp` or `c` in the language list — KEXTs are usually C++
    but the public headers may be C-callable.
    """
    if "cpp" not in languages and "c" not in languages and "objc" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_sources(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # ---- OSDefineMetaClassAndStructors → MODULE_INIT -----------------
        for m in _OS_DEFINE_RE.finditer(text):
            cls = m.group("cls")
            super_cls = m.group("super")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=cls,
                    type_origin="macos_kernel_ext",
                    metadata={
                        "macro": "OSDefineMetaClassAndStructors",
                        "class": cls,
                        "super": super_cls,
                    },
                )
            )

        # ---- OSDeclareDefaultStructors (header-side) → MODULE_INIT -------
        for m in _OS_DECLARE_RE.finditer(text):
            cls = m.group("cls")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MODULE_INIT,
                    file=rel,
                    line=_line_of(text, m.start()),
                    symbol=cls,
                    type_origin="macos_kernel_ext",
                    metadata={"macro": "OSDeclareDefaultStructors", "class": cls},
                )
            )

        # ---- <Class>::init / start / stop / free / message ---------------
        # Order matters only for symbol disambiguation when methods land
        # on the same line (they don't in idiomatic IOKit code).
        for regex, kind, method in (
            (_METHOD_INIT_RE, EntryPointKind.MODULE_INIT, "init"),
            (_METHOD_START_RE, EntryPointKind.BOOT_PATH, "start"),
            (_METHOD_STOP_RE, EntryPointKind.MODULE_EXIT, "stop"),
            (_METHOD_FREE_RE, EntryPointKind.MODULE_EXIT, "free"),
            (_METHOD_MESSAGE_RE, EntryPointKind.EVENT_LISTENER, "message"),
        ):
            for m in regex.finditer(text):
                cls = m.group("cls")
                # The symbol is `<Class>::<method>` so two classes that
                # both define ::start in the same file remain distinct.
                sym = f"{cls}::{method}"
                found.append(
                    EntryPoint(
                        kind=kind,
                        file=rel,
                        line=_line_of(text, m.start()),
                        symbol=sym,
                        type_origin="macos_kernel_ext",
                        metadata={"class": cls, "method": method},
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
