---
name: caa-pr-review-skill
description: >
  Trigger with "review the PR", "check the PR", "audit the PR", "pre-merge review".
  Use when reviewing PRs, auditing code, or running pre-merge quality gates.
version: 3.1.20
author: Emasoft
license: MIT
tags: [caa-pr-review, code-audit, claim-verification, quality-gate]
---

# PR Review

## Overview

Six-phase PR review pipeline: correctness swarm, claim verification, skeptical + security review in parallel, merge + dedup. Catches what standard audits miss.

## Prerequisites

- `gh` CLI authenticated, PR exists on GitHub, `docs_dev/` dir exists
- `${CLAUDE_PLUGIN_ROOT}` set, merge script at `scripts/caa-merge-reports.py`

## Instructions

1. Gather PR number, description, changed files grouped by domain
2. Spawn one `caa-code-correctness-agent` per domain in parallel
3. Spawn `caa-claim-verification-agent` (after step 2 completes)
4. Spawn `caa-skeptical-reviewer-agent` AND `caa-security-review-agent` in parallel
5. Run merge: `uv run ${MERGE_SCRIPT} --quiet ${REPORT_DIR} 1`, then spawn `caa-dedup-agent`
6. Present verdict per [review-complete.md](references/review-complete.md)

If MUST-FIX issues exist, do NOT push until resolved and pipeline re-run.

## Output

Final merged report in `docs_dev/` with verdict (PASS/CONDITIONAL/FAIL), per-finding severity, MUST-FIX/SHOULD-FIX/NIT counts. Details:

- [Output Format](references/output-format.md):
  - [Report Files](references/output-format.md#report-files)
  - [Final Report Contents](references/output-format.md#final-report-contents)

## Error Handling

Agent failures: re-spawn with new UUID. Merge errors: check report paths. Details:

- [Error Handling](references/error-handling.md):
  - [Phase Recovery](references/error-handling.md#phase-level-recovery)
  - [Merge Errors](references/error-handling.md#merge-script-errors)

## Examples

```
Input: "review PR 206"
Output: 6-phase pipeline → merged verdict with 3 MUST-FIX, 2 SHOULD-FIX, 5 NIT
```

```
Input: "just verify the claims in PR 206"
Output: Single caa-claim-verification-agent report
```

## Checklist

Copy this checklist and track your progress:

- [ ] All 6 phases completed (no skipped phases)
- [ ] PR description claims verified against actual code
- [ ] MUST-FIX issues resolved before push

## Resources

- [Protocol](references/protocol.md):
  - [Prerequisites](references/protocol.md#prerequisites)
- [Rationale](references/rationale.md):
  - [The Incident](references/rationale.md#the-incident)
- [Review Complete](references/review-complete.md):
  - [Verdict Template](references/review-complete.md#verdict-summary-template)
- [Critical Rules](references/critical-rules.md):
  - [Never Skip Phases](references/critical-rules.md#rule-1-never-skip-phases)
- [Model Selection](references/model-selection.md):
  - [Code Analysis Models](references/model-selection.md#code-analysis-models)
- [Quick Reference](references/quick-reference.md):
  - [Pipeline Triggers](references/quick-reference.md#pipeline-triggers)
- [Output Format](references/output-format.md):
  - [Report Files](references/output-format.md#report-files)
- [Error Handling](references/error-handling.md):
  - [Phase Recovery](references/error-handling.md#phase-level-recovery)
- [Agent Recovery](references/agent-recovery.md):
  - [Failure Modes](references/agent-recovery.md#failure-modes--detection)
- [Lessons Learned](references/lessons-learned.md):
  - [Checklist](references/lessons-learned.md#checklist)
