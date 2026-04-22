#!/usr/bin/env python3
"""caa-generate-prompts.py -- Pre-compute domain splits and generate agent prompt files.

Replaces expensive runtime file scanning by pre-computing domain classification,
sub-group splits, and ready-made prompt .md files for Claude Code agent spawning.

Usage:
    caa-generate-prompts.py --target <dir> --phase <phase> [options]

Examples:
    caa-generate-prompts.py --target src/ --phase audit --output reports/code-auditor/prompts/ --max-files 3
    caa-generate-prompts.py --target . --phase review --standard reference.md --quiet
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map file extensions to domain names
EXTENSION_TO_DOMAIN: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
    ".html": "html",
    ".htm": "html",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".java": "java",
    ".cfg": "config",
    ".ini": "config",
    ".conf": "config",
    ".env": "config",
}

# Directories to always skip during scanning
SKIP_DIRS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
}

# Phase templates keyed by phase name
PHASE_TEMPLATES: dict[str, dict[str, str]] = {
    "audit": {
        "instruction": (
            "Audit these files against the reference standard.\n"
            "Read each file COMPLETELY before writing any findings.\n"
            "Classify every finding into one of the sections below."
        ),
        "sections": "## MUST-FIX, ## SHOULD-FIX, ## NIT, ## CLEAN",
        "finding_prefix": "DA-P{group_index}",
        "finding_format": "[DA-P{group_index}-{seq}]",
    },
    "review": {
        "instruction": (
            "Audit these files for code correctness.\n"
            "Read every file completely before writing any findings.\n"
            "Focus on logic errors, race conditions, edge cases, and API misuse."
        ),
        "sections": "## MUST-FIX, ## SHOULD-FIX, ## NIT, ## CLEAN",
        "finding_prefix": "CC-P{group_index}",
        "finding_format": "[CC-P{group_index}-A{hex}-{seq}]",
    },
    "security": {
        "instruction": (
            "Audit these files for security vulnerabilities.\n"
            "Focus on OWASP Top 10, hardcoded secrets, injection vectors,\n"
            "path traversal, insecure deserialization, and broken access control.\n"
            "Read each file COMPLETELY before writing any findings."
        ),
        "sections": "## MUST-FIX, ## SHOULD-FIX, ## NIT, ## CLEAN",
        "finding_prefix": "SEC-P{group_index}",
        "finding_format": "[SEC-P{group_index}-{seq}]",
    },
    "fix": {
        "instruction": (
            "Apply fixes from the TODO file to these files.\n"
            "Read each file COMPLETELY before modifying.\n"
            "Make minimal, targeted changes -- do not refactor unrelated code.\n"
            "TODO file path: {{TODO_FILE_PATH}}"
        ),
        "sections": "## FIXED, ## SKIPPED (with reason), ## NEEDS-REVIEW",
        "finding_prefix": "FIX-P{group_index}",
        "finding_format": "[FIX-P{group_index}-{seq}]",
    },
    "verify": {
        "instruction": (
            "Cross-check the audit report against actual code.\n"
            "For each finding in the report, read the cited file and line,\n"
            "confirm or refute the finding, and note any false positives.\n"
            "Report path: {{REPORT_PATH}}"
        ),
        "sections": "## CONFIRMED, ## FALSE-POSITIVE, ## NEEDS-RECHECK",
        "finding_prefix": "VER-P{group_index}",
        "finding_format": "[VER-P{group_index}-{seq}]",
    },
}

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


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


def dim(text: str) -> str:
    return _c("2", text)


# ---------------------------------------------------------------------------
# Domain classification
# ---------------------------------------------------------------------------


def classify_domain(path: Path) -> str:
    """Return the domain name for a file based on its extension."""
    return EXTENSION_TO_DOMAIN.get(path.suffix.lower(), "other")


def should_skip_dir(name: str) -> bool:
    """Return True if a directory name should be skipped during scanning."""
    # Direct match against skip set
    if name in SKIP_DIRS:
        return True
    # Handle glob-style patterns like *.egg-info
    if name.endswith(".egg-info"):
        return True
    # Skip hidden directories (starting with .)
    if name.startswith(".") and name not in {".", ".."}:
        return True
    # Skip _dev folders (project convention)
    return name.endswith("_dev")


def scan_files(target: Path) -> list[Path]:
    """Recursively scan *target* for files, skipping ignored directories."""
    results: list[Path] = []
    for root, dirs, files in os.walk(target):
        # Prune directories in-place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for fname in files:
            fpath = Path(root) / fname
            # Skip files without extensions and hidden files
            if fpath.suffix and not fname.startswith("."):
                results.append(fpath.resolve())
    return results


def group_by_domain(files: list[Path]) -> dict[str, list[Path]]:
    """Group files into domain buckets, sorted alphabetically within each domain."""
    domains: dict[str, list[Path]] = {}
    for f in files:
        domain = classify_domain(f)
        domains.setdefault(domain, []).append(f)
    # Sort files within each domain alphabetically by full path
    for domain in domains:
        domains[domain].sort()
    return domains


def split_into_subgroups(files: list[Path], max_files: int) -> list[list[Path]]:
    """Split a sorted list of files into sub-groups of at most *max_files*."""
    return [files[i : i + max_files] for i in range(0, len(files), max_files)]


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------


def build_prompt(
    phase: str,
    domain: str,
    group_index: int,
    files: list[Path],
    standard: str | None,
    output_dir: Path,
    todo_file: str | None,
    report_path_override: str | None,
) -> str:
    """Build the full markdown prompt text for one sub-group."""
    template = PHASE_TEMPLATES[phase]
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    idx_str = f"{group_index:02d}"

    # Build the numbered file list
    file_list_lines = [f"{i + 1}. `{fpath}`" for i, fpath in enumerate(files)]
    file_list = "\n".join(file_list_lines)

    # Standard reference line
    standard_line = f"`{standard}`" if standard else "N/A"

    # Report output path
    report_name = f"caa-{phase}-{domain}-{idx_str}-{timestamp}.md"
    report_path = output_dir / report_name

    # Resolve phase-specific placeholders in the instruction template.
    # The `fix` phase needs {{TODO_FILE_PATH}}; the `verify` phase needs {{REPORT_PATH}}.
    # Both default to the computed report_path when no override is supplied so the
    # generated prompt is never left with unpopulated literal placeholders.
    instruction = template["instruction"]
    todo_value = todo_file if todo_file else str(report_path)
    report_value = report_path_override if report_path_override else str(report_path)
    instruction = instruction.replace("{{TODO_FILE_PATH}}", todo_value)
    instruction = instruction.replace("{{REPORT_PATH}}", report_value)

    # Finding ID format description
    finding_format = template["finding_format"].format(group_index=idx_str, hex="{hex}", seq="{SEQ}")

    prompt = f"""# {phase.capitalize()} Prompt: {domain.capitalize()} Group {idx_str}

