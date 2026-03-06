---
name: caa-codebase-audit-and-fix-skill
description: "Trigger with /audit-codebase, 'audit the codebase', 'compliance audit', 'codebase audit'. Use when auditing a codebase for compliance violations, generating TODOs, or applying automated fixes."
version: 3.1.9
author: Emasoft
license: MIT
tags: [codebase-audit, compliance, todo-generation, iterative-fix]
---

# Codebase Audit And Fix

## Overview

10-phase pipeline that audits every file in a codebase against a reference standard. Uses grep triage to skip clean files, 3-4 file batches to prevent hallucination, multi-wave verification to eliminate false positives, and iterative gap-fill for 100% coverage. When FIX_ENABLED, applies automated fixes with checkpoint-based recovery and multi-pass verification until all violations are resolved.

## Prerequisites

### Required Agents

| Agent | Phase | Purpose |
|-------|-------|---------|
| `caa-domain-auditor-agent` | 1, 3 | Discovery and gap-fill auditing of file batches |
| `caa-verification-agent` | 2, 3 | Cross-check audit reports and detect missed files |
| `caa-consolidation-agent` | 4 | Merge per-domain reports, dedup, classify findings |
| `caa-security-review-agent` | 4b | Security scan: vulnerabilities, secrets, dependency CVEs |
| `caa-todo-generator-agent` | 5 | Generate actionable TODO files from consolidated reports |
| `caa-fix-agent` | 6 | Implement TODO fixes with checkpoint recovery |
| `caa-fix-verifier-agent` | 7 | Verify fixes, detect regressions |

### Required Scripts

| Script | Phase | Purpose |
|--------|-------|---------|
| `${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-audit-reports.py` | 8 | Compile final merged report with stats |
| `${CLAUDE_PLUGIN_ROOT}/scripts/caa-generate-todos.py` | 5 | Structured TODO generation helper |

### Environment

- Python 3.12+ with `uv`
- Git repository (for diff-based change tracking)
- Sufficient disk space for report artifacts in `REPORT_DIR`
- `${CLAUDE_PLUGIN_ROOT}` must be set by the Claude Code plugin loader. Verify it is non-empty before running any scripts.
- If `USE_WORKTREES=true`: Git working tree must be clean (no uncommitted changes). Sufficient disk space for N worktree copies.

## Instructions

Follow these steps to run the audit pipeline:

1. Set `SCOPE_PATH` to the directory to audit and `REFERENCE_STANDARD` to the compliance doc path. Verify `REFERENCE_STANDARD` file exists and is non-empty before proceeding. If not, STOP with error: 'REFERENCE_STANDARD not found or empty at {path}.'
2. Generate a `RUN_ID` (8 lowercase hex chars: `uuid4().hex[:8]`) and set `PASS_NUMBER=1`
3. Run Phase 0: inventory all files, classify by domain, triage with grep, batch into groups of 3-4. If the file inventory returns zero files, STOP immediately with error: 'No files found in SCOPE_PATH ({path}). Verify the path exists and contains auditable files.' Do not proceed to Phase 1 with an empty file list.
4. Run Phase 1: spawn `caa-domain-auditor-agent` for each batch (concurrency 20)
5. Run Phase 2: spawn `caa-verification-agent` to cross-check all Phase 1 reports (concurrency 10)
6. Run Phase 3: gap-fill missed files, re-verify, loop max 3 times until 100% coverage
7. Run Phase 4: consolidate per-domain reports (max 5 inputs per agent, hierarchical if more)
8. Run Phase 4b: spawn `caa-security-review-agent` (MANDATORY, never skip) against all audited files. The security agent runs automated tools (trufflehog, bandit, osv-scanner, etc.) and performs manual vulnerability analysis. Its findings are appended to the consolidated reports before TODO generation.
9. Run Phase 5: generate `TODO-{scope}-changes.md` per domain with file:line:evidence triples
10. If `FIX_ENABLED=true`: run Phase 6 (apply fixes) and Phase 7 (verify fixes), loop until all PASS or max passes
11. Run Phase 8: compile final merged report with stats and links to all artifacts

### Parameters

