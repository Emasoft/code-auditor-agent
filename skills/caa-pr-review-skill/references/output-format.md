# Output Format

## Table of Contents

- [Report Files](#report-files)
- [Final Report Contents](#final-report-contents)

## Report Files

The pipeline produces (all under `$MAIN_ROOT/reports/code-auditor/`, all canonical `<ts±tz>-<slug>.<ext>` form):
- Per-domain correctness reports: `{TS}-caa-correctness-P1-{uuid}.md` (deleted after merge verification)
- Claim verification report: `{TS}-caa-claims-P1-{uuid}.md` (deleted after merge verification)
- Skeptical review report: `{TS}-caa-review-P1-{uuid}.md` (deleted after merge verification)
- Security review report: `{TS}-caa-security-P1-{uuid}.md` (deleted after merge verification)
- Intermediate merged report: `{TS}-caa-pr-review-P1-intermediate.md`
- Final deduplicated report: `{TS}-caa-pr-review-P1.md`

Per-agent outputs use a fresh `<TS>` per spawn; see `caa-pr-review-and-fix-skill/references/report-naming.md` for the complete canonical rule.

## Final Report Contents

Final report includes: verdict (APPROVE/REQUEST CHANGES/APPROVE WITH NITS), all
deduplicated issues with severity (MUST-FIX/SHOULD-FIX/NIT), deduplication log, and
original finding ID cross-references.
