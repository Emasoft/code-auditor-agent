---
name: ecaa-self-test-24
description: >
  Trigger with "ecaa self test", "run efficacy gate", "execute the skill
  ecaa-self-test-24". Use when verifying that the 24-step bug-detection
  pipeline (TRDD-7e364ace) actually catches every bug pattern it claims
  to — before a release, on a schedule, or as a manual gate. Runs the
  pytest script-half gate plus dispatches every agent-half against a
  seeded fixture and writes a pass/fail report.
version: 3.4.2
author: Emasoft
license: MIT
tags: [ecaa-self-test, efficacy, quality-gate, pipeline-test]
effort: high
allowed-tools: "Read, Write, Glob, Grep, Bash(uv:*), Bash(mkdir:*), Bash(date:*), Bash(rm:*), Bash(ls:*), Bash(cat:*), Bash(cp:*), Bash(git:*), Agent"
---

# Ecaa Self Test 24

## Overview

Self-test the 24-step bug-detection pipeline (TRDD-7e364ace). Two halves:

1. **Script halves** (steps 0, 5-15, 16-gate, 19) — 14 detectors, ~0.5s, free.
2. **Agent halves** (steps 1-4, 17, 18, 20, 21, 22, 23) — 10 LLM agents dispatched against seeded fixtures, ~$1 with Sonnet.

## Prerequisites

- `uv` + pytest, plugin loaded, write access to `<main-repo-root>/reports/code-auditor/efficacy-audit/`.

## Instructions

1. Resolve `MAIN_ROOT=$(git worktree list | head -n1 | awk '{print $1}')`, `TS=$(date +%Y%m%d_%H%M%S%z)`, `WS=/tmp/ecaa-$TS`. Create `$WS` and the report dir.
2. **Script-half gate.** From `$MAIN_ROOT` run `uv run pytest tests/integration/test_pipeline_efficacy.py -v --tb=short > "$WS/pytest.log" 2>&1`. The aggregator parses this log; do NOT abort on non-zero exit, just continue.
3. **Agent-half dispatch.** For every row in the [plan](references/plan.json), seed the fixture in `$WS/agent-<step>/` and dispatch via the `Agent` tool using the TERSE-JSON PROTOCOL (see orchestrator agent). ALL 21 parallel-safe dispatches MUST go in a single assistant message (one tool call message with 21 `Agent` blocks). Step 23 dispatches LAST in a separate message.
4. **Aggregate.** Run `uv run python scripts/ecaa_aggregate.py "$WS" "$MAIN_ROOT/skills/ecaa-self-test-24/references/plan.json" "$WS/pytest.log" "$MAIN_ROOT/reports/code-auditor/efficacy-audit/${TS}-self-test.json"`. The aggregator writes a 24-entry JSON (no markdown) and prints the verdict line.
5. **Emit verdict line.** Echo the aggregator's final stdout line verbatim. It matches one of:
   - `[PASS] ecaa-self-test-24 — <N>/<M> PASS. Result: <abs>`
   - `[PARTIAL] ecaa-self-test-24 — <N>/<M> PASS. Result: <abs>`
   - `[FAIL] ecaa-self-test-24 — <N>/<M> PASS. Result: <abs>`

## Output

JSON file at `<main-repo-root>/reports/code-auditor/efficacy-audit/<%Y%m%d_%H%M%S%z>-self-test.json` (24 entries: step, half, name, verdict, found, missing) plus a one-line verdict on stdout. NO markdown — the aggregator builds the JSON in ~100 ms.

## Error Handling

- pytest missing → `[FAIL] ecaa-self-test-24 — pytest not installed`.
- Agent dispatch refused / times out → mark step FAIL, continue.
- Budget cap → remaining steps `SKIPPED_BUDGET`, verdict `[PARTIAL]`.
- Report dir unwritable → `[FAIL]` immediately, do not swallow.

## Examples

```bash
claude --prefill "Begin." --agent ecaa-orchestrator --dangerously-skip-permissions \
  "Execute the skill /ecaa-self-test-24 and exit."
```

## Checklist

Copy this checklist and track your progress:

- [ ] `MAIN_ROOT` / `TS` / `WS` resolved; dirs created
- [ ] pytest gate ran; exit code captured
- [ ] Every row in the agent-test-plan reference dispatched (step 23 last)
- [ ] Each agent return line parsed, verdict recorded
- [ ] Report written under `reports/code-auditor/efficacy-audit/`
- [ ] Stdout ends with one of the three contract verdict lines
- [ ] No source-tree mutation (only `$WS` + the report file)

## Resources

- [agent-test-plan](references/agent-test-plan.md) — fixture seeds + verification table for every agent-half step
  - Conventions
  - Step 1 — caa-code-correctness-agent
  - Step 2 — caa-claim-verification-agent
  - Step 3 — caa-skeptical-reviewer-agent
  - Step 4 — caa-security-review-agent
  - Step 17 — caa-architecture-consistency-agent
  - Step 18 — caa-pre-mortem-agent
  - Step 20 — domain specialists, high-frequency
  - Step 21 — domain specialists, lower-frequency
  - Step 22 — caa-function-deep-dive-agent
  - Step 23 — caa-second-opinion-agent
  - Parallelism plan
- [report-format](references/report-format.md) — markdown template the orchestrator must produce
  - Filename rule
  - Section structure
  - Summary table columns
  - Sub-agent evidence file format
  - Cost & timing line
  - Verdict line (stdout contract)
