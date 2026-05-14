"""Apache Airflow DAG discoverer.

Finds DAG and task definitions used by Apache Airflow data pipelines:

- ``with DAG('id', ...) as dag:`` — context-manager DAG declaration.
- ``DAG('id', ...)`` — direct call form (assignment-style).
- ``@dag(...)`` decorator — TaskFlow-API DAG.
- ``PythonOperator(task_id='foo', ...)`` and any ``*Operator(task_id=...)``
  instantiation — classic operator-based task.
- ``@task`` and ``@task.virtualenv(...)`` / ``@task.docker(...)`` etc. —
  TaskFlow-API task decorators.

Each DAG and each task becomes ONE ``EntryPoint`` with kind
``DAG_TASK``. The discoverer is intentionally permissive about the
binding name (the user may import ``DAG`` as ``DAG`` or alias it) and
about decorator namespacing (``@task`` vs ``@dag.task`` vs
``@airflow.decorators.task``).

Heuristic, not AST-perfect, but deterministic. The text is read with a
preview-byte cap, decoded with ``errors='replace'`` so binary noise
never crashes the scan, and every list is sorted before return so the
golden output is byte-identical across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Filename uses the canonical type name directly, so TYPE_ORIGIN is
# redundant strictly speaking — declared anyway so the dispatcher's
# Rule-2 fallback works if the filename ever changes.
TYPE_ORIGIN = "data_pipeline_airflow"


# ``with DAG(...) as <var>:`` — capture the binding name and (if
# present) the dag_id literal. The dag_id may appear positional
# (``DAG('id', ...)``) or as a keyword (``DAG(dag_id='id', ...)``); we
# extract it post-hoc from the body of the call rather than baking
# both forms into the outer regex.
_WITH_DAG_RE = re.compile(
    r"with\s+DAG\s*\((?P<call_body>.*?)\)\s*as\s+(?P<binding>[A-Za-z_][A-Za-z0-9_]*)\s*:",
    re.DOTALL,
)

# ``<var> = DAG(...)`` — non-context-manager form. Same dag_id
# extraction strategy as the ``with`` form.
_ASSIGN_DAG_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<binding>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*DAG\s*\((?P<call_body>.*?)\)",
    re.MULTILINE | re.DOTALL,
)

# Inside a DAG(...) call: explicit ``dag_id="..."`` keyword.
_DAG_ID_KWARG_RE = re.compile(
    r"dag_id\s*=\s*(?P<quote>['\"])(?P<dag_id>[^'\"]+)(?P=quote)",
)

# Inside a DAG(...) call: first positional string literal — only valid
# if it appears BEFORE any keyword argument.
_DAG_ID_POSITIONAL_RE = re.compile(
    r"^\s*(?P<quote>['\"])(?P<dag_id>[^'\"]+)(?P=quote)",
)

# ``@dag(...)`` TaskFlow decorator — supports both ``@dag`` and
# ``@dag()`` and ``@<ns>.dag(...)``. The decorated function name comes
# from the next ``def`` line.
_DAG_DECORATOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)@(?:[A-Za-z_][A-Za-z0-9_]*\.)?dag\s*(?:\(|\b)",
    re.MULTILINE,
)

# ``<var> = SomethingOperator(task_id='foo', ...)`` — covers PythonOperator,
# BashOperator, KubernetesPodOperator, EmptyOperator, DummyOperator, etc.
# We require the class name to end in ``Operator`` to avoid spurious
# matches; ``task_id`` may appear anywhere in the kwargs blob.
_OPERATOR_RE = re.compile(
    r"(?P<klass>[A-Za-z_][A-Za-z0-9_]*Operator)\s*\(",
)

# ``task_id=...`` kwarg inside an operator call. We match the FIRST
# occurrence after the operator opens its paren — operator
# instantiations always pass ``task_id`` early in the argument list.
_TASK_ID_KWARG_RE = re.compile(
    r"task_id\s*=\s*(?P<quote>['\"])(?P<task_id>[^'\"]+)(?P=quote)",
)

# ``@task`` and ``@task(...)`` and ``@task.virtualenv(...)`` and
# ``@task.docker(...)`` and ``@<ns>.task(...)`` — TaskFlow-API task
# decorator. The decorated function name comes from the next ``def``.
_TASK_DECORATOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)@(?:[A-Za-z_][A-Za-z0-9_]*\.)?task(?:\.[A-Za-z_][A-Za-z0-9_]*)?\s*(?:\(|\n|$)",
    re.MULTILINE,
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — generous for DAG modules.


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of ``path``. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of ``offset`` within ``text``."""
    return text.count("\n", 0, offset) + 1


