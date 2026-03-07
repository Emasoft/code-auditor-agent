# Delta Audit Mode

## Table of Contents
- [Delta Audit Workflow](#delta-audit-workflow)

## Delta Audit Workflow

Re-audit only changed files since last full audit:
1. Identify changes: `git diff --name-only {LAST_AUDIT_COMMIT}` -> changed file list
2. Find affected dependents: `tldr change-impact {changed_files}` (if available) or manual import tracing
3. Combine changed files + affected dependents into the audit scope
4. Run standard Phase 1-5 on this reduced file set
5. Merge delta findings with previous full audit report using the merge script