| Param | Req | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `SCOPE_PATH` | Y | path | -- | Directory to audit |
| `REFERENCE_STANDARD` | Y | path | -- | Path to compliance doc |
| `VIOLATION_TYPES` | N | comma-separated string | `HARDCODED_API,HARDCODED_GOVERNANCE,DIRECT_DEPENDENCY,HARDCODED_PATH,MISSING_ABSTRACTION` | Violation labels |
| `AUDIT_PATTERNS` | N | list | auto-derived from VIOLATION_TYPES | Grep triage patterns (e.g. `localhost`, `http://`, `curl`, `fetch`, `hardcoded`, `direct.*import`) |
| `REPORT_DIR` | N | path | `docs_dev/` | Output directory |
| `FIX_ENABLED` | N | bool | `false` | Run fix phases 6-7 |
| `TODO_ONLY` | N | bool | `false` | Stop after phase 5 |
| `MAX_FIX_PASSES` | N | int | `5` | Max fix-verify loops |
| `USE_WORKTREES` | N | bool | false | Run agent swarms in isolated git worktrees |

Init: `RUN_ID` = 8 lowercase hex chars (e.g. `uuid4().hex[:8]`), `PASS_NUMBER=1`.

### Pipeline

| Phase | Action | Agent | Concurrency |
|-------|--------|-------|-------------|
| 0 | Prep: `find` inventory, domain classify, grep triage, batch (3-4 files), write manifest | orchestrator | -- |
| 1 | Discovery: audit each batch | `caa-domain-auditor-agent` | 20 |
| 2 | Verification: verify each Phase 1 report + missed-file detection | `caa-verification-agent` | 10 |
| 3 | Gap-fill: audit missed files, re-verify, loop max 3x | `caa-domain-auditor-agent` + verifier | 20 |
| 4 | Consolidation: merge per-domain (max 5 inputs/agent, hierarchical if more) | `caa-consolidation-agent` | 5 |
| 4b | Security scan: vulnerabilities, secrets, dependency CVEs (MANDATORY) | `caa-security-review-agent` | 1 |
| 5 | TODO generation: actionable TODO-{scope}-changes.md per domain | `caa-todo-generator-agent` | 5 |
| 6 | Fix (if FIX_ENABLED): implement TODOs with checkpoints | `caa-fix-agent` | 20 |
| 7 | Fix verify (if FIX_ENABLED): verify fixes, loop to P6 if FAILs | `caa-fix-verifier-agent` | 20 |
| 8 | Final report: compile stats, link artifacts | orchestrator | -- |

If `TODO_ONLY=true`, stop after phase 5. If `FIX_ENABLED=true`, loop P6-P7 until all PASS or `PASS_NUMBER > MAX_FIX_PASSES`.

### Report Naming

All files use `{REPORT_DIR}/caa-{type}-P{N}-R{RUN_ID}-{UUID}.md`. Each agent generates its own UUID.

| Type | Pattern |
|------|---------|
| Audit | `caa-audit-P{N}-R{RUN_ID}-{UUID}.md` |
| Verify | `caa-verify-P{N}-R{RUN_ID}-{UUID}.md` |
| Gap-fill | `caa-gapfill-P{N}-R{RUN_ID}-{UUID}.md` |
| Consolidated | `caa-consolidated-{domain}.md` |
| Security | `caa-security-P{N}-R{RUN_ID}-{UUID}.md` |
| TODO | `TODO-{scope}-changes.md` |
| Fix done | `caa-fixes-done-P{N}-{domain}.md` |
| Fix checkpoint | `caa-checkpoint-P{N}-{domain}.json` |
| Fix verify | `caa-fixverify-P{N}-R{RUN_ID}-{UUID}.md` |
| Manifest | `caa-manifest-R{RUN_ID}.json` |
| Final | `caa-audit-FINAL-{timestamp}.md` |

### Finding IDs

Format: `{PREFIX}-P{PASS}-{AGENT_PREFIX}-{SEQ}` where PREFIX=DA/VE/GF/FV, AGENT_PREFIX=A0..AF..A10.., SEQ=001+. Consolidation uses `CA-{DOMAIN}-{SEQ}` (no PASS/AGENT_PREFIX since it operates per-domain).

