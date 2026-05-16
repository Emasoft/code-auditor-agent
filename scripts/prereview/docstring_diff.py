#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 12 — Comment & docstring quality (TRDD-7e364ace L1-L6).

Python-only deterministic checks (other languages defer to their native
doc-string lint: jsdoc, godoc, rustdoc, etc., already covered by Step 5).

1. **`DOCSTRING_PARAM_MISMATCH`** — `def fn(a, b, c)` whose docstring
   documents `a` and `b` but not `c`, or documents a nonexistent `d`.
   Supports Google (`Args:` block), NumPy (`Parameters\\n---\\n`), and
   Sphinx (`:param name:`) styles.

2. **`TRIVIAL_DOCSTRING`** — module/class/function carries a docstring
   that's empty, ≤ 3 words, or matches boilerplate templates
   (`TODO`, `description here`, `placeholder`, single-noun summaries).

3. **`COMMENT_CONTRADICTS_LITERAL`** — inline comment on the same line
   as a numeric or string literal that mentions a DIFFERENT literal.
   Weak heuristic — agent confirms. Examples:
     `RETRIES = 3  # default is 5`            → contradicts 3
     `TIMEOUT = 1000  # ms (was 500)`         → mentions both 500 and 1000

Usage:
    python -m scripts.prereview.docstring_diff <repo_root> <out_dir>
        [--pr-files-from <txt>]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1
SCAN_CAP_BYTES = 200_000
TRIVIAL_WORD_THRESHOLD = 3  # ≤ this many words → flagged as trivial

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        "target",
        ".cache",
        ".idea",
        ".vscode",
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
        ".trashcan",
    }
)


# Boilerplate templates that almost certainly indicate an unfinished
# docstring. `Summary.` is intentionally NOT in this list — many real
# docstrings start with the word "Summary" before going into detail.
_TRIVIAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^todo\b",
        r"^fixme\b",
        r"^placeholder\b",
        r"^description\s+here\b",
        r"^docstring\s+(goes\s+here|here)\b",
        r"^add\s+description\b",
        r"^class\s+for\s+\w+\.?$",
        r"^function\s+for\s+\w+\.?$",
    )
)


@dataclass(frozen=True, slots=True)
class Finding:
    tool: str
    category: str
    file: str
    line: int
    severity: str
    code: str
    message: str


# ---- IO helpers ------------------------------------------------------------


def _enumerate_repo(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fname in sorted(filenames):
            out.append(Path(dirpath) / fname)
    return out


def _load_pr_files(repo_root: Path, path: Path | None) -> list[Path] | None:
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"--pr-files-from: not found: {path}")
    files: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rel = line.strip()
        if not rel or rel.startswith("#"):
            continue
        abs_path = (repo_root / rel).resolve()
        if abs_path.is_file():
            files.append(abs_path)
    return sorted(set(files))


def _read_text_capped(path: Path) -> str:
    try:
        with path.open("rb") as f:
            data = f.read(SCAN_CAP_BYTES)
    except OSError:
        return ""
    return data.decode("utf-8", errors="ignore")


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


# ---- Docstring parsing -----------------------------------------------------


_SPHINX_PARAM_RE = re.compile(r"^\s*:(?:param|parameter|arg|argument)\s+(\w+)\s*:", re.MULTILINE)


def _parse_google_args(doc: str) -> set[str]:
    """Return the param names documented in a Google-style `Args:` block."""
    names: set[str] = set()
    pattern = re.compile(r"^[ \t]*(?:Args|Arguments|Parameters)\s*:\s*$", re.MULTILINE)
    m = pattern.search(doc)
    if not m:
        return names
    # Lines after the header, indented further than the header.
    start = m.end()
    tail = doc[start:]
    lines = tail.splitlines()
    # Skip leading blank lines.
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return names
    body_indent = len(lines[idx]) - len(lines[idx].lstrip())
    # Match `name (type):` or `name:` lines at body_indent.
    arg_re = re.compile(rf"^[ \t]{{{body_indent}}}(\*{{0,2}}\w+)(?:\s*\([^)]*\))?\s*:")
    for line in lines[idx:]:
        if not line.strip():
            continue
        cur_indent = len(line) - len(line.lstrip())
        if cur_indent < body_indent:
            break
        m_arg = arg_re.match(line)
        if m_arg:
            raw = m_arg.group(1).lstrip("*")
            names.add(raw)
    return names


