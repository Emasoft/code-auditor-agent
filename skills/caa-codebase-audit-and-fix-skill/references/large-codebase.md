# Large Codebase Strategy (1000+ files)

## Table of Contents
- [Tier 1 - Automated Triage](#tier-1--automated-triage-no-agents)
- [Tier 2 - Selective Audit](#tier-2--selective-audit-agents)
- [Tier 3 - Full Coverage](#tier-3--full-coverage-optional)

## Tier 1 — Automated Triage (no agents)

- Run linter/type-checker (e.g., `ruff check`, `tsc --noEmit`, `tldr diagnostics .`) to identify files with existing issues
- Use `git log --since="6 months ago" --name-only` to identify recently changed files
- Prioritize: files with lint errors > recently changed files > high-complexity files > remainder
- Typically reduces audit scope to 10-30% of codebase

## Tier 2 — Selective Audit (agents)

- Audit only Tier 1 priority files
- Batch into groups of 3-4 files, max 20 concurrent agents per round
- Track progress in `{REPORT_DIR}/caa-audit-checkpoint.json`:
  ```json
  {"completed_batches": [0,1,2], "current_batch": 3, "total_batches": 67, "scope_files": 200}
  ```
- If context compaction occurs, resume from checkpoint

## Tier 3 — Full Coverage (optional)

- After Tier 2 fixes are applied, audit remaining files in batches
- Use checkpoint file to track progress across sessions