### Spawning Patterns

**Worktree mode:** When `USE_WORKTREES=true`, resolve `ABSOLUTE_REPORT_DIR = $(pwd)/{REPORT_DIR}` before spawning. Pass this absolute path as `REPORT_DIR` in every agent prompt and add `isolation: "worktree"` to every Task() call. For Phase 6 fix agents, after all complete, merge worktree branches back sequentially (see below).

All agents receive: `REFERENCE_STANDARD, REPORT_PATH`. Phase 1-3 agents also receive: `SCOPE_PATH, VIOLATION_TYPES, PASS, RUN_ID, AGENT_PREFIX, FINDING_ID_PREFIX`. Additional per-phase params:

**P1 Discovery**: `FILES` (max 4), `TRIAGE_STATUS` (LIKELY_VIOLATION/LIKELY_CLEAN). Report to `caa-audit-*`.
**P2 Verify**: `AUDIT_REPORT` path, `DOMAIN_FILES` list. 3 checks: violation claims, clean claims, missed files. Report to `caa-verify-*`.
**P3 Gap-fill**: Same as P1 but `TRIAGE_STATUS=MISSED`, prefix=GF, report to `caa-gapfill-*`.
**P4 Consolidate**: `INPUT_REPORTS` (max 5 paths), `DOMAIN_NAME`, `OUTPUT_PATH`. Merge, dedup, classify as VIOLATION/RECORD_KEEPING/FALSE_POSITIVE.
**P4b Security**: `DOMAIN=all-audited-files`, `FILES=ALL` (or list from manifest), `PASS=PASS_NUMBER`, `RUN_ID`, `FINDING_ID_PREFIX=SC-P{N}`, `REPORT_DIR`. Single instance. Runs automated security tools (trufflehog, bandit, osv-scanner) and manual vulnerability analysis. This phase is MANDATORY — never skip it. Append security findings to consolidated reports before TODO generation.
**P5 TODO**: `CONSOLIDATED_REPORT`, `SCOPE_NAME`, `TODO_PREFIX`, `OUTPUT_PATH`. Each TODO must have file:line:evidence triple.
**P6 Fix**: `TODO_FILE`, `ASSIGNED_TODOS`, `FILES`, `CHECKPOINT_PATH`, `REPORT_PATH`. Checkpoint after each fix. Harmonization: preserve existing + add new.
**P7 Fix-verify**: `FIXED_FILES`, `ORIGINAL_TODOS`, `FIX_REPORT`, `REPORT_PATH`. Verdict: PASS/FAIL/REGRESSION.

All agents end with: `REPORTING RULES: Write details to report file. Return ONLY: "[DONE/FAILED] {task} - {summary}. Report: {path}". Max 2 lines.`

### Fix Agent Worktree Merge-Back (USE_WORKTREES only)

When `USE_WORKTREES=true` and `FIX_ENABLED=true`, Phase 6 fix agents each work in isolated worktrees on separate branches. After ALL Phase 6 agents complete:

1. Merge each agent's branch back to the current branch sequentially (in domain assignment order)
2. If a merge conflict occurs, STOP and escalate to the user
3. After successful merge, remove the worktree: `git worktree remove {path}`
4. Run Phase 7 (fix verification) on the merged result

### Loop Termination

- Gap-fill: stops when 0 missed files or 3 iterations reached
- Fix loop: stops when all verifiers PASS or `PASS_NUMBER > MAX_FIX_PASSES`
- Agent retry: max 3 retries per agent; after 3, escalate
- Escalation: If gap-fill completes 3 iterations with <100% coverage, write a WARNING to the final report header listing uncovered files. If MAX_FIX_PASSES is reached with still-failing verifications, the final report MUST be marked 'INCOMPLETE - {N} unresolved issues after {MAX_FIX_PASSES} passes' and the user must be notified.

## Output

The pipeline produces the following artifacts in `REPORT_DIR`:

