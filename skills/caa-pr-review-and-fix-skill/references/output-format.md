# Output

## Table of Contents

- [Deliverables Table](#deliverables-table)
- [Key Outputs for the User](#key-outputs-for-the-user)

## Deliverables Table

The pipeline produces these deliverables across all passes. EVERY file follows the canonical `$MAIN_ROOT/reports/<component>/<ts±tz>-<slug>.<ext>` rule — see `report-naming.md` for the full rule.

| Deliverable | Location | When |
|-------------|----------|------|
| Per-pass review report (deduplicated) | `reports/code-auditor/{TS}-caa-pr-review-P{N}.md` | After each Procedure 1 |
| Per-group fix issues | `reports/code-auditor/{PIPELINE_TS}-caa-fix-group-{GROUP_ID}.md` | Procedure 2 step 1 (script-generated at pipeline-start grouping time) |
| Per-group lint results | `reports/code-auditor/{TS}-caa-lint-group-{GROUP_ID}.md` | Procedure 2 per-group lint step |
| Per-group security findings | `reports/code-auditor/{TS}-caa-security-group-{GROUP_ID}.md` | Phase 4 security review |
| Per-group review findings | `reports/code-auditor/{TS}-caa-review-group-{GROUP_ID}.md` | Phase 3 skeptical review |
| Per-domain fix summaries | `reports/code-auditor/{TS}-caa-fixes-done-P{N}-{domain}.md` | After each Procedure 2 |
| Test outcome per pass | `reports/code-auditor/{TS}-caa-tests-outcome-P{N}.md` | After each test run |
| Lint outcome (joined) | `reports/code-auditor/{TS}-caa-lint-outcome-P{N}.md` | After per-group lint joined by script |
| Recovery log | `reports/code-auditor/{TS}-caa-recovery-log-P{N}.md` | When agent failures occur |
| Final report (zero issues) | `reports/code-auditor/{TS}-caa-pr-review-and-fix-FINAL.md` | Pipeline completion |
| Escalation report (max passes) | `reports/code-auditor/{TS}-caa-pr-review-and-fix-escalation.md` | If limit reached |

## Key Outputs for the User

- **Final report** summarizes all passes, all fixes applied, and final verdict (APPROVE)
- **Escalation report** lists remaining unresolved issues if the pass limit was reached
- **Per-pass review reports** provide the detailed audit trail of findings and resolutions
