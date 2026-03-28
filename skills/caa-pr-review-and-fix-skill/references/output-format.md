# Output

## Table of Contents

- [Deliverables Table](#deliverables-table)
- [Key Outputs for the User](#key-outputs-for-the-user)

## Deliverables Table

The pipeline produces these deliverables across all passes:

| Deliverable | Location | When |
|-------------|----------|------|
| Per-pass review report (deduplicated) | `docs_dev/caa-pr-review-P{N}-{timestamp}.md` | After each Procedure 1 |
| Per-group fix issues | `docs_dev/caa-fix-group-{GROUP_ID}.md` | Procedure 2 step 1 (script-generated) |
| Per-group lint results | `docs_dev/caa-lint-group-{GROUP_ID}.md` | Procedure 2 per-group lint step |
| Per-group security findings | `docs_dev/caa-security-group-{GROUP_ID}.md` | Phase 4 security review |
| Per-group review findings | `docs_dev/caa-review-group-{GROUP_ID}.md` | Phase 3 skeptical review |
| Per-domain fix summaries | `docs_dev/caa-fixes-done-P{N}-{domain}.md` | After each Procedure 2 |
| Test outcome per pass | `docs_dev/caa-tests-outcome-P{N}.md` | After each test run |
| Lint outcome (joined) | `docs_dev/caa-lint-outcome-P{N}.md` | After per-group lint joined by script |
| Recovery log | `docs_dev/caa-recovery-log-P{N}.md` | When agent failures occur |
| Final report (zero issues) | `docs_dev/caa-pr-review-and-fix-FINAL-{timestamp}.md` | Pipeline completion |
| Escalation report (max passes) | `docs_dev/caa-pr-review-and-fix-escalation-{timestamp}.md` | If limit reached |

## Key Outputs for the User

- **Final report** summarizes all passes, all fixes applied, and final verdict (APPROVE)
- **Escalation report** lists remaining unresolved issues if the pass limit was reached
- **Per-pass review reports** provide the detailed audit trail of findings and resolutions
