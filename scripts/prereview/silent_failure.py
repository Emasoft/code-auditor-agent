#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 8 — Silent-failure hunter (TRDD-7e364ace cluster J1-J11).

Static detection of error-handling code that silently swallows failures.
Python receives a proper AST walk (precise); other languages get a
conservative regex pass that prefers false-negatives over false-positives
so the agent isn't drowned in noise.

Patterns detected per language:

PYTHON (ast.parse):
- `SILENT_EMPTY` — `except ...: pass` / `except ...: ...` (body is only
  Pass or Expr(Constant=...) — i.e. the documented "swallow" form).
- `SILENT_BARE` — `except:` with no exception class. Catches even
  SystemExit and KeyboardInterrupt by accident.
- `BROAD_CATCH` — `except Exception:` / `except BaseException:`. Defensible
  in some places (CLI entry points) but worth flagging.
- `SILENT_LOG_ONLY` — handler body has at least one log/print call AND
  no raise/return/sys.exit/typer.Exit. The agent decides if "log and
  swallow" is the right pattern here.
- `TODO_IN_HANDLER` — handler body contains a TODO/FIXME/XXX comment.
  Almost always an unfinished handler.

JS / TS / GO / RUST / RUBY (regex):
- `CATCH_EMPTY` — `catch (...) { }` with whitespace-only body.
- `CATCH_CONSOLE_ONLY` — body uses only `console.error/warn/log` /
  `fmt.Println` / `eprintln!` / `puts` with no return / throw / panic /
  ?-operator.
- `OPTIONAL_CHAIN_FALLIBLE` — `?.` over a method known to throw or
  return a Result (.json, .parse, .fetch, .text, .blob, .formData).
  Optional chaining short-circuits to `undefined` rather than throwing,
  which silently hides every malformed-input bug.

Universal:
- `MOCK_FALLBACK` — `if NODE_ENV !== 'production'` (or equivalent) with
  a body that references `mock` / `stub` / `fake` / `dummy`. Bug pattern:
  prod silently runs the fallback because env detection is off.

Usage:
    python -m scripts.prereview.silent_failure <repo_root> <out_dir>
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

