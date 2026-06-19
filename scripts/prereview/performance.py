#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 14 — Performance / memory / energy scanner (TRDD-7e364ace P1-P5, N5).

Detect the high-ROI performance smells a regex/AST pass can catch:

PYTHON (`ast.parse`):
- `N_PLUS_ONE_LOOP` — a database-shaped call (`*.query(`, `*.filter(`,
  `*.objects.get(`, `.objects.filter(`, `.fetch(`, `.aggregate(`,
  `.findOne(`, `.find_one(`, `session.query(`) appears INSIDE a
  `For`/`While` loop body. Classic N+1 anti-pattern.
- `RECURSIVE_NO_MEMO` — a function that calls itself by name and is
  NOT decorated with `@functools.cache` / `@functools.lru_cache` /
  `@cache` / `@lru_cache`. Heuristic: pure mathematical recursion
  almost always wants memoisation.
- `LARGE_FILE_FULL_READ` — `open(...).read()`, `pathlib.Path(...).read_text()`,
  `path.read_bytes()` where the file path name strongly suggests a
  large/streaming input (`*.log`, `*.csv`, `*.jsonl`, `*.ndjson`,
  `*.parquet`, `*.tsv`, `*.gz`, `*.zip`, `*.tar`). The agent confirms.

JS / TS (regex):
- `JS_N_PLUS_ONE_LOOP` — DB-shape call inside a `for`/`while`/
  `.forEach(`/`.map(` body.
- `JS_LARGE_FILE_SYNC_READ` — `fs.readFileSync(...)`,
  `readFileSync(...)`, `fs.readFile(...)` on a path that looks
  large-ish. Synchronous full-file reads block the event loop.

GO (regex):
- `GO_DB_IN_LOOP` — `db.Query`/`db.Exec`/`tx.Query`/`tx.Exec` inside
  `for` block.

Usage:
    python -m scripts.prereview.performance <repo_root> <out_dir>
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

# Attribute names that strongly suggest a DB call (Python). These are not
# exhaustive — the agent's job is to confirm. False-negative > false-positive
# in this category because every false-positive distracts the reviewer.
_PY_DB_CALL_ATTRS: frozenset[str] = frozenset(
    {
        "query",
        "filter",
        "filter_by",
        "get",
        "fetch",
        "aggregate",
        "findOne",
        "find_one",
        "find",
        "findMany",
        "find_many",
        "select",
        "execute",
        "scalar",
        "scalars",
        "first",
        "all",
    }
)

# Extension/keywords that mean "this file path is probably large".
# The extension regex is NOT anchored to end-of-string — the line that
# carries the read may continue with `.read()` etc., so we accept the
# extension followed by an optional closing quote then a non-word char.
_LARGE_FILE_NAME_RE = re.compile(
    r"\.(log|csv|tsv|jsonl|ndjson|parquet|gz|zip|tar|tgz|xml|xlsx|sqlite|db|bin)['\"]?(?=\W|$)",
    re.IGNORECASE,
)
# Left-only word boundary so `large_input.txt`, `bigData`, `BulkLoader`
# all match — agents tend to use snake_case / camelCase identifiers for
# big-data variables.
_LARGE_FILE_HINT_RE = re.compile(r"\b(large|huge|big|bulk|dataset|stream)", re.IGNORECASE)


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


# ---- Python AST -----------------------------------------------------------


