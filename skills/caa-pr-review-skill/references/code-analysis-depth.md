# Code-analysis depth parameter

## Table of Contents

- [Overview](#overview)
- [Depth presets](#depth-presets)
- [Step inventory (0-23)](#step-inventory-0-23)
- [Pre-flight scripts](#pre-flight-scripts)
- [Wiring details](#wiring-details)
- [Default behaviour](#default-behaviour)

## Overview

`/caa-pr-review` accepts `--code-analysis-depth N` (alias `--depth N`,
range `1..23`) and `--preset quick|standard|deep|thorough|full`. The
parameter controls how many of the 24 pipeline steps (Step 0 plus
steps 1..23) are executed. Step 0 (domain detection gate) is always
on — it costs no LLM tokens and downstream specialist agents depend
on its `specialist_firing` block.

Default depth = `4` (current behavior). Users opting into deeper
scans accept the additional token cost.

## Depth presets

| Preset | Depth | Steps run | Adds |
|---|---|---|---|
| `quick` | 4 | 1-4 | Current behavior. PR sanity check. |
| `standard` | 10 | 1-10 | Linters, cross-layer (+ripple+nil), multi-tenant, silent-failure, concurrency, complexity |
| `deep` | 15 | 1-15 | AWC extensions, comment quality, test quality, performance, database |
| `thorough` | 19 | 1-19 | Type-design, architecture, pre-mortem, operational |
| `full` | 23 | 1-23 | Every step. No bug escapes. Domain specialists, function deep-dive, Opus second-opinion |

## Step inventory (0-23)

| # | Step | Owner | Shipped? |
|---|---|---|---|
| 0 | Domain detection gate | `scripts/prereview/detect_languages_and_domains.py` | ✅ |
| 1 | Code correctness swarm | `caa-code-correctness-agent` | ✅ |
| 2 | Claim verification + linked issue | `caa-claim-verification-agent` | ✅ |
| 3 | Skeptical holistic review | `caa-skeptical-reviewer-agent` | ✅ |
| 4 | Security review | `caa-security-review-agent` | ✅ |
| 5 | Linter & scanner pre-flight | `scripts/prereview/run_linters.py` | ✅ |
| 6 | Cross-layer drift detector | `scripts/prereview/cross_layer.py` + `caa-cross-layer-auditor-agent` | ✅ (script) |
| 7 | Multi-tenant data isolation | `scripts/prereview/multi_tenant.py` + agent residue | ✅ (script) |
| 8 | Silent-failure hunter | `scripts/prereview/silent_failure.py` + agent residue | ✅ (script) |
| 9 | Concurrency hazards | `scripts/prereview/concurrency.py` + agent residue | ✅ (script) |
| 10 | Complexity & dead-code | `scripts/prereview/complexity.py` | ✅ |
| 11 | AWC extensions | Extends `caa-code-correctness-agent` | ⬜ |
| 12 | Comment & docstring quality | `scripts/prereview/docstring_diff.py` + new agent | ⬜ |
| 13 | Test quality | `scripts/prereview/test_quality.py` + agent | ⬜ |
| 14 | Performance / memory / energy | `scripts/prereview/performance.py` + new agent | ⬜ |
| 15 | Database / query / migration | `scripts/prereview/database.py` + new agent | ⬜ |
| 16 | Type-design analyzer | `caa-type-design-analyzer-agent` (new) | ⬜ |
| 17 | Architecture pattern consistency | `caa-architecture-consistency-agent` (new) | ⬜ |
| 18 | Pre-mortem / risk analyzer | `caa-pre-mortem-agent` (new) | ⬜ |
| 19 | Operational / deployment | `scripts/prereview/operational.py` + agent residue | ⬜ |
| 20 | Domain specialists (HF) | 6 new specialist agents (gated on Step 0 flags) | ⬜ |
| 21 | Domain specialists (LF) | 8 new specialist agents (gated on Step 0 flags) | ⬜ |
| 22 | Function-level deep-dive | `caa-function-deep-dive-agent` (new) | ⬜ |
| 23 | Opus second-opinion loop | `caa-second-opinion-agent` (new, Opus only) | ⬜ |

## Pre-flight scripts

For depth `>= 5`, the skill runs the pre-flight scripts in parallel
**before** the LLM-driven phases. Each script:

- Is fully deterministic (two runs → byte-identical JSON, modulo timestamp).
- Reads files from disk; never holds the whole repo in memory.
- Writes its findings to `<main-repo>/reports/caa-prereview/<ts>-<name>.json`.
- Returns the file path on stdout; the skill never inlines its body.

When invoked, the skill stores all per-step JSON paths in a shared
manifest under `<main-repo>/reports/caa-prereview/<ts>-manifest.json`,
which the downstream agents read instead of re-grepping the codebase.

## Wiring details

The skill resolves depth as follows:

1. Parse `--code-analysis-depth N` (or map the preset string → integer).
2. Validate `1 <= N <= 23` (clamp on invalid input, warn user).
3. Always run Step 0 (gate). Surface `domains_detected.json` path.
4. Run steps `1..N` in declared order, with parallelism inside tiers
   that allow it (the script-only tier II/III/IV runs all scripts in
   parallel via `concurrent.futures`).
5. Steps `N+1..23` are not invoked. They appear in the verdict report
   as "skipped (depth limit)" so reviewers can see what wasn't checked.
6. If a step references an agent or script that is not yet shipped,
   the verdict surfaces "TODO: not yet implemented".

## Default behaviour

Without an explicit depth/preset:

- `--code-analysis-depth 4` is used.
- Steps 1-4 run (current six-phase behavior).
- Token cost = same as today.
- Step 0 (gate) still runs, but it's pure-Python and adds no LLM cost.

This preserves backwards compatibility — existing `review the PR`
invocations behave identically to today.
