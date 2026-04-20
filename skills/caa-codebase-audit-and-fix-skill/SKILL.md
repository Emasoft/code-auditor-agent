---
name: caa-codebase-audit-and-fix-skill
description: "Trigger with /audit-codebase, 'audit the codebase', 'compliance audit', 'codebase audit'. Use when auditing a codebase for compliance violations, generating TODOs, or applying automated fixes."
version: 3.2.24
author: Emasoft
license: MIT
tags: [codebase-audit, compliance, todo-generation, iterative-fix]
effort: high
allowed-tools: "Read, Write, Glob, Grep, Bash(uv:*), Bash(git:*), Bash(python:*), Agent, WebFetch, mcp__plugin_llm-externalizer_llm-externalizer__*"
---

# Codebase Audit And Fix

## Overview

10-phase pipeline auditing every file against a reference standard with grep triage, batch processing, multi-wave verification, gap-fill, and optional automated fixes.

## Prerequisites

| Agent | Phase | Purpose |
|-------|-------|---------|
| `caa-domain-auditor-agent` | 1, 3 | Discovery and gap-fill auditing |
| `caa-verification-agent` | 2, 3 | Cross-check and missed-file detection |
| `caa-consolidation-agent` | 4 | Merge, dedup, classify findings |
| `caa-security-review-agent` | 4b | Vulnerabilities, secrets, CVEs |
| `caa-todo-generator-agent` | 5 | Actionable TODO generation |
| `caa-fix-agent` | 6 | Implement fixes with checkpoints |
| `caa-fix-verifier-agent` | 7 | Verify fixes, detect regressions |

Requires: Python 3.12+, `uv`, Git repo. Uses `${CLAUDE_PLUGIN_ROOT}` for scripts, `${CLAUDE_SKILL_DIR}` for reference docs, `${CLAUDE_PLUGIN_DATA}` for persistent audit state.

## Instructions

1. Set `SCOPE_PATH`, `REFERENCE_STANDARD`, generate `RUN_ID` (8 hex).
2. P0: Inventory all files, create 3-4 file batches per domain.
3. P1: Spawn `caa-domain-auditor-agent` swarms on each batch.
4. P2: Spawn `caa-verification-agent` to cross-check reports.
5. P3: Gap-fill any missed files with additional audit waves.
6. P4: Consolidate per-domain, then run P4b security scan (MANDATORY).
7. P5: Generate actionable TODOs via `caa-todo-generator-agent`.
8. P6-P7: If `FIX_ENABLED=true`, apply fixes and verify (else skip).
9. P8: Compile final report. See [instructions](references/instructions.md).

## Output

Produces a consolidated audit report in `reports/code-auditor/` with per-domain findings, a TODO list, and a final summary. See [output format](references/output-format.md).

## Error Handling

On agent failure, retry with checkpoint recovery. See [error handling](references/error-handling.md).

## Examples

```
Input: /audit-codebase with SCOPE_PATH=src/, FIX_ENABLED=false
Output: Audit report in reports/code-auditor/ with per-domain findings and TODO list
```

```
Input: /audit-codebase with FIX_ENABLED=true, MAX_FIX_PASSES=3
Output: All 9 phases run; fixes applied, verified, final report generated
```

## Checklist

Copy this checklist and track your progress:

- [ ] All files in SCOPE_PATH audited (0 missed)
- [ ] Security scan (P4b) completed
- [ ] TODO list generated and saved
- [ ] Final report compiled in reports/code-auditor/

## Resources

- [Instructions](references/instructions.md)
  - Phase Steps, Parameters, Pipeline, Report Naming
  - Finding IDs, Spawning Patterns, Fix Agent Worktree Merge-Back, Loop Termination
- [Output Format](references/output-format.md)
  - Pipeline artifacts and report structure
- [Model Selection](references/model-selection.md)
  - Model requirements per agent
- [Error Handling](references/error-handling.md)
  - Recovery strategies and retry logic
- [Completion Checklist](references/completion-checklist.md)
  - Progress tracking criteria
- [Remote Scanning](references/remote-scanning.md)
  - Local Clone Method, API-Only Method
- [Monorepo & Workspaces](references/monorepo.md)
  - Workspace detection and audit strategy
- [Large Codebase Strategy](references/large-codebase.md)
  - Tier 1 - Automated Triage, Tier 2 - Selective Audit, Tier 3 - Full Coverage
- [Delta Audit Mode](references/delta-audit.md)
  - Delta Audit Workflow
