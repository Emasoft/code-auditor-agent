#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 13 — Test-quality scanner (TRDD-7e364ace I1-I12, E9, N13).

Surface tests that pass without actually testing anything — the
biggest single source of false-confidence in a code review.

Python AST checks (test files only — `test_*.py` / `*_test.py`):
- `NO_ASSERTION_TEST` — `def test_*` function body contains no
  `assert`, no `pytest.raises(...)` context, no `unittest`
  `self.assert*` call, no mock `assert_called*` call.
- `ASSERT_TRUE_LITERAL` — `assert True` / `assert 1` / `assertTrue
  (True)` / `assert "ok" == "ok"` (same operand both sides).
- `MOCK_REPLACES_SUT_HEURISTIC` — `mock.patch` / `@patch(target)`
  where the target string matches a name explicitly imported by the
  test file. Classic "mocking what you're trying to test" smell.
- `MISSING_REGRESSION_TEST_FILE` — heuristic: scan src for files
  whose mtime is newer than the corresponding test file. Out of
  scope for the script (requires git history). Deferred to agent.

JS / TS (regex on test files — `*.test.{ts,tsx,js,jsx}` or `*.spec.*`):
- `JS_EXPECT_TRUE` — `expect(true).toBe(true)` / `expect(1).toBe(1)`
  / `expect("x").toBe("x")` / `expect(literal).toBeTruthy()` where the
  literal is truthy.
- `JS_NO_ASSERTION` — test arrow whose body has no `expect(`,
  `assert(`, `assert.`, `should.`, `chai.expect(`.

Usage:
    python -m scripts.prereview.test_quality <repo_root> <out_dir>
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


def _is_python_test_file(path: Path) -> bool:
    name = path.name
    return path.suffix.lower() == ".py" and (name.startswith("test_") or name.endswith("_test.py"))


def _is_js_test_file(path: Path) -> bool:
    name = path.name
    if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}:
        return False
    return any(suffix in name for suffix in (".test.", ".spec."))


# ---- Python AST checks -----------------------------------------------------


def _is_pytest_raises_with(node: ast.AST) -> bool:
    return isinstance(node, ast.With) and any(
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Attribute)
        and item.context_expr.func.attr == "raises"
        for item in node.items
    )


