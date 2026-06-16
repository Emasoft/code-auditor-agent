---
name: ecaa-self-test-24
description: >
  Trigger with "ecaa self test", "run efficacy gate". Use when verifying the ultracode engine
  catches every seeded bug in the bundled fixtures — before release or on a schedule. Runs the
  pytest gate plus one engine pass.
version: 4.0.0
author: Emasoft
license: MIT
tags: [ecaa-self-test, efficacy, quality-gate, ultracode]
effort: high
---

# Ecaa Self Test 24 (ultracode engine efficacy gate)

## Overview

Efficacy self-test for the migrated **ultracode engine** (`scripts/workflows/caa-engine.js`). Two halves:

1. **Script half (pytest, ~0.5s):** the deterministic-detector tests (`tests/integration/test_pipeline_efficacy.py`) — encoding, lint, structure, etc.
2. **Engine half:** run `caa-engine` once over the bundled seeded-bug fixtures
   (`references/fixtures/`, one per former specialist domain) with ALL domain lenses active, and
   assert the consolidated report flags a finding in EVERY fixture (each fixture contains ≥1 seeded
   defect). Replaces the old per-agent dispatches — combined + domain lenses embody every former agent's logic.

## Prerequisites

- `uv` + pytest installed; session effort `max`/`xhigh` (the engine is opus-only).
- Write access to `<main-repo-root>/reports/code-auditor-agent/efficacy-audit/`.

## Instructions

1. `MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"`, `TS="$(date +%Y%m%d_%H%M%S%z)"`.
2. **Script half:** from `$MAIN_ROOT` run `uv run pytest tests/integration/test_pipeline_efficacy.py -v --tb=short > "/tmp/ecaa-$TS-pytest.log" 2>&1` (do NOT abort on non-zero — record it).
3. **Engine half (needs ultracode):** with NO `Workflow` tool, SKIP this half — record `SKIPPED (ultracode
   required)` in the verdict and assert only on the script half (the simple-scan fallback can't substitute;
   this gate tests the ENGINE). Else resolve the fixture files (`git -C "$MAIN_ROOT" ls-files "skills/ecaa-self-test-24/references/fixtures"` → absolute paths) and invoke the engine with EVERY domain lens active:
   `Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js", args: {root: "$MAIN_ROOT", files: [<fixture abs paths>], mode: "scan", reportType: "audit", reportSuffix: "ecaa-self-test", runId: "ecaa-$TS", domainLenses: ["docker","solidity","ios-native","graphql","elixir","frontend","monorepo","i18n","l10n","jwt","prompt-injection","logging","mcp-server","api-design","type-design","assumption","function-contract","pre-mortem","architecture-consistency"], lensDir: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/lenses", conc: 6}})`.
   No `lensSet` (default `combined`; the engine fail-fasts on unknown values).
4. **Assert RECALL:** in `finalReport`, every seeded-bug fixture (all EXCEPT those under
   `references/fixtures/clean-suspicious/`) must appear with ≥1 confirmed finding; zero on a seeded
   fixture is a MISS.
5. **Assert PRECISION:** each fixture under `references/fixtures/clean-suspicious/` must have ZERO
   confirmed CRITICAL/MAJOR (a flagged-then-REFUTED/DOWNGRADED finding passes — see the "Refuted /
   downgraded" section). A confirmed CRITICAL/MAJOR on a clean fixture is a FALSE-POSITIVE failure.
6. **Verdict:** emit one line — `[PASS] ecaa-self-test-24 — recall <N>/<N> · precision <C>/<C> · pytest <P>/<P>` / `[PARTIAL] …` / `[FAIL] …` — and write the report + a verdict JSON to `<main-repo-root>/reports/code-auditor-agent/efficacy-audit/<TS>-self-test.{md,json}`. Report BOTH recall and precision.

## Output

The consolidated report + verdict line/JSON under `reports/code-auditor-agent/efficacy-audit/`. PASS = every seeded fixture flagged + pytest detectors passed.

## Error Handling

- pytest missing → `[FAIL] ecaa-self-test-24 — pytest not installed`.
- Engine returns problems (non-verified fixtures) → mark those fixtures MISS, verdict `[PARTIAL]`.
- Report dir unwritable → `[FAIL]` immediately. The engine itself is robust by construction (`.catch` + rate-limit re-queue).

## Examples

```
"run ecaa self test"     → pytest gate + one engine pass over references/fixtures/ → verdict
```

## Resources

- `scripts/workflows/caa-engine.js` — the engine under test.
- `references/fixtures/` — seeded-bug fixtures (one per former specialist domain).
- `tests/integration/test_pipeline_efficacy.py` — the script-detector half.
