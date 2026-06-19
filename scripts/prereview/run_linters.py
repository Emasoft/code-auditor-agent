#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 5 — Linter & scanner pre-flight wrapper (TRDD-7e364ace).

Runs every external static analyzer that's available on the machine —
ruff, mypy, bandit, pip-audit, eslint, biome, hadolint, markdownlint,
sqlfluff, codespell, gitleaks, trufflehog, semgrep, govet, govulncheck,
clippy, trivy, npm-audit — against the PR-touched files only, parses
each tool's native output (JSON when supported, line-format fall-back
otherwise), normalises every finding to a single schema, and emits one
JSON report. Downstream agents Read this JSON instead of re-running
the tools themselves.

The wrapper is deliberately tolerant:

- Missing tools are SKIPPED, never errored. The `tools_skipped` block
  records which tools weren't available and why, so a downstream agent
  can decide whether to flag "missing infrastructure" as a finding.
- A tool that exits non-zero is still parsed for findings — most
  linters use exit 1 to mean "issues found", not "I crashed".
- Per-tool runtime is capped at 300s. A tool that hangs is reported as
  skipped with `reason="timeout"`. The pipeline carries on.

Usage:
    python -m scripts.prereview.run_linters <repo_root> <out_dir>
        [--pr-files-from <txt>] [--domains-from <json>] [--tools t1,t2]

When `--pr-files-from` is omitted the wrapper lints every supported
file under `repo_root`. When `--domains-from` is given (output of the
Step-0 gate) tools whose language gate isn't satisfied are skipped
silently (no `tools_skipped` row — the gate is the reason).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

SCHEMA_VERSION = 1
TOOL_TIMEOUT_SECONDS = 300
PARALLEL_WORKERS = 8

# Common file groupings (extension → "domain key" used by tool gates).
_EXT_PYTHON = frozenset({".py", ".pyi"})
_EXT_JS = frozenset({".js", ".mjs", ".cjs", ".jsx"})
_EXT_TS = frozenset({".ts", ".tsx", ".mts", ".cts"})
_EXT_GO = frozenset({".go"})
_EXT_RUST = frozenset({".rs"})
_EXT_MD = frozenset({".md", ".markdown"})
_EXT_SQL = frozenset({".sql"})
_EXT_DOCKER = frozenset({"Dockerfile"})  # special: matched by name, not extension


@dataclass(frozen=True, slots=True)
class Finding:
    """Normalised single finding from any tool."""

    tool: str
    file: str
    line: int
    column: int
    severity: str  # error / warning / info / nit
    code: str
    message: str


# Map every external tool's severity vocabulary onto the documented 4-value enum.
# Without this, out-of-enum values leak through (bandit high/medium/low, mypy/
# clippy note/help, semgrep inventory/experimental, biome information) and any
# downstream filter or threshold keyed on the contract mis-handles them.
_SEVERITY_ALIASES = {
    "error": "error", "fatal": "error", "critical": "error", "high": "error",
    "warning": "warning", "warn": "warning", "medium": "warning", "moderate": "warning",
    "info": "info", "information": "info", "informational": "info", "note": "info",
    "help": "info", "hint": "info", "low": "info", "minor": "info",
    "convention": "info", "style": "info", "refactor": "info",
    "inventory": "info", "experimental": "info",
    "nit": "nit",
}


def _normalize_severity(raw: str) -> str:
    """Map any tool severity onto error/warning/info/nit; unknown → warning."""
    return _SEVERITY_ALIASES.get(raw.strip().lower(), "warning")


@dataclass(slots=True)
class _ToolRun:
    """Result of running one tool. Carries findings AND status."""

    name: str
    available: bool
    skipped_reason: str | None
    findings: list[Finding] = field(default_factory=list)
    raw_stderr_excerpt: str = ""
    duration_ms: int = 0


# A tool spec is a small immutable record.
@dataclass(frozen=True, slots=True)
class _Tool:
    name: str
    executable: str
    build_argv: Callable[[list[Path]], list[str]]
    parser: Callable[[str, str], list[Finding]]  # (stdout, stderr) → findings
    # If non-empty, only run when at least one matching file exists.
    matches_extensions: frozenset[str] = frozenset()
    # If non-empty, the matching file must be named one of these. Used by
    # Dockerfile-style tools whose target has no extension.
    matches_basenames: frozenset[str] = frozenset()
    # Language(s) one of which must be present per Step 0 gate. Empty = no gate.
    language_gate: tuple[str, ...] = ()


