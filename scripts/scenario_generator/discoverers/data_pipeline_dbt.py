"""dbt (data-build-tool) model discoverer.

Finds dbt transformations defined in a dbt project. The unit of work
in dbt is the *model* — one ``.sql`` file under ``models/`` represents
one SELECT statement that materializes a table, view, or incremental
load.

We emit one ``DAG_TASK`` entry point per ``.sql`` file found under any
``models/`` directory (most repos use a single top-level ``models/``,
but nested project layouts and packages mirror the same convention so
the recursive search is the right primitive).

For each model, the discoverer:

- Picks the file's relative path and the SQL file's first non-blank line
  as the discovery anchor.
- Pulls ``intended_behaviour_sources`` from a sibling ``schema.yml`` if
  one exists in the same directory and mentions the model by name —
  schema.yml is dbt's canonical place for model documentation.
- Pulls the docstring from the first ``-- comment`` block at the top
  of the .sql file when present.

dbt projects also typically contain seed (``.csv``), test (``.sql``
under ``tests/``), macro (``.sql`` under ``macros/``), and snapshot
files. None of those are *models* — the dispatcher's scenario set is
tuned to model-level concerns, so we deliberately scope to ``models/``
only.

Determinism: ``.sql`` files are sorted lexicographically before
iteration, and the emitted list is sorted on ``sort_key()`` before
return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "data_pipeline_dbt"


# Models live under any directory named ``models`` in the project tree.
_MODELS_DIRNAME = "models"

# Match a single ``model:`` block inside a schema.yml — captures the
# model name and the body (which contains ``description:`` etc.). dbt
# schema.yml uses YAML; we deliberately use regex rather than pulling a
# yaml dependency. The pattern is permissive about indentation and
# stops at the next ``- name:`` line OR end-of-string.
#
# We greedy-match the body and rely on a positive lookahead on the
# stop-marker to keep boundaries correct. Non-greedy quantifiers
# combined with the lookahead caused the previous version to stop after
# the first description line, missing every model past the first one.
_SCHEMA_MODEL_RE = re.compile(
    r"-\s*name:\s*(?P<name>[A-Za-z0-9_]+)\s*\n"
    r"(?P<body>(?:(?!\s*-\s*name:).*\n)*)",
)

# ``description:`` line inside a model block. dbt allows both inline
# (``description: foo``) and block scalars (``description: |``) — we
# only extract the single-line form which is by far the common case.
_SCHEMA_DESCRIPTION_RE = re.compile(
    r"^[ \t]+description:\s*(?P<desc>.+?)\s*$",
    re.MULTILINE,
)

# Leading ``-- ...`` comment lines at the top of a model file. dbt
# convention is to put a one-line description in a leading comment;
# anything more elaborate goes to schema.yml.
_LEADING_SQL_COMMENT_RE = re.compile(r"^\s*--\s*(?P<text>.+?)\s*$", re.MULTILINE)


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
        "target",  # dbt's compiled-output dir — never a source model
        "dbt_packages",  # vendored dbt packages
        "logs",
        "tests",
        "test",
        "snapshots",
        "macros",
        "seeds",
        "analyses",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
        "samples_dev",
        "examples_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — generous for SQL models.


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of ``path``. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _first_anchor_line(text: str) -> int:
    """1-indexed line of the first non-blank, non-comment-only line.

    Returns 1 when the file is empty or fully blank — we still want a
    sensible default for the EntryPoint.line field, which is part of
    the sort key.
    """
    for i, ln in enumerate(text.splitlines(), start=1):
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith("--"):
            continue
        return i
    return 1


def _parse_schema_descriptions(schema_path: Path) -> dict[str, str]:
    """Return a mapping of ``model_name -> first description line``.

    Returns ``{}`` when the schema file doesn't exist or can't be read.
    """
    if not schema_path.is_file():
        return {}
    text = _read(schema_path)
    if not text:
        return {}
    descriptions: dict[str, str] = {}
    for m in _SCHEMA_MODEL_RE.finditer(text):
        name = m.group("name")
        body = m.group("body")
        desc_match = _SCHEMA_DESCRIPTION_RE.search(body)
        if desc_match is None:
            continue
        # Strip optional surrounding quotes that YAML accepts as a
        # plain scalar.
        desc = desc_match.group("desc").strip().strip("\"'")
        if desc:
            descriptions[name] = desc
    return descriptions


def _leading_comment(text: str) -> str:
    """Return the first non-blank ``-- ...`` comment line at file top.

    The walk stops at the first non-comment, non-blank line — once the
    SQL starts, we no longer treat comments as documentation.
    """
    for ln in text.splitlines():
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith("--"):
            m = _LEADING_SQL_COMMENT_RE.match(ln)
            if m is not None:
                return m.group("text")
        return ""
    return ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find dbt models. Deterministic order.

    Language list is consulted as a sanity check — dbt projects always
    have ``.sql`` files but the language detector reports them under
    ``sql`` (when extensions are registered) or simply not at all (when
    the language list is empty). We do NOT gate on language presence —
    a dbt project is fully detected by its ``dbt_project.yml`` plus
    ``models/`` tree, and the type detector already enforces that.
    """
    del languages  # unused — see docstring
    repo_root = repo_root.resolve()

    sql_files: list[Path] = []
    for p in repo_root.rglob("*.sql"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        # The .sql file must live under a ``models`` directory anywhere
        # in its ancestor chain. The check on rel_parts[:-1] excludes
        # the filename itself.
        if _MODELS_DIRNAME not in rel_parts[:-1]:
            continue
        # And we still want to skip nested unwanted dirs (e.g. a stray
        # ``tests/`` under ``models/``). The ``models`` ancestor must
        # not have a skip-dir AFTER it though, so we only filter the
        # PARENT directories above ``models``.
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if p.is_file():
            sql_files.append(p)
    sql_files.sort()

    found: list[EntryPoint] = []
    # Cache per-directory schema.yml lookups so we don't re-parse it
    # once per model in the same folder.
    schema_cache: dict[Path, dict[str, str]] = {}

    for path in sql_files:
        text = _read(path)
        if not text:
            # Even empty SQL files count as model declarations.
            text = ""
        rel = str(path.relative_to(repo_root))
        model_name = path.stem  # foo.sql -> foo
        anchor_line = _first_anchor_line(text)

        # Per-directory schema.yml lookup for description.
        schema_dir = path.parent
        if schema_dir not in schema_cache:
            schema_cache[schema_dir] = _parse_schema_descriptions(schema_dir / "schema.yml")
        descriptions = schema_cache[schema_dir]
        schema_desc = descriptions.get(model_name, "")
        leading_comment = _leading_comment(text)
        docstring = schema_desc or leading_comment

        # If schema.yml supplied the description, point to it as the
        # canonical intended_behaviour source.
        sources: tuple[str, ...] = ()
        if schema_desc:
            # Repo-relative path to the schema.yml + the model name.
            schema_rel = str((schema_dir / "schema.yml").relative_to(repo_root))
            sources = (f"{schema_rel}:#models/{model_name}",)

        found.append(
            EntryPoint(
                kind=EntryPointKind.DAG_TASK,
                file=rel,
                line=anchor_line,
                symbol=f"model:{model_name}",
                type_origin="data_pipeline_dbt",
                metadata={
                    "kind": "model",
                    "model": model_name,
                    "framework": "dbt",
                },
                docstring=docstring,
                intended_behaviour_sources=sources,
            )
        )

    # Dedup on (file, line, symbol) — sql files are unique paths so
    # collisions are not expected, but we keep the safety net.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: e.sort_key())
    return unique
