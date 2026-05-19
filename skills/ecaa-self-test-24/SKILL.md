---
name: ecaa-self-test-24
description: >
  Trigger with "ecaa self test", "run efficacy gate". Use when verifying
  the 24-step bug-detection pipeline catches every seeded bug — before
  release or on a schedule. Runs the pytest gate plus 22 agent dispatches.
version: 3.4.3
author: Emasoft
license: MIT
tags: [ecaa-self-test, efficacy, quality-gate, pipeline-test]
effort: high
allowed-tools: "Read, Bash(uv:*), Bash(mkdir:*), Bash(date:*), Bash(git:*), Bash(ls:*), Bash(wc:*), Agent"
---

# Ecaa Self Test 24

## Overview

Self-test the 24-step bug-detection pipeline (TRDD-7e364ace). 36 plan rows:

1. **Script halves** (14: steps 0, 5-15, 16-gate, 19) — pytest detectors, ~0.5s, free.
2. **Agent halves** (22: steps 1-4, 17, 18, 20×6, 21×8, 22, 23) — sub-agent dispatches against pre-bundled fixtures, ~$0.50-$1.

`scripts/ecaa_aggregate.py` consumes per-dispatch evidence files plus the pytest log and writes the verdict JSON. NO markdown report.

## Prerequisites

- `uv` + pytest installed.
- Plugin loaded in this Claude Code session.
- Write access to `<main-repo-root>/reports/code-auditor/efficacy-audit/`.

## Instructions

1. Resolve `MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"`, `TS="$(date +%Y%m%d_%H%M%S%z)"`, `WS="/tmp/ecaa-$TS"`. `mkdir -p "$WS" "$MAIN_ROOT/reports/code-auditor/efficacy-audit"`.
2. **Script-half gate.** From `$MAIN_ROOT` run `uv run pytest tests/integration/test_pipeline_efficacy.py -v --tb=short > "$WS/pytest.log" 2>&1`. Aggregator parses this log; do NOT abort on non-zero exit.
3. **Agent-half dispatch.** Read the plan's `parallel_dispatch_order` array (21 keys). Dispatch ALL 21 in a SINGLE assistant message (one message with 21 `Agent` tool blocks) using the TERSE-JSON PROTOCOL from the ecaa-orchestrator agent. Splitting across messages serialises and adds 8-30s per split.
4. **Step 23 last.** Dispatch `caa-second-opinion-agent` (the `serial_after_batch` row) in a SEPARATE, LATER message — it consumes the upstream evidence files (`$WS/dispatch-*.json`).
5. **Completeness check.** `ls -1 $WS/dispatch-*.json | wc -l` must be 22. If lower, re-dispatch the missing keys in one more message.
6. **Aggregate.** Run `uv run python scripts/ecaa_aggregate.py "$WS" "$MAIN_ROOT/skills/ecaa-self-test-24/references/plan.json" "$WS/pytest.log" "$MAIN_ROOT/reports/code-auditor/efficacy-audit/${TS}-self-test.json"`. Writes a 36-row JSON and prints the verdict line.
7. **Emit verdict line.** Echo the aggregator's final stdout line verbatim. It matches one of:
   - `[PASS] ecaa-self-test-24 — 36/36 PASS. Result: <abs>`
   - `[PARTIAL] ecaa-self-test-24 — <N>/36 PASS. Result: <abs>`
   - `[FAIL] ecaa-self-test-24 — <N>/36 PASS. Result: <abs>`

## Output

JSON file at `<main-repo-root>/reports/code-auditor/efficacy-audit/<%Y%m%d_%H%M%S%z>-self-test.json` (36 entries: `step`, `half`, `name`, `verdict`, plus per-step diagnostic fields), plus a one-line verdict on stdout. NO markdown — the aggregator emits JSON only in ~100ms.

## Error Handling

- pytest missing → `[FAIL] ecaa-self-test-24 — pytest not installed`.
- Agent dispatch refused / evidence file missing → step marked FAIL `EVIDENCE_MISSING`, continue with other steps.
- Budget cap reached → remaining steps `SKIPPED_BUDGET`, verdict `[PARTIAL]`.
- Report dir unwritable → `[FAIL]` immediately.

## Examples

```bash
claude --prefill "Begin." --agent ecaa-orchestrator --dangerously-skip-permissions \
  "Execute the skill /ecaa-self-test-24 and exit."

# v2.1.139+ background mode: `--bg` dispatches non-blocking; monitor with
# `claude agents`, fetch verdict via `claude logs <id>`. Preserves model+effort.
claude --bg --name ecaa-self-test --prefill "Begin." --agent ecaa-orchestrator \
  --dangerously-skip-permissions "Execute the skill /ecaa-self-test-24 and exit."
```

## Resources

- [plan.json](references/plan.json) — canonical 36-row plan (cat, agent, fixture, expected_where). Aggregator's source of truth.
- [agent-test-plan.md](references/agent-test-plan.md) — human-readable test-plan
  - Conventions
  - Early-stage agent halves (steps 1-4)
  - Mid-stage and deep-dive agent halves (steps 17, 18, 22, 23)
  - Domain specialists (steps 20 and 21)
  - Parallelism plan
- [report-format.md](references/report-format.md) — JSON output schema
  - Filename rule
  - JSON top-level shape
  - Per-step entry schema
  - Sub-agent evidence file format
  - Verdict line (stdout contract)