# ---- Parsers (one per output format) ---------------------------------------


def _parse_ruff_json(stdout: str, _stderr: str) -> list[Finding]:
    """ruff --output-format json."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out
    for entry in data:
        out.append(
            Finding(
                tool="ruff",
                file=entry.get("filename", ""),
                line=int(entry.get("location", {}).get("row", 0)),
                column=int(entry.get("location", {}).get("column", 0)),
                severity="error" if entry.get("fix") is None else "warning",
                code=entry.get("code", ""),
                message=entry.get("message", ""),
            )
        )
    return out


def _parse_mypy_text(stdout: str, _stderr: str) -> list[Finding]:
    """mypy default output: `file.py:42:5: error: <msg> [code]`."""
    pattern = re.compile(
        r"^(?P<file>[^:]+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<sev>error|warning|note):\s*"
        r"(?P<msg>.+?)(?:\s*\[(?P<code>[^\]]+)\])?\s*$"
    )
    out: list[Finding] = []
    for line in stdout.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        out.append(
            Finding(
                tool="mypy",
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col") or 0),
                severity=m.group("sev"),
                code=m.group("code") or "",
                message=m.group("msg").strip(),
            )
        )
    return out


def _parse_eslint_json(stdout: str, _stderr: str) -> list[Finding]:
    """eslint -f json: list of files with messages[]."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out
    for file_block in data:
        fname = file_block.get("filePath", "")
        for msg in file_block.get("messages", []):
            severity_n = int(msg.get("severity", 1))
            severity = "error" if severity_n >= 2 else "warning"
            out.append(
                Finding(
                    tool="eslint",
                    file=fname,
                    line=int(msg.get("line", 0)),
                    column=int(msg.get("column", 0)),
                    severity=severity,
                    code=msg.get("ruleId") or "",
                    message=msg.get("message", ""),
                )
            )
    return out


def _byte_offset_to_line_col(file_path: str, byte_offset: int) -> tuple[int, int]:
    """Convert a 0-based UTF-8 byte offset (biome's TextRange) to a 1-based
    (line, column). Returns (0, 0) when the file can't be read — an explicit
    'unknown' beats a misleading byte offset reported as a line number."""
    if byte_offset < 0:
        return 0, 0
    try:
        data = Path(file_path).read_bytes()
    except OSError:
        return 0, 0
    chunk = data[:byte_offset]
    line = chunk.count(b"\n") + 1
    col = byte_offset - (chunk.rfind(b"\n") + 1) + 1
    return line, col


def _parse_biome_json(stdout: str, _stderr: str) -> list[Finding]:
    """biome --reporter json."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    diagnostics = data.get("diagnostics", []) if isinstance(data, dict) else []
    for d in diagnostics:
        loc = d.get("location", {}) or {}
        span = loc.get("span", [0, 0]) or [0, 0]
        file_path = loc.get("path", {}).get("file", "")
        # biome's span is [startByteOffset, endByteOffset] (a UTF-8 TextRange),
        # NOT [line, column] — the old code reported the raw byte offset as a
        # line number. Convert it to a real line/column by reading the file.
        line, column = _byte_offset_to_line_col(file_path, int(span[0]) if span else 0)
        out.append(
            Finding(
                tool="biome",
                file=file_path,
                line=line,
                column=column,
                severity=str(d.get("severity", "warning")).lower(),
                code=str(d.get("category", "")),
                message=str(d.get("description", "")),
            )
        )
    return out


def _parse_hadolint_json(stdout: str, _stderr: str) -> list[Finding]:
    """hadolint -f json."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out
    for entry in data:
        out.append(
            Finding(
                tool="hadolint",
                file=entry.get("file", ""),
                line=int(entry.get("line", 0)),
                column=int(entry.get("column", 0)),
                severity=str(entry.get("level", "warning")).lower(),
                code=entry.get("code", ""),
                message=entry.get("message", ""),
            )
        )
    return out


