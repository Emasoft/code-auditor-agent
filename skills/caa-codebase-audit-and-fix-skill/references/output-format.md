# Output Format

## Table of Contents
- [Pipeline Artifacts](#pipeline-artifacts)

## Pipeline Artifacts

The pipeline produces the following artifacts in `REPORT_DIR` (= `$MAIN_ROOT/reports/code-auditor/`). EVERY artifact follows the canonical `<ts±tz>-<slug>.<ext>` rule — see `instructions.md` § Report Naming for the full table. Per-agent outputs use a fresh `<TS>` per spawn; coordination files use the shared `<PIPELINE_TS>` (pipeline-start timestamp).

| Artifact | Description |
|----------|-------------|
| Per-batch audit reports | `<TS>-caa-audit-*` files from Phase 1 discovery |
| Verification reports | `<TS>-caa-verify-*` files confirming or rejecting findings |
| Gap-fill reports | `<TS>-caa-gapfill-*` files for previously missed files |
| Consolidated domain reports | `<TS>-caa-consolidated-{domain}.md` with deduplicated, classified findings |
| Security review report | `<TS>-caa-security-P{N}-R{RUN_ID}-{UUID}.md` with vulnerability findings and tool scan summary |
| TODO files | `<TS>-TODO-{scope}-changes.md` with actionable items per domain (file:line:evidence) |
| Fix reports (if FIX_ENABLED) | `<TS>-caa-fixes-done-*` with applied changes |
| Fix verification (if FIX_ENABLED) | `<TS>-caa-fixverify-*` with PASS/FAIL/REGRESSION verdicts |
| Manifest | `<PIPELINE_TS>-caa-manifest-R{RUN_ID}.json` tracking all files, batches, and agent assignments |
| Fix checkpoints (if FIX_ENABLED) | `<PIPELINE_TS>-caa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` for crash recovery |
| Fix Dispatch Ledger | `<PIPELINE_TS>-caa-fix-dispatch-P{N}-R{RUN_ID}.json` with per-group dispatch state |
| Final merged report | `<TS>-caa-audit-FINAL.md` with aggregate stats, violation counts, and links to all artifacts |
