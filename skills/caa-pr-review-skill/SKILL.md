---
name: caa-pr-review-skill
description: >
  Trigger with "review the PR", "check the PR", "audit the PR", "pre-merge review".
  Use when reviewing PRs, auditing code, or running pre-merge quality gates.
version: 3.4.4
author: Emasoft
license: MIT
tags: [caa-pr-review, code-audit, claim-verification, quality-gate]
effort: high
allowed-tools: "Read, Write, Glob, Grep, Bash(uv:*), Bash(git:*), Bash(gh:*), Agent, WebFetch, mcp__plugin_llm-externalizer_llm-externalizer__*"
---

# PR Review

## Overview

Depth-parameterised pipeline. `--code-analysis-depth N` (1..23, default 4) or `--preset quick|standard|deep|thorough|full` picks how many of the 24 steps run. Step 0 gate always-on. Depth 4 = current six-phase behaviour. Security scan (step 4) is **MANDATORY** at depth ≥ 4.

## Prerequisites

- `gh` CLI authenticated, PR on GitHub, `reports/code-auditor/` exists, `${CLAUDE_PLUGIN_ROOT}` set

## Instructions

1. Parse depth/preset; clamp 1..23, default 4.
2. Always run Step 0 `detect_languages_and_domains.py` → `reports/caa-prereview/<ts>-domains_detected.json`.
3. If depth ≥ 5, run pre-flight scripts in parallel; emit `<ts>-manifest.json`.
4. Run LLM phases 1-4: correctness → claim verification → skeptical + security (parallel).
5. Merge: `uv run ${MERGE_SCRIPT} --quiet ${REPORT_DIR} 1`, then `caa-dedup-agent`.
6. Present verdict per review-complete.md; list skipped steps (depth limit / TODO).

If MUST-FIX exists, do NOT push until resolved and pipeline re-run.

## Output

Final merged report in `reports/code-auditor/` with verdict (PASS/CONDITIONAL/FAIL), per-finding severity, MUST-FIX/SHOULD-FIX/NIT counts. Details:

- [Output Format](references/output-format.md):
  - Report Files, Final Report Contents

## Error Handling

Agent failures: re-spawn with new UUID. Merge errors: check report paths. Details:

- [Error Handling](references/error-handling.md):
  - Phase-Level Recovery, Merge Script Errors, Authentication Errors

## Examples

```
Input: "review PR 206"                         (depth 4, current default)
Input: "review PR 206 --preset standard"       (depth 10, adds pre-flight scripts)
Input: "review PR 206 --code-analysis-depth 15" (deep)
Output: 6-phase pipeline → verdict (3 MUST-FIX, 2 SHOULD-FIX, 5 NIT)
```

Phase 4 (security) is mandatory at every depth ≥ 4. Partial runs are not supported within a tier — see critical-rules.md Rule 1.

## Checklist

Copy this checklist and track your progress:

- [ ] All 6 phases completed (no skipped phases)
- [ ] PR description claims verified against actual code
- [ ] MUST-FIX issues resolved before push

## Resources

- [Code-analysis depth](references/code-analysis-depth.md):
  - Overview, Depth presets, Step inventory (0-23), Pre-flight scripts
  - Wiring details, Default behaviour
- [Protocol](references/protocol.md):
  - Maintenance Note, Prerequisites, Phase 1: Code Correctness Swarm
  - Phase 2: Claim Verification, Phase 3 + Phase 4 (Parallel)
  - Phase 3: Skeptical Review, Phase 4: Security Review
  - Phase 5: Merge Reports + Deduplicate, Phase 6: Present Results
- [Rationale](references/rationale.md):
  - The Incident, Four Complementary Perspectives
- [Review Complete](references/review-complete.md):
  - Verdict Summary Template, Field Descriptions
- [Critical Rules](references/critical-rules.md):
  - Rule 1: Never Skip Phases, Rule 2: Phase Order, Rule 3: UUID Filenames
  - Rule 4: Two-Stage Merge, Rule 5: Agent Prefix Assignment
  - Rule 6: UUID Collision Prevention, Rule 7: Same Line Not Same Bug
  - Rule 8: Re-Run After Fixes, Rule 9: Merge Script Safety
- [Model Selection](references/model-selection.md):
  - Code Analysis Models, Haiku Usage
- [Quick Reference](references/quick-reference.md):
  - Pipeline Triggers, Individual Agent Triggers
- [Output Format](references/output-format.md):
  - Report Files, Final Report Contents
- [Error Handling](references/error-handling.md):
  - Phase-Level Recovery, Merge Script Errors, Authentication Errors
- [Agent Recovery](references/agent-recovery.md):
  - Failure Modes & Detection, Step 1: Detect the Loss, Step 2: Verify the Loss
  - Step 3: Clean Up Partial Artifacts, Step 4: Re-Spawn the Task
  - Step 5: Record the Failure, Special Cases, Lost during context compaction
  - Agent wrote report with wrong pass number
  - Multiple correctness agents for the same domain, Agent Recovery Checklist
- [Lessons Learned](references/lessons-learned.md):
  - Lessons, Checklist
