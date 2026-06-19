#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 15 — Database / query / migration correctness (TRDD-7e364ace N15).

PYTHON (`ast.parse`):
- `EMPTY_DOWNGRADE` — Alembic / Django migration file declares
  `def downgrade()` whose body is only `pass`/`...`/string-doc. A
  forward-only migration with a no-op downgrade is a deployment-
  rollback hazard.
- `MISSING_DOWNGRADE` — Alembic migration file declares `def upgrade()`
  but no `def downgrade()` at all.
- `SQL_INJECTION_FSTRING` — `cursor.execute(f"...{x}...")` /
  `session.execute(f"...")`. The agent confirms it isn't a stub /
  test fixture.

GENERIC SQL (text scan on `*.sql` / migrations):
- `ALTER_TABLE_OUTSIDE_MIGRATION` — `ALTER TABLE ...` statement in a
  source file whose path doesn't contain `/migrations/` or `/migrate/`.
- `DROP_TABLE_OUTSIDE_MIGRATION` — same idea for `DROP TABLE`.

Usage:
    python -m scripts.prereview.database <repo_root> <out_dir>
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
        # Confine to the repo tree: a `../../etc/hosts` listing entry resolves
        # outside repo_root (out-of-tree read). Mirrors concurrency.py's fix.
        if abs_path.is_file() and abs_path.is_relative_to(repo_root.resolve()):
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


def _is_migration_path(path: Path) -> bool:
    """Path looks like it's inside an Alembic/Django migration tree."""
    parts = {p.lower() for p in path.parts}
    return bool({"migrations", "migrate", "alembic", "versions"}.intersection(parts))


# ---- Python AST checks -----------------------------------------------------


def _is_no_op_body(body: list[ast.stmt]) -> bool:
    """The body is empty, only `pass`, only `...`, or only a docstring."""
    if not body:
        return True
    # Allow a leading docstring.
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            return True
        # `raise NotImplementedError(...)` is intentionally NOT no-op.
    return False


def _check_migrations(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() != ".py":
            continue
        if not _is_migration_path(path):
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = _rel(repo_root, path)
        has_upgrade = False
        has_downgrade = False
        for node in tree.body:
            # Match async migrations too: ast.AsyncFunctionDef is NOT a subclass of
            # ast.FunctionDef, so `async def upgrade()/downgrade()` (mainstream in
            # async Alembic) would otherwise be silently invisible — has_upgrade /
            # has_downgrade stay False and EMPTY/MISSING_DOWNGRADE never fire.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "upgrade":
                    has_upgrade = True
                elif node.name == "downgrade":
                    has_downgrade = True
                    if _is_no_op_body(node.body):
                        out.append(
                            Finding(
                                tool="database",
                                category="empty_downgrade",
                                file=rel,
                                line=node.lineno,
                                severity="warning",
                                code="EMPTY_DOWNGRADE",
                                message=("migration `downgrade()` body is empty / pass — no rollback safety"),
                            )
                        )
        if has_upgrade and not has_downgrade:
            out.append(
                Finding(
                    tool="database",
                    category="missing_downgrade",
                    file=rel,
                    line=1,
                    severity="warning",
                    code="MISSING_DOWNGRADE",
                    message="migration declares `upgrade()` but no `downgrade()` — irreversible",
                )
            )
    return out


def _is_sql_injection_call(call: ast.Call) -> bool:
    """`x.execute(f"...{var}...")` / `cursor.execute(...) % var` etc."""
    func = call.func
    is_execute = (
        isinstance(func, ast.Attribute) and func.attr in {"execute", "executescript", "execute_many", "executemany"}
    ) or (isinstance(func, ast.Name) and func.id in {"execute", "text"})
    if not is_execute or not call.args:
        return False
    first = call.args[0]
    # f-string with at least one interpolation
    if isinstance(first, ast.JoinedStr) and any(isinstance(part, ast.FormattedValue) for part in first.values):
        return True
    # Old-style: `"... %s" % var`
    if (
        isinstance(first, ast.BinOp)
        and isinstance(first.op, ast.Mod)
        and isinstance(first.left, ast.Constant)
        and isinstance(first.left.value, str)
    ):
        return True
    # str.format(...): `"...{}...".format(var)`
    if isinstance(first, ast.Call):
        ff = first.func
        if isinstance(ff, ast.Attribute) and ff.attr == "format":
            return True
    return False


def _check_python_sql(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
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
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_sql_injection_call(node):
                out.append(
                    Finding(
                        tool="database",
                        category="sql_injection",
                        file=rel,
                        line=node.lineno,
                        severity="error",
                        code="SQL_INJECTION_FSTRING",
                        message=("`execute(...)` with f-string / %-format / .format() — use parameterised queries"),
                    )
                )
    return out


# ---- Generic SQL scan -----------------------------------------------------


_ALTER_TABLE_RE = re.compile(r"^\s*ALTER\s+TABLE\b", re.IGNORECASE)
_DROP_TABLE_RE = re.compile(r"^\s*DROP\s+TABLE\b", re.IGNORECASE)


def _check_generic_sql(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() != ".sql":
            continue
        if _is_migration_path(path):
            continue  # ALTER/DROP in migration files is the intended location
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        for line_idx, line in enumerate(text.splitlines(), start=1):
            if _ALTER_TABLE_RE.match(line):
                out.append(
                    Finding(
                        tool="database",
                        category="schema_change_outside_migration",
                        file=rel,
                        line=line_idx,
                        severity="warning",
                        code="ALTER_TABLE_OUTSIDE_MIGRATION",
                        message="`ALTER TABLE` outside a migrations/ tree — verify intent",
                    )
                )
            elif _DROP_TABLE_RE.match(line):
                out.append(
                    Finding(
                        tool="database",
                        category="schema_change_outside_migration",
                        file=rel,
                        line=line_idx,
                        severity="warning",
                        code="DROP_TABLE_OUTSIDE_MIGRATION",
                        message="`DROP TABLE` outside a migrations/ tree — destructive",
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
    findings.extend(_check_migrations(repo_root, all_files))
    findings.extend(_check_python_sql(repo_root, all_files))
    findings.extend(_check_generic_sql(repo_root, all_files))
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
        description="Step 15 — Database / query / migration correctness.",
        prog="database",
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
    out_path = out_dir / f"{payload['timestamp']}-database.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
