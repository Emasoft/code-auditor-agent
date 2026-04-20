# Output Format

## Table of Contents

- [Report Files](#report-files)
- [Final Report Contents](#final-report-contents)

## Report Files

The pipeline produces:
- Per-domain correctness reports: `reports/code-auditor/caa-correctness-P1-{uuid}.md` (deleted after merge verification)
- Claim verification report: `reports/code-auditor/caa-claims-P1-{uuid}.md` (deleted after merge verification)
- Skeptical review report: `reports/code-auditor/caa-review-P1-{uuid}.md` (deleted after merge verification)
- Security review report: `reports/code-auditor/caa-security-P1-{uuid}.md` (deleted after merge verification)
- Intermediate merged report: `reports/code-auditor/caa-pr-review-P1-intermediate-{timestamp}.md`
- Final deduplicated report: `reports/code-auditor/caa-pr-review-P1-{timestamp}.md`

## Final Report Contents

Final report includes: verdict (APPROVE/REQUEST CHANGES/APPROVE WITH NITS), all
deduplicated issues with severity (MUST-FIX/SHOULD-FIX/NIT), deduplication log, and
original finding ID cross-references.