def _has_assertion(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Walk the function body; return True if any assertion shape appears."""
    for n in ast.walk(func):
        if isinstance(n, ast.Assert):
            return True
        if _is_pytest_raises_with(n):
            return True
        if isinstance(n, ast.Call):
            func_node = n.func
            # `self.assertX(...)` / `cls.assertX(...)`
            if isinstance(func_node, ast.Attribute) and func_node.attr.startswith("assert"):
                return True
            # `mock.assert_called*`
            if isinstance(func_node, ast.Attribute) and func_node.attr.startswith("assert_"):
                return True
            # `unittest.TestCase.assert*` via class attr
            if isinstance(func_node, ast.Name) and func_node.id in {
                "assert_",
                "assertEqual",
                "assertTrue",
                "assertFalse",
                "assertIs",
                "assertIn",
                "assertRaises",
            }:
                return True
    return False


def _is_assert_true_literal(stmt: ast.AST) -> bool:
    """Detect `assert True` / `assert 1` / `assert 'x' == 'x'` / `assertTrue(True)`."""
    if isinstance(stmt, ast.Assert):
        test = stmt.test
        # `assert True` / `assert 1`
        if isinstance(test, ast.Constant) and bool(test.value):
            return True
        # `assert "x" == "x"` or `assert 1 == 1` (same operand both sides)
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
            left = test.left
            right = test.comparators[0]
            if (
                isinstance(left, ast.Constant)
                and isinstance(right, ast.Constant)
                and isinstance(test.ops[0], ast.Eq)
                and left.value == right.value
            ):
                return True
        return False
    # `self.assertTrue(True)`, `assertTrue(True)`
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        func = call.func
        is_assert_true = (isinstance(func, ast.Attribute) and func.attr == "assertTrue") or (
            isinstance(func, ast.Name) and func.id == "assertTrue"
        )
        if is_assert_true and len(call.args) == 1:
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and bool(arg.value):
                return True
    return False


def _imported_top_level_names(tree: ast.Module) -> set[str]:
    """Collect every top-level name explicitly imported by the test file."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".", 1)[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                for alias in node.names:
                    names.add(alias.asname or alias.name)
                    names.add(f"{node.module}.{alias.name}")
    return names


def _patch_targets(tree: ast.Module) -> list[tuple[ast.AST, str]]:
    """Find every `mock.patch('...')` / `@patch('...')` target string."""
    out: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        # Decorator form: @patch("a.b.c")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                target = _patch_target_from_call(dec)
                if target is not None:
                    out.append((dec, target))
        # Direct call form: mock.patch("a.b.c") inside a body
        if isinstance(node, ast.Call):
            target = _patch_target_from_call(node)
            if target is not None:
                out.append((node, target))
    return out


def _patch_target_from_call(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    is_patch = (isinstance(func, ast.Attribute) and func.attr == "patch") or (
        isinstance(func, ast.Name) and func.id == "patch"
    )
    if not is_patch:
        return None
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _check_python_tests(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if not _is_python_test_file(path):
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = _rel(repo_root, path)
        imports = _imported_top_level_names(tree)
        # MOCK_REPLACES_SUT: patch targets matching anything the test imports.
        for patch_node, target in _patch_targets(tree):
            line = getattr(patch_node, "lineno", 1)
            # Strip the patch target back to a candidate import name.
            target_root = target.split(".", 1)[0]
            if target in imports or target_root in imports:
                # Bonus check: only flag if the imported name is a function/
                # class from the same module (i.e. probably the SUT). We use
                # the heuristic "imported name appears verbatim or as the
                # prefix of the patch path".
                out.append(
                    Finding(
                        tool="test_quality",
                        category="mock_replaces_sut",
                        file=rel,
                        line=line,
                        severity="warning",
                        code="MOCK_REPLACES_SUT_HEURISTIC",
                        message=(
                            f"`patch('{target}')` matches an imported name in the test — "
                            f"the test may be mocking its own subject under test"
                        ),
                    )
                )
        # Per-function checks.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            # ASSERT_TRUE_LITERAL — check each top-level statement in body
            for stmt in node.body:
                if _is_assert_true_literal(stmt):
                    out.append(
                        Finding(
                            tool="test_quality",
                            category="assert_true_literal",
                            file=rel,
                            line=getattr(stmt, "lineno", node.lineno),
                            severity="error",
                            code="ASSERT_TRUE_LITERAL",
                            message=f"`{node.name}` contains `assert True`-style no-op assertion",
                        )
                    )
            # NO_ASSERTION_TEST
            if not _has_assertion(node):
                out.append(
                    Finding(
                        tool="test_quality",
                        category="no_assertion",
                        file=rel,
                        line=node.lineno,
                        severity="warning",
                        code="NO_ASSERTION_TEST",
                        message=(
                            f"`{node.name}` has no assert / pytest.raises / assertX / "
                            f"mock.assert_called — test always passes"
                        ),
                    )
                )
    return out


# ---- JS/TS regex checks ----------------------------------------------------


_JS_EXPECT_TRUE_RE = re.compile(
    r"""expect\s*\(\s*(?P<arg>true|1|"[^"]+"|'[^']+'|\d+)\s*\)
        \s*\.(?:toBe|toEqual|toStrictEqual)\(\s*(?P<exp>true|1|"[^"]+"|'[^']+'|\d+)\s*\)""",
    re.VERBOSE,
)
_JS_EXPECT_TRUTHY_RE = re.compile(
    r"""expect\s*\(\s*(?P<arg>true|1|"[^"]+"|'[^']+'|\d+)\s*\)\s*\.toBeTruthy\(\s*\)""",
    re.VERBOSE,
)
# `test('...', () => {...})` / `it('...', () => {...})` whose body
# contains no `expect(`, `assert(`, `assert.`, `should.`, or `chai.expect(`.
_JS_TEST_HEAD_RE = re.compile(r"\b(?:test|it)\s*\(\s*['\"`][^'\"`]+['\"`]\s*,\s*(?:async\s*)?\(\s*\)\s*=>\s*\{")


def _check_js_tests(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if not _is_js_test_file(path):
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        # JS_EXPECT_TRUE
        for m in _JS_EXPECT_TRUE_RE.finditer(text):
            if m.group("arg") != m.group("exp"):
                continue
            line = text.count("\n", 0, m.start()) + 1
            out.append(
                Finding(
                    tool="test_quality",
                    category="assert_true_literal",
                    file=rel,
                    line=line,
                    severity="error",
                    code="JS_EXPECT_TRUE",
                    message=f"`expect({m.group('arg')}).toBe({m.group('exp')})` — tautological assertion",
                )
            )
        for m in _JS_EXPECT_TRUTHY_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            out.append(
                Finding(
                    tool="test_quality",
                    category="assert_true_literal",
                    file=rel,
                    line=line,
                    severity="error",
                    code="JS_EXPECT_TRUTHY",
                    message=f"`expect({m.group('arg')}).toBeTruthy()` — literal is always truthy",
                )
            )
        # JS_NO_ASSERTION (heuristic): for each test/it body, scan until
        # the matching `}` (brace balance) and see if any assertion shape
        # appears.
        for m in _JS_TEST_HEAD_RE.finditer(text):
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
                i += 1
            if depth != 0:
                continue
            body = text[body_start + 1 : i]
            if any(
                shape in body
                for shape in (
                    "expect(",
                    "assert(",
                    "assert.",
                    "should.",
                    "chai.expect(",
                    ".toThrow(",
                )
            ):
                continue
            line = text.count("\n", 0, m.start()) + 1
            out.append(
                Finding(
                    tool="test_quality",
                    category="no_assertion",
                    file=rel,
                    line=line,
                    severity="warning",
                    code="JS_NO_ASSERTION",
                    message="JS/TS test body has no assertion shape — test always passes",
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
    findings.extend(_check_python_tests(repo_root, all_files))
    findings.extend(_check_js_tests(repo_root, all_files))
    findings.sort(key=lambda f: (f.category, f.file, f.line, f.code))
    # Dedup on (file, line, code): a `@patch(...)` decorator is reached by both
    # the FunctionDef-decorator branch and the standalone-Call branch of
    # _patch_targets (ast.walk visits the same Call node twice), so one decorator
    # otherwise yields two identical MOCK_REPLACES_SUT_HEURISTIC findings.
    _seen: set[tuple[str, int, str]] = set()
    _deduped: list[Finding] = []
    for _f in findings:
        _key = (_f.file, _f.line, _f.code)
        if _key in _seen:
            continue
        _seen.add(_key)
        _deduped.append(_f)
    findings = _deduped
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
        description="Step 13 — Test-quality scanner.",
        prog="test_quality",
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
    out_path = out_dir / f"{payload['timestamp']}-test_quality.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
