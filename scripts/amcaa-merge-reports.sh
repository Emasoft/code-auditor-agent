#!/bin/bash
# Requires bash 4+ (for associative arrays). macOS ships bash 3.2 — install bash via Homebrew.
# AMCAA Merge Reports — Combines findings from all 3 review phases into one final report.
#
# Usage:
#   amcaa-merge-reports.sh <output_dir> [report_glob_pattern]
#
# Arguments:
#   output_dir           Directory containing phase reports and where final report goes
#   report_glob_pattern  Optional glob pattern (default: "amcaa-*.md")
#
# Expects reports named:
#   amcaa-correctness-*.md  (Phase 1 — code correctness, may be multiple)
#   amcaa-claims.md         (Phase 2 — claim verification)
#   amcaa-review.md         (Phase 3 — skeptical review)
#
# Output:
#   amcaa-pr-review-YYYY-MM-DD-HHMMSS.md  (merged final report)
#
# Exit codes:
#   0 — No MUST-FIX issues found
#   1 — MUST-FIX issues found (PR needs changes before merge)
#   2 — Error (missing reports, invalid input)

set -eo pipefail

# Require bash 4+ for associative arrays (declare -A)
if ((BASH_VERSINFO[0] < 4)); then
  echo "Error: bash 4+ required (found ${BASH_VERSION}). Install via: brew install bash" >&2
  exit 2
fi

# ── Configuration ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

OUTPUT_DIR="${1:-.}"
PATTERN="${2:-amcaa-*.md}"
TIMESTAMP=$(date +%Y-%m-%d-%H%M%S)
FINAL_REPORT="${OUTPUT_DIR}/amcaa-pr-review-${TIMESTAMP}.md"

# ── Validate input ────────────────────────────────────────────────────────────
if [ ! -d "$OUTPUT_DIR" ]; then
    echo -e "${RED}Error: Output directory '${OUTPUT_DIR}' does not exist${NC}"
    exit 2
fi

# Find all phase reports
REPORTS=()
while IFS= read -r -d '' file; do
    REPORTS+=("$file")
done < <(find "$OUTPUT_DIR" -maxdepth 1 -name "$PATTERN" -print0 | sort -z)

