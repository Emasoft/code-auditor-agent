"""FastAPI route discoverer — reference implementation pattern.

Finds HTTP route registrations across the codebase:
- @app.get(...), @app.post(...), @app.put(...), @app.delete(...),
  @app.patch(...), @app.head(...), @app.options(...)
- @router.get(...), etc. on any APIRouter() instance
- @app.add_api_route(path, fn, methods=[...]) — explicit form

Emits one EntryPoint per (file, line, HTTP method, path) triple.

Heuristic, not AST-perfect, but deterministic. We grep on the route
DECORATOR line; the symbol is the immediately following `def name(...)`
line. Multi-line decorators (path on one line, method on next) are
handled by reading 4 lines after the @app/@router match.

Intended-behaviour sources: nearby docstring + OpenAPI references if
present in the same file or in `openapi.json`/`openapi.yaml` at the
repo root.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

_DECORATOR_RE = re.compile(
    r"^\s*@(?P<binding>\w+)\.(?P<method>get|post|put|delete|patch|head|options)\s*\(",
    re.MULTILINE,
)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>\w+)\s*\(", re.MULTILINE)
_PATH_RE = re.compile(r'(["\'])(?P<path>/[^"\']*)\1')
_ADD_API_ROUTE_RE = re.compile(
    r"\.add_api_route\s*\(\s*[\"\'](?P<path>/[^\"\']*)[\"\'].*?methods\s*=\s*\[(?P<methods>[^\]]+)\]",
    re.DOTALL,
)
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — enough for big route files


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _docstring_after_def(text: str, def_match: re.Match[str]) -> str:
    """Extract the docstring directly following a `def ...:` line, if any."""
    rest = text[def_match.end() :]
    m = _DOCSTRING_RE.search(rest)
    if not m:
        return ""
    # Only count it as the function's docstring if it's within the first
    # ~600 characters after the def (anything farther is unrelated).
    if m.start() > 600:
        return ""
    body = m.group(1) or m.group(2) or ""
    # First non-empty line of the docstring.
    for ln in body.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _openapi_path_summary(repo_root: Path, http_method: str, route_path: str) -> str:
    """Best-effort: pluck the summary/description from openapi.{json,yaml} for the route."""
    import json

    for candidate in ("openapi.json", "openapi.yaml", "openapi.yml"):
        f = repo_root / candidate
        if not f.exists():
            continue
        if candidate.endswith(".json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            paths = data.get("paths", {})
            verb = paths.get(route_path, {}).get(http_method.lower(), {})
            summary = verb.get("summary") or verb.get("description") or ""
            if summary:
                return f"{candidate}:#/paths{route_path}/{http_method.lower()}"
        # Skip yaml parsing here for the v1 — yaml dep not pinned.
    return ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find FastAPI routes. Deterministic order."""
    if "python" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    py_files = []
    for p in repo_root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            py_files.append(p)
    py_files.sort()

    for path in py_files:
        text = _read(path)
        if not text:
            continue
        if "fastapi" not in text.lower() and "@app." not in text and "@router." not in text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) Decorator form: @app.get(...) or @router.post(...) etc.
        for dec_match in _DECORATOR_RE.finditer(text):
            method = dec_match.group("method").upper()
            decorator_end = dec_match.end()
            # Path is in the decorator's argument list — first quoted string after the `(`.
            tail = text[decorator_end : decorator_end + 1024]
            path_match = _PATH_RE.search(tail)
            route_path = path_match.group("path") if path_match else "?"

            # The function definition is the next `def ...` line.
            def_match = _DEF_RE.search(text, decorator_end)
            if def_match is None:
                continue
            # Ensure no other decorator block intervenes — bail if more than 8 lines apart.
            between = text[decorator_end : def_match.start()]
            if between.count("\n") > 12:
                continue

            symbol = def_match.group("name")
            line = _line_of(text, dec_match.start())
            docstring = _docstring_after_def(text, def_match)
            openapi_ref = _openapi_path_summary(repo_root, method, route_path)
            sources: tuple[str, ...] = ()
            if openapi_ref:
                sources = (openapi_ref,)

            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="web_service_python",
                    metadata={
                        "method": method,
                        "path": route_path,
                        "framework": "fastapi",
                        "binding": dec_match.group("binding"),
                    },
                    docstring=docstring,
                    intended_behaviour_sources=sources,
                )
            )

        # 2) Explicit form: app.add_api_route(path, handler, methods=[...])
        for m in _ADD_API_ROUTE_RE.finditer(text):
            route_path = m.group("path")
            methods_blob = m.group("methods")
            methods = [s.strip().strip("\"'") for s in methods_blob.split(",") if s.strip()]
            line = _line_of(text, m.start())
            for method in methods:
                if not method:
                    continue
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=f"add_api_route:{method}:{route_path}",
                        type_origin="web_service_python",
                        metadata={
                            "method": method.upper(),
                            "path": route_path,
                            "framework": "fastapi",
                            "binding": "add_api_route",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by sort_key + method (same file/line/symbol can't have two methods).
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, str(ep.metadata.get("method", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("method", ""))))
    return unique