def _parse_markdownlint_json(stdout: str, _stderr: str) -> list[Finding]:
    """markdownlint --output (.json) or markdownlint-cli2 --json.

    Tries the cli2 schema first (object keyed by file), then falls back to
    the v1 list-of-entries schema.
    """
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    if isinstance(data, dict):
        for fname, entries in data.items():
            if not isinstance(entries, list):
                continue
            for e in entries:
                out.append(
                    Finding(
                        tool="markdownlint",
                        file=fname,
                        line=int(e.get("lineNumber", 0)),
                        column=0,
                        severity="warning",
                        code=",".join(e.get("ruleNames", [])),
                        message=str(e.get("ruleDescription", "")),
                    )
                )
    elif isinstance(data, list):
        for e in data:
            out.append(
                Finding(
                    tool="markdownlint",
                    file=e.get("fileName", ""),
                    line=int(e.get("lineNumber", 0)),
                    column=0,
                    severity="warning",
                    code=",".join(e.get("ruleNames", [])),
                    message=str(e.get("ruleDescription", "")),
                )
            )
    return out


def _parse_sqlfluff_json(stdout: str, _stderr: str) -> list[Finding]:
    """sqlfluff lint --format json."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out
    for file_block in data:
        fname = file_block.get("filepath", "")
        for v in file_block.get("violations", []):
            out.append(
                Finding(
                    tool="sqlfluff",
                    file=fname,
                    line=int(v.get("line_no", 0)),
                    column=int(v.get("line_pos", 0)),
                    severity="warning",
                    code=str(v.get("code", "")),
                    message=str(v.get("description", "")),
                )
            )
    return out


def _parse_gitleaks_json(stdout: str, _stderr: str) -> list[Finding]:
    """gitleaks detect --report-format json."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out
    for e in data:
        out.append(
            Finding(
                tool="gitleaks",
                file=e.get("File", ""),
                line=int(e.get("StartLine", 0)),
                column=int(e.get("StartColumn", 0)),
                severity="error",
                code=str(e.get("RuleID", "")),
                message=str(e.get("Description", "")),
            )
        )
    return out


