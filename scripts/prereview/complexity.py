#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 10 — Complexity & dead-code scanner (TRDD-7e364ace clusters M3-M5,
N2-perf, N12.1-N12.4, P4, G13).

PYTHON (`ast.parse`):
- `FN_TOO_LONG` — function or method spans more than `MAX_FN_LINES`
  source lines.
- `TOO_MANY_BRANCHES` — function body has more than
  `MAX_FN_BRANCHES` `If`/`For`/`While`/`Try`/`With`/`Match` nodes.
- `TOO_MANY_PARAMS` — function signature declares more than
  `MAX_FN_PARAMS` parameters (counting all kinds: positional, keyword,
  *args, **kwargs).
- `HIGH_COMPLEXITY` — McCabe cyclomatic complexity exceeds
  `MAX_FN_COMPLEXITY` (V(G) = 1 + count of branching nodes).
- `DEEP_NESTING` — any `For`/`While`/`If`/`With` nested deeper than
  `MAX_NEST_DEPTH` levels within a single function.
- `UNUSED_IMPORT` — `Import` / `ImportFrom` whose bound name is never
  referenced in the file (ruff catches these but the script-first split
  surfaces them in the unified JSON so the agent doesn't need to
  re-run ruff).
- `UNREACHABLE` — statements appearing after `Return`/`Raise`/
  `Break`/`Continue` in the same block.
- `ORPHAN_MODULE_DEF` — module-level `def` / `class` whose name is
  never referenced in the same file AND is not part of `__all__`. Weak
  signal across files; the agent confirms with cross-file knowledge.

JS / TS (regex-approximate):
- `FN_TOO_LONG_REGEX` — `function foo(...)` / `const foo = (...) => {`
  spanning more than `MAX_FN_LINES` lines. Brace-balance approximation
  (good enough for the 80% case).

Usage:
    python -m scripts.prereview.complexity <repo_root> <out_dir>
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
SCAN_CAP_BYTES = 400_000

# Thresholds — defaults from the TRDD. Tuned to err on "flag too much" so
# downstream agents see the candidates and can dismiss false positives.
MAX_FN_LINES = 20
MAX_FN_BRANCHES = 5
MAX_FN_PARAMS = 3
MAX_FN_COMPLEXITY = 10
MAX_NEST_DEPTH = 2

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


# ---- Python AST checks -----------------------------------------------------


_BRANCH_NODE_TYPES: tuple[type[ast.AST], ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.AsyncWith,
    ast.Match,
)


def _function_branches(node: ast.AST) -> int:
    """Count branch-introducing nodes inside a function (excluding nested fn defs)."""
    n = 0
    for child in ast.walk(node):
        if isinstance(child, _BRANCH_NODE_TYPES):
            n += 1
        # Boolean operators (and/or) add a branch each (McCabe-style).
        if isinstance(child, ast.BoolOp):
            n += max(0, len(child.values) - 1)
        # Comprehensions with `if` clauses also add branches.
        if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in child.generators:
                n += len(gen.ifs)
    return n


