---
name: caa-pr-review-and-fix-skill
description: >
  Use when reviewing and fixing PRs with automated iterative resolution.
  Trigger with "review and fix the PR", "audit and fix the PR", "pre-merge review and fix".
version: 3.1.17
author: Emasoft
license: MIT
tags:
  - caa-pr-review
  - code-audit
  - claim-verification
  - quality-gate
  - auto-fix
---

# PR Review And Fix

## Overview

Iterative review-and-fix loop combining two procedures until zero issues remain or max passes reached. PROCEDURE 1 runs a six-phase review pipeline (correctness swarm, claim verification, skeptical review, security review, merge+dedup, present). PROCEDURE 2 spawns fix agents, runs tests, commits. Loop repeats up to 25 passes.

## Prerequisites

Copy this checklist and track your progress:

- [ ] `gh` CLI installed and authenticated
- [ ] PR exists on GitHub (need PR number or branch)
- [ ] `docs_dev/` exists and is in `.gitignore`
- [ ] `${CLAUDE_PLUGIN_ROOT}` is set and non-empty
- [ ] Merge script exists at `${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-reports.py`

## Instructions

1. Initialize `PASS_NUMBER=1`, `MAX_PASSES=25`. Read [Critical Rules](references/critical-rules.md) first.
2. Run **PROCEDURE 1** (six-phase review): see [Procedure 1](references/procedure-1-review.md).
3. If zero issues found, write final report and exit with APPROVE.
4. If `PASS_NUMBER > MAX_PASSES`, write escalation report and exit.
5. Run **PROCEDURE 2** (fix cycle): see [Procedure 2](references/procedure-2-fix.md).
6. Increment `PASS_NUMBER`, go to step 2.

## Output

Produces per-pass review reports and a final summary in `docs_dev/`:

- [Output Format](references/output-format.md):
  - [Deliverables Table](references/output-format.md#deliverables-table)

## Error Handling

On agent failure: detect, clean up, re-spawn. On phase failure: retry once, then escalate.

- [Error Handling](references/error-handling.md):
  - [Error Recovery by Phase](references/error-handling.md#error-recovery-by-phase)
- [Agent Recovery](references/agent-recovery.md):
  - [Failure Modes](references/agent-recovery.md#failure-modes--detection)

## Examples

**Input:**
```
User: "review and fix PR 206"
```

**Output:**
```
Pass 1: Review finds 8 issues -> fix agents resolve all -> commit
Pass 2: Review finds 2 regressions -> fix agents resolve -> commit
Pass 3: Review finds 0 issues -> APPROVE, final report written
```

## Resources

- [Procedure 1: Code Review](references/procedure-1-review.md):
  - [Phase 1: Correctness Swarm](references/procedure-1-review.md#phase-1-code-correctness-swarm)
- [Procedure 2: Code Fix](references/procedure-2-fix.md):
  - [Fix Protocol](references/procedure-2-fix.md#fix-protocol)
- [Pass Counter](references/pass-counter.md):
  - [Initialization](references/pass-counter.md#initialization)
- [Loop Termination](references/loop-termination.md):
  - [Termination Logic](references/loop-termination.md#termination-logic)
- [Report Naming](references/report-naming.md):
  - [Filename Table](references/report-naming.md#filename-table)
- [Critical Rules](references/critical-rules.md):
  - [Rule 1](references/critical-rules.md#rule-1-never-skip-phases)
- [Model Selection](references/model-selection.md):
  - [Rules](references/model-selection.md#rules)
- [Worktree Mode](references/worktree-mode.md):
  - [How It Works](references/worktree-mode.md#how-it-works)
- [Rationale](references/rationale.md):
  - [The Incident](references/rationale.md#the-incident)
- [Lessons Learned](references/lessons-learned.md):
  - [Review Architecture](references/lessons-learned.md#review-architecture-lessons)
- [Examples](references/examples.md):
  - [Full Review-and-Fix Pipeline](references/examples.md#full-review-and-fix-pipeline)
