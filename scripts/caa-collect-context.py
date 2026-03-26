#!/usr/bin/env python3
"""caa-collect-context.py -- Pre-gather context for CAA agents.

Automates information retrieval so agents don't waste tokens searching.
Uses `tldr` CLI and `gh` CLI to collect structured information.

Usage:
    caa-collect-context.py <mode> <output_path> [options]

Modes:
    pr-info             Collect PR metadata for claim verification and review agents
    file-context        Collect code structure for a list of files
    codebase-overview   Collect high-level codebase info for audit agents

Examples:
    caa-collect-context.py pr-info /tmp/pr-context.md --pr 42 --repo owner/repo
    caa-collect-context.py file-context /tmp/files.md --files src/a.py src/b.py
    caa-collect-context.py file-context /tmp/files.md --files-from changed.txt
    caa-collect-context.py codebase-overview /tmp/overview.md --path src/
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Color helpers (respect NO_COLOR env var)
# ---------------------------------------------------------------------------

_NO_COLOR = os.environ.get("NO_COLOR", "") != "" or not sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Wrap *text* in ANSI color *code* unless colors are suppressed."""
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return _c("32", text)


def red(text: str) -> str:
    return _c("31", text)


def yellow(text: str) -> str:
    return _c("33", text)


def dim(text: str) -> str:
    return _c("2", text)


# ---------------------------------------------------------------------------
# Tool availability checks
# ---------------------------------------------------------------------------


def _tool_available(name: str) -> bool:
    """Return True if *name* is on PATH."""
    return shutil.which(name) is not None


