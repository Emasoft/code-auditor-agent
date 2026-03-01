#!/usr/bin/env python3
# CAA TODO Generator — Pre-processes consolidated reports into skeleton TODOs.
# Extracts violations from consolidated audit reports and generates sequentially
# numbered TODO entries grouped by priority. Used as a pre-processor before the
# caa-todo-generator-agent adds context and implementation guidance.
#
# Severity mapping:
#   ## MUST-FIX   → P1 (critical violations requiring immediate fix)
#   ## SHOULD-FIX → P2 (important violations that should be addressed)
#   ## NIT        → P3 (style/consistency issues, low priority)
#
# Usage:
#   caa-generate-todos.py <consolidated_report> <scope_name> <output_path> [todo_prefix]
#
# Arguments:
#   consolidated_report  Path to the consolidated audit report (.md)
#   scope_name           Name of the audited scope (e.g. "amcos", "plugin-assistant-manager")
#   output_path          Output path for the generated TODO file
#   todo_prefix          Optional prefix for TODO IDs (default: scope_name uppercase)
#
# Output format (per entry):
#   ## [PREFIX-NNN] P{1,2,3} — Title
#   - **File:** path/to/file.ts:line
#   - **Category:** HARDCODED_API | DIRECT_DEPENDENCY | etc.
#   - **Finding ID:** [original-finding-id]
#   - **Status:** PENDING
#   - **Description:** (to be filled by caa-todo-generator-agent)
#   - **Fix:** (to be filled by caa-todo-generator-agent)
#
# Exit codes:
#   0 — TODOs generated successfully
#   2 — Error (missing input, invalid format)

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# ── ANSI Color Configuration ─────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

# ── Section detection patterns ───────────────────────────────────────────────
# These regexes detect severity section headers in the consolidated report
RE_MUST_FIX = re.compile(r"^#{1,3}\s*(MUST.FIX|CRITICAL|FAILED CLAIMS)", re.IGNORECASE)
RE_SHOULD_FIX = re.compile(r"^#{1,3}\s*(SHOULD.FIX|PARTIALLY IMPLEMENTED|WARNING)", re.IGNORECASE)
RE_NIT = re.compile(r"^#{1,3}\s*(NIT|CONSISTENCY|STYLE|SUGGESTION)", re.IGNORECASE)
RE_END_SECTION = re.compile(
    r"^#{1,3}\s*(CLEAN|VERIFIED|COMPLIANT|NO.VIOLATIONS|SOURCE REPORTS)",
    re.IGNORECASE,
)

# Finding header: ## [ID-NNN] Title or ### [ID-NNN] Title (2-5 hashes)
RE_FINDING_HEADER = re.compile(r"^#{2,5}\s*\[")

# Finding ID extraction: [XX-NNN] or [XX-P1-NNN] or [XX-P1-A0f-NNN]
RE_FINDING_ID = re.compile(r"\[[A-Z]{2,4}(-P[0-9]+)?(-A[0-9A-Fa-f]+)?-[0-9]+\]")

# Title extraction: strip leading hashes/spaces and the bracketed ID
RE_TITLE_STRIP = re.compile(r"^[\s#]*\[[^\]]*\]\s*")

# File reference line: - **File:** path or * **file** : path
RE_FILE_LINE = re.compile(r"^\s*[-*]\s*\*?\*?file\*?\*?\s*:", re.IGNORECASE)

# Inline file:line reference in backticks: `path/to/file.ts:42`
RE_INLINE_FILE = re.compile(r"`([a-zA-Z0-9_./-]+\.[a-z]+:[0-9]+)`")

# Category/type/violation line
RE_CATEGORY_LINE = re.compile(r"^\s*[-*]\s*\*?\*?(category|type|violation)\*?\*?\s*:", re.IGNORECASE)

# Inline uppercase category marker: HARDCODED_API, DIRECT_DEPENDENCY, etc.
RE_INLINE_CATEGORY = re.compile(r"[A-Z]{2,}_[A-Z_]{2,}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CAA TODO Generator — extract findings from consolidated audit reports into skeleton TODOs.",
        usage="%(prog)s <consolidated_report> <scope_name> <output_path> [todo_prefix]",
    )
    parser.add_argument(
        "consolidated_report",
        type=Path,
        help="Path to the consolidated audit report (.md)",
    )
    parser.add_argument(
        "scope_name",
        help='Name of the audited scope (e.g. "amcos", "plugin-assistant-manager")',
    )
    parser.add_argument(
        "output_path",
        type=Path,
        help="Output path for the generated TODO file",
    )
    parser.add_argument(
        "todo_prefix",
        nargs="?",
        default=None,
        help="Optional prefix for TODO IDs (default: scope_name uppercase with hyphens replaced by underscores)",
    )
    return parser.parse_args()


