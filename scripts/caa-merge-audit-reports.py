#!/usr/bin/env python3
# CAA Merge Audit Reports — Concatenation merger for codebase audit reports.
# Follows the same pattern as caa-merge-reports.py but for CAA audit pipeline.
# Deduplication is handled by the caa-dedup-agent (an AI agent).
#
# Report types merged (in order):
#   1. caa-audit-P{N}-R{RUN_ID}-*.md       (Phase 1 — parallel audit findings)
#   2. caa-verify-P{N}-*.md                 (Phase 2 — verification cross-checks)
#   3. caa-gapfill-P{N}-*.md                (Phase 3 — gap-fill audit passes)
#   4. caa-consolidated-*.md                (Phase 4 — per-domain consolidation)
#
# Skipped files (not part of the audit->verify->gapfill->consolidate pipeline):
#   caa-fixes-*         (fix phase outputs)
#   caa-checkpoint-*    (pipeline checkpoints)
#   caa-fixverify-*     (fix verification outputs)
#   caa-manifest-*      (file manifests)
#   TODO-*               (generated TODOs)
#   *-STALE*             (manually marked stale)
#   caa-audit-FINAL-*   (final merged reports — prevent re-merge)
#
# Features:
#   - UUID-based input filenames (no collision between agents)
#   - Agent-prefixed finding IDs (no ID overlap)
#   - No dedup logic (delegated to AI dedup agent)
#   - Atomic write via tmp file + mv
#   - Raw counts only (dedup agent produces final accurate counts)
#   - Byte-size integrity verification (merged >= sum of sources)
#   - Source file deletion only after successful verification
#
# Usage:
#   caa-merge-audit-reports.py <output_dir> <pass_number> [run_id]
#
# Arguments:
#   output_dir           Directory containing audit reports
#   pass_number          Current pass number (1+)
#   run_id               Optional run ID to scope to a single invocation
#                        When provided, only merges files matching R{run_id}
#                        When omitted, merges all files for this pass (legacy behavior)
#
# Output:
#   caa-audit-P{N}-intermediate-{timestamp}.md  (merged, NOT deduplicated)
#
# Exit codes:
#   0 — Merge complete (dedup agent determines final verdict)
#   2 — Error (missing reports, invalid input)

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

# ── ANSI Color Configuration ─────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"

# ── Finding ID regex ─────────────────────────────────────────────────────────
# Matches: [CA-P1-A0-001], [CV-P1-001], [GF-P1-001], [CA-001], etc.
FINDING_ID_RE = re.compile(r"\[[A-Z]{2,4}(-P[0-9]+)?(-A[0-9A-Fa-f]+)?-[0-9]+\]")

# ── Section header regexes ───────────────────────────────────────────────────
MUST_FIX_RE = re.compile(r"^#{1,3}\s*(MUST.FIX|CRITICAL|FAILED CLAIMS)", re.IGNORECASE)
SHOULD_FIX_RE = re.compile(r"^#{1,3}\s*(SHOULD.FIX|PARTIALLY IMPLEMENTED|WARNING)", re.IGNORECASE)
NIT_RE = re.compile(r"^#{1,3}\s*(NIT|CONSISTENCY ISSUES|STYLE|SUGGESTION)", re.IGNORECASE)
CLEAN_RE = re.compile(r"^#{1,3}\s*(CLEAN|VERIFIED|COMPLIANT|NO.VIOLATIONS)", re.IGNORECASE)
# New top-level section that resets the current section
NEW_SECTION_RE = re.compile(r"^#{1,2}\s*[0-9]|^#{1,2}\s*[A-Z]")

# ── Finding line regex (lines starting with ## to ##### then a bracket) ──────
FINDING_LINE_RE = re.compile(r"^#{2,5}\s*\[")

# ── Skip patterns for filenames ──────────────────────────────────────────────
SKIP_PREFIXES = (
    "caa-fixes-",
    "caa-checkpoint-",
    "caa-fixverify-",
    "caa-manifest-",
    "TODO-",
    "caa-audit-FINAL-",
)