def _parse_semgrep_json(stdout: str, _stderr: str) -> list[Finding]:
    """semgrep --json: top-level `results` list."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    for r in data.get("results", []) if isinstance(data, dict) else []:
        start = r.get("start", {}) or {}
        sev_raw = (r.get("extra", {}) or {}).get("severity", "WARNING")
        out.append(
            Finding(
                tool="semgrep",
                file=r.get("path", ""),
                line=int(start.get("line", 0)),
                column=int(start.get("col", 0)),
                severity=str(sev_raw).lower(),
                code=str(r.get("check_id", "")),
                message=str((r.get("extra", {}) or {}).get("message", "")),
            )
        )
    return out


def _parse_bandit_json(stdout: str, _stderr: str) -> list[Finding]:
    """bandit -f json: top-level `results` list."""
    out: list[Finding] = []
    if not stdout.strip():
        return out
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return out
    for r in data.get("results", []) if isinstance(data, dict) else []:
        out.append(
            Finding(
                tool="bandit",
                file=r.get("filename", ""),
                line=int(r.get("line_number", 0)),
                column=int(r.get("col_offset", 0)),
                severity=str(r.get("issue_severity", "warning")).lower(),
                code=str(r.get("test_id", "")),
                message=str(r.get("issue_text", "")),
            )
        )
    return out


def _parse_govulncheck_json(stdout: str, _stderr: str) -> list[Finding]:
    """govulncheck -json emits a stream of newline-delimited messages.

    Each message has a `finding` key. We surface the vuln OSV id and the
    affected symbol/file as the message body.
    """
    out: list[Finding] = []
    for raw_line in stdout.splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        finding = payload.get("finding")
        if not finding:
            continue
        osv = finding.get("osv", "")
        for trace in finding.get("trace", []) or []:
            pos = trace.get("position", {}) or {}
            out.append(
                Finding(
                    tool="govulncheck",
                    file=pos.get("filename", ""),
                    line=int(pos.get("line", 0)),
                    column=int(pos.get("column", 0)),
                    severity="error",
                    code=osv,
                    message=f"{trace.get('function', '')} via {trace.get('module', '')}",
                )
            )
    return out


def _parse_clippy_json(stdout: str, _stderr: str) -> list[Finding]:
    """cargo clippy --message-format json: stream of messages.

    Only `compiler-message` entries are diagnostic.
    """
    out: list[Finding] = []
    for raw_line in stdout.splitlines():
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if payload.get("reason") != "compiler-message":
            continue
        msg = payload.get("message", {}) or {}
        spans = msg.get("spans", []) or []
        first_span = spans[0] if spans else {}
        out.append(
            Finding(
                tool="clippy",
                file=first_span.get("file_name", ""),
                line=int(first_span.get("line_start", 0)),
                column=int(first_span.get("column_start", 0)),
                severity=str(msg.get("level", "warning")).lower(),
                code=str((msg.get("code", {}) or {}).get("code", "")),
                message=str(msg.get("message", "")),
            )
        )
    return out


def _parse_codespell_text(stdout: str, _stderr: str) -> list[Finding]:
    """codespell default format: `path:line: word ==> suggestion`."""
    pattern = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\s*(?P<msg>.+)$")
    out: list[Finding] = []
    for line in stdout.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        out.append(
            Finding(
                tool="codespell",
                file=m.group("file"),
                line=int(m.group("line")),
                column=0,
                severity="nit",
                code="typo",
                message=m.group("msg").strip(),
            )
        )
    return out


def _parse_govet_text(stdout: str, stderr: str) -> list[Finding]:
    """go vet writes diagnostics to stderr: `file.go:line:col: msg`."""
    pattern = re.compile(r"^(?P<file>[^:]+\.go):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.+)$")
    out: list[Finding] = []
    for line in (stdout + "\n" + stderr).splitlines():
        m = pattern.match(line)
        if not m:
            continue
        out.append(
            Finding(
                tool="govet",
                file=m.group("file"),
                line=int(m.group("line")),
                column=int(m.group("col")),
                severity="error",
                code="vet",
                message=m.group("msg").strip(),
            )
        )
    return out


# ---- Tool registry ---------------------------------------------------------


def _argv_with_files(base: list[str], files: list[Path]) -> list[str]:
    return [*base, *[str(f) for f in files]]


def _ruff_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["ruff", "check", "--output-format", "json"], files)


def _mypy_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["mypy", "--show-column-numbers", "--no-pretty", "--no-error-summary"], files)


def _eslint_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["eslint", "-f", "json"], files)


def _biome_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["biome", "check", "--reporter", "json"], files)


def _hadolint_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["hadolint", "-f", "json"], files)


def _markdownlint_argv(files: list[Path]) -> list[str]:
    # The v1 markdownlint binary uses --json; v2 (cli2) uses --json too,
    # but with a different schema. The parser handles both shapes.
    return _argv_with_files(["markdownlint", "--json"], files)


def _sqlfluff_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["sqlfluff", "lint", "--format", "json"], files)


def _gitleaks_argv(files: list[Path]) -> list[str]:
    # gitleaks scans repos, not arbitrary file lists. We run it against the
    # whole repo root because `--source <file>` only works on dirs. The
    # caller still gets exactly the gitleaks coverage they'd run by hand.
    if not files:
        return ["gitleaks", "detect", "--no-banner", "--report-format", "json", "--report-path", "/dev/stdout"]
    repo_root = files[0].parts[0] if files[0].is_absolute() else "."
    return [
        "gitleaks",
        "detect",
        "--no-banner",
        "--source",
        str(repo_root),
        "--report-format",
        "json",
        "--report-path",
        "/dev/stdout",
    ]


def _semgrep_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["semgrep", "--config", "auto", "--json", "--quiet"], files)


def _bandit_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["bandit", "-q", "-f", "json"], files)


def _govulncheck_argv(_files: list[Path]) -> list[str]:
    # govulncheck wants `./...` not a file list.
    return ["govulncheck", "-json", "./..."]


def _clippy_argv(_files: list[Path]) -> list[str]:
    return ["cargo", "clippy", "--message-format", "json", "--quiet"]


def _codespell_argv(files: list[Path]) -> list[str]:
    return _argv_with_files(["codespell", "--quiet-level", "0"], files)


def _govet_argv(_files: list[Path]) -> list[str]:
    return ["go", "vet", "./..."]


# Tool registry — order shapes the order of finding emission but not detection.
_TOOLS: tuple[_Tool, ...] = (
    _Tool("ruff", "ruff", _ruff_argv, _parse_ruff_json, _EXT_PYTHON, language_gate=("python",)),
    _Tool("mypy", "mypy", _mypy_argv, _parse_mypy_text, _EXT_PYTHON, language_gate=("python",)),
    _Tool("bandit", "bandit", _bandit_argv, _parse_bandit_json, _EXT_PYTHON, language_gate=("python",)),
    _Tool(
        "eslint",
        "eslint",
        _eslint_argv,
        _parse_eslint_json,
        _EXT_JS | _EXT_TS,
        language_gate=("javascript", "typescript"),
    ),
    _Tool(
        "biome",
        "biome",
        _biome_argv,
        _parse_biome_json,
        _EXT_JS | _EXT_TS,
        language_gate=("javascript", "typescript"),
    ),
    _Tool(
        "hadolint",
        "hadolint",
        _hadolint_argv,
        _parse_hadolint_json,
        matches_basenames=_EXT_DOCKER,
    ),
    _Tool("markdownlint", "markdownlint", _markdownlint_argv, _parse_markdownlint_json, _EXT_MD),
    _Tool("sqlfluff", "sqlfluff", _sqlfluff_argv, _parse_sqlfluff_json, _EXT_SQL),
    _Tool("gitleaks", "gitleaks", _gitleaks_argv, _parse_gitleaks_json, frozenset()),  # repo-wide
    _Tool("semgrep", "semgrep", _semgrep_argv, _parse_semgrep_json, frozenset()),  # tool decides
    _Tool(
        "govet",
        "go",
        _govet_argv,
        _parse_govet_text,
        _EXT_GO,
        language_gate=("go",),
    ),
    _Tool(
        "govulncheck",
        "govulncheck",
        _govulncheck_argv,
        _parse_govulncheck_json,
        _EXT_GO,
        language_gate=("go",),
    ),
    _Tool("clippy", "cargo", _clippy_argv, _parse_clippy_json, _EXT_RUST, language_gate=("rust",)),
    _Tool("codespell", "codespell", _codespell_argv, _parse_codespell_text, frozenset()),
)


# ---- Driver ---------------------------------------------------------------


def _load_pr_files(repo_root: Path, path: Path | None) -> list[Path] | None:
    """Load `--pr-files-from` if given; return None for "lint everything"."""
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


def _enumerate_files(repo_root: Path) -> list[Path]:
    """Walk repo_root respecting `_SKIP_DIRS`. Used when no --pr-files-from."""
    skip = {
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
    out: list[Path] = []
    for dirpath, dirnames, filenames in __import__("os").walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for fname in sorted(filenames):
            out.append(Path(dirpath) / fname)
    return out


def _load_domains(path: Path | None) -> dict[str, dict[str, object]] | None:
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"--domains-from: not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "languages" not in data:
        raise ValueError(f"--domains-from: not a Step-0 domains_detected.json: {path}")
    langs: dict[str, dict[str, object]] = data["languages"]
    return langs


def _detected_languages(langs: dict[str, dict[str, object]] | None) -> set[str] | None:
    if langs is None:
        return None
    return {name for name, info in langs.items() if info.get("detected")}


def _files_for_tool(tool: _Tool, all_files: list[Path]) -> list[Path]:
    matches: list[Path] = []
    for f in all_files:
        if tool.matches_basenames and f.name in tool.matches_basenames:
            matches.append(f)
            continue
        if tool.matches_extensions and f.suffix.lower() in tool.matches_extensions:
            matches.append(f)
    return matches


def _run_one_tool(repo_root: Path, tool: _Tool, files: list[Path]) -> _ToolRun:
    """Spawn the tool, capture output, parse, normalise."""
    started_at = time.monotonic()
    if not shutil.which(tool.executable):
        return _ToolRun(name=tool.name, available=False, skipped_reason="not installed")
    argv = tool.build_argv(files)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _ToolRun(name=tool.name, available=True, skipped_reason="timeout")
    except OSError as exc:
        return _ToolRun(name=tool.name, available=False, skipped_reason=f"spawn failed: {exc}")
    findings = tool.parser(proc.stdout, proc.stderr)
    # Normalise file paths: rewrite repo_root prefix → relative POSIX, so
    # downstream agents and merges across machines stay comparable.
    rep_root_str = str(repo_root)
    out_findings: list[Finding] = []
    for f in findings:
        rel = f.file
        if rel.startswith(rep_root_str):
            rel = rel[len(rep_root_str) :].lstrip("/")
        elif rel.startswith("./"):
            rel = rel[2:]
        out_findings.append(
            Finding(
                tool=f.tool or tool.name,
                file=rel,
                line=f.line,
                column=f.column,
                severity=f.severity,
                code=f.code,
                message=f.message,
            )
        )
    return _ToolRun(
        name=tool.name,
        available=True,
        skipped_reason=None,
        findings=out_findings,
        raw_stderr_excerpt=proc.stderr[:512],
        duration_ms=int((time.monotonic() - started_at) * 1000),
    )


def _select_tools(
    tools: Iterable[_Tool],
    detected_langs: set[str] | None,
    only_names: set[str] | None,
) -> list[tuple[_Tool, str | None]]:
    """Return (tool, gate-skip-reason or None) for every tool the user wants."""
    selected: list[tuple[_Tool, str | None]] = []
    for tool in tools:
        if only_names is not None and tool.name not in only_names:
            continue
        # Gate by language presence when known. The gate-skip reason is
        # surfaced in `tools_skipped` so downstream agents can see WHY a
        # tool wasn't run (vs the tool being absent from the machine).
        if detected_langs is not None and tool.language_gate:
            if not (set(tool.language_gate) & detected_langs):
                selected.append((tool, "language not present in repo"))
                continue
        selected.append((tool, None))
    return selected


def _local_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S%z", time.localtime())


def run_linters(
    repo_root: Path,
    pr_files: list[Path] | None,
    detected_langs: set[str] | None,
    only_tools: set[str] | None = None,
) -> dict[str, object]:
    """Execute every applicable tool, return a JSON-ready dict."""
    if not repo_root.is_dir():
        raise NotADirectoryError(f"repo_root is not a directory: {repo_root}")
    all_files = pr_files if pr_files is not None else _enumerate_files(repo_root)
    selected = _select_tools(_TOOLS, detected_langs, only_tools)
    runs: list[_ToolRun] = []
    runs_pending: list[tuple[_Tool, list[Path]]] = []
    skipped_by_gate: list[dict[str, str]] = []
    for tool, gate_skip in selected:
        if gate_skip is not None:
            skipped_by_gate.append({"name": tool.name, "reason": gate_skip})
            continue
        files = _files_for_tool(tool, all_files)
        # Tools without file-match (repo-wide scanners like gitleaks/semgrep)
        # are dispatched with the empty list — they decide what to scan.
        if (tool.matches_extensions or tool.matches_basenames) and not files:
            skipped_by_gate.append({"name": tool.name, "reason": "no matching files"})
            continue
        runs_pending.append((tool, files))
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        future_map = {ex.submit(_run_one_tool, repo_root, tool, files): tool.name for tool, files in runs_pending}
        for fut in concurrent.futures.as_completed(future_map):
            runs.append(fut.result())
    # Deterministic ordering: sort by tool name, then findings by (file, line, col, code).
    runs.sort(key=lambda r: r.name)
    findings_total: list[Finding] = []
    tools_run: list[str] = []
    tools_skipped: list[dict[str, str]] = list(skipped_by_gate)
    by_tool_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for run in runs:
        if run.available and not run.skipped_reason:
            tools_run.append(run.name)
            # Normalize every finding's severity to the documented enum here, at
            # the single aggregation point, so all parsers are covered at once.
            normalized = [replace(f, severity=_normalize_severity(f.severity)) for f in run.findings]
            by_tool_counts[run.name] = len(normalized)
            findings_total.extend(normalized)
            for f in normalized:
                severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
        else:
            tools_skipped.append({"name": run.name, "reason": run.skipped_reason or "unavailable"})
    findings_total.sort(key=lambda f: (f.file, f.line, f.column, f.code, f.tool))
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "repo_root": str(repo_root.resolve()),
        "tools_run": sorted(tools_run),
        "tools_skipped": sorted(tools_skipped, key=lambda r: r["name"]),
        "by_tool_count": dict(sorted(by_tool_counts.items())),
        "severity_count": dict(sorted(severity_counts.items())),
        "total_findings": len(findings_total),
        "findings": [asdict(f) for f in findings_total],
    }


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 5 — Linter & scanner pre-flight wrapper.",
        prog="run_linters",
    )
    parser.add_argument("repo_root", help="Absolute path to the repository to lint.")
    parser.add_argument("out_dir", help="Where the JSON report is written.")
    parser.add_argument(
        "--pr-files-from",
        help="Optional file: each line is a repo-relative path. If absent, every supported file is linted.",
    )
    parser.add_argument(
        "--domains-from",
        help="Path to a Step-0 domains_detected.json. Used to skip tools whose language is absent.",
    )
    parser.add_argument(
        "--tools",
        help="Comma-separated subset of tools to run (default: all).",
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
        langs = _load_domains(Path(args.domains_from) if args.domains_from else None)
        detected = _detected_languages(langs)
        only_tools = set(t.strip() for t in args.tools.split(",")) if args.tools else None
        payload = run_linters(repo_root, pr_files, detected, only_tools)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = out_dir / f"{payload['timestamp']}-linters.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
