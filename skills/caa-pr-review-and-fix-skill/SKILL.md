---
name: caa-pr-review-and-fix-skill
description: >
  Trigger with "review and fix the PR", "audit and fix the PR", "pre-merge review and fix".
  Use when reviewing and fixing PRs with automated iterative resolution.
version: 3.2.22
author: Emasoft
license: MIT
tags: [caa-pr-review, code-audit, claim-verification, quality-gate, auto-fix]
effort: high
allowed-tools: "Read, Write, Edit, Glob, Grep, Bash(uv:*), Bash(git:*), Bash(gh:*), Agent, WebFetch, mcp__plugin_llm-externalizer_llm-externalizer__*"
---

# PR Review And Fix

## Overview

Iterative review-and-fix: six-phase review (P1) then fix+test+commit (P2), repeating up to 25 passes.

## Prerequisites

`gh` authenticated, PR on GitHub, `docs_dev/` exists, `${CLAUDE_PLUGIN_ROOT}` set, `scripts/caa-merge-reports.py`

## Instructions

1. Initialize `PASS_NUMBER=1`, `MAX_PASSES=25`. Read critical-rules.md first.
2. Run **PROCEDURE 1** (six-phase review): see procedure-1-review.md.
3. If zero issues found, write final report and exit with APPROVE.
4. If `PASS_NUMBER > MAX_PASSES`, write escalation report and exit.
5. Run **PROCEDURE 2** (fix cycle): see procedure-2-fix.md.
6. Increment `PASS_NUMBER`, go to step 2.

## Output

- [Output Format](references/output-format.md):
  - Deliverables Table, Key Outputs for the User

## Error Handling

- [Error Handling](references/error-handling.md):
  - Error Recovery by Phase
- [Agent Recovery](references/agent-recovery.md):
  - Failure Modes & Detection, Step 1: Detect the Loss, Step 2: Verify the Loss, Step 3: Clean Up Partial Artifacts
  - Step 4: Re-Spawn the Task, Step 5: Record the Failure, Special Cases, Lost during context compaction
  - Agent wrote report with wrong pass number (version/cache collision), Agent Recovery Checklist
  - Multiple correctness agents for the same domain (domain label collision), Test runner left no report but tests actually ran

## Checklist

Copy this checklist and track your progress:

- [ ] All passes completed, zero issues
- [ ] Final report in docs_dev/

## Examples

```
Input: "review and fix PR 206"
Output: Pass 1: 8 issues fixed. Pass 2: 2 regressions. Pass 3: 0 issues → APPROVE.
```

## Resources

- [Procedure 1: Code Review](references/procedure-1-review.md):
  - Pre-Pass Cleanup (MANDATORY), Agent Manifest, Prerequisites, Phase 1: Code Correctness Swarm
  - Phase 2: Claim Verification, Phase 3: Skeptical Review, Phase 4: Security Review
  - Phase 5: Merge Reports + Deduplicate, Phase 6: Present Results, Procedure 1 Checklist
- [Procedure 2: Code Fix](references/procedure-2-fix.md):
  - Agent Selection (Dynamic), Fix Protocol, Linting Step (Docker Required)
  - Commit After Fixes, Procedure 2 Output, Procedure 2 Checklist
- [Pass Counter](references/pass-counter.md):
  - Initialization, Run ID Generation, Pass Increment and Limit
- [Loop Termination](references/loop-termination.md):
  - Termination Logic, Final Report Format
- [Report Naming](references/report-naming.md):
  - Overview, Filename Table, UUID Filename Generation, Agent-Prefixed Finding IDs, Pre-Pass Cleanup
- [Critical Rules](references/critical-rules.md):
  - Rules 1-14: Phase ordering, UUID naming, two-stage merge, dedup verdict, fix-all, commit cadence, 25-pass limit
- [Model Selection](references/model-selection.md):
  - Rules
- [Worktree Mode](references/worktree-mode.md):
  - How It Works, Prerequisites for Worktree Mode, When NOT to Use Worktrees
- [Rationale](references/rationale.md):
  - The Incident, Four Complementary Review Perspectives
- [Lessons Learned](references/lessons-learned.md):
  - Review Architecture Lessons, Fix Cycle Lessons, Pipeline Robustness Lessons, Lessons Learned Review Checklist
- [Examples](references/examples.md):
  - Full Review-and-Fix Pipeline
