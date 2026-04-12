---
name: caa-delta-audit-cmd
description: >
  Run an incremental audit of only the files changed since a previous audit or commit.
  Finds changed files via git diff, traces their dependents, and audits only that subset.
  Merges delta findings with a previous full audit report. NOT a substitute for full audit.
trigger:
  - "/delta-audit"
  - "audit the changes"
  - "audit the delta"
  - "audit recent changes"
  - "incremental audit"
parameters:
  - name: scope
    description: Directory path to audit
    required: true
  - name: since
    description: "Git ref to diff against (commit SHA, tag, or branch). Default: last tagged audit"
    required: false
  - name: fix
    description: Enable fix phases (6-7)
    required: false
    default: "false"
  - name: previous-report
    description: "Path to previous full audit report to merge delta findings into"
    required: false
  - name: report-dir
    description: "Directory for reports (default: reports_dev/code-auditor/)"
    required: false
    default: "reports_dev/code-auditor/"
---

# Delta Audit (Incremental)

This command audits ONLY files changed since a previous point in git history. It is NOT a substitute for a full codebase audit — it is an incremental update between full audits.

## Usage

```
/delta-audit --scope ./src --since v3.2.0
/delta-audit --scope ./src --since HEAD~10 --fix
/delta-audit --scope . --since abc123def --previous-report reports_dev/code-auditor/caa-audit-FINAL-2026-03-15.md
```

## What Happens

1. Identify changed files: `git diff --name-only {since}` within `--scope`
2. Trace dependents: find files that import/reference the changed files
3. Combine changed files + dependents into the delta audit scope
4. Run the standard Phase 1-7 pipeline on this reduced scope
5. If `--previous-report` is provided, merge delta findings with the previous report

## Limitations

- Misses issues in unchanged files that interact with changed code
- Does not detect new cross-file inconsistencies in unchanged code
- Always run a full `/audit-codebase` periodically (recommended: weekly or per milestone)
