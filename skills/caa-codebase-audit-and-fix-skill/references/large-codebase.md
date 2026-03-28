# Large Codebase Strategy (1000+ files)

## Table of Contents
- [Full Coverage (Default)](#full-coverage-default)
- [Automated Triage for Prioritization](#automated-triage-for-prioritization)
- [Checkpoint and Resume](#checkpoint-and-resume)

## Full Coverage (Default)

**Every file is audited. No files are skipped.** For large codebases, the challenge is managing concurrency and context — not reducing scope.

Phase 0 groups ALL files into batches of 3-4. The externalizer processes all groups via GROUP markers in a single call. Fix agents receive only their group's reports. This scales to any codebase size without skipping files.

For codebases with 1000+ files:
- Phase 0 produces ~250-350 groups
- Externalizer auto-batches groups that exceed context window
- Agent concurrency capped at 20 per round
- Checkpoint file tracks progress for resume after interruption

## Automated Triage for Prioritization

Triage determines PROCESSING ORDER, not scope. All files are audited — triage just decides which groups go first:

1. Run linter/type-checker (`ruff check`, `tsc --noEmit`, `tldr diagnostics .`) to identify files with existing issues
2. Tag groups: files with lint errors → HIGH priority, others → NORMAL priority
3. Process HIGH priority groups first in Phase 1, then NORMAL groups
4. This gets actionable findings early without skipping any files

## Checkpoint and Resume

Track progress in `{REPORT_DIR}/caa-audit-checkpoint.json`:

```json
{"completed_groups": [0,1,2], "current_group": 3, "total_groups": 267, "scope_files": 1000}
```

If context compaction or crash occurs, resume from checkpoint. The Fix Dispatch Ledger + checkpoint together ensure no group is processed twice and no group is missed.