if [ ${#REPORTS[@]} -eq 0 ]; then
    echo -e "${RED}Error: No reports matching '${PATTERN}' found in '${OUTPUT_DIR}'${NC}"
    exit 2
fi

echo -e "${CYAN}AMCAA Report Merger${NC}"
echo -e "Found ${#REPORTS[@]} reports to merge"
echo ""

# ── Count findings by severity ─────────────────────────────────────────────────
MUST_FIX_COUNT=0
SHOULD_FIX_COUNT=0
NIT_COUNT=0
TOTAL_FINDINGS=0

# Track unique finding IDs to deduplicate
declare -A SEEN_FINDINGS

# Temporary files for categorized findings
MUST_FIX_FINDINGS=$(mktemp)
SHOULD_FIX_FINDINGS=$(mktemp)
NIT_FINDINGS=$(mktemp)
CLEAN_FILES=$(mktemp)

trap 'rm -f "$MUST_FIX_FINDINGS" "$SHOULD_FIX_FINDINGS" "$NIT_FINDINGS" "$CLEAN_FILES"' EXIT

# ── Process each report ────────────────────────────────────────────────────────
for report in "${REPORTS[@]}"; do
    report_name=$(basename "$report")
    echo -e "  Processing: ${report_name}"

    # Extract MUST-FIX sections
    in_section=""
    finding_id=""

    while IFS= read -r line; do
        # Detect section headers
        if [[ "$line" =~ ^#{1,3}[[:space:]]*(MUST.FIX|FAILED[[:space:]]CLAIMS) ]]; then
            in_section="must-fix"
            finding_id=""
            continue
        elif [[ "$line" =~ ^#{1,3}[[:space:]]*(SHOULD.FIX|PARTIALLY[[:space:]]IMPLEMENTED) ]]; then
            in_section="should-fix"
            finding_id=""
            continue
        elif [[ "$line" =~ ^#{1,3}[[:space:]]*(NIT|CONSISTENCY[[:space:]]ISSUES) ]]; then
            in_section="nit"
            finding_id=""
            continue
        elif [[ "$line" =~ ^#{1,3}[[:space:]]*(CLEAN|VERIFIED) ]]; then
            in_section="clean"
            finding_id=""
            continue
        elif [[ "$line" =~ ^#{1,2}[[:space:]]*[0-9] ]] || [[ "$line" =~ ^#{1,2}[[:space:]]*[A-Z] ]] && [ "$in_section" != "" ]; then
            # New top-level section, exit current parsing
            in_section=""
            finding_id=""
            continue
        fi

        # Extract finding IDs like [CC-001], [CV-001], [SR-001]
        if [[ "$line" =~ ^#{2,5}[[:space:]]*\[ ]]; then
            finding_id=$(echo "$line" | grep -oE '\[[A-Z]{2}(-P[0-9]+)?-[0-9]+\]' | head -1)
        fi

        # Route content to appropriate category
        # Use composite dedup key (report:findingId) to prevent cross-agent ID collisions.
        # Multiple correctness agents independently number CC-P{N}-001, CC-P{N}-002, etc.
        # Using just the finding ID as key caused: (a) undercounting, (b) MUST-FIX severity
        # theft when a SHOULD-FIX with the same ID was seen first from an earlier report.
        case "$in_section" in
            must-fix)
                echo "$line" >> "$MUST_FIX_FINDINGS"
                if [ -n "$finding_id" ]; then
                    dedup_key="${report_name}:${finding_id}"
                    if [ -z "${SEEN_FINDINGS[$dedup_key]+x}" ]; then
                        SEEN_FINDINGS[$dedup_key]=1
                        MUST_FIX_COUNT=$((MUST_FIX_COUNT + 1))
                        TOTAL_FINDINGS=$((TOTAL_FINDINGS + 1))
                    fi
                    finding_id=""
                fi
                ;;
            should-fix)
                echo "$line" >> "$SHOULD_FIX_FINDINGS"
                if [ -n "$finding_id" ]; then
                    dedup_key="${report_name}:${finding_id}"
                    if [ -z "${SEEN_FINDINGS[$dedup_key]+x}" ]; then
                        SEEN_FINDINGS[$dedup_key]=1
                        SHOULD_FIX_COUNT=$((SHOULD_FIX_COUNT + 1))
                        TOTAL_FINDINGS=$((TOTAL_FINDINGS + 1))
                    fi
                    finding_id=""
                fi
                ;;
            nit)
                echo "$line" >> "$NIT_FINDINGS"
                if [ -n "$finding_id" ]; then
                    dedup_key="${report_name}:${finding_id}"
                    if [ -z "${SEEN_FINDINGS[$dedup_key]+x}" ]; then
                        SEEN_FINDINGS[$dedup_key]=1
                        NIT_COUNT=$((NIT_COUNT + 1))
                        TOTAL_FINDINGS=$((TOTAL_FINDINGS + 1))
                    fi
                    finding_id=""
                fi
                ;;
            clean)
                echo "$line" >> "$CLEAN_FILES"
                ;;
        esac
    done < "$report"
done

# ── Generate final report ──────────────────────────────────────────────────────
cat > "$FINAL_REPORT" << HEADER
# AMCAA Final PR Review Report

**Generated:** ${TIMESTAMP}
**Reports merged:** ${#REPORTS[@]}
**Pipeline:** Code Correctness → Claim Verification → Skeptical Review

---

## Summary

| Severity | Count |
|----------|-------|
| **MUST-FIX** | ${MUST_FIX_COUNT} |
| **SHOULD-FIX** | ${SHOULD_FIX_COUNT} |
| **NIT** | ${NIT_COUNT} |
| **Total findings** | ${TOTAL_FINDINGS} |

HEADER

# Add verdict based on findings
if [ "$MUST_FIX_COUNT" -gt 0 ]; then
    echo "**Verdict: REQUEST CHANGES** — ${MUST_FIX_COUNT} must-fix issue(s) found." >> "$FINAL_REPORT"
elif [ "$SHOULD_FIX_COUNT" -gt 0 ]; then
    echo "**Verdict: APPROVE WITH NITS** — No blocking issues, but ${SHOULD_FIX_COUNT} recommended fix(es)." >> "$FINAL_REPORT"
else
    echo "**Verdict: APPROVE** — No significant issues found." >> "$FINAL_REPORT"
fi

{
    echo ""
    echo "---"
    echo ""
} >> "$FINAL_REPORT"

# MUST-FIX section — output if count > 0 OR temp file has content (safety net)
if [ "$MUST_FIX_COUNT" -gt 0 ] || [ -s "$MUST_FIX_FINDINGS" ]; then
    {
        echo "## MUST-FIX Issues"
        echo ""
        cat "$MUST_FIX_FINDINGS"
        echo ""
        echo "---"
        echo ""
    } >> "$FINAL_REPORT"
fi

# SHOULD-FIX section
if [ "$SHOULD_FIX_COUNT" -gt 0 ] || [ -s "$SHOULD_FIX_FINDINGS" ]; then
    {
        echo "## SHOULD-FIX Issues"
        echo ""
        cat "$SHOULD_FIX_FINDINGS"
        echo ""
        echo "---"
        echo ""
    } >> "$FINAL_REPORT"
fi

# NIT section
if [ "$NIT_COUNT" -gt 0 ] || [ -s "$NIT_FINDINGS" ]; then
    {
        echo "## Nits & Suggestions"
        echo ""
        cat "$NIT_FINDINGS"
        echo ""
        echo "---"
        echo ""
    } >> "$FINAL_REPORT"
fi

# Source reports
{
    echo "## Source Reports"
    echo ""
    for report in "${REPORTS[@]}"; do
        echo "- \`$(basename "$report")\`"
    done
    echo ""
} >> "$FINAL_REPORT"

# ── Print summary to stdout ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${CYAN}  AMCAA Final Report: ${FINAL_REPORT}${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo ""

if [ "$MUST_FIX_COUNT" -gt 0 ]; then
    echo -e "  ${RED}MUST-FIX:    ${MUST_FIX_COUNT}${NC}"
else
    echo -e "  ${GREEN}MUST-FIX:    0${NC}"
fi

if [ "$SHOULD_FIX_COUNT" -gt 0 ]; then
    echo -e "  ${YELLOW}SHOULD-FIX:  ${SHOULD_FIX_COUNT}${NC}"
else
    echo -e "  ${GREEN}SHOULD-FIX:  0${NC}"
fi

echo -e "  NIT:         ${NIT_COUNT}"
echo -e "  Total:       ${TOTAL_FINDINGS}"
echo ""

if [ "$MUST_FIX_COUNT" -gt 0 ]; then
    echo -e "${RED}PR needs changes before merge.${NC}"
    exit 1
else
    echo -e "${GREEN}No blocking issues found.${NC}"
    exit 0
fi
