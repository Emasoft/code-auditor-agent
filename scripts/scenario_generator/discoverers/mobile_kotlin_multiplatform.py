"""Kotlin Multiplatform Mobile (KMM) discoverer.

Finds entry points in KMM projects for the `mobile_kotlin_multiplatform`
software type. The relevant surface area for cross-platform mobile is
the SHARED contract — declarations in `commonMain` source sets that
each platform must `actual`-implement. Two element shapes are
recognised:

- `expect fun <name>(...): <type>` — a top-level shared function
  declaration. Each platform (`androidMain`, `iosMain`, `jvmMain`, ...)
  must provide an `actual fun <name>(...)` body. Emitted as
  LIBRARY_EXPORT with metadata `{element: "expect_fun"}`.
- `expect class <Name>(...) { ... }` — a top-level shared class
  declaration. Each platform must provide an `actual class <Name>` body.
  Emitted as LIBRARY_EXPORT with metadata `{element: "expect_class"}`.

These are the cross-platform LIBRARY contracts the walker should
trace — every scenario "what if iOS implements it one way and Android
another?" hinges on the shape declared at the `expect` site.

Only `commonMain` sources are scanned. `actual` definitions live in
`androidMain` / `iosMain` / `jvmMain` and are platform-specific; the
walker resolves them when needed but they are not entry points in the
shared-API sense.

Regex-based, deterministic. The shape is well-defined enough that AST
would be overkill — and `kotlin-ast` is not a stdlib module.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match `expect fun <name>(...)` at top level. Allow leading modifiers
# (`internal`, `public`, none) and require column 0 so we don't match
# member functions inside an expect class body.
_EXPECT_FUN_RE = re.compile(
    r"^\s*(?:internal\s+|public\s+|private\s+)?expect\s+fun\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)

# Match `expect class <Name>` at top level. Same modifier handling.
_EXPECT_CLASS_RE = re.compile(
    r"^\s*(?:internal\s+|public\s+|private\s+)?expect\s+class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".gradle",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "out",
        "bin",
        "obj",
        ".cache",
        "node_modules",
        "vendor",
        "__pycache__",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "examples_dev",
        "samples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Kotlin source files rarely exceed this


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES bytes, UTF-8 with replace."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dir check against RELATIVE parts only.

    Same reasoning as every other discoverer — checking absolute parts
    would mis-skip fixtures under `tests/fixtures/...`.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _is_common_main(path: Path, repo_root: Path) -> bool:
    """Return True iff `path` lives under any `commonMain` source set.

    The KMM convention is `<module>/src/commonMain/kotlin/...` — we
    check for `commonMain` anywhere in the path-from-repo-root, which
    also catches non-standard layouts that respect the source-set name.
    """
    try:
        rel_parts = path.relative_to(repo_root).parts
    except ValueError:
        return False
    return "commonMain" in rel_parts


def _iter_kotlin_files(repo_root: Path) -> list[Path]:
    """Sorted list of .kt files inside `commonMain` source sets."""
    out: list[Path] = []
    for p in repo_root.rglob("*.kt"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        if not _is_common_main(p, repo_root):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find KMM shared (expect) declarations.

    `languages` is advisory — the detector gated dispatch via the KMM
    fingerprint (`kotlin-multiplatform` in build.gradle.kts). We run
    on `commonMain/*.kt` regardless of the language list.
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_kotlin_files(repo_root):
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter — skip files with no `expect ` keyword.
        if "expect " not in text:
            continue
        rel = str(path.relative_to(repo_root))

        for m in _EXPECT_FUN_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="mobile_kotlin_multiplatform",
                    metadata={
                        "element": "expect_fun",
                        "source_set": "commonMain",
                        "language": "kotlin",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        for m in _EXPECT_CLASS_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="mobile_kotlin_multiplatform",
                    metadata={
                        "element": "expect_class",
                        "source_set": "commonMain",
                        "language": "kotlin",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind, element) — same name as both
    # a fun and a class is unusual but technically legal in different
    # files, so include the element in the dedup key.
    seen: set[tuple[str, int, str, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        element = str(ep.metadata.get("element", ""))
        key = (ep.file, ep.line, ep.symbol, ep.kind.value, element)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(key=lambda e: (e.sort_key(), e.kind.value, str(e.metadata.get("element", ""))))
    return unique
