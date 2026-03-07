# Output Format

## Table of Contents
- [Pipeline Artifacts](#pipeline-artifacts)

## Pipeline Artifacts

The pipeline produces the following artifacts in `REPORT_DIR`:

| Artifact | Description |
|----------|-------------|
| Per-batch audit reports | Individual `caa-audit-*` files from Phase 1 discovery |
| Verification reports | `caa-verify-*` files confirming or rejecting findings |
| Gap-fill reports | `caa-gapfill-*` files for previously missed files |
| Consolidated domain reports | `caa-consolidated-{domain}.md` with deduplicated, classified findings |
| Security review report | `caa-security-P{N}-R{RUN_ID}-{UUID}.md` with vulnerability findings and tool scan summary |
| TODO files | `TODO-{scope}-changes.md` with actionable items per domain (file:line:evidence) |
| Fix reports (if FIX_ENABLED) | `caa-fixes-done-*` with applied changes and checkpoints |
| Fix verification (if FIX_ENABLED) | `caa-fixverify-*` with PASS/FAIL/REGRESSION verdicts |
| Manifest | `caa-manifest-R{RUN_ID}.json` tracking all files, batches, and agent assignments |
| Final merged report | `caa-audit-FINAL-{timestamp}.md` with aggregate stats, violation counts, and links to all artifacts |
