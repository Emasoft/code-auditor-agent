"""Fallback discoverer — used when no specific type matched.

The contract is the same as every discoverer:
    def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]

For unknown software we look for the most universal entry-point patterns
that exist in nearly every codebase:

- `main()` / `if __name__ == "__main__":` (Python, JS, Rust, Go, C, etc.)
- module-level top-level callables in scripts (`#!/usr/bin/env`)
- exported public symbols in libraries (heuristic: `def public_name()`
  at module scope, where name doesn't start with `_`)
- top-level entry shells (`_start`, `entry`, `Main`)

We deliberately stay shallow — overshooting on unknown software is worse
than undershooting. The agent's report tells the user "no specific
discoverer for type X; recommend adding one to extend coverage".

Deterministic at every step.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Common file extensions where we look for entry points. Order matters
# only for evidence preferences when a symbol appears in multiple
# language equivalents.
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
}


# Regex per language to find a "main" or top-level callable.
_MAIN_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r'^if\s+__name__\s*==\s*[\'"]__main__[\'"]', re.MULTILINE),
        re.compile(r"^def\s+(main)\s*\(", re.MULTILINE),
    ],
    "javascript": [re.compile(r"^(?:async\s+)?function\s+(main)\s*\(", re.MULTILINE)],
    "typescript": [re.compile(r"^(?:async\s+)?function\s+(main)\s*\(", re.MULTILINE)],
    "rust": [re.compile(r"^fn\s+(main)\s*\(", re.MULTILINE)],
    "go": [re.compile(r"^func\s+(main)\s*\(", re.MULTILINE)],
    "c": [re.compile(r"^int\s+(main)\s*\(", re.MULTILINE)],
    "cpp": [re.compile(r"^int\s+(main)\s*\(", re.MULTILINE)],
    "csharp": [re.compile(r"static\s+(?:async\s+)?(?:Task|void|int)\s+(Main)\s*\(", re.MULTILINE)],
    "ruby": [re.compile(r"^(?:if|unless)\s+__FILE__\s*==\s*\$PROGRAM_NAME", re.MULTILINE)],
    "java": [re.compile(r"public\s+static\s+void\s+(main)\s*\(", re.MULTILINE)],
    "kotlin": [re.compile(r"^fun\s+(main)\s*\(", re.MULTILINE)],
    "swift": [re.compile(r"@main", re.MULTILINE)],
}


# Regex per language for "exported public callable at module top level".
_PUBLIC_CALLABLE_PATTERNS: dict[str, re.Pattern[str]] = {
    # def foo(...) at column 0, name not starting with _
    "python": re.compile(r"^def\s+([a-z][a-zA-Z0-9_]*)\s*\(", re.MULTILINE),
    # export function foo(...) — only top-level (not inside braces); regex
    # is line-anchored which is good enough for unknown-software heuristic.
    "javascript": re.compile(r"^export\s+(?:async\s+)?function\s+([a-zA-Z][a-zA-Z0-9_]*)\s*\(", re.MULTILINE),
    "typescript": re.compile(r"^export\s+(?:async\s+)?function\s+([a-zA-Z][a-zA-Z0-9_]*)\s*\(", re.MULTILINE),
    "rust": re.compile(r"^pub\s+fn\s+([a-z][a-zA-Z0-9_]*)\s*[<(]", re.MULTILINE),
    "go": re.compile(r"^func\s+([A-Z][a-zA-Z0-9_]*)\s*\(", re.MULTILINE),
}


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        ".cache",
        ".idea",
        ".vscode",
        ".gradle",
        ".cargo",
        ".terraform",
        ".pulumi",
        "tests",
        "test",
        "__tests__",
        "spec",
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


CONTENT_PREVIEW_BYTES = 32768


def _iter_source_files(repo_root: Path) -> list[Path]:
    """Sorted list of source files we will inspect. Deterministic."""
    out: list[Path] = []
    for ext in _EXT_TO_LANG:
        for p in repo_root.rglob(f"*{ext}"):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if not p.is_file():
                continue
            out.append(p)
    out.sort()
    return out


def _read_preview(path: Path) -> str:
    try:
        data = path.read_bytes()[:CONTENT_PREVIEW_BYTES]
    except OSError:
        return ""
    try:
        return data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _docstring_near(text: str, line: int) -> str:
    """Best-effort 'docstring or top-of-function comment' near a line.

    Looks at the 5 lines before and 5 lines after; concatenates leading
    `#`/`//`/`*`-comment lines or python triple-quoted docstrings.
    """
    lines = text.splitlines()
    start = max(0, line - 1)
    chunk = lines[start : start + 8]
    out: list[str] = []
    for ln in chunk:
        s = ln.strip()
        if s.startswith(("#", "//", "*")) or s.startswith('"""') or s.startswith("'''"):
            out.append(s.lstrip("#/* ").rstrip("\"'"))
            continue
        if out:
            break
    return " ".join(out).strip()


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Return entry points found in `repo_root`. Deterministic order."""
    repo_root = repo_root.resolve()
    entries: list[EntryPoint] = []

    for path in _iter_source_files(repo_root):
        lang = _EXT_TO_LANG.get(path.suffix.lower())
        if lang is None:
            continue
        text = _read_preview(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # main() / entry-point hits
        for pat in _MAIN_PATTERNS.get(lang, []):
            for m in pat.finditer(text):
                symbol = m.group(1) if m.lastindex else "__main__"
                line = _line_of(text, m.start())
                entries.append(
                    EntryPoint(
                        kind=EntryPointKind.MAIN_FUNCTION,
                        file=rel,
                        line=line,
                        symbol=symbol,
                        type_origin="unknown_software",
                        metadata={"language": lang, "via": "main_pattern"},
                        docstring=_docstring_near(text, line),
                    )
                )

        # Public callables (libraries / general modules)
        public_pat = _PUBLIC_CALLABLE_PATTERNS.get(lang)
        if public_pat is not None:
            for m in public_pat.finditer(text):
                symbol = m.group(1)
                line = _line_of(text, m.start())
                entries.append(
                    EntryPoint(
                        kind=EntryPointKind.LIBRARY_EXPORT,
                        file=rel,
                        line=line,
                        symbol=symbol,
                        type_origin="unknown_software",
                        metadata={"language": lang, "via": "public_callable"},
                        docstring=_docstring_near(text, line),
                    )
                )

    # Deduplicate by (file, line, symbol) — sometimes both patterns fire.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in entries:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(key=lambda e: e.sort_key())
    return unique