# Log-call shapes that mean "I'm only writing to the log, not handling".
# NOTE: matched (see `_is_log_call`) against the DOTTED CALLEE NAME — e.g. "print",
# "logger.info" — which NEVER contains "(". Each shape must therefore end at a word
# boundary (\b), not a literal "(": `^print\(` could never match the bare name
# "print", so the documented print-in-except case was silently broken.
_LOG_CALL_PATTERNS = re.compile(
    r"^(?:logger|log|logging|self\.log|self\._log|self\.logger)\.(?:debug|info|warning|warn|error|exception|critical)\b"
    r"|^print\b"
    r"|^console\.(?:error|warn|info|log|debug)\b"
    r"|^fmt\.(?:Println|Printf|Print)\b"
    r"|^eprintln!"
    r"|^println!"
    r"|^puts\s"
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


# ---- File enumeration / IO -------------------------------------------------


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


# ---- Python AST checks -----------------------------------------------------


def _node_is_log_call(node: ast.AST) -> bool:
    """Recognise `logger.error(...)`, `print(...)`, `self.log.info(...)` etc."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    # Build a dotted form: walk the .func chain.
    chain: list[str] = []
    current: ast.AST = call.func
    while isinstance(current, ast.Attribute):
        chain.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        chain.append(current.id)
    chain.reverse()
    dotted = ".".join(chain)
    return bool(_LOG_CALL_PATTERNS.match(dotted))


def _handler_body_is_only_logging(handler: ast.ExceptHandler) -> bool:
    """The body contains at least one log call and no raise/return/exit."""
    has_log = False
    for stmt in handler.body:
        if isinstance(stmt, ast.Raise | ast.Return):
            return False
        # `sys.exit(...)` / `typer.Exit(...)` count as proper propagation.
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if isinstance(call.func, ast.Attribute) and call.func.attr in {"exit", "Exit"}:
                return False
            if isinstance(call.func, ast.Name) and call.func.id in {"exit", "quit"}:
                return False
        if _node_is_log_call(stmt):
            has_log = True
    return has_log


def _handler_body_is_silent_pass(handler: ast.ExceptHandler) -> bool:
    """Body is *only* `pass`, `...`, or string-doc — the textbook 'swallow'."""
    if len(handler.body) != 1:
        return False
    stmt = handler.body[0]
    if isinstance(stmt, ast.Pass):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _is_broad_exception_type(node: ast.AST) -> bool:
    """`Exception` or `BaseException` (with or without a module qualifier)."""
    if isinstance(node, ast.Name):
        return node.id in {"Exception", "BaseException"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"Exception", "BaseException"}
    if isinstance(node, ast.Tuple):
        return any(_is_broad_exception_type(elt) for elt in node.elts)
    return False


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
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                line = handler.lineno
                if handler.type is None:
                    out.append(
                        Finding(
                            tool="silent_failure",
                            category="bare_except",
                            file=rel,
                            line=line,
                            severity="warning",
                            code="SILENT_BARE",
                            message="bare `except:` catches SystemExit/KeyboardInterrupt and hides every bug",
                        )
                    )
                elif _is_broad_exception_type(handler.type):
                    out.append(
                        Finding(
                            tool="silent_failure",
                            category="broad_except",
                            file=rel,
                            line=line,
                            severity="nit",
                            code="BROAD_CATCH",
                            message="`except Exception` / `except BaseException` is too broad — narrow or re-raise",
                        )
                    )
                if _handler_body_is_silent_pass(handler):
                    out.append(
                        Finding(
                            tool="silent_failure",
                            category="empty_handler",
                            file=rel,
                            line=line,
                            severity="warning",
                            code="SILENT_EMPTY",
                            message="exception handler body is empty (pass / ...) — failure is invisible",
                        )
                    )
                elif _handler_body_is_only_logging(handler):
                    out.append(
                        Finding(
                            tool="silent_failure",
                            category="log_only_handler",
                            file=rel,
                            line=line,
                            severity="nit",
                            code="SILENT_LOG_ONLY",
                            message="exception handler only logs — verify swallow-and-continue is intended",
                        )
                    )
                # TODO / FIXME in handler body — almost always unfinished.
                handler_text = ast.get_source_segment(text, handler) or ""
                if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", handler_text):
                    out.append(
                        Finding(
                            tool="silent_failure",
                            category="todo_in_handler",
                            file=rel,
                            line=line,
                            severity="warning",
                            code="TODO_IN_HANDLER",
                            message="exception handler carries a TODO/FIXME/XXX/HACK — unfinished error path",
                        )
                    )
    return out


# ---- JS/TS regex checks ----------------------------------------------------


_JS_CATCH_RE = re.compile(
    r"catch\s*(?:\(\s*(?P<binder>[^)]*)\s*\))?\s*\{(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
    re.DOTALL,
)
_OPTIONAL_CHAIN_RE = re.compile(r"\?\.\s*(?P<method>json|parse|fetch|text|blob|formData|JSON\.parse)\s*\(")


def _js_handler_is_silent(body: str) -> str | None:
    """Return a finding code if the catch body is suspicious, else None."""
    cleaned = re.sub(r"//.*", "", body)
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)
    stripped = cleaned.strip()
    if not stripped:
        return "CATCH_EMPTY"
    # If the body only contains console.* with no throw / return.
    if "throw " in stripped or "throw;" in stripped or "return " in stripped:
        return None
    if "process.exit" in stripped:
        return None
    # Strip statement separators.
    statements = [s.strip() for s in stripped.split(";") if s.strip()]
    if statements and all(re.match(r"^console\.(error|warn|info|log|debug)\b", s) for s in statements):
        return "CATCH_CONSOLE_ONLY"
    return None


def _check_js(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        for m in _JS_CATCH_RE.finditer(text):
            code = _js_handler_is_silent(m.group("body"))
            if code is None:
                continue
            # Line number = chars-to-match-start newline count + 1
            line = text.count("\n", 0, m.start()) + 1
            messages = {
                "CATCH_EMPTY": "JS/TS catch block is empty",
                "CATCH_CONSOLE_ONLY": "JS/TS catch block only writes to console — verify swallow is intended",
            }
            out.append(
                Finding(
                    tool="silent_failure",
                    category="empty_handler" if code == "CATCH_EMPTY" else "log_only_handler",
                    file=rel,
                    line=line,
                    severity="warning" if code == "CATCH_EMPTY" else "nit",
                    code=code,
                    message=messages[code],
                )
            )
        for m in _OPTIONAL_CHAIN_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            out.append(
                Finding(
                    tool="silent_failure",
                    category="optional_chain_fallible",
                    file=rel,
                    line=line,
                    severity="nit",
                    code="OPTIONAL_CHAIN_FALLIBLE",
                    message=(
                        f"`?.{m.group('method')}()` silently short-circuits — fallible calls should "
                        f"raise / return Result"
                    ),
                )
            )
    return out


# ---- Mock-in-prod fallback (universal) -------------------------------------


# A relaxed pattern that catches:
#   if NODE_ENV !== 'production' { ... mock ... }
#   if process.env.NODE_ENV !== "production": ... mock ...
#   if os.environ.get("ENV") != "prod": ... mock ...
_MOCK_FALLBACK_HEAD = re.compile(
    r"""(?:if\s*\(?\s*(?:process\.env\.NODE_ENV|os\.environ\[?["']ENV["']\]?|os\.environ\.get\(["']ENV["']\)|NODE_ENV)
    \s*(?:!==|!=|<>)\s*["'](?:production|prod)["']\s*\)?)""",
    re.VERBOSE | re.IGNORECASE,
)


def _check_mock_fallback(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        lines = text.splitlines()
        for line_idx, line in enumerate(lines):
            m = _MOCK_FALLBACK_HEAD.search(line)
            if not m:
                continue
            # Look at the next 10 lines for a mock/stub/fake/dummy reference.
            window = "\n".join(lines[line_idx : line_idx + 10])
            # Left-only word boundary so `mockApi` / `fake_api` / `FakeService`
            # still match. A strict `\bmock\b` would miss every camel-case or
            # snake-case identifier — exactly the shapes that mock fallbacks
            # use in the wild.
            if re.search(r"\b(mock|stub|fake|dummy)", window, re.IGNORECASE):
                out.append(
                    Finding(
                        tool="silent_failure",
                        category="mock_in_prod_fallback",
                        file=rel,
                        line=line_idx + 1,
                        severity="warning",
                        code="MOCK_FALLBACK",
                        message=(
                            "env-conditional branch references a mock/stub/fake — "
                            "verify production cannot accidentally enter this branch"
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
    findings.extend(_check_python(repo_root, all_files))
    findings.extend(_check_js(repo_root, all_files))
    findings.extend(_check_mock_fallback(repo_root, all_files))
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
        description="Step 8 — Silent-failure hunter.",
        prog="silent_failure",
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
    out_path = out_dir / f"{payload['timestamp']}-silent_failure.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
