"""Dagster asset/op/graph/job discoverer.

Finds Dagster data-pipeline entry points across Python source. Dagster
exposes four primary decorators that each represent a distinct unit of
pipeline work:

- ``@asset`` / ``@asset(...)`` — declarative table-like outputs. The
  most common Dagster idiom for new pipelines.
- ``@op``    / ``@op(...)``    — imperative computation units (the
  predecessor of ``@asset``; still common in legacy code).
- ``@graph`` / ``@graph(...)`` — composes multiple ops into one
  reusable subgraph.
- ``@job``   / ``@job(...)``   — top-level executable workflow.

Each decorator becomes ONE ``DAG_TASK`` ``EntryPoint``; the metadata's
``kind`` field captures which decorator produced it so downstream
families (and the scenario generator's title templates) can target
asset-specific or job-specific failure modes if desired.

The discoverer also handles namespaced decorators
(``@dg.asset(...)`` / ``@dagster.op(...)``) by allowing an optional
``<binding>.`` prefix on the decorator regex.

Determinism: ``.py`` files are sorted before iteration and the emitted
list is sorted via ``sort_key()`` plus a kind suffix so order is
stable across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "data_pipeline_dagster"


# A single regex captures all four decorator flavours. ``kind`` is the
# named group that distinguishes asset vs op vs graph vs job. The
# optional ``args`` group catches any keyword arguments inside ``(...)``.
_DAGSTER_DECORATOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)@(?:[A-Za-z_][A-Za-z0-9_]*\.)?"
    r"(?P<kind>asset|op|graph|job)"
    r"(?:\s*\((?P<args>[^)]*)\))?\s*(?:\n|$)",
    re.MULTILINE,
)

# Explicit ``name="..."`` kwarg inside the decorator's argument list.
_NAME_KWARG_RE = re.compile(
    r"name\s*=\s*(?P<quote>['\"])(?P<name>[^'\"]+)(?P=quote)",
)

_DEF_RE = re.compile(r"^[ \t]*(?:async\s+)?def\s+(?P<name>\w+)\s*\(", re.MULTILINE)
_DOCSTRING_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        "tests",
        "test",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — generous for Dagster modules.


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of ``path``. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of ``offset`` within ``text``."""
    return text.count("\n", 0, offset) + 1


def _docstring_after_def(text: str, def_match: re.Match[str]) -> str:
    """Extract the docstring directly following a ``def ...:`` line, if any."""
    rest = text[def_match.end() :]
    m = _DOCSTRING_RE.search(rest)
    if not m:
        return ""
    if m.start() > 600:
        return ""
    body = m.group(1) or m.group(2) or ""
    for ln in body.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _extract_name(args_blob: str | None) -> str:
    """Pull ``name="..."`` from a decorator argument string, if present."""
    if not args_blob:
        return ""
    m = _NAME_KWARG_RE.search(args_blob)
    if m is None:
        return ""
    return m.group("name")


# Symbol-prefix per kind — keeps downstream titles unambiguous (an
# ``asset:my_table`` is read very differently from a ``job:my_table``).
_KIND_PREFIX: dict[str, str] = {
    "asset": "asset",
    "op": "op",
    "graph": "graph",
    "job": "job",
}


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Dagster entry points. Deterministic order."""
    if "python" not in languages:
        return []
    repo_root = repo_root.resolve()

    py_files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if p.is_file():
            py_files.append(p)
    py_files.sort()

    found: list[EntryPoint] = []

    for path in py_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter — only files that mention dagster or any of
        # the decorator names get the full regex sweep. Note that
        # bare ``@op`` / ``@job`` are common in other contexts too, so
        # we require ``dagster`` to appear somewhere in the file to
        # avoid spurious matches across the rest of the repo.
        low = text.lower()
        if "dagster" not in low:
            continue
        rel = str(path.relative_to(repo_root))

        for dec in _DAGSTER_DECORATOR_RE.finditer(text):
            kind = dec.group("kind")
            def_match = _DEF_RE.search(text, dec.end())
            if def_match is None:
                continue
            between = text[dec.end() : def_match.start()]
            if between.count("\n") > 12:
                continue
            fn_name = def_match.group("name")
            explicit_name = _extract_name(dec.group("args"))
            display_name = explicit_name or fn_name
            line = _line_of(text, dec.start())
            docstring = _docstring_after_def(text, def_match)
            prefix = _KIND_PREFIX[kind]
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=f"{prefix}:{display_name}",
                    type_origin="data_pipeline_dagster",
                    metadata={
                        "kind": kind,
                        "name": display_name,
                        "function": fn_name,
                        "framework": "dagster",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind). Same file+line legitimately
    # has only one decorator anchor in practice, but a stacked
    # ``@asset`` + ``@op`` would collide on (file, line) so kind goes
    # into the key.
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, str(ep.metadata.get("kind", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("kind", ""))))
    return unique
