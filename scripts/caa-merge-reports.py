#!/usr/bin/env python3
# CAA Merge Reports v2 — Concatenation merger with NO deduplication.
# Python port of caa-merge-reports.sh, following the same patterns as
# caa-merge-audit-reports.py.
#
# Deduplication is handled by the caa-dedup-agent (an AI agent).
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
#   caa-merge-reports.py <output_dir> <pass_number> [run_id]
#
# Arguments:
#   output_dir           Directory containing phase reports
#   pass_number          Current pass number (1-25)
#   run_id               Optional run ID to scope to a single invocation
#                        When provided, only merges files matching R{run_id}
#                        When omitted, merges all files for this pass (legacy behavior)
#
# Input files (UUID-named by agents):
#   caa-correctness-P{N}-{uuid}.md  (Phase 1 -- may be multiple)
#   caa-claims-P{N}-{uuid}.md       (Phase 2 -- one)
#   caa-review-P{N}-{uuid}.md       (Phase 3 -- one)
#   caa-security-P{N}-{uuid}.md     (Phase 4 -- one, runs in parallel with review)
#
# Output:
#   caa-pr-review-P{N}-intermediate-{timestamp}.md  (merged, NOT deduplicated)
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


def _colors_supported() -> bool:
    """Return True only when the terminal supports ANSI escape sequences."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON"))
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_USE_COLOR = _colors_supported()
RED = "\033[0;31m" if _USE_COLOR else ""
GREEN = "\033[0;32m" if _USE_COLOR else ""
YELLOW = "\033[1;33m" if _USE_COLOR else ""
CYAN = "\033[0;36m" if _USE_COLOR else ""
BOLD = "\033[1m" if _USE_COLOR else ""
NC = "\033[0m" if _USE_COLOR else ""

# -- Finding ID regex ----------------------------------------------------------
# Matches: [CC-P4-A0-001], [CV-P4-001], [SR-P4-001], [CC-001], [CAA-P1-001], etc.
FINDING_ID_RE = re.compile(r"\[[A-Z]{2,4}(-P[0-9]+)?(-A[0-9A-Fa-f]+)?-[0-9]+\]")

# -- Section header regexes ----------------------------------------------------
# NOTE: #{1,4} to capture #### headers from skeptical-reviewer agent (CONTRACT-PR-001)
MUST_FIX_RE = re.compile(r"^#{1,4}\s*(MUST.FIX|FAILED\sCLAIMS)", re.IGNORECASE)
SHOULD_FIX_RE = re.compile(r"^#{1,4}\s*(SHOULD.FIX|PARTIALLY\sIMPLEMENTED)", re.IGNORECASE)
NIT_RE = re.compile(r"^#{1,4}\s*(NIT|CONSISTENCY\sISSUES)", re.IGNORECASE)
CLEAN_RE = re.compile(r"^#{1,4}\s*(CLEAN|VERIFIED)", re.IGNORECASE)
RECORD_KEEPING_RE = re.compile(r"^#{1,4}\s*(RECORD.KEEPING)", re.IGNORECASE)
# New top-level section that resets the current section
NEW_SECTION_RE = re.compile(r"^#{1,2}\s*[0-9]|^#{1,2}\s*[A-Z]")

# -- Finding line regex (lines starting with ## to ##### then a bracket) --------
FINDING_LINE_RE = re.compile(r"^#{2,5}\s*\[")

# -- Skip prefixes for filenames -----------------------------------------------
SKIP_PREFIXES = (
    "caa-pr-review-",
    "caa-fixes-",
    "caa-tests-",
    "caa-lint-",
    "caa-checkpoint-",
    "caa-agents-",
    "caa-recovery-",
)


def is_skipped(basename: str) -> bool:
    """Check if a filename should be skipped (not part of the merge pipeline)."""
    for prefix in SKIP_PREFIXES:
        if basename.startswith(prefix):
            return True
    # Skip intermediate merge outputs to prevent re-merging on subsequent runs
    if "-intermediate-" in basename:
        return True
    # Skip files manually marked as stale
    return "-STALE" in basename


def classify_report(basename: str) -> str:
    """Classify a report by its type prefix for phase ordering."""
    if basename.startswith("caa-correctness-"):
        return "correctness"
    elif basename.startswith("caa-claims-"):
        return "claims"
    elif basename.startswith("caa-review-"):
        return "review"
    elif basename.startswith("caa-security-"):
        return "security"
    else:
        return "other"


def main() -> None:
    # -- Argument parsing ------------------------------------------------------
    parser = argparse.ArgumentParser(
        description=(
            "CAA Merge Reports v2 -- Concatenation merger with NO deduplication. "
            "Deduplication is handled by the caa-dedup-agent."
        ),
        usage="caa-merge-reports.py <output_dir> <pass_number> [run_id]",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory containing phase reports",
    )
    parser.add_argument(
        "pass_number",
        type=int,
        help="Current pass number (1-25)",
    )
    parser.add_argument(
        "run_id",
        type=str,
        nargs="?",
        default="",
        help="Optional run ID to scope to a single invocation",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output, print only final summary line",
    )
    args = parser.parse_args()
    quiet: bool = args.quiet

    output_dir = Path(args.output_dir)
    pass_number = args.pass_number
    run_id = args.run_id
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")

    # Build glob pattern: if run_id provided, scope to that run only
    if run_id:
        pattern = f"caa-*-P{pass_number}-R{run_id}-*.md"
        if not quiet:
            print(f"{CYAN}Run ID: {run_id} (scoped merge){NC}")
    else:
        pattern = f"caa-*-P{pass_number}-*.md"
        if not quiet:
            print(f"{YELLOW}No run ID -- merging ALL files for pass {pass_number} (legacy mode){NC}")

    intermediate_report = output_dir / f"caa-pr-review-P{pass_number}-intermediate-{timestamp}.md"

    # -- Validate input --------------------------------------------------------
    if not output_dir.is_dir():
        print(f"{RED}Error: Output directory '{output_dir}' does not exist{NC}", file=sys.stderr)
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
            if "-STALE" in basename and not quiet:
                print(f"  {YELLOW}Skipping stale: {basename}{NC}")
            continue

        reports.append(entry)

    if not reports:
        print(f"{RED}Error: No reports matching '{pattern}' found in '{output_dir}'{NC}", file=sys.stderr)
        sys.exit(2)

    if not quiet:
        print(f"{CYAN}{BOLD}CAA Report Merger v2 (no-dedup, UUID-aware){NC}")
        print(f"Found {len(reports)} reports to merge for pass {pass_number}")
        print()

    # -- Sort reports by phase: correctness -> claims -> review -> security -> other -------
    correctness_reports: list[Path] = []
    claims_reports: list[Path] = []
    review_reports: list[Path] = []
    security_reports: list[Path] = []
    other_reports: list[Path] = []

    for report in reports:
        rtype = classify_report(report.name)
        if rtype == "correctness":
            correctness_reports.append(report)
        elif rtype == "claims":
            claims_reports.append(report)
        elif rtype == "review":
            review_reports.append(report)
        elif rtype == "security":
            security_reports.append(report)
        else:
            other_reports.append(report)

    ordered_reports = correctness_reports + claims_reports + review_reports + security_reports + other_reports

    # -- Severity section accumulators -----------------------------------------
    must_fix_lines: list[str] = []
    should_fix_lines: list[str] = []
    nit_lines: list[str] = []
    clean_lines: list[str] = []
    record_keeping_lines: list[str] = []

    # -- Raw finding counts (pre-dedup) ----------------------------------------
    raw_must_fix = 0
    raw_should_fix = 0
    raw_nit = 0
    raw_total = 0

    # -- Process each report ---------------------------------------------------
    for report in ordered_reports:
        report_name = report.name
        if not quiet:
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
                elif RECORD_KEEPING_RE.search(line_stripped):
                    in_section = "record-keeping"
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
                elif in_section == "record-keeping":
                    record_keeping_lines.append(line_stripped)

    # -- Write intermediate report (atomic: write to tmp, then os.replace) -----
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        dir=str(output_dir),
        prefix="caa-merge-v2-",
    )

    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
            # Header (matches the bash script output format exactly)
            tmp_f.write(
                f"# CAA Merged Report (Pre-Deduplication)\n"
                f"\n"
                f"**Generated:** {timestamp}\n"
                f"**Pass:** {pass_number}\n"
                f"**Run ID:** {run_id if run_id else '(none -- legacy mode)'}\n"
                f"**Reports merged:** {len(ordered_reports)}\n"
                f"**Pipeline:** Correctness \u2192 Claims \u2192 Skeptical Review \u2192 Security\n"
                f"**Status:** INTERMEDIATE \u2014 awaiting deduplication by caa-dedup-agent\n"
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
                f"The caa-dedup-agent will produce final accurate counts.\n"
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

            # Record-keeping section (preserved items, not actionable findings)
            if record_keeping_lines:
                tmp_f.write("---\n\n## RECORD_KEEPING (PRESERVE)\n\n")
                tmp_f.write("\n".join(record_keeping_lines))
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

    # -- Verify merged file integrity (non-empty check) -------------------------
    # The merger only extracts severity-section content from source files, so the
    # merged output will typically be smaller than the sum of source sizes. A byte-size
    # comparison is therefore unreliable. Instead we simply verify the merged file
    # exists and is non-empty before cleaning up source files.

    if not intermediate_report.exists():
        print(f"{RED}Integrity check FAILED: merged file does not exist{NC}", file=sys.stderr)
        print(f"{RED}Source files NOT deleted — investigate data loss.{NC}", file=sys.stderr)
        sys.exit(2)

    merged_size = intermediate_report.stat().st_size

    if merged_size > 0:
        if not quiet:
            print(f"{GREEN}Integrity check PASSED: merged file exists and is non-empty ({merged_size} bytes){NC}")
            print()

        # Safe to delete source files -- merged output confirmed non-empty
        if not quiet:
            print(f"Cleaning up {len(ordered_reports)} source report(s)...")
        for report in ordered_reports:
            report.unlink(missing_ok=True)
            if not quiet:
                print(f"  Deleted: {report.name}")
    else:
        print(f"{RED}Integrity check FAILED: merged file is empty (0 bytes){NC}", file=sys.stderr)
        print(f"{RED}Source files NOT deleted \u2014 investigate data loss.{NC}", file=sys.stderr)
        print(f"{YELLOW}Source files preserved for manual inspection:{NC}", file=sys.stderr)
        for report in ordered_reports:
            if report.exists():
                size = report.stat().st_size
                print(f"  {report.name} ({size} bytes)", file=sys.stderr)
            else:
                print(f"  {report.name} (file missing)", file=sys.stderr)
        sys.exit(2)

    # -- Print summary to stdout -----------------------------------------------
    if not quiet:
        print()
        separator = "\u2550" * 59
        print(f"{CYAN}{separator}{NC}")
        print(f"{CYAN}  CAA Intermediate Report: {intermediate_report}{NC}")
        print(f"{CYAN}{separator}{NC}")
        print()
        print(f"  Raw MUST-FIX:    {raw_must_fix}")
        print(f"  Raw SHOULD-FIX:  {raw_should_fix}")
        print(f"  Raw NIT:         {raw_nit}")
        print(f"  Raw Total:       {raw_total}")
        print()
        print(f"{YELLOW}Awaiting caa-dedup-agent for final counts and verdict.{NC}")

    # Always print concise summary (even in --quiet mode)
    print(f"[OK] {intermediate_report} — {raw_total} raw findings from {len(ordered_reports)} reports")

    # Always exit 0 -- the dedup agent determines the final verdict
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"{RED}Fatal: {exc}{NC}", file=sys.stderr)
        sys.exit(2)
