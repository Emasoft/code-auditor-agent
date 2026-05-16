#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 7 — Multi-tenant data-isolation scanner (TRDD-7e364ace cluster N11).

Deterministic detection of the four most common multi-tenancy bugs:

1. **Query predicates missing the tenant column** — SQLAlchemy
   `.filter_by(user_id=...)` / Django `.filter(user=...)` / Prisma
   `where: { userId: ... }` / raw `WHERE user_id = ?` calls that never
   mention `tenant_id` / `org_id` / `workspace_id` / `account_id` in
   the same line OR the 2-line window above. These are the classic
   "we forgot the tenant filter" bugs that let user A's records leak
   into user B's tenant.

2. **Cache keys without tenant scoping** — `cache.get(f"user:{user_id}")`,
   `redis.get(f"sess:{id}")`, etc. without a tenant marker anywhere in
   the format string. Cross-tenant cache poisoning is a high-impact
   silent bug.

3. **Module-level mutable state** — top-level mutable containers
   (`CACHE: dict = {}`, `SESSIONS = []`, `STATE = {...}`) inside an
   application module. These accumulate per-tenant data on a singleton
   that survives across requests, mixing tenants.

4. **Function signatures requiring tenant_id** — when a function takes
   `user_id` but not `tenant_id`/`org_id`/`workspace_id`, flag the
   signature. The agent confirms by reading the function body.

The script gates on the Step-0 `multi_tenant` domain flag if a
`domains_detected.json` is supplied — if multi-tenancy isn't detected
the scanner emits zero findings without scanning. (Without the flag
it scans everything; downstream agents filter as needed.)

Usage:
    python -m scripts.prereview.multi_tenant <repo_root> <out_dir>
        [--pr-files-from <txt>] [--domains-from <json>]
