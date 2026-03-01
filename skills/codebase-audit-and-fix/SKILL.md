---
name: codebase-audit-and-fix
description: "Full codebase audit pipeline: discover, verify, gap-fill, consolidate, TODO, fix loop. Use when auditing an entire codebase for compliance violations, architectural issues, or decoupling standards. Trigger with /audit-codebase or 'audit the codebase'."
version: 1.0.0
author: Emasoft
license: MIT
tags: [codebase-audit, compliance, todo-generation, iterative-fix]
---

# Codebase Audit And Fix

9-phase pipeline auditing every file in scope against a reference standard. Uses grep triage to skip clean files, 3-4 file batches to prevent hallucination, multi-wave verification to eliminate false positives, and iterative gap-fill for 100% coverage.

## Parameters

| Param | Req | Default | Description |
|-------|-----|---------|-------------|
| `SCOPE_PATH` | Y | -- | Directory to audit |
| `REFERENCE_STANDARD` | Y | -- | Path to compliance doc |
| `VIOLATION_TYPES` | N | `HARDCODED_API,HARDCODED_GOVERNANCE,DIRECT_DEPENDENCY,HARDCODED_PATH,MISSING_ABSTRACTION` | Violation labels |
| `AUDIT_PATTERNS` | N | 14 defaults | Grep triage patterns |
| `REPORT_DIR` | N | `docs_dev/` | Output directory |
| `FIX_ENABLED` | N | `false` | Run fix phases 6-7 |
| `TODO_ONLY` | N | `false` | Stop after phase 5 |
| `MAX_FIX_PASSES` | N | `5` | Max fix-verify loops |

Init: `RUN_ID` = 8 lowercase hex chars (e.g. `uuid4().hex[:8]`), `PASS_NUMBER=1`.

## Pipeline

| Phase | Action | Agent | Concurrency |
|-------|--------|-------|-------------|
| 0 | Prep: `find` inventory, domain classify, grep triage, batch (3-4 files), write manifest | orchestrator | -- |
| 1 | Discovery: audit each batch | `amcaa-domain-auditor-agent` | 20 |
| 2 | Verification: verify each Phase 1 report + missed-file detection | `amcaa-verification-agent` | 10 |
| 3 | Gap-fill: audit missed files, re-verify, loop max 3x | `amcaa-domain-auditor-agent` + verifier | 20 |
| 4 | Consolidation: merge per-domain (max 5 inputs/agent, hierarchical if more) | `amcaa-consolidation-agent` | 5 |
| 5 | TODO generation: actionable TODO-{scope}-changes.md per domain | `amcaa-todo-generator-agent` | 5 |
| 6 | Fix (if FIX_ENABLED): implement TODOs with checkpoints | `amcaa-fix-agent` | 20 |
| 7 | Fix verify (if FIX_ENABLED): verify fixes, loop to P6 if FAILs | `amcaa-fix-verifier-agent` | 20 |
| 8 | Final report: compile stats, link artifacts | orchestrator | -- |

If `TODO_ONLY=true`, stop after phase 5. If `FIX_ENABLED=true`, loop P6-P7 until all PASS or `PASS_NUMBER > MAX_FIX_PASSES`.

## Report Naming

All files use `{REPORT_DIR}/amcaa-{type}-P{N}-R{RUN_ID}-{UUID}.md`. Each agent generates its own UUID.

| Type | Pattern |
|------|---------|
| Audit | `amcaa-audit-P{N}-R{RUN_ID}-{UUID}.md` |
| Verify | `amcaa-verify-P{N}-R{RUN_ID}-{UUID}.md` |
| Gap-fill | `amcaa-gapfill-P{N}-R{RUN_ID}-{UUID}.md` |
| Consolidated | `amcaa-consolidated-{domain}.md` |
| TODO | `TODO-{scope}-changes.md` |
| Fix done | `amcaa-fixes-done-P{N}-{domain}.md` |
| Fix checkpoint | `amcaa-checkpoint-P{N}-{domain}.json` |
| Fix verify | `amcaa-fixverify-P{N}-R{RUN_ID}-{UUID}.md` |
| Manifest | `amcaa-manifest-R{RUN_ID}.json` |
| Final | `amcaa-audit-FINAL-{timestamp}.md` |

## Finding IDs

Format: `{PREFIX}-P{PASS}-{AGENT_PREFIX}-{SEQ}` where PREFIX=DA/VE/GF/FV, AGENT_PREFIX=A0..AF..A10.., SEQ=001+. Consolidation uses `CA-{DOMAIN}-{SEQ}` (no PASS/AGENT_PREFIX since it operates per-domain).

## Spawning Patterns

All agents receive: `REFERENCE_STANDARD, REPORT_PATH`. Phase 1-3 agents also receive: `SCOPE_PATH, VIOLATION_TYPES, PASS, RUN_ID, AGENT_PREFIX, FINDING_ID_PREFIX`. Additional per-phase params:

**P1 Discovery**: `FILES` (max 4), `TRIAGE_STATUS` (LIKELY_VIOLATION/LIKELY_CLEAN). Report to `amcaa-audit-*`.
**P2 Verify**: `AUDIT_REPORT` path, `DOMAIN_FILES` list. 3 checks: violation claims, clean claims, missed files. Report to `amcaa-verify-*`.
**P3 Gap-fill**: Same as P1 but `TRIAGE_STATUS=MISSED`, prefix=GF, report to `amcaa-gapfill-*`.
**P4 Consolidate**: `INPUT_REPORTS` (max 5 paths), `DOMAIN_NAME`, `OUTPUT_PATH`. Merge, dedup, classify as VIOLATION/RECORD_KEEPING/FALSE_POSITIVE.
**P5 TODO**: `CONSOLIDATED_REPORT`, `SCOPE_NAME`, `TODO_PREFIX`, `OUTPUT_PATH`. Each TODO must have file:line:evidence triple.
**P6 Fix**: `TODO_FILE`, `ASSIGNED_TODOS`, `FILES`, `CHECKPOINT_PATH`, `REPORT_PATH`. Checkpoint after each fix. Harmonization: preserve existing + add new.
**P7 Fix-verify**: `FIXED_FILES`, `ORIGINAL_TODOS`, `FIX_REPORT`, `REPORT_PATH`. Verdict: PASS/FAIL/REGRESSION.

All agents end with: `REPORTING RULES: Write details to report file. Return ONLY: "[DONE/FAILED] {task} - {summary}. Report: {path}". Max 2 lines.`

## Loop Termination

- Gap-fill: stops when 0 missed files or 3 iterations reached
- Fix loop: stops when all verifiers PASS or `PASS_NUMBER > MAX_FIX_PASSES`
- Agent retry: max 3 retries per agent; after 3, escalate

## Recovery

If agent fails: check if output file exists and is complete. If yes, use it. If not, re-spawn with new UUID, same prefix. Read manifest to recover from context compaction.