def strip_markdown_formatting(text: str) -> str:
    """Remove backticks and asterisks from a string, then strip whitespace."""
    return text.replace("`", "").replace("*", "").strip()


def main() -> None:
    args = parse_args()

    consolidated_report: Path = args.consolidated_report
    scope_name: str = args.scope_name
    output_path: Path = args.output_path
    todo_prefix: str = args.todo_prefix or scope_name.upper().replace("-", "_")

    # ── Validate input ───────────────────────────────────────────────────────
    if not consolidated_report.is_file():
        print(
            f"{RED}Error: Consolidated report not found: '{consolidated_report}'{NC}",
            file=sys.stderr,
        )
        sys.exit(2)

    output_dir = output_path.parent
    if not output_dir.is_dir():
        print(
            f"{RED}Error: Output directory does not exist: '{output_dir}'{NC}",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"{CYAN}{BOLD}CAA TODO Generator{NC}")
    print(f"  Report:  {consolidated_report}")
    print(f"  Scope:   {scope_name}")
    print(f"  Prefix:  {todo_prefix}")
    print(f"  Output:  {output_path}")
    print()

    # ── Counters ─────────────────────────────────────────────────────────────
    todo_num = 0
    p1_count = 0
    p2_count = 0
    p3_count = 0

    # ── State machine variables ──────────────────────────────────────────────
    current_priority = ""
    current_finding_id = ""
    current_title = ""
    current_file = ""
    current_category = ""
    in_finding = False

    # ── Accumulate output lines, then atomic-write at the end ────────────────
    output_lines: list[str] = []

    def flush_finding() -> None:
        """Write the accumulated finding as a skeleton TODO entry."""
        nonlocal todo_num, p1_count, p2_count, p3_count
        nonlocal current_finding_id, current_title, current_file, current_category, in_finding

        if not current_finding_id and not current_title:
            return

        todo_num += 1
        padded_num = f"{todo_num:03d}"

        if current_priority == "P1":
            p1_count += 1
        elif current_priority == "P2":
            p2_count += 1
        elif current_priority == "P3":
            p3_count += 1

        # Clean up title: strip leading hashes, brackets, whitespace
        clean_title = re.sub(r"^[\s#]*", "", current_title).strip()

        output_lines.append(f"## [{todo_prefix}-{padded_num}] {current_priority} — {clean_title}")
        output_lines.append("")

        if current_file:
            output_lines.append(f"- **File:** {current_file}")
        else:
            output_lines.append("- **File:** (unknown — verify manually)")

        if current_category:
            output_lines.append(f"- **Category:** {current_category}")
        else:
            output_lines.append("- **Category:** (unclassified)")

        if current_finding_id:
            output_lines.append(f"- **Finding ID:** {current_finding_id}")

        output_lines.append("- **Status:** PENDING")
        output_lines.append("- **Description:** (to be filled by caa-todo-generator-agent)")
        output_lines.append("- **Fix:** (to be filled by caa-todo-generator-agent)")
        output_lines.append("")

        # Reset state
        current_finding_id = ""
        current_title = ""
        current_file = ""
        current_category = ""
        in_finding = False

    # ── Write TODO file header ───────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    report_basename = consolidated_report.name

    output_lines.append(f"# TODO — {scope_name} Audit Fixes")
    output_lines.append("")
    output_lines.append(f"**Generated:** {timestamp}")
    output_lines.append(f"**Source:** {report_basename}")
    output_lines.append(f"**Scope:** {scope_name}")
    output_lines.append(f"**Prefix:** {todo_prefix}")
    output_lines.append("**Status:** SKELETON — awaiting caa-todo-generator-agent for implementation details")
    output_lines.append("")
    output_lines.append("---")
    output_lines.append("")

    # ── Parse consolidated report and extract findings ───────────────────────
    with consolidated_report.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")

            # Detect severity section headers
            if RE_MUST_FIX.search(line):
                flush_finding()
                current_priority = "P1"
                print(f"  Entering section: {BOLD}MUST-FIX (P1){NC}")
                continue
            elif RE_SHOULD_FIX.search(line):
                flush_finding()
                current_priority = "P2"
                print(f"  Entering section: {BOLD}SHOULD-FIX (P2){NC}")
                continue
            elif RE_NIT.search(line):
                flush_finding()
                current_priority = "P3"
                print(f"  Entering section: {BOLD}NIT (P3){NC}")
                continue
            elif RE_END_SECTION.search(line):
                # End of findings sections — flush and stop priority parsing
                flush_finding()
                current_priority = ""
                continue

            # Skip lines outside a severity section
            if not current_priority:
                continue

            # Detect individual finding headers: ## [ID-NNN] Title or ### [ID-NNN] Title
            if RE_FINDING_HEADER.search(line):
                flush_finding()
                in_finding = True

                # Extract finding ID
                id_match = RE_FINDING_ID.search(line)
                current_finding_id = id_match.group(0) if id_match else ""

                # Extract title (everything after the finding ID)
                current_title = RE_TITLE_STRIP.sub("", line)
                continue

            # Inside a finding block, extract metadata
            if in_finding:
                # Extract file reference: **File:** path or `path:line`
                if RE_FILE_LINE.search(line):
                    # Everything after the colon, stripped of markdown formatting
                    colon_pos = line.index(":")
                    # Find the colon after "File" (skip any colon inside the label)
                    # The pattern matches "file:", so find after label
                    file_part = line[colon_pos + 1 :]
                    current_file = strip_markdown_formatting(file_part)

                # Extract file reference from inline code: at `path/to/file.ts:42`
                if not current_file:
                    inline_match = RE_INLINE_FILE.search(line)
                    if inline_match:
                        current_file = inline_match.group(1)

                # Extract category: **Category:** TYPE or **Type:** TYPE
                if RE_CATEGORY_LINE.search(line):
                    colon_pos = line.index(":")
                    cat_part = line[colon_pos + 1 :]
                    current_category = strip_markdown_formatting(cat_part)

                # Extract category from inline markers: HARDCODED_API, DIRECT_DEPENDENCY, etc.
                if not current_category:
                    cat_match = RE_INLINE_CATEGORY.search(line)
                    if cat_match:
                        current_category = cat_match.group(0)

    # Flush final finding
    flush_finding()

    # ── Write summary footer ─────────────────────────────────────────────────
    output_lines.append("---")
    output_lines.append("")
    output_lines.append("## Summary")
    output_lines.append("")
    output_lines.append("| Priority | Count |")
    output_lines.append("|----------|-------|")
    output_lines.append(f"| **P1 (MUST-FIX)** | {p1_count} |")
    output_lines.append(f"| **P2 (SHOULD-FIX)** | {p2_count} |")
    output_lines.append(f"| **P3 (NIT)** | {p3_count} |")
    output_lines.append(f"| **Total** | {todo_num} |")
    output_lines.append("")
    output_lines.append("**Next step:** Run caa-todo-generator-agent to fill in descriptions and fix guidance.")

    # ── Atomic write: write to .tmp then rename ──────────────────────────────
    tmp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        tmp_output.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        tmp_output.rename(output_path)
    except Exception as exc:
        # Clean up temp file on failure
        tmp_output.unlink(missing_ok=True)
        print(f"{RED}Error: Failed to write output: {exc}{NC}", file=sys.stderr)
        sys.exit(2)

    # ── Print summary ────────────────────────────────────────────────────────
    print()
    print(f"{CYAN}═══════════════════════════════════════════════════════════{NC}")
    print(f"{CYAN}  CAA TODO File: {output_path}{NC}")
    print(f"{CYAN}═══════════════════════════════════════════════════════════{NC}")
    print()
    print(f"  P1 (MUST-FIX):    {p1_count}")
    print(f"  P2 (SHOULD-FIX):  {p2_count}")
    print(f"  P3 (NIT):         {p3_count}")
    print(f"  Total TODOs:      {todo_num}")
    print()

    if todo_num == 0:
        print(
            f"{YELLOW}No findings extracted. Check that the consolidated report has "
            f"## MUST-FIX / ## SHOULD-FIX / ## NIT sections.{NC}"
        )
    else:
        print(f"{GREEN}Generated {todo_num} skeleton TODO entries.{NC}")
        print(f"{YELLOW}Run caa-todo-generator-agent to add implementation details.{NC}")

    sys.exit(0)


if __name__ == "__main__":
    main()
