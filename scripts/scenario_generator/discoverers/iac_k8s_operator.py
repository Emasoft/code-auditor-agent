"""Kubernetes operator + raw-manifest discoverer.

For a kubebuilder-based operator we discover two kinds of entry points:

1. **Raw Kubernetes manifests** — every `apiVersion`/`kind`/`metadata.name`
   triple in any `.yaml`/`.yml` file under `config/`, `manifests/`,
   `deploy/`, or the chart's own templated CRDs. Each one is an
   "infrastructure resource" the walker can analyse (CRDs,
   ServiceAccounts, Roles, RoleBindings, Deployments, etc.).
2. **Reconcile loops** — every Go function whose signature contains
   `Reconcile(` (the convention for controller-runtime reconcilers) and
   every Python kopf handler decorated with `@kopf.on.create/update/delete`.

Heuristic regex-only parsing (no yaml dependency). The walker reasons
about operator scenarios at the (kind, name) boundary for manifests and
at the reconciler-function boundary for the operator binary; that's
enough for the family expansion (controller_reconcile,
auth_state_transition, persistence_corruption, ...).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_k8s_operator"


_API_VERSION_RE = re.compile(r"""^\s*apiVersion\s*:\s*(?P<v>.+?)\s*$""", re.MULTILINE)
_KIND_RE = re.compile(r"""^\s*kind\s*:\s*(?P<k>.+?)\s*$""", re.MULTILINE)
_METADATA_NAME_RE = re.compile(
    r"""^metadata\s*:\s*\n(?:[ \t]+[^\n]*\n)*?[ \t]+name\s*:\s*(?P<n>.+?)\s*$""",
    re.MULTILINE,
)

# Go: func (r *FooReconciler) Reconcile(ctx context.Context, req ctrl.Request) ...
_GO_RECONCILE_RE = re.compile(
    r"""^func\s+\(\s*(?P<recv>\w+)\s+\*?(?P<rtype>\w+)\s*\)\s+Reconcile\s*\(""",
    re.MULTILINE,
)

# Python kopf decorator: @kopf.on.<event>('group', 'version', 'plural')
_KOPF_DECORATOR_RE = re.compile(
    r"""^@kopf\.on\.(?P<event>create|update|delete|resume|field|timer|daemon)\s*\(""",
    re.MULTILINE,
)
_PYTHON_DEF_RE = re.compile(r"""^\s*(?:async\s+)?def\s+(?P<name>\w+)\s*\(""", re.MULTILINE)


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
        "vendor",
        # Helm sub-charts — not part of the operator itself.
        "charts",
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _split_docs(text: str) -> list[tuple[int, str]]:
    """Split multi-document YAML on `^---$` lines. Return [(start_line, body), ...]."""
    docs: list[tuple[int, str]] = []
    lines = text.splitlines(keepends=True)
    current_start_line = 1
    current_buf: list[str] = []
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            if current_buf:
                docs.append((current_start_line, "".join(current_buf)))
                current_buf = []
            current_start_line = i + 2
            continue
        current_buf.append(ln)
    if current_buf:
        body = "".join(current_buf)
        if body.strip():
            docs.append((current_start_line, body))
    return docs


def _iter_relevant_files(repo_root: Path) -> list[Path]:
    """Yield .yaml/.yml/.go/.py files outside SKIP_DIRS, deterministically."""
    out: list[Path] = []
    for p in repo_root.rglob("*"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".yaml", ".yml", ".go", ".py"):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find K8s operator manifests + reconciler loops. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_relevant_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        suffix = path.suffix.lower()

        # 1) YAML manifests — every kind/name pair becomes an EntryPoint.
        if suffix in (".yaml", ".yml"):
            for doc_start_line, body in _split_docs(text):
                kind_m = _KIND_RE.search(body)
                api_m = _API_VERSION_RE.search(body)
                name_m = _METADATA_NAME_RE.search(body)
                kind_val = kind_m.group("k").strip() if kind_m else ""
                api_val = api_m.group("v").strip() if api_m else ""
                name_val = name_m.group("n").strip() if name_m else ""
                # Skip docs that aren't Kubernetes-shaped (no kind line).
                if not kind_val:
                    continue
                # Skip kubebuilder.yaml config — it's a project descriptor,
                # not a runtime resource.
                if path.name == "kubebuilder.yaml":
                    continue
                symbol = f"{kind_val}/{name_val}" if name_val else kind_val
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.TERRAFORM_RESOURCE,
                        file=rel,
                        line=doc_start_line,
                        symbol=symbol,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "kind": kind_val,
                            "apiVersion": api_val,
                            "name": name_val,
                            "manifest": True,
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )
            continue

        # 2) Go reconciler functions — `func (r *FooReconciler) Reconcile(...)`.
        if suffix == ".go":
            for m in _GO_RECONCILE_RE.finditer(text):
                line = _line_of(text, m.start())
                rtype = m.group("rtype")
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.CONTROLLER_RECONCILE,
                        file=rel,
                        line=line,
                        symbol=f"{rtype}.Reconcile",
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "language": "go",
                            "receiver_type": rtype,
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )
            continue

        # 3) Python kopf handlers — `@kopf.on.<event>(...)` over a `def`.
        if suffix == ".py":
            for dec in _KOPF_DECORATOR_RE.finditer(text):
                event = dec.group("event")
                def_m = _PYTHON_DEF_RE.search(text, dec.end())
                if def_m is None:
                    continue
                between = text[dec.end() : def_m.start()]
                if between.count("\n") > 12:
                    continue
                name = def_m.group("name")
                line = _line_of(text, dec.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.CONTROLLER_RECONCILE,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "language": "python",
                            "framework": "kopf",
                            "event": event,
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )
            continue

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
