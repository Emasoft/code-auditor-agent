"""Library-export discoverer for Python packages.

Selective discoverer for the `library_python` software type (more
precise than `unknown_software`, which lists every top-level callable
across the tree).

A function or class is a LIBRARY EXPORT iff:

1. It is defined at module scope (column 0 `def name(...)` /
   `async def name(...)` / `class Name:`) — nested defs are skipped.
2. Its name does NOT start with `_`.
3. If the module defines `__all__`, the symbol MUST appear in it.
   If `__all__` is absent, every public top-level callable in the
   module qualifies.
4. The module is inside a *package* — i.e. it lives in (or under) a
   directory that contains an `__init__.py`. Root-level scripts that
   are not part of a package are skipped.

Skipped subtrees: `tests/`, `test/`, `_internal/`, `_private/`.

The docstring extracted for a symbol is the first non-empty line of
its triple-quoted body (PEP 257 first line).

Deterministic at every step — output is byte-identical across runs
for the same input.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

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
        "_internal",
        "_private",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — generous for library modules


def _read(path: Path) -> str:
    """Read a file's text content; return '' on any I/O or decode failure."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _parse(text: str) -> ast.Module | None:
    """Parse text into an AST module; return None on syntax error."""
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _first_docstring_line(node: ast.AST) -> str:
    """Return the first non-empty line of the symbol's docstring, or ''.

    Uses `ast.get_docstring` to extract the canonical PEP 257 docstring
    body, then returns its first non-empty stripped line.
    """
    if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.ClassDef | ast.Module):
        return ""
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    for ln in doc.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _extract_all_names(module: ast.Module) -> frozenset[str] | None:
    """Return the set of names in `__all__` if it is defined at module scope.

    Returns None when `__all__` is absent — that signals the caller to
    fall back to "every public top-level symbol qualifies".

    Only literal lists/tuples of string constants count; dynamic
    constructions (`__all__ = something()`) are conservatively ignored,
    in which case None is returned.
    """
    found: set[str] | None = None
    for stmt in module.body:
        # __all__ = [...]
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    names = _names_from_iterable(stmt.value)
                    if names is not None:
                        found = set(names)
        # __all__: list[str] = [...]
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__" and stmt.value is not None:
                names = _names_from_iterable(stmt.value)
                if names is not None:
                    found = set(names)
    return frozenset(found) if found is not None else None


def _names_from_iterable(node: ast.AST) -> list[str] | None:
    """Extract string names from a list/tuple literal of constants."""
    if not isinstance(node, ast.List | ast.Tuple):
        return None
    out: list[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
        else:
            # Non-literal element — bail out conservatively.
            return None
    return out


def _is_package_dir(d: Path) -> bool:
    """A directory is a Python package iff it contains an __init__.py."""
    return (d / "__init__.py").is_file()


def _enclosing_package(path: Path, repo_root: Path) -> Path | None:
    """Return the nearest ancestor of `path` (inside repo_root) that is a
    package directory, or None if `path` is not inside any package."""
    parent = path.parent
    while parent != repo_root and parent != parent.parent:
        if _is_package_dir(parent):
            return parent
        parent = parent.parent
    # Also consider repo_root itself (in case the repo root is a package).
    if parent == repo_root and _is_package_dir(parent):
        return parent
    return None


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find library exports in a Python package. Deterministic order.

    Returns an empty list when `python` is not in `languages` — keeps
    the dispatch in emit_scenarios_json type-safe.
    """
    if "python" not in languages:
        return []
    repo_root = repo_root.resolve()

    # Collect all .py files inside packages, excluding skip dirs.
    # IMPORTANT: skip-dir check is against the path RELATIVE to repo_root,
    # not the absolute path — otherwise a fixture path that happens to
    # contain a `tests/` ancestor (or a user home with `dist`, etc.) would
    # cause the entire tree to be excluded.
    py_files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if _enclosing_package(p, repo_root) is None:
            # Not inside a package — root-level script, skipped per rule 4.
            continue
        py_files.append(p)
    py_files.sort()

    found: list[EntryPoint] = []

    for path in py_files:
        text = _read(path)
        if not text:
            continue
        module = _parse(text)
        if module is None:
            continue

        all_names = _extract_all_names(module)
        rel = str(path.relative_to(repo_root))
        # Scope is "package" for __init__.py (the package's public face),
        # otherwise "module".
        scope = "package" if path.name == "__init__.py" else "module"

        for stmt in module.body:
            # Only top-level def/async def/class qualifies (rule 1).
            if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            name = stmt.name
            # Rule 2: name must not start with `_`.
            if name.startswith("_"):
                continue
            # Rule 3: respect __all__ when defined.
            if all_names is not None:
                in_all = name in all_names
                if not in_all:
                    continue
            else:
                in_all = False

            line = stmt.lineno
            docstring = _first_docstring_line(stmt)

            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="library_python",
                    metadata={
                        "language": "python",
                        "scope": scope,
                        "in_all": in_all,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Deduplicate by (file, line, symbol) and sort deterministically.
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
