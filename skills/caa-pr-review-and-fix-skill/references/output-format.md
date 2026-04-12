# Output

## Table of Contents

- [Deliverables Table](#deliverables-table)
- [Key Outputs for the User](#key-outputs-for-the-user)

## Deliverables Table

The pipeline produces these deliverables across all passes:

| Deliverable | Location | When |
|-------------|----------|------|
| Per-pass review report (deduplicated) | `reports_dev/code-auditor/caa-pr-review-P{N}-{timestamp}.md` | After each Procedure 1 |
| Per-group fix issues | `reports_dev/code-auditor/caa-fix-group-{GROUP_ID}.md` | Procedure 2 step 1 (script-generated) |
| Per-group lint results | `reports_dev/code-auditor/caa-lint-group-{GROUP_ID}.md` | Procedure 2 per-group lint step |
| Per-group security findings | `reports_dev/code-auditor/caa-security-group-{GROUP_ID}.md` | Phase 4 security review |
| Per-group review findings | `reports_dev/code-auditor/caa-review-group-{GROUP_ID}.md` | Phase 3 skeptical review |
| Per-domain fix summaries | `reports_dev/code-auditor/caa-fixes-done-P{N}-{domain}.md` | After each Procedure 2 |
| Test outcome per pass | `reports_dev/code-auditor/caa-tests-outcome-P{N}.md` | After each test run |
| Lint outcome (joined) | `reports_dev/code-auditor/caa-lint-outcome-P{N}.md` | After per-group lint joined by script |
| Recovery log | `reports_dev/code-auditor/caa-recovery-log-P{N}.md` | When agent failures occur |
| Final report (zero issues) | `reports_dev/code-auditor/caa-pr-review-and-fix-FINAL-{timestamp}.md` | Pipeline completion |
| Escalation report (max passes) | `reports_dev/code-auditor/caa-pr-review-and-fix-escalation-{timestamp}.md` | If limit reached |

## Key Outputs for the User

- **Final report** summarizes all passes, all fixes applied, and final verdict (APPROVE)
- **Escalation report** lists remaining unresolved issues if the pass limit was reached
- **Per-pass review reports** provide the detailed audit trail of findings and resolutions
