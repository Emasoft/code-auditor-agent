---
name: caa-scenario-generator-skill
description: >
  Trigger with "/caa-extended-audit", "generate scenarios", "discover entry
  points". Use when an extended audit needs end-to-end scenario walks beyond
  line review. Emits scenarios.json for the ultracode engine's scenario-walk lens.
version: 4.4.0
author: Emasoft
license: MIT
tags: [caa-scenario-generator, scenario-discovery, type-detection, extended-audit]
effort: low
allowed-tools: "Read, Write, Glob, Grep, Bash(uv:*), Bash(mkdir:*), Bash(rm:*), Bash(cp:*)"
---

# Scenario Generator

## Overview

Three-stage deterministic discovery: **detect → discover → emit**. Stage 1 classifies
the codebase into one or more of ~70 software types. Stage 2 dispatches to a per-type
discoverer that finds entry points (HTTP routes, CLI commands, ISR vectors, syscall
handlers, FPGA top-level ports, etc.). Stage 3 expands each entry point across the
applicable scenario families and emits a universal `scenarios.json`. No LLM at any
step — two runs on the same codebase produce byte-identical output. See
TRDD-6857f67f §3.1 for the full design.

## Prerequisites

- `${CLAUDE_PLUGIN_ROOT}` set; `scripts/scenario_generator/` shipped with this plugin.
- `python3` ≥ 3.12 available via `uv`.
- Target codebase path passed in via the orchestrator.

## Instructions

1. **Detect**: run `uv run --no-project python -m scripts.scenario_generator.detect_software_type <codebase_root>`. Surface the JSON to confirm what was detected.
2. **Emit scenarios**: run `uv run --no-project python -m scripts.scenario_generator.emit_scenarios_json <codebase_root> <main-repo>/reports/caa-scenario-generator/`. Output: timestamped `scenarios.json` + `detected-types.json`.
3. **Emit human-readable index**: run `uv run --no-project python -m scripts.scenario_generator.emit_scenarios_md <scenarios.json>` and tee to `<main-repo>/reports/caa-scenario-generator/<ts>-scenarios.md`.
4. **Return the file paths to the orchestrator.** The walker swarm picks up the JSON.

## Output

Two timestamped files under `<main-repo>/reports/caa-scenario-generator/`:
- `<ts>-scenarios.json` — universal schema (§3.1.d), consumed by the engine's `scenario-walk` lens (`scripts/workflows/lenses/scenario-walk.lens.md`).
- `<ts>-scenarios.md` — human-readable index grouped by type × family.

Plus `<ts>-detected-types.json` recording which types matched and why. Details:

- [Output schema](references/02-scenario-schema.md):
  - Top-level shape
  - EntryPointKind enum
  - ActorRole enum
  - Examples per kind
  - Walker contract

## Error Handling

If no software type matches: scenarios.json contains `unknown_software` with the
fallback discoverer's output. Walker still runs and reports the type-mismatch.
Details:

- [Type detection registry](references/01-software-type-detection.md):
  - Overview
  - Detection algorithm
  - The registry by category
  - Conflict resolution
- [Discoverers catalog](references/03-discoverers.md):
  - Discoverer contract
  - Dispatch
  - Phase 1 discoverers
  - Adding a new discoverer
  - Discoverer outputs by kind
  - Performance budget
- [Scenario families](references/04-scenario-families.md):
  - Overview
  - Family applies-to map
  - Per-family failure modes
  - Adding a family
  - Why these families and not others

## Checklist

Copy this checklist and track your progress:

- [ ] Detection ran and returned ≥ 1 type (or `unknown_software`)
- [ ] scenarios.json + detected-types.json written under reports/caa-scenario-generator/
- [ ] Same command run twice produces byte-identical output
- [ ] Returned file paths to orchestrator (NEVER inline the report bodies)

## Resources

- `scripts/scenario_generator/detect_software_type.py` — §3.1.c registry
- `scripts/scenario_generator/scenario_families.py` — §3.1.e registry
- `scripts/scenario_generator/emit_scenarios_json.py` — composition entry point
- `scripts/scenario_generator/discoverers/` — per-type discoverers
- `tests/fixtures/scenario_generator/` — golden fixtures (11 in v0.1.0)
- `tests/test_scenario_generator.py` — byte-identical regression test

## Examples

```
User: /caa-audit-codebase --extended
Orchestrator: invokes the caa-scenario-generator-skill with args="/path/to/codebase"
The skill emits scenarios.json + detected-types.json → returns paths
Orchestrator: runs /caa-scan --extended → the engine's scenario-walk lens consumes scenarios.json
```