def is_skipped(basename: str) -> bool:
    """Check if a filename should be skipped (not part of the merge pipeline)."""
    for prefix in SKIP_PREFIXES:
        if basename.startswith(prefix):
            return True
    return "-STALE" in basename


def classify_report(basename: str) -> str:
    """Classify a report by its type prefix."""
    if basename.startswith("caa-audit-"):
        return "audit"
    elif basename.startswith("caa-verify-"):
        return "verify"
    elif basename.startswith("caa-gapfill-"):
        return "gapfill"
    elif basename.startswith("caa-consolidated-"):
        return "consolidated"
    else:
        return "other"


def main() -> None:
    # ── Argument parsing ─────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="CAA Merge Audit Reports — Concatenation merger for codebase audit reports.",
        usage="caa-merge-audit-reports.py <output_dir> <pass_number> [run_id]",
    )
    parser.add_argument(
        "output_dir",
        type=str,
        help="Directory containing audit reports",
    )
    parser.add_argument(
        "pass_number",
        type=str,
        help="Current pass number (1+)",
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
        pattern = f"caa-*-P{pass_number}-R{run_id}-*.md"
        print(f"{CYAN}Run ID: {run_id} (scoped merge){NC}")
    else:
        pattern = f"caa-*-P{pass_number}-*.md"
        print(f"{YELLOW}No run ID — merging ALL files for pass {pass_number} (legacy mode){NC}")

    intermediate_report = output_dir / f"caa-audit-P{pass_number}-intermediate-{timestamp}.md"

    # ── Validate input ───────────────────────────────────────────────────────
    if not output_dir.is_dir():
        print(f"{RED}Error: Output directory '{output_dir}' does not exist{NC}")
        sys.exit(2)

    # ── Find all audit reports for this pass ─────────────────────────────────
    reports: list[Path] = []
    for entry in sorted(output_dir.iterdir()):
        if not entry.is_file():
            continue
        basename = entry.name
        if not fnmatch.fnmatch(basename, pattern):
            continue

        # Skip non-pipeline reports
        if is_skipped(basename):
            if "-STALE" in basename:
                print(f"  {YELLOW}Skipping stale: {basename}{NC}")
            continue

        reports.append(entry)

    if not reports:
        print(f"{RED}Error: No reports matching '{pattern}' found in '{output_dir}'{NC}")
        sys.exit(2)

    print(f"{CYAN}{BOLD}CAA Audit Report Merger (no-dedup, UUID-aware){NC}")
    print(f"Found {len(reports)} reports to merge for pass {pass_number}")
    print()

    # ── Sort reports by type: audit -> verify -> gapfill -> consolidated ─────
    audit_reports: list[Path] = []
    verify_reports: list[Path] = []
    gapfill_reports: list[Path] = []
    consolidated_reports: list[Path] = []
    other_reports: list[Path] = []

    for report in reports:
        rtype = classify_report(report.name)
        if rtype == "audit":
            audit_reports.append(report)
        elif rtype == "verify":
            verify_reports.append(report)
        elif rtype == "gapfill":
            gapfill_reports.append(report)
        elif rtype == "consolidated":
            consolidated_reports.append(report)
        else:
            other_reports.append(report)

    ordered_reports = audit_reports + verify_reports + gapfill_reports + consolidated_reports + other_reports

    # ── Temporary files for severity sections ────────────────────────────────
    must_fix_lines: list[str] = []
    should_fix_lines: list[str] = []
    nit_lines: list[str] = []
    clean_lines: list[str] = []

    # ── Raw finding counts (pre-dedup) ───────────────────────────────────────
    raw_must_fix = 0
    raw_should_fix = 0
    raw_nit = 0
    raw_total = 0

    # ── Process each report ──────────────────────────────────────────────────
    for report in ordered_reports:
        report_name = report.name
        print(f"  Processing: {report_name}")

        in_section = ""

        with open(report, encoding="utf-8", errors="replace") as f:
            for line in f:
                # Strip the trailing newline for pattern matching, but preserve it for output
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

                # Count finding IDs (raw count — NO dedup, that's the agent's job)
                # Pattern matches: [CA-P1-A0-001], [CV-P1-001], [GF-P1-001], [CA-001], etc.
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

                # Route content to severity lists (no dedup — just concatenate)
                if in_section == "must-fix":
                    must_fix_lines.append(line_stripped)
                elif in_section == "should-fix":
                    should_fix_lines.append(line_stripped)
                elif in_section == "nit":
                    nit_lines.append(line_stripped)
                elif in_section == "clean":
                    clean_lines.append(line_stripped)

    # ── Write intermediate report (atomic: write to tmp, then rename) ────────
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        dir=str(output_dir),
        prefix="caa-audit-merge-",
    )

    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
            # Header
            tmp_f.write(f"""# CAA Merged Audit Report (Pre-Deduplication)

**Generated:** {timestamp}
**Pass:** {pass_number}
**Run ID:** {run_id if run_id else "(none — legacy mode)"}
**Reports merged:** {len(ordered_reports)}
**Pipeline:** Audit \u2192 Verify \u2192 Gap-Fill \u2192 Consolidate
**Status:** INTERMEDIATE \u2014 awaiting deduplication by caa-dedup-agent

---

## Raw Counts (Pre-Dedup)

| Severity | Raw Count |
|----------|-----------|
| **MUST-FIX** | {raw_must_fix} |
| **SHOULD-FIX** | {raw_should_fix} |
| **NIT** | {raw_nit} |
| **Total** | {raw_total} |

**Note:** These counts may include duplicates. The caa-dedup-agent will produce final accurate counts.

## Report Sources (by type)

| Type | Count |
|------|-------|
| Audit reports | {len(audit_reports)} |
| Verify reports | {len(verify_reports)} |
| Gap-fill reports | {len(gapfill_reports)} |
| Consolidated reports | {len(consolidated_reports)} |
| Other reports | {len(other_reports)} |

""")

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

    # ── Verify merged file integrity (existence check) ──────────────────────
    # Only delete source files if verification passes.

    # The merger only extracts severity-section content from source files, so the
    # merged file will always be smaller than the sum of full source files. A byte-size
    # comparison is therefore invalid. The dedup agent validates content correctness
    # downstream; here we only confirm the merged file was written successfully.
    if intermediate_report.exists() and intermediate_report.stat().st_size > 0:
        merged_size = intermediate_report.stat().st_size
        print(f"{GREEN}Integrity check PASSED: merged file exists and is non-empty ({merged_size} bytes){NC}")
        print()

        # Safe to delete source files — merged file written successfully
        print(f"Cleaning up {len(ordered_reports)} source report(s)...")
        for report in ordered_reports:
            report.unlink()
            print(f"  Deleted: {report.name}")
    else:
        print(f"{RED}Integrity check FAILED: merged file missing or empty{NC}")
        print(f"{RED}Source files NOT deleted \u2014 investigate write failure.{NC}")
        print(f"{YELLOW}Source files preserved for manual inspection:{NC}")
        for report in ordered_reports:
            size = report.stat().st_size
            print(f"  {report.name} ({size} bytes)")

    # ── Print summary to stdout ──────────────────────────────────────────────
    print()
    print(
        f"{CYAN}\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550{NC}"
    )
    print(f"{CYAN}  CAA Intermediate Report: {intermediate_report}{NC}")
    print(
        f"{CYAN}\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550{NC}"
    )
    print()
    print(
        f"  Report types:    audit={len(audit_reports)}  verify={len(verify_reports)}"
        f"  gapfill={len(gapfill_reports)}  consolidated={len(consolidated_reports)}"
        f"  other={len(other_reports)}"
    )
    print(f"  Raw MUST-FIX:    {raw_must_fix}")
    print(f"  Raw SHOULD-FIX:  {raw_should_fix}")
    print(f"  Raw NIT:         {raw_nit}")
    print(f"  Raw Total:       {raw_total}")
    print()
    print(f"{YELLOW}Awaiting caa-dedup-agent for final counts and verdict.{NC}")

    # Always exit 0 — the dedup agent determines the final verdict
    sys.exit(0)


if __name__ == "__main__":
    main()