| Artifact | Description |
|----------|-------------|
| Per-batch audit reports | Individual `caa-audit-*` files from Phase 1 discovery |
| Verification reports | `caa-verify-*` files confirming or rejecting findings |
| Gap-fill reports | `caa-gapfill-*` files for previously missed files |
| Consolidated domain reports | `caa-consolidated-{domain}.md` with deduplicated, classified findings |
| Security review report | `caa-security-P{N}-R{RUN_ID}-{UUID}.md` with vulnerability findings and tool scan summary |
| TODO files | `TODO-{scope}-changes.md` with actionable items per domain (file:line:evidence) |
| Fix reports (if FIX_ENABLED) | `caa-fixes-done-*` with applied changes and checkpoints |
| Fix verification (if FIX_ENABLED) | `caa-fixverify-*` with PASS/FAIL/REGRESSION verdicts |
| Manifest | `caa-manifest-R{RUN_ID}.json` tracking all files, batches, and agent assignments |
| Final merged report | `caa-audit-FINAL-{timestamp}.md` with aggregate stats, violation counts, and links to all artifacts |

## Error Handling

- **Agent failure**: Check if the output file exists and is complete. If yes, use it. If not, re-spawn with a new UUID but the same agent prefix.
- **Context compaction**: Read the manifest (`caa-manifest-R{RUN_ID}.json`) to recover full pipeline state after context compaction.
- **Partial runs**: The manifest tracks per-file completion status. Resume from the last incomplete phase.
- **Checkpoint recovery (Phase 6)**: Each fix agent writes a checkpoint JSON after every fix. On failure, the replacement agent reads the checkpoint and continues from the last successful fix.
- **Escalation**: After 3 retries on the same agent task, escalate to the orchestrator for manual intervention.

## Examples

### Example 1: Audit-only (no fixes)

```bash
# Trigger via slash command:
/audit-codebase

# Orchestrator sets:
SCOPE_PATH=src/
REFERENCE_STANDARD=docs/compliance-standard.md
REPORT_DIR=docs_dev/
FIX_ENABLED=false
TODO_ONLY=false
```

This runs all 8 phases (skipping 6-7) and produces a final merged report with TODO files.

### Example 2: Audit with TODO generation only

```bash
/audit-codebase

# Orchestrator sets:
SCOPE_PATH=src/api/
REFERENCE_STANDARD=docs/api-decoupling-standard.md
TODO_ONLY=true
```

Stops after Phase 5. Produces consolidated reports and TODO files but does not apply fixes.

### Example 3: Full audit with automated fixes

```bash
/audit-codebase

# Orchestrator sets:
SCOPE_PATH=src/
REFERENCE_STANDARD=docs/compliance-standard.md
FIX_ENABLED=true
MAX_FIX_PASSES=3
```

Runs all 9 phases including the P6-P7 fix loop (up to 3 passes). Produces fix reports, verification results, and the final merged report.

## Resources

### Agents

- `caa-domain-auditor-agent` - File batch auditing (Phases 1, 3)
- `caa-verification-agent` - Report cross-checking (Phase 2, 3)
- `caa-consolidation-agent` - Per-domain report merging (Phase 4)
- `caa-todo-generator-agent` - TODO file generation (Phase 5)
- `caa-security-review-agent` - Security vulnerability scanning (Phase 4b)
- `caa-fix-agent` - Automated fix application (Phase 6)
- `caa-fix-verifier-agent` - Fix verification (Phase 7)

### Scripts

- `${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-audit-reports.py` - Final report compilation
- `${CLAUDE_PLUGIN_ROOT}/scripts/caa-generate-todos.py` - Structured TODO generation

### Related Commands

- `/audit-codebase` - Triggers this skill from the CLI

## Completion Checklist

Copy this checklist and track your progress:

- [ ] Scope path and reference standard identified
- [ ] Phase 1: Discovery swarm completed for all batches
- [ ] Phase 2: Verification swarm cross-checked all reports
- [ ] Phase 3: Gap-fill achieved 100% file coverage
- [ ] Phase 4: Per-domain consolidation completed
- [ ] Phase 4b: Security review agent spawned and completed (caa-security-P{N}-*.md)
- [ ] Phase 5: TODO files generated for each scope (including security findings)
- [ ] Phase 6: Fixes applied (if FIX_ENABLED)
- [ ] Phase 7: Fix verification passed (if FIX_ENABLED)
- [ ] Phase 8: Final merged report generated
