"""Database-engine discoverer.

Selective discoverer for the `database_engine` software type. Targets
the surface that an embedded DB / KV store / SQLite extension /
custom database engine typically exposes:

1. **Query executor entry points** — `query_execute` and its variants
   in C, Rust, or Cpp. Mapped to DB_QUERY_HANDLER.

2. **Storage engine callbacks** — `btree_insert`, `btree_split`,
   `page_alloc`, `page_release`, `wal_append`, `wal_replay`,
   `commit_record`. Each is a sensitive write path the walker must
   reason about under partial-failure scenarios. Mapped to
   LIBRARY_EXPORT (the storage layer is "linkable infrastructure"
   from the walker's perspective).

3. **Transaction APIs** — `mvcc_begin`, `mvcc_commit`, `mvcc_abort`,
   `tx_begin`, `tx_commit`, `tx_abort`. Mapped to DB_QUERY_HANDLER
   (they are query-level state mutators).

`type_origin` is hard-coded to `"database_engine"`. Output is sorted
by (file, line, symbol) with a metadata category tiebreaker.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regexes. We tightly enumerate the recognised function-name prefixes so
# the discoverer does NOT claim every utility helper in the codebase. The
# names listed here are the conventional storage-engine API surface; the
# discoverer reports each occurrence regardless of access modifier.
# ---------------------------------------------------------------------------

# Names that map to DB_QUERY_HANDLER (query layer + transaction state).
_QUERY_NAMES: frozenset[str] = frozenset(
    {
        "query_execute",
        "query_exec",
        "query_prepare",
        "query_step",
        "query_finalize",
        "mvcc_begin",
        "mvcc_commit",
        "mvcc_abort",
        "tx_begin",
        "tx_commit",
        "tx_abort",
    }
)

# Names that map to LIBRARY_EXPORT (storage layer building blocks).
_STORAGE_NAMES: frozenset[str] = frozenset(
    {
        "btree_insert",
        "btree_delete",
        "btree_split",
        "btree_search",
        "btree_lookup",
        "btree_merge",
        "page_alloc",
        "page_release",
        "page_free",
        "page_get",
        "page_put",
        "wal_append",
        "wal_replay",
        "wal_truncate",
        "wal_checkpoint",
        "commit_record",
        "checkpoint",
    }
)


def _names_pattern(names: frozenset[str]) -> str:
    """Build a name-alternation regex chunk from a frozenset.

    Names are sorted so the generated regex is deterministic — different
    Python versions hash frozensets differently, but alphabetic sort
    pins the alternation order.
    """
    return "|".join(re.escape(n) for n in sorted(names))


_QUERY_PAT = _names_pattern(_QUERY_NAMES)
_STORAGE_PAT = _names_pattern(_STORAGE_NAMES)
_ALL_PAT = _names_pattern(_QUERY_NAMES | _STORAGE_NAMES)


# Python: `def <name>(` at module scope (or method-level — for an
# embedded engine the access pattern is less restrictive).
_PY_DB_FN_RE = re.compile(
    rf"^\s*(?:async\s+)?def\s+(?P<name>{_ALL_PAT})\s*\(",
    re.MULTILINE,
)

# Rust: `fn <name>(` with optional `pub` and qualifiers.
_RUST_DB_FN_RE = re.compile(
    rf"^\s*(?:pub\s+(?:\([^)]*\)\s+)?)?(?:async\s+|unsafe\s+|const\s+|extern\s+(?:\"[^\"]+\"\s+)?)*"
    rf"fn\s+(?P<name>{_ALL_PAT})\s*\(",
    re.MULTILINE,
)

# C: `<return_type> <name>(` — return-type tokens are any sequence of
# identifier characters, struct/keyword tokens, pointers, and
# whitespace. The function name is the load-bearing match. The `\s*`
# before the name (rather than `\s+`) tolerates `struct page *foo(` —
# i.e. a pointer-glued name with no whitespace between `*` and the
# function identifier.
_C_DB_FN_RE = re.compile(
    rf"^[A-Za-z_][\*\sA-Za-z0-9_]*?[\s\*](?P<name>{_ALL_PAT})\s*\(",
    re.MULTILINE,
)

# C++: same shape as C but namespaced names (`db::storage::page_alloc`)
# are common — we accept the bare name after the last `::`.
_CPP_DB_FN_RE = re.compile(
    rf"^[A-Za-z_][\*\sA-Za-z0-9_:]*?\s+(?:[A-Za-z_][A-Za-z0-9_]*::)*(?P<name>{_ALL_PAT})\s*\(",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        "node_modules",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "benches",
        "bench",
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
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path`. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True if any DIRECTORY component (relative to repo_root) is skipped."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])


def _iter_files(repo_root: Path, ext_globs: tuple[str, ...]) -> list[Path]:
    """Return a deterministic sorted list of files matching any of the globs."""
    seen: set[Path] = set()
    for glob in ext_globs:
        for p in repo_root.rglob(glob):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            seen.add(p)
    return sorted(seen)


def _classify(name: str) -> tuple[EntryPointKind, str]:
    """Classify a name into (kind, category)."""
    if name in _QUERY_NAMES:
        # query_execute / tx_*, mvcc_* → DB_QUERY_HANDLER.
        if name.startswith("tx_") or name.startswith("mvcc_"):
            return (EntryPointKind.DB_QUERY_HANDLER, "transaction")
        return (EntryPointKind.DB_QUERY_HANDLER, "query")
    # btree_*/page_*/wal_*/commit_*/checkpoint → LIBRARY_EXPORT (storage).
    if name.startswith("btree_"):
        return (EntryPointKind.LIBRARY_EXPORT, "btree")
    if name.startswith("page_"):
        return (EntryPointKind.LIBRARY_EXPORT, "page")
    if name.startswith("wal_"):
        return (EntryPointKind.LIBRARY_EXPORT, "wal")
    return (EntryPointKind.LIBRARY_EXPORT, "storage")


def _emit(
    rel: str,
    text: str,
    pattern: re.Pattern[str],
    language: str,
    out: list[EntryPoint],
) -> None:
    """Run `pattern` over `text` and append EntryPoint records to `out`."""
    for m in pattern.finditer(text):
        name = m.group("name")
        line = _line_of(text, m.start())
        kind, category = _classify(name)
        out.append(
            EntryPoint(
                kind=kind,
                file=rel,
                line=line,
                symbol=name,
                type_origin="database_engine",
                metadata={
                    "language": language,
                    "category": category,
                },
            )
        )


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find database-engine entry points. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # ---- Python ------------------------------------------------------------
    if "python" in languages:
        for path in _iter_files(repo_root, ("*.py",)):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _PY_DB_FN_RE, "python", found)

    # ---- Rust --------------------------------------------------------------
    if "rust" in languages:
        for path in _iter_files(repo_root, ("*.rs",)):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _RUST_DB_FN_RE, "rust", found)

    # ---- C -----------------------------------------------------------------
    if "c" in languages:
        for path in _iter_files(repo_root, ("*.c",)):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _C_DB_FN_RE, "c", found)

    # ---- C++ ---------------------------------------------------------------
    if "cpp" in languages:
        for path in _iter_files(repo_root, ("*.cpp", "*.cc", "*.cxx")):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _CPP_DB_FN_RE, "cpp", found)

    # Dedup by (file, line, symbol) and sort deterministically.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("category", "")), e.kind.value))
    return unique
