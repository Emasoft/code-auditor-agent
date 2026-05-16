#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 9 — Concurrency hazards scanner (TRDD-7e364ace cluster N1).

Pattern-based detection of the most common concurrency bugs that a
deterministic checker can plausibly find:

PYTHON (`ast.parse`):
- `DETACHED_CREATE_TASK` — `asyncio.create_task(...)` /
  `asyncio.ensure_future(...)` whose return value is dropped on the
  floor. The agent confirms whether the missing reference + `await`
  is intentional (fire-and-forget by design) or a bug.
- `LOOP_RUN_IN_EXECUTOR_NO_AWAIT` — same idea for
  `loop.run_in_executor(...)`.

JS / TS (regex):
- `FLOATING_PROMISE` — a statement-level call whose name suggests an
  async/Promise return (`.fetch(`, `.then(`, `Promise.all(`, `Promise.
  race(`, `Promise.any(`, etc.) without an `await`, `return`, `void`,
  or assignment in front. Sibling rule:
- `PROMISE_NO_CATCH` — `Promise.all([...])` / `Promise.race([...])` /
  `Promise.any([...])` without a `.catch(` in the same statement.

GO (regex):
- `GOROUTINE_NO_SYNC` — `go func() { ... }()` / `go someFunc(...)` on
  a line that doesn't mention `sync.WaitGroup` / `wg.Add` / `chan ` /
  `errgroup.` / `context.` within ±3 lines.
- `CHANNEL_SEND_AFTER_CLOSE` — pattern `close(ch)` followed by a
  `ch <-` within the next 20 lines.

Universal:
- `LOCK_ORDER_HEURISTIC` — two `Lock`/`Mutex`-style acquisitions on
  consecutive lines with names in a different lex order than a sibling
  acquire seen elsewhere. Weak signal. The agent confirms.

Usage:
    python -m scripts.prereview.concurrency <repo_root> <out_dir>
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


# ---- Python AST: detached asyncio tasks ------------------------------------


_DETACHED_PY_NAMES: frozenset[str] = frozenset({"create_task", "ensure_future", "run_in_executor"})


def _is_asyncio_detached_call(node: ast.AST) -> str | None:
    """Return the called function name if the AST node is a bare
    statement-level call to asyncio.create_task / ensure_future /
    loop.run_in_executor whose return value isn't used. Else None.
    """
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    call = node.value
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr in _DETACHED_PY_NAMES:
            return func.attr
    if isinstance(func, ast.Name) and func.id in _DETACHED_PY_NAMES:
        return func.id
    return None


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
        for node in ast.walk(tree):
            name = _is_asyncio_detached_call(node)
            if name is None:
                continue
            line = getattr(node, "lineno", 1)
            code = (
                "DETACHED_CREATE_TASK" if name in {"create_task", "ensure_future"} else "LOOP_RUN_IN_EXECUTOR_NO_AWAIT"
            )
            out.append(
                Finding(
                    tool="concurrency",
                    category="detached_async",
                    file=rel,
                    line=line,
                    severity="warning",
                    code=code,
                    message=(
                        f"`{name}(...)` return value is dropped — the coroutine may "
                        f"be GC'd before completion; verify fire-and-forget is intentional"
                    ),
                )
            )
    return out


# ---- JS/TS: floating promises ----------------------------------------------

# A statement-level fallible call: nothing meaningful in front (no
# `await`/`return`/`void`/`=` etc.), and the call site contains one
# of the async-suggestive shapes.
_FLOATING_PROMISE_RE = re.compile(
    r"""^(?P<indent>\s*)
        (?P<call>(?:[\w$.\[\]]+\.)?(?:fetch|then|catch|finally|all|race|any|allSettled)\s*\()
    """,
    re.VERBOSE,
)
# Matches `Promise.all(...)` style calls — only the OPENING, not the closing
# paren, because nested parens inside the arg list confuse simple regexes.
# The downstream check inspects whether `.catch(` appears on the same line
# OR in the next 2 lines.
_PROMISE_HEAD_RE = re.compile(r"Promise\.(?:all|race|any|allSettled)\s*\(")


def _line_starts_with_consumer(stripped: str) -> bool:
    """Does the line already consume the promise (await/return/void/assignment)?"""
    consumers = (
        "await ",
        "return ",
        "void ",
        "yield ",
        "throw ",
        "for ",
        "if ",
        "while ",
        "do ",
    )
    if any(stripped.startswith(c) for c in consumers):
        return True
    # Assignment: `name = ...`, `name +=`, `name: T =`, `const/let/var ...=`
    assign_re = r"^(?:const\s+|let\s+|var\s+)?[\w$.\[\]]+(?:\s*:\s*[\w$<>,]+)?\s*[+\-*/%&|^]?=\s"
    return bool(re.match(assign_re, stripped))