def _extract_dag_id(call_body: str) -> str:
    """Extract the ``dag_id`` from a DAG(...) call body.

    Prefers the explicit ``dag_id=...`` keyword form; falls back to the
    first positional string literal. Returns ``''`` when no id can be
    located so the caller can decide whether to emit an entry point
    keyed on the binding instead.
    """
    kw = _DAG_ID_KWARG_RE.search(call_body)
    if kw is not None:
        return kw.group("dag_id")
    pos = _DAG_ID_POSITIONAL_RE.match(call_body)
    if pos is not None:
        return pos.group("dag_id")
    return ""


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


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Airflow DAG + task entry points. Deterministic order."""
    if "python" not in languages:
        return []
    repo_root = repo_root.resolve()

    # Collect Python files inside repo_root, honouring skip-dirs against
    # the RELATIVE parts (so fixtures under tests/fixtures/... aren't
    # accidentally skipped because their absolute path contains
    # 'tests').
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
        # Cheap pre-filter: only files that even mention airflow.
        low = text.lower()
        if "airflow" not in low and "@dag" not in text and "@task" not in text and "operator(" not in low:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) ``with DAG(...) as <binding>:`` form.
        for m in _WITH_DAG_RE.finditer(text):
            call_body = m.group("call_body")
            dag_id = _extract_dag_id(call_body)
            binding = m.group("binding")
            line = _line_of(text, m.start())
            symbol = f"dag:{dag_id}" if dag_id else f"dag:{binding}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="data_pipeline_airflow",
                    metadata={
                        "kind": "dag",
                        "dag_id": dag_id or binding,
                        "binding": binding,
                        "framework": "airflow",
                        "form": "context_manager",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) ``<var> = DAG(...)`` assignment form.
        for m in _ASSIGN_DAG_RE.finditer(text):
            call_body = m.group("call_body")
            dag_id = _extract_dag_id(call_body)
            binding = m.group("binding")
            line = _line_of(text, m.start())
            symbol = f"dag:{dag_id}" if dag_id else f"dag:{binding}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="data_pipeline_airflow",
                    metadata={
                        "kind": "dag",
                        "dag_id": dag_id or binding,
                        "binding": binding,
                        "framework": "airflow",
                        "form": "assignment",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 3) ``@dag(...)`` TaskFlow-API decorator. We must NOT match
        # ``@task`` / ``@task.foo`` here — the regex above only fires on
        # the literal ``dag`` suffix.
        for dec in _DAG_DECORATOR_RE.finditer(text):
            def_match = _DEF_RE.search(text, dec.end())
            if def_match is None:
                continue
            between = text[dec.end() : def_match.start()]
            if between.count("\n") > 12:
                continue
            symbol = def_match.group("name")
            line = _line_of(text, dec.start())
            docstring = _docstring_after_def(text, def_match)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=f"dag:{symbol}",
                    type_origin="data_pipeline_airflow",
                    metadata={
                        "kind": "dag",
                        "dag_id": symbol,
                        "framework": "airflow",
                        "form": "decorator",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # 4) ``SomeOperator(task_id='foo', ...)`` classic operator form.
        # The operator name and task_id pair into one DAG_TASK.
        for op in _OPERATOR_RE.finditer(text):
            klass = op.group("klass")
            # Look for ``task_id=...`` within the next 1024 chars.
            tail = text[op.end() : op.end() + 1024]
            tk = _TASK_ID_KWARG_RE.search(tail)
            if tk is None:
                continue
            task_id = tk.group("task_id")
            line = _line_of(text, op.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=f"task:{task_id}",
                    type_origin="data_pipeline_airflow",
                    metadata={
                        "kind": "task",
                        "task_id": task_id,
                        "operator": klass,
                        "framework": "airflow",
                        "form": "operator",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 5) ``@task`` / ``@task.virtualenv(...)`` etc. TaskFlow tasks.
        # We must not double-match ``@dag`` here (different regex).
        for dec in _TASK_DECORATOR_RE.finditer(text):
            def_match = _DEF_RE.search(text, dec.end())
            if def_match is None:
                continue
            between = text[dec.end() : def_match.start()]
            if between.count("\n") > 12:
                continue
            symbol = def_match.group("name")
            line = _line_of(text, dec.start())
            docstring = _docstring_after_def(text, def_match)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.DAG_TASK,
                    file=rel,
                    line=line,
                    symbol=f"task:{symbol}",
                    type_origin="data_pipeline_airflow",
                    metadata={
                        "kind": "task",
                        "task_id": symbol,
                        "framework": "airflow",
                        "form": "decorator",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, metadata.kind) — same file+line can
    # legitimately host both a DAG and a task only across distinct
    # symbols, so include the symbol in the key.
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
