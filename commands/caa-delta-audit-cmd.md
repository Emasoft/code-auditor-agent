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
    description: "Directory for reports (default: reports/code-auditor/)"
    required: false
    default: "reports/code-auditor/"
  - name: extended
    description: >
      Add scenario-walker + assumption-auditor swarms scoped to the delta
      (TRDD-6857f67f). Runs caa-scenario-generator-skill in delta mode —
      scenarios are emitted only for entry points that the changed files
      participate in. Assumption auditor runs only on changed files. Same
      cross-category consolidation as /audit-codebase --extended.
    required: false
    default: "false"
---

# Delta Audit (Incremental)

This command audits ONLY files changed since a previous point in git history. It is NOT a substitute for a full codebase audit — it is an incremental update between full audits.

## Usage

```
/delta-audit --scope ./src --since v3.2.0
/delta-audit --scope ./src --since HEAD~10 --fix
/delta-audit --scope . --since abc123def --previous-report reports/code-auditor/20260315_120000+0000-caa-audit-FINAL.md

# Extended delta — scenario walker + assumption auditor on the delta only
/delta-audit --scope ./src --since v3.2.0 --extended
```

## What Happens

1. Identify changed files: `git diff --name-only {since}` within `--scope`
2. Trace dependents: find files that import/reference the changed files
3. Combine changed files + dependents into the delta audit scope
4. Run the standard Phase 1-7 pipeline on this reduced scope
5. If `--extended`: scenario-generator runs in delta mode — emits scenarios
   only for entry points participating in the changed files. Walker swarm
   processes those scenarios; assumption-auditor swarm processes the changed
   files. Cross-category findings merged at consolidation.
6. If `--previous-report` is provided, merge delta findings with the previous report

## Limitations

- Misses issues in unchanged files that interact with changed code
- Does not detect new cross-file inconsistencies in unchanged code
- Always run a full `/audit-codebase` periodically (recommended: weekly or per milestone)