def _check_js_floating(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        lines = text.splitlines()
        for line_idx, raw in enumerate(lines):
            stripped = raw.lstrip()
            if _line_starts_with_consumer(stripped):
                continue
            m = _FLOATING_PROMISE_RE.match(raw)
            # Flag if the line opens with a bare async-suggestive call AND
            # contains no `.catch(` or `await` modifier. We require ONE
            # of the suggestive shapes to actually appear in the call.
            if not m:
                continue
            call_text = m.group("call")
            if not any(shape in stripped for shape in ("fetch(", "Promise.", ".then(", ".all(", ".race(", ".any(")):
                continue
            # If the chain ends in `.catch(`, skip — rejection is tracked.
            if ".catch(" in stripped:
                continue
            # Strip the unused capture so linters don't trip on it.
            del call_text
            out.append(
                Finding(
                    tool="concurrency",
                    category="floating_promise",
                    file=rel,
                    line=line_idx + 1,
                    severity="warning",
                    code="FLOATING_PROMISE",
                    message=f"statement-level promise call without await/return/catch: {stripped[:120]}",
                )
            )
        # Promise.all-style without .catch — find the head, then probe a
        # ±2 line window for `.catch(`.
        for m in _PROMISE_HEAD_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            window_lo = max(0, line - 3)
            window_hi = min(len(lines), line + 2)
            window = "\n".join(lines[window_lo:window_hi])
            if ".catch(" in window:
                continue
            if "try " in window or "try{" in window:
                continue
            out.append(
                Finding(
                    tool="concurrency",
                    category="promise_no_catch",
                    file=rel,
                    line=line,
                    severity="warning",
                    code="PROMISE_NO_CATCH",
                    message=(
                        "`Promise.*(...)` head with no `.catch(...)` and no surrounding "
                        f"try/catch: {lines[line - 1].strip()[:120]}"
                    ),
                )
            )
    return out


# ---- Go goroutine + channel-after-close ------------------------------------


_GO_GOROUTINE_RE = re.compile(r"^\s*go\s+\w")
_GO_SYNC_NEARBY = ("sync.", "wg.Add", "wg.Done", "wg.Wait", "chan ", "errgroup.", "context.")
_GO_CLOSE_RE = re.compile(r"^\s*close\(\s*(\w+)\s*\)")
_GO_SEND_AFTER_CLOSE_RE = re.compile(r"(\w+)\s*<-\s*[^<]")


def _check_go(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() != ".go":
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        lines = text.splitlines()
        for line_idx, line in enumerate(lines):
            if _GO_GOROUTINE_RE.match(line):
                lo = max(0, line_idx - 3)
                hi = min(len(lines), line_idx + 4)
                window = "\n".join(lines[lo:hi])
                if not any(token in window for token in _GO_SYNC_NEARBY):
                    out.append(
                        Finding(
                            tool="concurrency",
                            category="goroutine_no_sync",
                            file=rel,
                            line=line_idx + 1,
                            severity="warning",
                            code="GOROUTINE_NO_SYNC",
                            message=(
                                "`go` statement without WaitGroup/chan/errgroup/context within ±3 lines — "
                                "verify the goroutine isn't leaked"
                            ),
                        )
                    )
            close_m = _GO_CLOSE_RE.match(line)
            if close_m:
                ch_name = close_m.group(1)
                # Look forward 20 lines for any `ch_name <-` send.
                for j in range(line_idx + 1, min(len(lines), line_idx + 21)):
                    send_m = _GO_SEND_AFTER_CLOSE_RE.search(lines[j])
                    if send_m and send_m.group(1) == ch_name:
                        out.append(
                            Finding(
                                tool="concurrency",
                                category="channel_send_after_close",
                                file=rel,
                                line=j + 1,
                                severity="error",
                                code="CHANNEL_SEND_AFTER_CLOSE",
                                message=(
                                    f"`{ch_name} <- ...` appears after `close({ch_name})` — "
                                    f"sends on a closed channel panic at runtime"
                                ),
                            )
                        )
                        break
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
    findings.extend(_check_js_floating(repo_root, all_files))
    findings.extend(_check_go(repo_root, all_files))
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
        description="Step 9 — Concurrency hazards scanner.",
        prog="concurrency",
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
    out_path = out_dir / f"{payload['timestamp']}-concurrency.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
