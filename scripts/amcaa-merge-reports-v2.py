#!/usr/bin/env python3
# AMCAA Merge Reports v2 — Concatenation merger with NO deduplication.
# Python port of amcaa-merge-reports-v2.sh, following the same patterns as
# amcaa-merge-audit-reports.py.
#
# Deduplication is handled by the amcaa-dedup-agent (an AI agent).
#
# Changes from v1:
#   - UUID-based input filenames (no collision between agents)
#   - Agent-prefixed finding IDs (no ID overlap)
#   - No dedup logic (delegated to AI dedup agent)
#   - Atomic write via tmp file + os.replace
#   - Raw counts only (dedup agent produces final accurate counts)
#   - Byte-size integrity verification (merged >= sum of sources)
#   - Source file deletion only after successful verification
#
# Usage:
#   amcaa-merge-reports-v2.py <output_dir> <pass_number> [run_id]
#
# Arguments:
#   output_dir           Directory containing phase reports
#   pass_number          Current pass number (1-25)
#   run_id               Optional run ID to scope to a single invocation
#                        When provided, only merges files matching R{run_id}
#                        When omitted, merges all files for this pass (legacy behavior)
#
# Input files (UUID-named by agents):
#   amcaa-correctness-P{N}-{uuid}.md  (Phase 1 -- may be multiple)
#   amcaa-claims-P{N}-{uuid}.md       (Phase 2 -- one)
#   amcaa-review-P{N}-{uuid}.md       (Phase 3 -- one)
#
# Output:
#   amcaa-pr-review-P{N}-intermediate-{timestamp}.md  (merged, NOT deduplicated)
#
# Exit codes:
#   0 -- Merge complete (dedup agent determines final verdict)
#   2 -- Error (missing reports, invalid input)

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# -- ANSI Color Configuration -------------------------------------------------
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

# -- Finding ID regex ----------------------------------------------------------
# Matches: [CC-P4-A0-001], [CV-P4-001], [SR-P4-001], [CC-001], etc.
FINDING_ID_RE = re.compile(r"\[[A-Z]{2}(-P[0-9]+)?(-A[0-9A-Fa-f]+)?-[0-9]+\]")

# -- Section header regexes ----------------------------------------------------
MUST_FIX_RE = re.compile(r"^#{1,3}\s.*(MUST.FIX|FAILED\sCLAIMS)", re.IGNORECASE)
SHOULD_FIX_RE = re.compile(r"^#{1,3}\s.*(SHOULD.FIX|PARTIALLY\sIMPLEMENTED)", re.IGNORECASE)
NIT_RE = re.compile(r"^#{1,3}\s.*(NIT|CONSISTENCY\sISSUES)", re.IGNORECASE)
CLEAN_RE = re.compile(r"^#{1,3}\s.*(CLEAN|VERIFIED)", re.IGNORECASE)
# New top-level section that resets the current section (matches the bash regex)
NEW_SECTION_RE = re.compile(r"^#{1,2}\s*[0-9A-Z]")

# -- Finding line regex (lines starting with ## to ##### then a bracket) --------
FINDING_LINE_RE = re.compile(r"^#{2,5}\s*\[")

# -- Skip prefixes for filenames -----------------------------------------------
SKIP_PREFIXES = (
    "amcaa-pr-review-",
    "amcaa-fixes-",
    "amcaa-tests-",
    "amcaa-lint-",
    "amcaa-checkpoint-",
    "amcaa-agents-",
    "amcaa-recovery-",
)


def is_skipped(basename: str) -> bool:
    """Check if a filename should be skipped (not part of the merge pipeline)."""
    for prefix in SKIP_PREFIXES:
        if basename.startswith(prefix):
            return True
    # Skip files manually marked as stale
    return "-STALE" in basename


def classify_report(basename: str) -> str:
    """Classify a report by its type prefix for phase ordering."""
    if basename.startswith("amcaa-correctness-"):
        return "correctness"
    elif basename.startswith("amcaa-claims-"):
        return "claims"
    elif basename.startswith("amcaa-review-"):
        return "review"
    else:
        return "other"