def _parse_numpy_params(doc: str) -> set[str]:
    """Return the param names documented in a NumPy-style `Parameters` block."""
    names: set[str] = set()
    pattern = re.compile(r"^[ \t]*Parameters\s*$\n[ \t]*-{3,}[ \t]*$", re.MULTILINE)
    m = pattern.search(doc)
    if not m:
        return names
    start = m.end()
    tail = doc[start:]
    # NumPy block: `name : type` lines flush-left to the docstring indent.
    arg_re = re.compile(r"^[ \t]*(\*{0,2}\w+)\s*:\s*\S")
    for raw in tail.splitlines():
        if not raw.strip():
            # Blank line after content terminates the section
            if names:
                continue
            continue
        # Hard stop: next section header (Returns / Raises / etc. with dashes).
        if re.match(r"^[ \t]*[A-Z][a-zA-Z ]+\s*$", raw):
            # Likely a new section header without dashes — let next iteration confirm.
            continue
        if re.match(r"^[ \t]*-{3,}[ \t]*$", raw):
            # Underline of a new section header → stop.
            break
        m_arg = arg_re.match(raw)
        if m_arg:
            names.add(m_arg.group(1).lstrip("*"))
    return names


def _parse_sphinx_params(doc: str) -> set[str]:
    return {m.group(1) for m in _SPHINX_PARAM_RE.finditer(doc)}


def _documented_params(doc: str) -> set[str]:
    """Union of params across the three supported docstring styles."""
    return _parse_google_args(doc) | _parse_numpy_params(doc) | _parse_sphinx_params(doc)


def _is_trivial_docstring(doc: str) -> bool:
    """The docstring is too short or matches a boilerplate template."""
    stripped = doc.strip()
    if not stripped:
        return True
    first_line = stripped.splitlines()[0].strip()
    if not first_line:
        return True
    for pat in _TRIVIAL_PATTERNS:
        if pat.search(first_line):
            return True
    word_count = len(re.findall(r"\b\w+\b", stripped))
    return word_count <= TRIVIAL_WORD_THRESHOLD


# ---- Function-level docstring/param scan -----------------------------------