def _function_param_count(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = func.args
    total = len(args.args) + len(args.posonlyargs) + len(args.kwonlyargs)
    if args.vararg is not None:
        total += 1
    if args.kwarg is not None:
        total += 1
    return total


def _function_length_lines(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    # Every concrete statement node carries lineno/end_lineno per Python's
    # AST; pyright doesn't see the union narrowing here. Default to func
    # itself if a child somehow lacks the attribute.
    def _node_end(n: ast.AST) -> int:
        end = getattr(n, "end_lineno", None)
        if end is not None:
            return end
        return getattr(n, "lineno", func.lineno)

    last = max((_node_end(n) for n in ast.walk(func)), default=func.lineno)
    return max(0, last - func.lineno + 1)


def _max_nest_depth(node: ast.AST) -> int:
    """Max nesting depth of For/While/If/With/Try/Match within a function."""
    max_depth = 0

    def walk(n: ast.AST, depth: int) -> None:
        nonlocal max_depth
        if isinstance(n, _BRANCH_NODE_TYPES):
            depth += 1
            if depth > max_depth:
                max_depth = depth
        for child in ast.iter_child_nodes(n):
            # Don't descend into nested function definitions; they get their
            # own depth from their own walk.
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            walk(child, depth)

    walk(node, 0)
    return max_depth


def _unreachable_in_block(stmts: list[ast.stmt]) -> list[ast.stmt]:
    """Return any statements that come after Return/Raise/Break/Continue."""
    out: list[ast.stmt] = []
    terminated = False
    for s in stmts:
        if terminated:
            out.append(s)
            continue
        if isinstance(s, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            terminated = True
    return out


class _UnreachableCollector(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.findings: list[Finding] = []

    def _check_block(self, block: list[ast.stmt]) -> None:
        for s in _unreachable_in_block(block):
            self.findings.append(
                Finding(
                    tool="complexity",
                    category="unreachable_code",
                    file=self.rel,
                    line=s.lineno,
                    severity="warning",
                    code="UNREACHABLE",
                    message="statement appears after Return/Raise/Break/Continue in same block",
                )
            )

    def generic_visit(self, node: ast.AST) -> None:
        for _field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(v, ast.stmt) for v in value):
                self._check_block(list(value))
        super().generic_visit(node)


def _collect_used_names(tree: ast.Module) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                used.add(node.value.id)
        elif isinstance(node, ast.alias) and node.asname:
            # `import x as y` — the binding is `y`, the import body is `x`
            # which is its own `Name` not in scope, so we already handled it.
            pass
    # `__all__` entries also count as "used" (they declare a public API).
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    used.add(elt.value)
    return used


def _check_unused_imports(rel: str, tree: ast.Module, used: set[str]) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if bound not in used:
                    out.append(
                        Finding(
                            tool="complexity",
                            category="unused_import",
                            file=rel,
                            line=node.lineno,
                            severity="nit",
                            code="UNUSED_IMPORT",
                            message=f"import `{bound}` is never referenced in this file",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    # star imports cannot be flagged for unused
                    continue
                bound = alias.asname or alias.name
                if bound not in used:
                    out.append(
                        Finding(
                            tool="complexity",
                            category="unused_import",
                            file=rel,
                            line=node.lineno,
                            severity="nit",
                            code="UNUSED_IMPORT",
                            message=f"`from {node.module or '.'} import {bound}` is never referenced in this file",
                        )
                    )
    return out


def _check_orphan_module_defs(rel: str, tree: ast.Module, used: set[str]) -> list[Finding]:
    out: list[Finding] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Skip dunder / private names (those are convention-driven).
            if node.name.startswith("_"):
                continue
            if node.name in used:
                continue
            out.append(
                Finding(
                    tool="complexity",
                    category="orphan_module_def",
                    file=rel,
                    line=node.lineno,
                    severity="nit",
                    code="ORPHAN_MODULE_DEF",
                    message=(
                        f"module-level `{node.name}` is never referenced in this file "
                        f"and not in __all__ — confirm cross-file usage"
                    ),
                )
            )
    return out


def _check_python(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
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
        # Function-level checks.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            length = _function_length_lines(node)
            if length > MAX_FN_LINES:
                out.append(
                    Finding(
                        tool="complexity",
                        category="fn_too_long",
                        file=rel,
                        line=node.lineno,
                        severity="nit",
                        code="FN_TOO_LONG",
                        message=f"function `{node.name}` is {length} lines (max {MAX_FN_LINES})",
                    )
                )
            param_count = _function_param_count(node)
            if param_count > MAX_FN_PARAMS:
                out.append(
                    Finding(
                        tool="complexity",
                        category="too_many_params",
                        file=rel,
                        line=node.lineno,
                        severity="nit",
                        code="TOO_MANY_PARAMS",
                        message=(f"function `{node.name}` declares {param_count} parameters (max {MAX_FN_PARAMS})"),
                    )
                )
            branches = _function_branches(node)
            if branches > MAX_FN_BRANCHES:
                out.append(
                    Finding(
                        tool="complexity",
                        category="too_many_branches",
                        file=rel,
                        line=node.lineno,
                        severity="nit",
                        code="TOO_MANY_BRANCHES",
                        message=(f"function `{node.name}` has {branches} branch nodes (max {MAX_FN_BRANCHES})"),
                    )
                )
            # Cyclomatic complexity ≈ 1 + branches (close approximation;
            # exact McCabe also includes case clauses individually but the
            # `Match` is counted above so the over-estimate is small).
            complexity = 1 + branches
            if complexity > MAX_FN_COMPLEXITY:
                out.append(
                    Finding(
                        tool="complexity",
                        category="high_complexity",
                        file=rel,
                        line=node.lineno,
                        severity="warning",
                        code="HIGH_COMPLEXITY",
                        message=(
                            f"function `{node.name}` cyclomatic complexity ≈ {complexity} (max {MAX_FN_COMPLEXITY})"
                        ),
                    )
                )
            depth = _max_nest_depth(node)
            if depth > MAX_NEST_DEPTH:
                out.append(
                    Finding(
                        tool="complexity",
                        category="deep_nesting",
                        file=rel,
                        line=node.lineno,
                        severity="nit",
                        code="DEEP_NESTING",
                        message=(
                            f"function `{node.name}` nests control flow {depth} levels deep (max {MAX_NEST_DEPTH})"
                        ),
                    )
                )
        # Module-level checks.
        used = _collect_used_names(tree)
        out.extend(_check_unused_imports(rel, tree, used))
        out.extend(_check_orphan_module_defs(rel, tree, used))
        collector = _UnreachableCollector(rel)
        collector.visit(tree)
        out.extend(collector.findings)
    return out


# ---- JS/TS heuristic function-length check ---------------------------------


_JS_FN_HEAD_RE = re.compile(
    r"(?:^|\W)(?:function\s+(?P<n1>[\w$]+)\s*\([^)]*\)|"
    r"(?:const|let|var)\s+(?P<n2>[\w$]+)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>)\s*\{"
)


def _js_fn_lengths(text: str) -> list[tuple[str, int, int]]:
    """Return [(fn_name, start_line, length_lines)] using brace balance."""
    out: list[tuple[str, int, int]] = []
    for m in _JS_FN_HEAD_RE.finditer(text):
        name = m.group("n1") or m.group("n2") or "<anonymous>"
        body_start = m.end() - 1  # the `{`
        depth = 0
        i = body_start
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
                # Skip line comments — they can hide a `}` inside a string.
                # Conservative: only skip if we're at the start of a token.
                eol = text.find("\n", i)
                if eol == -1:
                    break
                i = eol
            i += 1
        if depth != 0:
            continue  # unbalanced, skip
        body_end = i
        start_line = text.count("\n", 0, m.start()) + 1
        end_line = text.count("\n", 0, body_end) + 1
        out.append((name, start_line, end_line - start_line + 1))
    return out


def _check_js(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        for name, start_line, length in _js_fn_lengths(text):
            if length > MAX_FN_LINES:
                out.append(
                    Finding(
                        tool="complexity",
                        category="fn_too_long",
                        file=rel,
                        line=start_line,
                        severity="nit",
                        code="FN_TOO_LONG_REGEX",
                        message=f"JS/TS function `{name}` spans {length} lines (max {MAX_FN_LINES})",
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
    findings.extend(_check_python(repo_root, all_files))
    findings.extend(_check_js(repo_root, all_files))
    findings.sort(key=lambda f: (f.category, f.file, f.line, f.code))
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "repo_root": str(repo_root.resolve()),
        "thresholds": {
            "max_fn_lines": MAX_FN_LINES,
            "max_fn_branches": MAX_FN_BRANCHES,
            "max_fn_params": MAX_FN_PARAMS,
            "max_fn_complexity": MAX_FN_COMPLEXITY,
            "max_nest_depth": MAX_NEST_DEPTH,
        },
        "total_findings": len(findings),
        "by_category": dict(sorted(by_category.items())),
        "findings": [asdict(f) for f in findings],
    }


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 10 — Complexity & dead-code scanner.",
        prog="complexity",
    )
    parser.add_argument("repo_root", help="Absolute path to the repository to scan.")
    parser.add_argument("out_dir", help="Where the JSON report is written.")
    parser.add_argument(
        "--pr-files-from",
        help="Optional file: each line is a repo-relative path of a PR-touched file.",
    )
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
    out_path = out_dir / f"{payload['timestamp']}-complexity.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