## Task
{instruction}

## Files to Process
{file_list}

## Reference Standard
{standard_line}

## Output Requirements
- Write report to: `{report_path}`
- Use sections: {template["sections"]}
- Each finding needs: file, line number, evidence, specific fix
- Finding ID format: {finding_format}

## Reporting Rules
- Write ALL detailed findings to the report file
- Return to orchestrator ONLY: "[DONE/FAILED] {phase}-{domain}-{idx_str} - brief result. Report: {{filepath}}"
- NEVER return code blocks, file contents, or verbose explanations
- Max 2 lines of text back to orchestrator
"""
    return prompt


def generate_prompts(
    target: Path,
    phase: str,
    output_dir: Path,
    max_files: int,
    standard: str | None,
    quiet: bool,
    todo_file: str | None,
    report_path_override: str | None,
) -> int:
    """Main generation logic. Returns the number of prompt files written."""
    # Scan and classify files
    all_files = scan_files(target)
    if not all_files:
        print(red(f"[ERROR] No files found in {target}"))
        return 0

    domains = group_by_domain(all_files)

    if not quiet:
        print(f"Scanned {len(all_files)} files across {len(domains)} domains in {target}")

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    total_prompts = 0
    domain_summaries: list[str] = []

    # Process domains in sorted order for deterministic output
    for domain in sorted(domains.keys()):
        files = domains[domain]
        subgroups = split_into_subgroups(files, max_files)
        domain_summaries.append(f"{domain} ({len(files)} files, {len(subgroups)} groups)")

        if not quiet:
            print(f"  {domain}: {len(files)} files -> {len(subgroups)} groups")

        for idx, group_files in enumerate(subgroups, start=1):
            prompt_text = build_prompt(
                phase=phase,
                domain=domain,
                group_index=idx,
                files=group_files,
                standard=standard,
                output_dir=output_dir,
                todo_file=todo_file,
                report_path_override=report_path_override,
            )

            # Write prompt file
            prompt_filename = f"prompt-{phase}-{domain}-{idx:02d}.md"
            prompt_path = output_dir / prompt_filename
            prompt_path.write_text(prompt_text, encoding="utf-8")

            if not quiet:
                print(dim(f"    wrote {prompt_filename} ({len(group_files)} files)"))

            total_prompts += 1

    # Print summary
    summary_domains = ", ".join(domain_summaries)
    print(green(f"[OK] Generated {total_prompts} prompt files in {output_dir}"))
    print(f"Domains: {summary_domains}")

    return total_prompts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="caa-generate-prompts",
        description="Pre-compute domain splits and generate ready-made prompt files for CAA agent spawning.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Directory to scan for source files.",
    )
    parser.add_argument(
        "--phase",
        choices=list(PHASE_TEMPLATES.keys()),
        required=True,
        help="Phase template to use for prompt generation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/code-auditor/prompts"),
        help="Directory to write generated prompt .md files (default: reports/code-auditor/prompts/).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=3,
        help="Maximum files per sub-group (default: 3).",
    )
    parser.add_argument(
        "--standard",
        type=str,
        default=None,
        help="Path to reference standard document (for audit phases).",
    )
    parser.add_argument(
        "--todo-file",
        type=str,
        default=None,
        help="Path to TODO file (substituted into {{TODO_FILE_PATH}} for the 'fix' phase).",
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default=None,
        help="Path to audit report (substituted into {{REPORT_PATH}} for the 'verify' phase).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output, print only summary.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = parse_args(argv)

    # Validate target directory
    target = args.target.resolve()
    if not target.is_dir():
        print(red(f"[ERROR] Target is not a directory: {target}"), file=sys.stderr)
        return 1

    # Validate standard file if provided
    if args.standard:
        standard_path = Path(args.standard).resolve()
        if not standard_path.is_file():
            print(red(f"[ERROR] Standard file not found: {standard_path}"), file=sys.stderr)
            return 1
        standard_str = str(standard_path)
    else:
        standard_str = None

    output_dir = args.output.resolve()

    count = generate_prompts(
        target=target,
        phase=args.phase,
        output_dir=output_dir,
        max_files=args.max_files,
        standard=standard_str,
        quiet=args.quiet,
        todo_file=args.todo_file,
        report_path_override=args.report_path,
    )

    return 0 if count > 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except BrokenPipeError:
        # Handle piping to head/less gracefully
        sys.exit(0)
