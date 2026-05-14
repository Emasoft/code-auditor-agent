"""Helm chart template discoverer.

Finds each Helm chart `templates/<file>.yaml` and emits one EntryPoint
per YAML document inside that file. A single template file may contain
multiple `---`-separated documents — each one is its own EntryPoint.

For each document we extract `apiVersion`, `kind`, and `metadata.name`
(or the literal string after `name:` if a Go-template expression like
`{{ include "chart.fullname" . }}` is used). The symbol is the doc's
`kind/<name>`; metadata records the apiVersion and template path so the
walker can reason about chart-relative paths.

Heuristic regex-only parsing (no yaml dependency). Go-template
substitutions are tolerated — we only need the surface-level
`apiVersion: <x>`, `kind: <y>`, `metadata:` and `  name: <z>` lines to
emit a usable entry point. Lines whose value is a `{{ ... }}` expression
are recorded verbatim as the value.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_helm"


_API_VERSION_RE = re.compile(r"""^\s*apiVersion\s*:\s*(?P<v>.+?)\s*$""", re.MULTILINE)
_KIND_RE = re.compile(r"""^\s*kind\s*:\s*(?P<k>.+?)\s*$""", re.MULTILINE)
# metadata.name is conventionally two-space-indented under metadata:
_METADATA_NAME_RE = re.compile(
    r"""^metadata\s*:\s*\n(?:[ \t]+[^\n]*\n)*?[ \t]+name\s*:\s*(?P<n>.+?)\s*$""",
    re.MULTILINE,
)


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
        # Helm's own deps folder — vendored sub-charts are not "this chart".
        "charts",
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB — Helm templates can be large


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _split_docs(text: str) -> list[tuple[int, str]]:
    """Split multi-document YAML on `^---$` lines. Return [(start_line, body), ...].

    A leading `---` is allowed; an absent separator means the whole file
    is one doc starting at line 1. The start_line is the line number in
    the original file where the doc's first line lives.
    """
    docs: list[tuple[int, str]] = []
    lines = text.splitlines(keepends=True)
    current_start_line = 1
    current_buf: list[str] = []
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            if current_buf:
                docs.append((current_start_line, "".join(current_buf)))
                current_buf = []
            current_start_line = i + 2  # next line after this `---`
            continue
        current_buf.append(ln)
    if current_buf:
        # Only add if the doc has actual content (not only blanks).
        body = "".join(current_buf)
        if body.strip():
            docs.append((current_start_line, body))
    return docs


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Helm templates. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # Find every `templates/` directory under a chart root (anywhere a
    # Chart.yaml sits next to it). To stay simple and deterministic we
    # walk *.yaml / *.yml under any directory named exactly `templates`.
    template_files: list[Path] = []
    for p in repo_root.rglob("*"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        if "templates" not in rel_parts:
            continue
        if p.suffix.lower() not in (".yaml", ".yml"):
            continue
        template_files.append(p)
    template_files.sort()

    for path in template_files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # Find the index of `templates/` in the relative path so we can
        # record the chart-relative template path in metadata.
        rel_parts = path.relative_to(repo_root).parts
        try:
            t_idx = rel_parts.index("templates")
            template_rel = "/".join(rel_parts[t_idx:])
        except ValueError:
            template_rel = rel

        docs = _split_docs(text)
        for doc_start_line, body in docs:
            kind_m = _KIND_RE.search(body)
            api_m = _API_VERSION_RE.search(body)
            name_m = _METADATA_NAME_RE.search(body)

            kind_val = kind_m.group("k").strip() if kind_m else ""
            api_val = api_m.group("v").strip() if api_m else ""
            name_val = name_m.group("n").strip() if name_m else ""

            # Skip docs that are not Kubernetes-shaped at all (no kind).
            if not kind_val:
                continue

            symbol = f"{kind_val}/{name_val}" if name_val else kind_val
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HELM_TEMPLATE,
                    file=rel,
                    line=doc_start_line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "kind": kind_val,
                        "apiVersion": api_val,
                        "name": name_val,
                        "template_path": template_rel,
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol).
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
