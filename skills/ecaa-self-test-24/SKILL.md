---
name: ecaa-self-test-24
description: >
  Trigger with "ecaa self test", "run efficacy gate", "execute the skill
  ecaa-self-test-24". Use when verifying that the 24-step bug-detection
  pipeline (TRDD-7e364ace) actually catches every bug pattern it claims
  to — before a release, on a schedule, or as a manual gate. Runs the
  pytest script-half gate plus dispatches every agent-half (22 sub-agent
  invocations across 36 plan rows) against pre-bundled fixtures, then
  runs the Python aggregator and emits one verdict line.
version: 3.4.2
author: Emasoft
license: MIT
tags: [ecaa-self-test, efficacy, quality-gate, pipeline-test]
effort: high
allowed-tools: "Read, Write, Bash(uv:*), Bash(mkdir:*), Bash(date:*), Bash(git:*), Bash(echo:*), Agent, Skill"
---

# Ecaa Self Test 24

## Overview

Self-test the 24-step bug-detection pipeline (TRDD-7e364ace). 36 plan rows in two halves:

1. **Script halves** (14 rows: steps 0, 5-15, 16-gate, 19) — detectors run via pytest, ~0.5s, free.
2. **Agent halves** (22 rows: steps 1-4, 17, 18, 20×6 specialists, 21×8 specialists, 22, 23) — sub-agent dispatches against pre-bundled fixtures, ~$0.50-$1 with Sonnet/Opus.

The aggregator (`scripts/ecaa_aggregate.py`) consumes per-dispatch evidence files (`dispatch-*.json`) plus the pytest log and writes the verdict JSON. NO markdown report.

## Prerequisites

- `uv` + pytest installed.
- Plugin loaded in this Claude Code session.
- Write access to `<main-repo-root>/reports/code-auditor/efficacy-audit/`.

## Instructions

1. Resolve `MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"`, `TS="$(date +%Y%m%d_%H%M%S%z)"`, `WS="/tmp/ecaa-$TS"`. `mkdir -p "$WS" "$MAIN_ROOT/reports/code-auditor/efficacy-audit"`.
2. **Script-half gate.** From `$MAIN_ROOT` run `uv run pytest tests/integration/test_pipeline_efficacy.py -v --tb=short > "$WS/pytest.log" 2>&1`. Aggregator parses this log; do NOT abort on non-zero exit.
3. **Agent-half dispatch.** For every `half=="agent"` row in [plan.json](references/plan.json), pass the absolute fixture path to the named sub-agent via the `Agent` tool using the TERSE-JSON PROTOCOL (see ecaa-orchestrator agent). ALL 21 parallel-safe dispatches MUST go in a SINGLE assistant message (one message with 21 `Agent` tool blocks). Step 23 (`caa-second-opinion-agent`) dispatches LAST in a separate message because it consumes the upstream evidence files.
4. **Aggregate.** Run `uv run python scripts/ecaa_aggregate.py "$WS" "$MAIN_ROOT/skills/ecaa-self-test-24/references/plan.json" "$WS/pytest.log" "$MAIN_ROOT/reports/code-auditor/efficacy-audit/${TS}-self-test.json"`. The aggregator writes a 36-row JSON (one entry per plan key) and prints the verdict line as its final stdout line.
5. **Emit verdict line.** Echo the aggregator's final stdout line verbatim. It matches one of:
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
```

## Checklist

Copy this checklist and track your progress:

- [ ] `MAIN_ROOT` / `TS` / `WS` resolved; dirs created
- [ ] pytest gate ran; `$WS/pytest.log` captured
- [ ] All 21 parallel-safe agent dispatches in one assistant message
- [ ] Step 23 dispatched in a separate, later message
- [ ] `scripts/ecaa_aggregate.py` ran; verdict line captured
- [ ] JSON report written under `reports/code-auditor/efficacy-audit/`
- [ ] Stdout ends with one of the three contract verdict lines
- [ ] No source-tree mutation (only `$WS` + the report file)

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