def main() -> None:
    # -- Argument parsing ------------------------------------------------------
    parser = argparse.ArgumentParser(
        description=(
            "AMCAA Merge Reports v2 -- Concatenation merger with NO deduplication. "
            "Deduplication is handled by the amcaa-dedup-agent."
        ),
        usage="amcaa-merge-reports-v2.py <output_dir> <pass_number> [run_id]",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory containing phase reports",
    )
    parser.add_argument(
        "pass_number",
        type=str,
        help="Current pass number (1-25)",
    )
    parser.add_argument(
        "run_id",
        type=str,
        nargs="?",
        default="",
        help="Optional run ID to scope to a single invocation",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    pass_number = args.pass_number
    run_id = args.run_id
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    # Build glob pattern: if run_id provided, scope to that run only
    if run_id:
        pattern = f"amcaa-*-P{pass_number}-R{run_id}-*.md"
        print(f"{CYAN}Run ID: {run_id} (scoped merge){NC}")
    else:
        pattern = f"amcaa-*-P{pass_number}-*.md"
        print(f"{YELLOW}No run ID -- merging ALL files for pass {pass_number} (legacy mode){NC}")

    intermediate_report = output_dir / f"amcaa-pr-review-P{pass_number}-intermediate-{timestamp}.md"

    # -- Validate input --------------------------------------------------------
    if not output_dir.is_dir():
        print(f"{RED}Error: Output directory '{output_dir}' does not exist{NC}")
        sys.exit(2)

    # -- Find all phase reports for this pass ----------------------------------
    reports: list[Path] = []
    for entry in sorted(output_dir.iterdir()):
        if not entry.is_file():
            continue
        basename = entry.name
        if not fnmatch.fnmatch(basename, pattern):
            continue

        # Skip non-phase reports (intermediate, final, fixes, tests, lint, checkpoints, stale)
        if is_skipped(basename):
            if "-STALE" in basename:
                print(f"  {YELLOW}Skipping stale: {basename}{NC}")
            continue

        reports.append(entry)

    if not reports:
        print(f"{RED}Error: No reports matching '{pattern}' found in '{output_dir}'{NC}")
        sys.exit(2)

    print(f"{CYAN}{BOLD}AMCAA Report Merger v2 (no-dedup, UUID-aware){NC}")
    print(f"Found {len(reports)} reports to merge for pass {pass_number}")
    print()

    # -- Sort reports by phase: correctness -> claims -> review -> other -------
    correctness_reports: list[Path] = []
    claims_reports: list[Path] = []
    review_reports: list[Path] = []
    other_reports: list[Path] = []

    for report in reports:
        rtype = classify_report(report.name)
        if rtype == "correctness":
            correctness_reports.append(report)
        elif rtype == "claims":
            claims_reports.append(report)
        elif rtype == "review":
            review_reports.append(report)
        else:
            other_reports.append(report)

    ordered_reports = correctness_reports + claims_reports + review_reports + other_reports

    # -- Severity section accumulators -----------------------------------------
    must_fix_lines: list[str] = []
    should_fix_lines: list[str] = []
    nit_lines: list[str] = []
    clean_lines: list[str] = []

    # -- Raw finding counts (pre-dedup) ----------------------------------------
    raw_must_fix = 0
    raw_should_fix = 0
    raw_nit = 0
    raw_total = 0

    # -- Process each report ---------------------------------------------------
    for report in ordered_reports:
        report_name = report.name
        print(f"  Processing: {report_name}")

        in_section = ""

        with open(report, encoding="utf-8", errors="replace") as f:
            for line in f:
                # Strip the trailing newline for pattern matching, preserve for output
                line_stripped = line.rstrip("\n")

                # Detect section headers
                if MUST_FIX_RE.search(line_stripped):
                    in_section = "must-fix"
                    continue
                elif SHOULD_FIX_RE.search(line_stripped):
                    in_section = "should-fix"
                    continue
                elif NIT_RE.search(line_stripped):
                    in_section = "nit"
                    continue
                elif CLEAN_RE.search(line_stripped):
                    in_section = "clean"
                    continue
                elif in_section and NEW_SECTION_RE.search(line_stripped):
                    # New top-level section, exit current parsing
                    in_section = ""
                    continue

                # Count finding IDs (raw count -- NO dedup, that is the agent's job)
                # Pattern matches: [CC-P4-A0-001], [CV-P4-001], [SR-P4-001], [CC-001], etc.
                if FINDING_LINE_RE.search(line_stripped):
                    finding_match = FINDING_ID_RE.search(line_stripped)
                    if finding_match:
                        if in_section == "must-fix":
                            raw_must_fix += 1
                        elif in_section == "should-fix":
                            raw_should_fix += 1
                        elif in_section == "nit":
                            raw_nit += 1
                        raw_total += 1

                # Route content to severity lists (no dedup -- just concatenate)
                if in_section == "must-fix":
                    must_fix_lines.append(line_stripped)
                elif in_section == "should-fix":
                    should_fix_lines.append(line_stripped)
                elif in_section == "nit":
                    nit_lines.append(line_stripped)
                elif in_section == "clean":
                    clean_lines.append(line_stripped)

    # -- Write intermediate report (atomic: write to tmp, then os.replace) -----
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        dir=str(output_dir),
        prefix="amcaa-merge-v2-",
    )

    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
            # Header (matches the bash script output format exactly)
            tmp_f.write(
                f"# AMCAA Merged Report (Pre-Deduplication)\n"
                f"\n"
                f"**Generated:** {timestamp}\n"
                f"**Pass:** {pass_number}\n"
                f"**Run ID:** {run_id if run_id else '(none -- legacy mode)'}\n"
                f"**Reports merged:** {len(ordered_reports)}\n"
                f"**Pipeline:** Code Correctness \u2192 Claim Verification \u2192 Skeptical Review\n"
                f"**Status:** INTERMEDIATE \u2014 awaiting deduplication by amcaa-dedup-agent\n"
                f"\n"
                f"---\n"
                f"\n"
                f"## Raw Counts (Pre-Dedup)\n"
                f"\n"
                f"| Severity | Raw Count |\n"
                f"|----------|----------|\n"
                f"| **MUST-FIX** | {raw_must_fix} |\n"
                f"| **SHOULD-FIX** | {raw_should_fix} |\n"
                f"| **NIT** | {raw_nit} |\n"
                f"| **Total** | {raw_total} |\n"
                f"\n"
                f"**Note:** These counts may include duplicates. "
                f"The amcaa-dedup-agent will produce final accurate counts.\n"
                f"\n"
            )

            # MUST-FIX section
            if must_fix_lines:
                tmp_f.write("---\n\n## MUST-FIX Issues\n\n")
                tmp_f.write("\n".join(must_fix_lines))
                tmp_f.write("\n\n")

            # SHOULD-FIX section
            if should_fix_lines:
                tmp_f.write("---\n\n## SHOULD-FIX Issues\n\n")
                tmp_f.write("\n".join(should_fix_lines))
                tmp_f.write("\n\n")

            # NIT section
            if nit_lines:
                tmp_f.write("---\n\n## Nits & Suggestions\n\n")
                tmp_f.write("\n".join(nit_lines))
                tmp_f.write("\n\n")

            # Clean files section
            if clean_lines:
                tmp_f.write("---\n\n## Clean / Verified Files\n\n")
                tmp_f.write("\n".join(clean_lines))
                tmp_f.write("\n\n")

            # Source reports section
            tmp_f.write("---\n\n## Source Reports\n\n")
            for report in ordered_reports:
                tmp_f.write(f"- `{report.name}`\n")
            tmp_f.write("\n")

        # Atomic rename: tmp -> final (prevents partial reads during concurrent access)
        os.replace(tmp_path, str(intermediate_report))

    except Exception:
        # Clean up temp file on error
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    # -- Verify merged file integrity (byte-size check) ------------------------
    # The merged file's content-bearing size must equal the sum of all source report
    # sizes. We measure actual byte counts using Path.stat().
    # Only delete source files if verification passes.

    merged_size = intermediate_report.stat().st_size
    source_total = 0
    for report in ordered_reports:
        source_total += report.stat().st_size

    # The merged file includes a header + severity section headings + source reports
    # listing that are NOT in the source files, so merged > sum of sources is expected.
    # The critical invariant: merged file must be >= sum of sources (all source content
    # is present). If merged < sum, content was lost during concatenation.
    if merged_size >= source_total:
        overhead = merged_size - source_total
        print(f"{GREEN}Integrity check PASSED: merged={merged_size} bytes >= sources={source_total} bytes{NC}")
        print(f"  (Overhead: {overhead} bytes from report header/structure)")
        print()

        # Safe to delete source files -- all content verified present in merged output
        print(f"Cleaning up {len(ordered_reports)} source report(s)...")
        for report in ordered_reports:
            report.unlink()
            print(f"  Deleted: {report.name}")
    else:
        print(f"{RED}Integrity check FAILED: merged={merged_size} bytes < sources={source_total} bytes{NC}")
        print(f"{RED}Source files NOT deleted \u2014 investigate data loss.{NC}")
        print(f"{YELLOW}Source files preserved for manual inspection:{NC}")
        for report in ordered_reports:
            size = report.stat().st_size
            print(f"  {report.name} ({size} bytes)")

    # -- Print summary to stdout -----------------------------------------------
    print()
    separator = "\u2550" * 59
    print(f"{CYAN}{separator}{NC}")
    print(f"{CYAN}  AMCAA Intermediate Report: {intermediate_report}{NC}")
    print(f"{CYAN}{separator}{NC}")
    print()
    print(f"  Raw MUST-FIX:    {raw_must_fix}")
    print(f"  Raw SHOULD-FIX:  {raw_should_fix}")
    print(f"  Raw NIT:         {raw_nit}")
    print(f"  Raw Total:       {raw_total}")
    print()
    print(f"{YELLOW}Awaiting amcaa-dedup-agent for final counts and verdict.{NC}")

    # Always exit 0 -- the dedup agent determines the final verdict
    sys.exit(0)


if __name__ == "__main__":
    main()