"""

from __future__ import annotations

import argparse
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
CONTEXT_WINDOW_LINES = 2  # lines above/below the trigger to scan for tenant_id

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
        ".terraform",
        ".pulumi",
        ".gradle",
        ".cargo",
    }
)

_TENANT_MARKERS: tuple[str, ...] = (
    "tenant_id",
    "tenantId",
    "org_id",
    "orgId",
    "organization_id",
    "organizationId",
    "workspace_id",
    "workspaceId",
    "account_id",
    "accountId",
    "tenant",  # plain `tenant` keyword (Django: `tenant=request.tenant`)
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


# ---- Pattern bank ---------------------------------------------------------


# Query-predicate triggers: each tuple is (regex, code-suffix-hint).
# The detector also captures the matched snippet so the agent has context.
_QUERY_TRIGGERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\.filter_by\([^)]*\buser_id\s*="), "SQLALCHEMY_FILTER_BY"),
    (re.compile(r"\.filter\([^)]*\buser_id\s*="), "SQLALCHEMY_FILTER"),
    (re.compile(r"\.objects\.filter\([^)]*\buser\s*="), "DJANGO_FILTER"),
    (re.compile(r"\.where\(\s*\{?\s*userId\b"), "KYSELY_WHERE"),
    (re.compile(r"where\s*:\s*\{\s*[^}]*userId\b"), "PRISMA_WHERE"),
    (re.compile(r"WHERE\s+\w*user_id\s*[=<>]"), "RAW_SQL_WHERE_USER"),
)

# Cache-API triggers. `cache.get(...)`, `redis.get(...)`, etc.
_CACHE_TRIGGERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:cache|redis|memcache|mc|kv|store)\.(?:get|set|delete|hget|hset|setex)\("),
    re.compile(r"\b(?:Cache|Redis)\.(?:get|set|delete)\("),
    re.compile(r"\bredisClient\.(?:get|set|hGet|hSet|setEx)\("),
)

# Module-level mutable state — top-level (column 0) assignment to a
# mutable container literal. Pattern intentionally restrictive to keep
# false-positive rate low: must be a bare name + `=` + `{`/`[`/`set()`/
# `dict()`/`list()` (not nested inside a function).
_MODULE_STATE_RE = re.compile(
    r"^(?P<name>[A-Z_][A-Z0-9_]+|[a-z][a-z0-9_]*)"
    r"(?:\s*:\s*[\w\[\]\., ]+)?"
    r"\s*=\s*(?:\{\s*\}|\[\s*\]|set\(\s*\)|dict\(\s*\)|list\(\s*\)|\{[^}]*:[^}]*\}|\[[^\]]+\])"
    r"\s*(?:#.*)?$"
)

# Function-signature trigger: a def/function/fn that takes user_id but
# might not take tenant_id. We just capture the def line; the body
# check is delegated to the agent (too brittle to AST-walk every
# language). Python, JS/TS arrow, Go function syntax.
_FUNC_SIG_TRIGGERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^def\s+\w+\s*\([^)]*\buser_id\b"),
    re.compile(r"^async\s+def\s+\w+\s*\([^)]*\buser_id\b"),
    re.compile(r"function\s+\w+\s*\([^)]*\buserId\b"),
    re.compile(r"\bfn\s+\w+\s*\([^)]*\buser_id\b"),
)


# ---- File enumeration ------------------------------------------------------


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


def _load_domains(path: Path | None) -> dict[str, dict[str, object]] | None:
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"--domains-from: not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "domains" not in data:
        raise ValueError(f"--domains-from: not a Step-0 domains_detected.json: {path}")
    return data["domains"]


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


# ---- Checks ---------------------------------------------------------------


def _context_window(lines: list[str], idx: int) -> str:
    """Return the joined context around index idx (inclusive)."""
    lo = max(0, idx - CONTEXT_WINDOW_LINES)
    hi = min(len(lines), idx + CONTEXT_WINDOW_LINES + 1)
    return "\n".join(lines[lo:hi])


def _has_tenant_marker(text: str) -> bool:
    return any(marker in text for marker in _TENANT_MARKERS)


def _check_queries(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".sql"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        lines = text.splitlines()
        rel = _rel(repo_root, path)
        for line_idx, line in enumerate(lines):
            for trigger_re, code_hint in _QUERY_TRIGGERS:
                m = trigger_re.search(line)
                if not m:
                    continue
                context = _context_window(lines, line_idx)
                if _has_tenant_marker(context):
                    continue
                out.append(
                    Finding(
                        tool="multi_tenant",
                        category="query_missing_tenant",
                        file=rel,
                        line=line_idx + 1,
                        severity="warning",
                        code=code_hint,
                        message=(
                            f"Query predicate filters on user but no tenant_id/"
                            f"org_id/workspace_id seen within ±{CONTEXT_WINDOW_LINES} lines: "
                            f"{line.strip()[:120]}"
                        ),
                    )
                )
    return out


def _check_cache_keys(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        lines = text.splitlines()
        rel = _rel(repo_root, path)
        for line_idx, line in enumerate(lines):
            for trigger_re in _CACHE_TRIGGERS:
                m = trigger_re.search(line)
                if not m:
                    continue
                # If the same line already includes a tenant marker, skip.
                if _has_tenant_marker(line):
                    continue
                # Also accept tenant markers in the immediate preceding line
                # (e.g. `key = f"{tenant_id}:..."` on the line above).
                context = _context_window(lines, line_idx)
                if _has_tenant_marker(context):
                    continue
                # Cache lines that don't look like they hold per-user data
                # (e.g. `cache.delete(global_key)`) are still flagged — the
                # agent reads the broader context to confirm.
                out.append(
                    Finding(
                        tool="multi_tenant",
                        category="cache_key_missing_tenant",
                        file=rel,
                        line=line_idx + 1,
                        severity="warning",
                        code="CACHE_KEY_NO_TENANT",
                        message=(
                            f"Cache API call without tenant_id in key (line or ±{CONTEXT_WINDOW_LINES}): "
                            f"{line.strip()[:120]}"
                        ),
                    )
                )
                break  # one finding per line is enough
    return out


def _check_module_state(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        lines = text.splitlines()
        rel = _rel(repo_root, path)
        in_function = False  # crude — track indented `def` / `function` blocks
        function_indent = -1
        for line_idx, raw in enumerate(lines):
            line = raw.rstrip()
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            # Crude function-scope tracker: any `def `/`function `/`async def`
            # at any indent opens a function scope; we close it when we see
            # a top-level line again.
            if stripped.startswith(("def ", "async def ", "function ", "fn ")):
                in_function = True
                function_indent = indent
                continue
            if in_function and indent <= function_indent and stripped:
                in_function = False
            if in_function or indent > 0:
                continue
            m = _MODULE_STATE_RE.match(line)
            if not m:
                continue
            name = m.group("name")
            # Filter out obvious non-state names: ALLCAPS constants of
            # immutable shape (single-value dict/list literals look mutable
            # but are arguably config). Conservatism: only flag when the
            # initialiser is genuinely an EMPTY container — empty dicts/
            # lists/sets are the strongest module-state smell because they
            # MUST be filled at runtime, almost always per-tenant.
            initialiser = line.split("=", 1)[1].strip().rstrip("#").strip()
            empty_initialisers = {"{}", "[]", "set()", "dict()", "list()"}
            if initialiser.split("#", 1)[0].strip() not in empty_initialisers:
                continue
            out.append(
                Finding(
                    tool="multi_tenant",
                    category="module_level_mutable_state",
                    file=rel,
                    line=line_idx + 1,
                    severity="nit",
                    code="MODULE_STATE",
                    message=(
                        f"Top-level mutable container '{name}' may accumulate cross-tenant data; "
                        f"verify it is scoped per-tenant or rebuilt per-request"
                    ),
                )
            )
    return out


def _check_function_signatures(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        lines = text.splitlines()
        rel = _rel(repo_root, path)
        for line_idx, line in enumerate(lines):
            for trigger_re in _FUNC_SIG_TRIGGERS:
                m = trigger_re.search(line)
                if not m:
                    continue
                if _has_tenant_marker(line):
                    continue
                # Look at the next 8 lines for tenant_id (continuation lines
                # of the signature, or right inside the body).
                window = "\n".join(lines[line_idx : line_idx + 8])
                if _has_tenant_marker(window):
                    continue
                out.append(
                    Finding(
                        tool="multi_tenant",
                        category="function_takes_user_not_tenant",
                        file=rel,
                        line=line_idx + 1,
                        severity="nit",
                        code="FN_SIG_NO_TENANT",
                        message=(
                            f"Function signature accepts user_id but not tenant_id/"
                            f"org_id/workspace_id within 8 lines: {line.strip()[:120]}"
                        ),
                    )
                )
                break
    return out


# ---- Driver ---------------------------------------------------------------


def _local_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S%z", time.localtime())


def detect(
    repo_root: Path,
    pr_files: list[Path] | None = None,
    domains: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    if not repo_root.is_dir():
        raise NotADirectoryError(f"repo_root is not a directory: {repo_root}")
    # If domains is supplied AND the multi_tenant flag is False, emit an
    # empty report with the "skipped: multi_tenant not detected" reason.
    gated_off = False
    if domains is not None:
        mt = domains.get("multi_tenant") or {}
        if not mt.get("detected"):
            gated_off = True
    findings: list[Finding] = []
    if not gated_off:
        all_files = pr_files if pr_files is not None else _enumerate_repo(repo_root)
        findings.extend(_check_queries(repo_root, all_files))
        findings.extend(_check_cache_keys(repo_root, all_files))
        findings.extend(_check_module_state(repo_root, all_files))
        findings.extend(_check_function_signatures(repo_root, all_files))
        findings.sort(key=lambda f: (f.category, f.file, f.line, f.code))
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "repo_root": str(repo_root.resolve()),
        "gated_off_multi_tenant_not_detected": gated_off,
        "total_findings": len(findings),
        "by_category": dict(sorted(by_category.items())),
        "findings": [asdict(f) for f in findings],
    }


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 7 — Multi-tenant data-isolation scanner.",
        prog="multi_tenant",
    )
    parser.add_argument("repo_root", help="Absolute path to the repository to scan.")
    parser.add_argument("out_dir", help="Where the JSON report is written.")
    parser.add_argument(
        "--pr-files-from",
        help="Optional file: each line is a repo-relative path of a PR-touched file.",
    )
    parser.add_argument(
        "--domains-from",
        help="Path to a Step-0 domains_detected.json. Used to gate the scanner.",
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
        domains = _load_domains(Path(args.domains_from) if args.domains_from else None)
        payload = detect(repo_root, pr_files, domains)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = out_dir / f"{payload['timestamp']}-multi_tenant.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
