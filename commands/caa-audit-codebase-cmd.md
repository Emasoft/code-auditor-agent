---
name: caa-audit-codebase-cmd
description: >
  Run a full codebase audit against a reference standard. Discovers all files, triages with
  grep, audits in parallel batches, verifies findings, fills gaps, consolidates per-domain,
  and generates actionable TODO files. Optionally applies fixes with verification loop.
trigger:
  - "/audit-codebase"
  - "audit the codebase"
  - "run code audit"
  - "compliance audit"
  - "decoupling audit"
parameters:
  - name: scope
    description: Directory path to audit
    required: true
  - name: standard
    description: Path to reference standard document
    required: true
  - name: types
    description: "Comma-separated violation types (default HARDCODED_API,HARDCODED_GOVERNANCE,DIRECT_DEPENDENCY,HARDCODED_PATH,MISSING_ABSTRACTION)"
    required: false
  - name: fix
    description: Enable fix phases (6-7)
    required: false
    default: "false"
  - name: todo-only
    description: Stop after Phase 5 (generate TODOs, don't fix)
    required: false
    default: "false"
  - name: grep-patterns
    description: Path to file with custom grep patterns (one per line)
    required: false
  - name: report-dir
    description: "Directory for reports (default: docs_dev/)"
    required: false
    default: "docs_dev/"
  - name: max-fix-passes
    description: "Maximum fix-verify iterations (default 5)"
    required: false
    default: "5"
  - name: worktrees
    description: Run agent swarms in isolated git worktrees
    required: false
    default: "false"
---

# Codebase Audit & Fix

This command launches the `caa-codebase-audit-and-fix-skill` skill pipeline.

## Usage

```
/audit-codebase --scope ./plugins/my-plugin --standard ./docs/compliance-rules.md
/audit-codebase --scope ./src --standard ./standards/api-rules.md --fix
/audit-codebase --scope ./plugins/amcos --standard ./docs/decoupling-standard.md --todo-only --types HARDCODED_API,DIRECT_DEPENDENCY
```

## What Happens

1. **Phase 0**: Inventories all files, classifies by domain, triages with grep
2. **Phase 1**: Spawns parallel auditor agents (3-4 files each)
3. **Phase 2**: Verification swarm cross-checks all audit reports
4. **Phase 3**: Gap-fill audits missed files (iterative until 100% coverage)
5. **Phase 4**: Consolidation per domain (dedup, severity harmonization)
6. **Phase 4b**: Security review — spawns caa-security-review-agent for vulnerability, secrets, and dependency scanning
7. **Phase 5**: Generates actionable TODO files per scope
8. **Phase 6** (if --fix): Applies fixes from TODOs
9. **Phase 7** (if --fix): Verifies fixes, loops if regressions found
10. **Phase 8**: Final merged report
- When `--worktrees` is enabled, each agent swarm runs in isolated git worktrees. Fix agent branches are merged back sequentially after completion.

## Reports

All reports written to `--report-dir` (default: docs_dev/).
See the `caa-codebase-audit-and-fix-skill` skill for report naming conventions.