def _walks_into_db_call(node: ast.AST) -> tuple[int, str] | None:
    """If `node` is a DB-shape Call, return (lineno, call_name); else None."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _PY_DB_CALL_ATTRS:
        return (getattr(node, "lineno", 0), func.attr)
    return None


def _check_n_plus_one_python(rel: str, tree: ast.Module) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        # Walk only the loop body; ignore the iterator expression itself
        # (a `.filter()` in the `for x in q.filter(...)` is not an N+1).
        for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            db = _walks_into_db_call(child)
            if db is None:
                continue
            line, call_name = db
            out.append(
                Finding(
                    tool="performance",
                    category="n_plus_one",
                    file=rel,
                    line=line,
                    severity="warning",
                    code="N_PLUS_ONE_LOOP",
                    message=(
                        f"`.{call_name}(...)` inside a loop — classic N+1 anti-pattern, "
                        f"consider batching / `select_related`"
                    ),
                )
            )
    return out


def _check_recursive_no_memo(rel: str, tree: ast.Module) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Decorated with cache?
        has_cache_decorator = False
        for dec in node.decorator_list:
            name = _decorator_name(dec)
            if name in {"cache", "lru_cache", "functools.cache", "functools.lru_cache"}:
                has_cache_decorator = True
                break
        if has_cache_decorator:
            continue
        if not _calls_self(node):
            continue
        out.append(
            Finding(
                tool="performance",
                category="recursive_no_memo",
                file=rel,
                line=node.lineno,
                severity="nit",
                code="RECURSIVE_NO_MEMO",
                message=(
                    f"function `{node.name}` calls itself but is not decorated with "
                    f"`@cache` / `@lru_cache` — verify recursion is bounded and small"
                ),
            )
        )
    return out


def _decorator_name(dec: ast.AST) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = dec
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ""


def _calls_self(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    name = func.name
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            target = n.func
            if isinstance(target, ast.Name) and target.id == name:
                return True
            if isinstance(target, ast.Attribute) and target.attr == name:
                return True
    return False


def _check_large_file_read_python(rel: str, text: str, tree: ast.Module) -> list[Finding]:
    out: list[Finding] = []
    # Look at every Call of `.read(`/`.read_text(`/`.read_bytes(`/`open(`
    # and check the surrounding line text for a large-file extension hint.
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_read_call = False
        if isinstance(func, ast.Attribute) and func.attr in {"read", "read_text", "read_bytes"}:
            is_read_call = True
        if isinstance(func, ast.Name) and func.id == "open":
            is_read_call = True
        if not is_read_call:
            continue
        line_no = getattr(node, "lineno", 1)
        line = lines[line_no - 1] if 0 <= line_no - 1 < len(lines) else ""
        if _LARGE_FILE_NAME_RE.search(line) or _LARGE_FILE_HINT_RE.search(line):
            out.append(
                Finding(
                    tool="performance",
                    category="large_file_full_read",
                    file=rel,
                    line=line_no,
                    severity="warning",
                    code="LARGE_FILE_FULL_READ",
                    message=(
                        "full-file read on a path that looks large — consider streaming "
                        "(chunked reads / iterating lines / Polars/pandas chunksize)"
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
        out.extend(_check_n_plus_one_python(rel, tree))
        out.extend(_check_recursive_no_memo(rel, tree))
        out.extend(_check_large_file_read_python(rel, text, tree))
    return out


# ---- JS / TS regex --------------------------------------------------------


_JS_DB_CALL_RE = re.compile(
    r"\b(?:db|client|conn|tx|store)\.(query|exec|execute|find|findOne|findMany|aggregate|insert|update|delete)\s*\("
    r"|\b(?:prisma|knex|sequelize|drizzle)\.[\w.]+\."
)
# Loop-head heuristic — `for(`/`while(`/`for await(` use word boundaries
# so they don't match inside identifiers; `.forEach(`/`.map(`/`.flatMap(`
# use the leading dot as a natural delimiter.
_JS_LOOP_HEAD_RE = re.compile(r"\bfor\s*\(|\bwhile\s*\(|\.forEach\s*\(|\.map\s*\(|\.flatMap\s*\(|\bfor\s+await\s*\(")
_JS_READ_SYNC_RE = re.compile(
    r"(?:fs\.|require\(['\"]fs['\"]\)\.)?(readFileSync|readFile)\s*\(\s*(?P<path>['\"][^'\"]+['\"])"
)


def _check_js_perf(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        # JS_N_PLUS_ONE_LOOP — scan for DB shape inside loop bodies by
        # brace balance.
        for m in _JS_LOOP_HEAD_RE.finditer(text):
            # Find the matching `{` that opens the body.
            i = m.end()
            while i < len(text) and text[i] not in "{;":
                i += 1
            if i >= len(text) or text[i] != "{":
                continue
            body_start = i
            depth = 0
            j = body_start
            while j < len(text):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            body = text[body_start + 1 : j]
            db_m = _JS_DB_CALL_RE.search(body)
            if db_m:
                # Line number = newlines before the db call.
                line = text.count("\n", 0, body_start + 1 + db_m.start()) + 1
                out.append(
                    Finding(
                        tool="performance",
                        category="n_plus_one",
                        file=rel,
                        line=line,
                        severity="warning",
                        code="JS_N_PLUS_ONE_LOOP",
                        message=(
                            "DB-shape call inside a `for`/`while`/`.forEach(`/`.map(` body — classic N+1 anti-pattern"
                        ),
                    )
                )
        # JS_LARGE_FILE_SYNC_READ
        for m in _JS_READ_SYNC_RE.finditer(text):
            path_lit = m.group("path")
            if not (_LARGE_FILE_NAME_RE.search(path_lit) or _LARGE_FILE_HINT_RE.search(path_lit)):
                # readFileSync without a large-file hint — still flag as a
                # warning since the SYNC variant blocks the event loop.
                line = text.count("\n", 0, m.start()) + 1
                fn_name = m.group(1)
                if fn_name.endswith("Sync"):
                    out.append(
                        Finding(
                            tool="performance",
                            category="blocking_sync_read",
                            file=rel,
                            line=line,
                            severity="nit",
                            code="JS_SYNC_FILE_READ",
                            message=f"`{fn_name}(...)` blocks the event loop — use async fs.promises form",
                        )
                    )
                continue
            line = text.count("\n", 0, m.start()) + 1
            out.append(
                Finding(
                    tool="performance",
                    category="large_file_full_read",
                    file=rel,
                    line=line,
                    severity="warning",
                    code="JS_LARGE_FILE_SYNC_READ",
                    message=(f"`{m.group(1)}(...)` on a path that looks large — stream / pipe instead"),
                )
            )
    return out


# ---- Go regex -------------------------------------------------------------


_GO_FOR_HEAD_RE = re.compile(r"^\s*for\b[^{]*\{")
_GO_DB_CALL_RE = re.compile(r"\b(?:db|tx)\.(Query|QueryContext|Exec|ExecContext|QueryRow)\s*\(")


def _check_go_perf(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() != ".go":
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        lines = text.splitlines()
        # Brace balance tracker for `for` blocks.
        in_for_depth = 0
        depth = 0
        for line_idx, raw in enumerate(lines):
            stripped = raw.strip()
            opens = raw.count("{")
            closes = raw.count("}")
            if _GO_FOR_HEAD_RE.match(raw):
                in_for_depth = depth + 1
            db_m = _GO_DB_CALL_RE.search(stripped)
            if db_m and in_for_depth > 0 and depth >= in_for_depth - 1:
                out.append(
                    Finding(
                        tool="performance",
                        category="n_plus_one",
                        file=rel,
                        line=line_idx + 1,
                        severity="warning",
                        code="GO_DB_IN_LOOP",
                        message=(f"`.{db_m.group(1)}(...)` inside `for` block — classic N+1 anti-pattern"),
                    )
                )
            depth += opens - closes
            if depth < in_for_depth:
                in_for_depth = 0
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
    findings.extend(_check_js_perf(repo_root, all_files))
    findings.extend(_check_go_perf(repo_root, all_files))
    findings.sort(key=lambda f: (f.category, f.file, f.line, f.code))
    # Dedup on (file, line, code): some checks match the same smell via two AST
    # shapes — e.g. open(...).read() hits both the .read() Attribute and the
    # inner open() Name at the same line, and a nested loop is walked once per
    # enclosing loop — inflating the very counts the tool reports.
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
        description="Step 14 — Performance / memory / energy scanner.",
        prog="performance",
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
    out_path = out_dir / f"{payload['timestamp']}-performance.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
