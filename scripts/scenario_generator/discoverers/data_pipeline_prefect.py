"""Prefect flow + task discoverer.

Finds Prefect data-pipeline entry points across Python source:

- ``@flow`` / ``@flow(name="foo", ...)`` — decorates a function that is
  a Prefect flow. The flow's name defaults to the function name unless
  ``name=...`` is supplied.
- ``@task`` / ``@task(name="foo", ...)`` — decorates a function that
  is a Prefect task. Like flows, name defaults to the function name.

Both flow and task decorators can also be imported under an alias
(``from prefect import flow as pflow``). To keep the discoverer
predictable we anchor on the literal decorator suffix (``flow`` /
``task``), the most common spelling. ``@<ns>.flow(...)`` and
``@<ns>.task(...)`` are also matched.

Emits one ``EntryPoint`` per decorator with kind ``DAG_TASK``. The
metadata distinguishes flows from tasks via ``kind`` and carries the
explicit ``name`` when supplied (so the walker can show "Prefect flow:
hello_world" rather than just the function name).

Determinism: ``.py`` files are sorted before iteration and the emitted
list is sorted via ``sort_key()`` plus the kind suffix so flow vs task
ordering on the same line is stable.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "data_pipeline_prefect"


# ``@flow`` / ``@flow()`` / ``@flow(name="foo", ...)`` / ``@<ns>.flow(...)``.
# The trailing alternation handles both decorator-with-args and
# bare-decorator forms.
_FLOW_DECORATOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)@(?:[A-Za-z_][A-Za-z0-9_]*\.)?flow(?:\s*\((?P<args>[^)]*)\))?\s*(?:\n|$)",
    re.MULTILINE,
)

# ``@task`` / ``@task()`` / ``@task(name="foo", ...)`` / ``@<ns>.task(...)``.
_TASK_DECORATOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)@(?:[A-Za-z_][A-Za-z0-9_]*\.)?task(?:\s*\((?P<args>[^)]*)\))?\s*(?:\n|$)",
    re.MULTILINE,
)

# Explicit ``name="foo"`` kwarg inside a decorator's argument list.
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — generous for flow modules.


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


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Prefect flows + tasks. Deterministic order."""
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
        # Cheap pre-filter — only files that even mention prefect get
        # the full regex sweep.
        if "prefect" not in text.lower() and "@flow" not in text and "@task" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) Flow decorators.
        for dec in _FLOW_DECORATOR_RE.finditer(text):
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
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=f"flow:{display_name}",
                    type_origin="data_pipeline_prefect",
                    metadata={
                        "kind": "flow",
                        "flow_name": display_name,
                        "function": fn_name,
                        "framework": "prefect",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # 2) Task decorators.
        for dec in _TASK_DECORATOR_RE.finditer(text):
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
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=f"task:{display_name}",
                    type_origin="data_pipeline_prefect",
                    metadata={
                        "kind": "task",
                        "task_name": display_name,
                        "function": fn_name,
                        "framework": "prefect",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind).
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