def _run(cmd: list[str], *, timeout: int = 120) -> tuple[int, str]:
    """Run *cmd* and return (exit_code, stdout). Stderr is captured but discarded."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def collect_pr_info(
    output_path: Path,
    *,
    pr_number: str | None = None,
    repo: str | None = None,
) -> tuple[int, str]:
    """Collect PR metadata, diff, changed files, and per-file code structure.

    Returns (file_count, summary_note).
    """
    has_gh = _tool_available("gh")
    has_tldr = _tool_available("tldr")

    lines: list[str] = []
    lines.append("# PR Context\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")

    file_count = 0

    # -- GH section ----------------------------------------------------------
    if not has_gh:
        lines.append("\n> **Note:** `gh` CLI not found -- PR metadata skipped.\n")
    else:
        # Build base gh args
        gh_base: list[str] = ["gh", "pr"]
        repo_args: list[str] = []
        if repo:
            repo_args = ["--repo", repo]

        pr_ref = pr_number if pr_number else ""

        # PR view (metadata)
        cmd_view = [*gh_base, "view", *([pr_ref] if pr_ref else []), *repo_args]
        rc, out = _run(cmd_view)
        lines.append("\n## PR Metadata\n")
        if rc == 0:
            lines.append(f"```\n{out.rstrip()}\n```\n")
        else:
            lines.append(f"> `gh pr view` failed (exit {rc}).\n")

        # PR diff
        cmd_diff = [*gh_base, "diff", *([pr_ref] if pr_ref else []), *repo_args]
        rc, out = _run(cmd_diff, timeout=180)
        diff_path = output_path.with_suffix(".diff")
        lines.append("\n## PR Diff\n")
        if rc == 0:
            diff_path.write_text(out, encoding="utf-8")
            lines.append(f"Full diff saved to: `{diff_path}`\n")
            # Also include a truncated preview (first 200 lines)
            preview_lines = out.splitlines()[:200]
            lines.append(f"\n<details><summary>Diff preview (first 200 of {len(out.splitlines())} lines)</summary>\n")
            lines.append(f"```diff\n{chr(10).join(preview_lines)}\n```\n</details>\n")
        else:
            lines.append(f"> `gh pr diff` failed (exit {rc}).\n")

        # Changed files list
        cmd_files = [
            *gh_base,
            "view",
            *([pr_ref] if pr_ref else []),
            *repo_args,
            "--json",
            "files",
            "--jq",
            ".files[].path",
        ]
        rc, out = _run(cmd_files)
        changed_files: list[str] = []
        lines.append("\n## Changed Files\n")
        if rc == 0 and out.strip():
            changed_files = [f.strip() for f in out.strip().splitlines() if f.strip()]
            file_count = len(changed_files)
            for f in changed_files:
                lines.append(f"- `{f}`\n")
        else:
            lines.append("> Could not retrieve changed files list.\n")

        # Per-file code structure via tldr
        if changed_files and has_tldr:
            lines.append("\n## Per-File Code Structure\n")
            for fpath in changed_files:
                if not Path(fpath).exists():
                    lines.append(f"\n### `{fpath}` (file not found locally)\n")
                    continue
                lines.append(f"\n### `{fpath}`\n")
                rc_s, out_s = _run(["tldr", "structure", fpath])
                if rc_s == 0 and out_s.strip():
                    lines.append(f"```\n{out_s.rstrip()}\n```\n")
                else:
                    lines.append("> `tldr structure` returned no output.\n")
        elif changed_files and not has_tldr:
            lines.append("\n> **Note:** `tldr` CLI not found -- per-file structure skipped.\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    size = output_path.stat().st_size
    return file_count, f"pr-info collected ({file_count} files, {size} bytes)"


def collect_file_context(
    output_path: Path,
    *,
    files: list[str] | None = None,
    files_from: str | None = None,
) -> tuple[int, str]:
    """Collect code structure and imports for a list of files.

    Returns (file_count, summary_note).
    """
    has_tldr = _tool_available("tldr")

    # Resolve file list
    file_list: list[str] = []
    if files:
        file_list = list(files)
    elif files_from:
        src = Path(files_from)
        if src.exists():
            file_list = [line.strip() for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                f"# File Context\n\nError: --files-from path does not exist: {files_from}\n", encoding="utf-8"
            )
            return 0, "file-context failed (files-from path missing)"

    if not file_list:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# File Context\n\nNo files specified.\n", encoding="utf-8")
        return 0, "file-context collected (0 files, 0 bytes)"

    lines: list[str] = []
    lines.append("# File Context\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
    lines.append(f"Files: {len(file_list)}\n")

    if not has_tldr:
        lines.append("\n> **Note:** `tldr` CLI not found -- structure and imports skipped.\n")
        lines.append("\n## File List\n")
        for fpath in file_list:
            exists = Path(fpath).exists()
            status = "" if exists else " (not found)"
            lines.append(f"- `{fpath}`{status}\n")
    else:
        for fpath in file_list:
            lines.append(f"\n## `{fpath}`\n")
            if not Path(fpath).exists():
                lines.append("> File not found locally.\n")
                continue

            # Structure
            rc_s, out_s = _run(["tldr", "structure", fpath])
            lines.append("\n### Structure\n")
            if rc_s == 0 and out_s.strip():
                lines.append(f"```\n{out_s.rstrip()}\n```\n")
            else:
                lines.append("> No structure output.\n")

            # Imports
            rc_i, out_i = _run(["tldr", "imports", fpath])
            lines.append("\n### Imports\n")
            if rc_i == 0 and out_i.strip():
                lines.append(f"```\n{out_i.rstrip()}\n```\n")
            else:
                lines.append("> No imports output.\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    size = output_path.stat().st_size
    return len(file_list), f"file-context collected ({len(file_list)} files, {size} bytes)"


def collect_codebase_overview(
    output_path: Path,
    *,
    path: str = ".",
) -> tuple[int, str]:
    """Collect high-level codebase info: tree, architecture, dead code.

    Returns (file_count, summary_note).
    """
    has_tldr = _tool_available("tldr")

    lines: list[str] = []
    lines.append("# Codebase Overview\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
    lines.append(f"Path: `{path}`\n")

    file_count = 0

    if not has_tldr:
        lines.append("\n> **Note:** `tldr` CLI not found -- all sections skipped.\n")
    else:
        # Tree of source files
        lines.append("\n## Source Tree\n")
        rc, out = _run(["tldr", "tree", path, "--ext", ".py,.ts,.js,.go,.rs"], timeout=60)
        if rc == 0 and out.strip():
            # Count files from tree output (rough heuristic: lines with file extensions)
            tree_lines = out.strip().splitlines()
            file_count = sum(
                1 for tl in tree_lines if any(tl.rstrip().endswith(ext) for ext in (".py", ".ts", ".js", ".go", ".rs"))
            )
            lines.append(f"```\n{out.rstrip()}\n```\n")
        else:
            lines.append("> `tldr tree` returned no output.\n")

        # Architecture layers
        lines.append("\n## Architecture\n")
        rc, out = _run(["tldr", "arch", path], timeout=120)
        if rc == 0 and out.strip():
            lines.append(f"```\n{out.rstrip()}\n```\n")
        else:
            lines.append("> `tldr arch` returned no output.\n")

        # Dead code candidates
        lines.append("\n## Dead Code Candidates\n")
        rc, out = _run(["tldr", "dead", path], timeout=120)
        if rc == 0 and out.strip():
            lines.append(f"```\n{out.rstrip()}\n```\n")
        else:
            lines.append("> `tldr dead` returned no output.\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    size = output_path.stat().st_size
    return file_count, f"codebase-overview collected ({file_count} files, {size} bytes)"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caa-collect-context",
        description="Pre-gather context for CAA agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s pr-info /tmp/pr-ctx.md --pr 42 --repo owner/repo
              %(prog)s file-context /tmp/files.md --files src/a.py src/b.py
              %(prog)s file-context /tmp/files.md --files-from changed.txt
              %(prog)s codebase-overview /tmp/overview.md --path src/
        """),
    )
    parser.add_argument("mode", choices=["pr-info", "file-context", "codebase-overview"], help="Collection mode")
    parser.add_argument("output_path", type=Path, help="Path to write the output markdown file")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout summary line")

    # pr-info options
    parser.add_argument("--pr", default=None, help="PR number (for pr-info mode)")
    parser.add_argument("--repo", default=None, help="GitHub repo in owner/name format (for pr-info mode)")

    # file-context options
    file_group = parser.add_mutually_exclusive_group()
    file_group.add_argument("--files", nargs="+", default=None, help="List of file paths (for file-context mode)")
    file_group.add_argument(
        "--files-from", default=None, help="Path to a file listing one path per line (for file-context mode)"
    )

    # codebase-overview options
    parser.add_argument("--path", default=".", help="Root path to analyze (for codebase-overview mode)")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    mode: str = args.mode
    output_path: Path = args.output_path

    if mode == "pr-info":
        _, summary = collect_pr_info(output_path, pr_number=args.pr, repo=args.repo)
    elif mode == "file-context":
        _, summary = collect_file_context(output_path, files=args.files, files_from=args.files_from)
    elif mode == "codebase-overview":
        _, summary = collect_codebase_overview(output_path, path=args.path)
    else:
        # argparse prevents this, but satisfy the type checker
        print(red(f"[ERROR] Unknown mode: {mode}"), file=sys.stderr)
        return 2

    if not args.quiet:
        print(green(f"[OK] {output_path} -- {summary}"))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(yellow("\n[INTERRUPTED]"), file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(red(f"[ERROR] {exc}"), file=sys.stderr)
        sys.exit(2)
