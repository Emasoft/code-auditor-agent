# Output

## Table of Contents

- [Deliverables Table](#deliverables-table)
- [Key Outputs for the User](#key-outputs-for-the-user)

## Deliverables Table

The pipeline produces these deliverables across all passes:

| Deliverable | Location | When |
|-------------|----------|------|
| Per-pass review report (deduplicated) | `docs_dev/caa-pr-review-P{N}-{timestamp}.md` | After each Procedure 1 |
| Per-domain fix summaries | `docs_dev/caa-fixes-done-P{N}-{domain}.md` | After each Procedure 2 |
| Test outcome per pass | `docs_dev/caa-tests-outcome-P{N}.md` | After each test run |
| Lint outcome per pass | `docs_dev/caa-lint-outcome-P{N}.md` | After each lint run (Docker only) |
| Lint summary JSON | `docs_dev/megalinter-P{N}/lint-summary.json` | After each lint run (Docker only) |
| Recovery log | `docs_dev/caa-recovery-log-P{N}.md` | When agent failures occur |
| Final report (zero issues) | `docs_dev/caa-pr-review-and-fix-FINAL-{timestamp}.md` | Pipeline completion |
| Escalation report (max passes) | `docs_dev/caa-pr-review-and-fix-escalation-{timestamp}.md` | If limit reached |

## Key Outputs for the User

- **Final report** summarizes all passes, all fixes applied, and final verdict (APPROVE)
- **Escalation report** lists remaining unresolved issues if the pass limit was reached
- **Per-pass review reports** provide the detailed audit trail of findings and resolutions
