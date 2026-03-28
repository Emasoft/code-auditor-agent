# Delta Audit Mode

## Table of Contents
- [When to Use Delta Mode](#when-to-use-delta-mode)
- [Delta Audit Workflow](#delta-audit-workflow)

## When to Use Delta Mode

**Delta mode is NEVER the default.** A "codebase audit" always means auditing EVERY file in the codebase. Delta mode is a separate, explicitly requested operation for incremental updates between full audits.

Use delta mode ONLY when the user explicitly requests it (e.g., "audit only the changes since last audit", "audit the delta", "audit recent changes"). If the user says "audit the codebase" without qualification, run a FULL audit of every file.

## Delta Audit Workflow

When explicitly requested:
1. Identify changes: `git diff --name-only {LAST_AUDIT_COMMIT}` -> changed file list
2. Find affected dependents: `tldr change-impact {changed_files}` (if available) or manual import tracing
3. Combine changed files + affected dependents into the audit scope
4. Run standard Phase 1-5 on this reduced file set
5. Merge delta findings with previous full audit report using the merge script

**WARNING:** Delta audits miss issues in unchanged files that interact with changed code. Always run a full audit periodically.