def _function_params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the names of every parameter (positional, kw-only, *args, **kwargs)."""
    args = func.args
    out: set[str] = set()
    out |= {a.arg for a in args.posonlyargs}
    out |= {a.arg for a in args.args}
    out |= {a.arg for a in args.kwonlyargs}
    if args.vararg is not None:
        out.add(args.vararg.arg)
    if args.kwarg is not None:
        out.add(args.kwarg.arg)
    # `self` / `cls` are implicit; never required in docstrings.
    out.discard("self")
    out.discard("cls")
    return out


def _check_python_docstrings(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".pyi"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = _rel(repo_root, path)
        # Module-level docstring trivial check.
        mod_doc = ast.get_docstring(tree)
        if mod_doc is not None and _is_trivial_docstring(mod_doc):
            out.append(
                Finding(
                    tool="docstring_diff",
                    category="trivial_docstring",
                    file=rel,
                    line=1,
                    severity="nit",
                    code="TRIVIAL_DOCSTRING",
                    message="module docstring is trivial (empty / ≤ 3 words / boilerplate)",
                )
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node)
                if doc is not None and _is_trivial_docstring(doc):
                    out.append(
                        Finding(
                            tool="docstring_diff",
                            category="trivial_docstring",
                            file=rel,
                            line=node.lineno,
                            severity="nit",
                            code="TRIVIAL_DOCSTRING",
                            message=f"class `{node.name}` docstring is trivial",
                        )
                    )
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node)
            params = _function_params(node)
            if doc is None:
                continue  # don't require docstrings; only audit when present
            if _is_trivial_docstring(doc):
                out.append(
                    Finding(
                        tool="docstring_diff",
                        category="trivial_docstring",
                        file=rel,
                        line=node.lineno,
                        severity="nit",
                        code="TRIVIAL_DOCSTRING",
                        message=f"function `{node.name}` docstring is trivial",
                    )
                )
                continue
            documented = _documented_params(doc)
            if not documented:
                continue  # docstring without param tables — out of scope
            missing = params - documented
            extra = documented - params
            if missing:
                out.append(
                    Finding(
                        tool="docstring_diff",
                        category="docstring_param_mismatch",
                        file=rel,
                        line=node.lineno,
                        severity="warning",
                        code="DOCSTRING_PARAM_MISSING",
                        message=(f"function `{node.name}` docstring is missing params: {sorted(missing)}"),
                    )
                )
            if extra:
                out.append(
                    Finding(
                        tool="docstring_diff",
                        category="docstring_param_mismatch",
                        file=rel,
                        line=node.lineno,
                        severity="warning",
                        code="DOCSTRING_PARAM_GHOST",
                        message=(f"function `{node.name}` docstring documents nonexistent params: {sorted(extra)}"),
                    )
                )
    return out


# ---- Inline-comment contradiction scan -------------------------------------


# A naive heuristic: an assignment line where the right-hand side has a
# number AND the inline comment mentions a DIFFERENT number.
_INLINE_NUM_ASSIGN_RE = re.compile(
    r"""^\s*[\w.\[\]]+\s*[+\-*/%]?=\s*(?P<rhs>-?\d+(?:\.\d+)?)\s*[\s,)\]}]*\s*\#\s*(?P<comment>.+)$"""
)
_COMMENT_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _check_comment_contradictions(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".pyi"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        for line_idx, raw in enumerate(text.splitlines(), start=1):
            m = _INLINE_NUM_ASSIGN_RE.match(raw)
            if not m:
                continue
            rhs_val = m.group("rhs")
            comment = m.group("comment")
            comment_nums = _COMMENT_NUM_RE.findall(comment)
            if not comment_nums:
                continue
            diff_nums = [n for n in comment_nums if n != rhs_val]
            if not diff_nums:
                continue
            out.append(
                Finding(
                    tool="docstring_diff",
                    category="comment_contradicts_literal",
                    file=rel,
                    line=line_idx,
                    severity="nit",
                    code="COMMENT_CONTRADICTS_LITERAL",
                    message=(
                        f"line assigns `{rhs_val}` but inline comment mentions different number(s) "
                        f"{diff_nums} — verify intent: {raw.strip()[:120]}"
                    ),
                )
            )
    return out


# ---- Driver ---------------------------------------------------------------


def _local_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S%z", time.localtime())


def detect(repo_root: Path, pr_files: list[Path] | None = None) -> dict[str, object]:
    if not repo_root.is_dir():
        raise NotADirectoryError(f"repo_root is not a directory: {repo_root}")
    all_files = pr_files if pr_files is not None else _enumerate_repo(repo_root)
    findings: list[Finding] = []
    findings.extend(_check_python_docstrings(repo_root, all_files))
    findings.extend(_check_comment_contradictions(repo_root, all_files))
    findings.sort(key=lambda f: (f.category, f.file, f.line, f.code))
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "repo_root": str(repo_root.resolve()),
        "total_findings": len(findings),
        "by_category": dict(sorted(by_category.items())),
        "findings": [asdict(f) for f in findings],
    }


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 12 — Comment & docstring quality.",
        prog="docstring_diff",
    )
    parser.add_argument("repo_root")
    parser.add_argument("out_dir")
    parser.add_argument("--pr-files-from")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_argv(argv[1:])
    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"out_dir unwritable: {exc}", file=sys.stderr)
        return 1
    try:
        pr_files = _load_pr_files(repo_root, Path(args.pr_files_from) if args.pr_files_from else None)
        payload = detect(repo_root, pr_files)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = out_dir / f"{payload['timestamp']}-docstring_diff.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
