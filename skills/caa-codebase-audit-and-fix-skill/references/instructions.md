# Instructions

## Table of Contents
- [Phase Steps](#phase-steps)
- [Parameters](#parameters)
- [Pipeline](#pipeline)
- [Report Naming](#report-naming)
- [Finding IDs](#finding-ids)
- [Spawning Patterns](#spawning-patterns)
- [Fix Agent Worktree Merge-Back](#fix-agent-worktree-merge-back-use_worktrees-only)
- [Loop Termination](#loop-termination)

## Phase Steps

Follow these steps to run the audit pipeline:

1. Set `SCOPE_PATH` to the directory to audit and `REFERENCE_STANDARD` to the compliance doc path. Verify `REFERENCE_STANDARD` file exists and is non-empty before proceeding. If not, STOP with error: 'REFERENCE_STANDARD not found or empty at {path}.'
2. Generate a `RUN_ID` (8 lowercase hex chars: `uuid4().hex[:8]`) and set `PASS_NUMBER=1`
3. Run Phase 0: inventory all files, classify by domain, triage with grep, batch into groups of 3-4. If the file inventory returns zero files, STOP immediately with error: 'No files found in SCOPE_PATH ({path}). Verify the path exists and contains auditable files.' Do not proceed to Phase 1 with an empty file list. **Create the Fix Dispatch Ledger** at `{REPORT_DIR}/caa-fix-dispatch-P{PASS_NUMBER}-R{RUN_ID}.json` — record each domain's batch of files so the fix phase can map reports to source files (see Phase 6).

   **File type coverage**: The inventory MUST include ALL text files, not just source code:
   - Source code: `.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, `.rb`, `.sh`, `.bash`
   - Config files: `.yaml`, `.yml`, `.toml`, `.json`, `.xml`, `.ini`, `.cfg`
   - Prompt/definition files: `.md` files in `agents/`, `skills/`, `commands/` directories
   - CI/CD files: `.github/workflows/*.yml`, `Dockerfile`, `.dockerignore`
   - Metadata: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`

   Route config/metadata files to the code-correctness agent for syntax validation.
   Route prompt/definition `.md` files to the security-review agent for prompt injection scanning.
   Route CI/CD files to both code-correctness (syntax) and security-review (secrets/permissions).

4. Run Phase 1: spawn `caa-domain-auditor-agent` for each batch (concurrency 20)
5. Run Phase 2: spawn `caa-verification-agent` to cross-check all Phase 1 reports (concurrency 10)
6. Run Phase 3: gap-fill missed files, re-verify, loop max 3 times until 100% coverage
7. Run Phase 4: consolidate per-domain reports. **Consolidation externalizer option:** If `llm-externalizer` MCP is available, prefer `mcp__plugin_llm-externalizer_llm-externalizer__chat` with `input_files_paths` (the 3-5 report files), `instructions` (project context + consolidation instructions including dedup-by-file+line+type rules and output format), `system` ("Senior code auditor specializing in compliance review"), `temperature: 0.3`, and `ensemble: false` (consolidation is a straightforward merge — single model suffices, saves tokens). Fall back to spawning `caa-consolidation-agent` if externalizer unavailable or reports exceed 5 (hierarchical merge)
8. Run Phase 4b: spawn `caa-security-review-agent` (MANDATORY, never skip) against all audited files. The security agent runs automated tools (trufflehog, bandit, osv-scanner, etc.) and performs manual vulnerability analysis. Its findings are appended to the consolidated reports before TODO generation.
9. Run Phase 5: generate `TODO-{scope}-changes.md` per domain with file:line:evidence triples. **TODO externalizer option:** If `llm-externalizer` MCP is available, prefer `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (consolidated report), `instructions` (TODO format template + priority rules + dependency ordering instructions), and `ensemble: false` (TODO generation is template-based — single model suffices). The `language` is auto-detected from file extension. Note: 120s timeout per call (MCP spec limit) — for very large consolidated reports, set `max_tokens` to cap output length. Fall back to spawning `caa-todo-generator-agent` if externalizer unavailable or cross-scope dependencies are complex
10. If `FIX_ENABLED=true`: run Phase 6 (apply fixes) and Phase 7 (verify fixes), loop until all PASS or max passes. **Phase 6 LLM Externalizer analysis:** At the start of Phase 6, call `mcp__plugin_llm-externalizer_llm-externalizer__discover`. If available, use the externalizer for **analysis only** (write tools `fix_code`, `batch_fix`, `revert_file` were removed): read the Fix Dispatch Ledger, process each domain's audit reports ONE BY ONE (never merge them), extract per-file findings. For complex issues, call `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (the source file), `instructions` (project context + issues to diagnose), and `scan_secrets: true` to get detailed fix guidance. Then apply fixes manually with Read+Edit tools or spawn `caa-fix-agent`. Do NOT use line numbers — reference function names, variable names, or quote exact code snippets. **Timeout:** 120s per call (MCP spec limit) — set `max_tokens` for large files. Up to 5 analysis calls can run in parallel. On bad fixes, revert via `git checkout` on affected files. Update ledger `fix_status` after each file. Fall back to spawning `caa-fix-agent` if externalizer unavailable. The ledger survives context compactions — on crash/restart, resume from the first `pending` entry.
11. Run Phase 8: run the merge script to produce an intermediate report, then spawn `caa-dedup-agent` to produce the final deduplicated report. Rename the dedup output to `caa-audit-FINAL-{timestamp}.md`

## Parameters

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

**Persistent state:** When `${CLAUDE_PLUGIN_DATA}` is available, write the Fix Dispatch Ledger and agent checkpoints there so they survive context compactions and plugin updates. Fall back to `docs_dev/` if the variable is not set.

## Pipeline

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

**Gap-fill queue consumption:** Before running Phase 3, read all Phase 2 verification reports. Extract files listed under POTENTIALLY_MISSED sections. These files MUST be added to the Phase 3 re-audit file list along with any gap-fill files identified during Phase 0 inventory.

If `TODO_ONLY=true`, stop after phase 5. If `FIX_ENABLED=true`, loop P6-P7 until all PASS or `PASS_NUMBER > MAX_FIX_PASSES`.

## Report Naming

Most pipeline reports use `{REPORT_DIR}/caa-{type}-P{N}-R{RUN_ID}-{UUID}.md` (agent-generated UUID). Exceptions: consolidated, TODO, and final reports use simpler naming (see table).

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
| Fix dispatch ledger | `caa-fix-dispatch-P{N}-R{RUN_ID}.json` |
| Final | `caa-audit-FINAL-{timestamp}.md` |

## Finding IDs

Format: `{PREFIX}-P{PASS}-{AGENT_PREFIX}-{SEQ}` where PREFIX=DA/VE/GF/FV, AGENT_PREFIX=A0..AF..A10.., SEQ=001+. Consolidation uses `CA-{DOMAIN}-{SEQ}` (no PASS/AGENT_PREFIX since it operates per-domain).

**Deterministic suffix assignment:** Domain-to-AGENT_SUFFIX mapping MUST be alphabetically sorted and stable across passes. Sort domains alphabetically, then assign A0, A1, A2... in that order. This prevents finding ID collisions between passes.

## Spawning Patterns

**Worktree mode:** When `USE_WORKTREES=true`, resolve `ABSOLUTE_REPORT_DIR = $(pwd)/{REPORT_DIR}` before spawning. Pass this absolute path as `REPORT_DIR` in every agent prompt and add `isolation: "worktree"` to every Task() call. For Phase 6 fix agents, after all complete, merge worktree branches back sequentially (see below).

All agents receive: `REFERENCE_STANDARD, REPORT_PATH`. Phase 1-3 agents also receive: `SCOPE_PATH, VIOLATION_TYPES, PASS, RUN_ID, AGENT_PREFIX, FINDING_ID_PREFIX`. Additional per-phase params:

**P1 Discovery**: `FILES` (max 4), `TRIAGE_STATUS` (LIKELY_VIOLATION/LIKELY_CLEAN). Report to `caa-audit-*`.
**P2 Verify**: `AUDIT_REPORT` path, `DOMAIN_FILES` list. 3 checks: violation claims, clean claims, missed files. Report to `caa-verify-*`.
**P3 Gap-fill**: Same as P1 but `TRIAGE_STATUS=MISSED`, prefix=GF, report to `caa-gapfill-*`.
**P4 Consolidate**: If externalizer available, call `mcp__plugin_llm-externalizer_llm-externalizer__chat` with `input_files_paths` (report paths, max 5), `instructions` (consolidation instructions: merge, dedup by file+line+type, classify as VIOLATION/RECORD_KEEPING/FALSE_POSITIVE, output to `{OUTPUT_PATH}`), `system` ("Senior code auditor specializing in compliance review"), `temperature: 0.3`, and `ensemble: false` (single model suffices for merging). Fallback: spawn `caa-consolidation-agent` with `INPUT_REPORTS` (max 5 paths), `DOMAIN_NAME`, `OUTPUT_PATH`.
**P4b Security**: `DOMAIN=all-audited-files`, `FILES=ALL` (or list from manifest), `PASS=PASS_NUMBER`, `RUN_ID`, `FINDING_ID_PREFIX=SC-P{N}`, `REPORT_DIR`. Single instance. Runs automated security tools (trufflehog, bandit, osv-scanner) and manual vulnerability analysis. This phase is MANDATORY — never skip it. Append security findings to consolidated reports before TODO generation. **Externalizer pre-scan:** Before spawning the security agent, optionally call `mcp__plugin_llm-externalizer_llm-externalizer__scan_folder` with `folder_path` (the SCOPE_PATH), `extensions` ([".py", ".ts", ".js", ".yml", ".yaml", ".json"]), `scan_secrets: true`, `use_gitignore: true`, `max_files: 500`, and `instructions` ("Find security vulnerabilities: hardcoded secrets, injection vectors, unsafe deserialization, command injection, path traversal. Project context: {brief description}"). This pre-scan catches low-hanging issues cheaply before the full security agent runs.
**Security scope:** Pass FILES = the complete file inventory from Phase 0 (all files in scope, not just those that had findings in Phase 1-3).
**P5 TODO**: If externalizer available, call `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (consolidated report), `instructions` (TODO format template + priority rules + dependency ordering), and `ensemble: false` (template-based — single model suffices). Fallback: spawn `caa-todo-generator-agent` with `CONSOLIDATED_REPORT`, `SCOPE_NAME`, `TODO_PREFIX`, `OUTPUT_PATH`. Each TODO must have file:line:evidence triple.
**P6 Fix**: If `llm-externalizer` MCP is available (check via `discover`), use it for **analysis only** (write tools `fix_code`, `batch_fix`, `revert_file` were removed): read the Fix Dispatch Ledger, process each report individually. For complex issues, call `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (the source file), `instructions` (project context + issues), and `scan_secrets: true` to get fix guidance. Then apply fixes with Read+Edit tools or spawn `caa-fix-agent`. Do NOT use line numbers — reference function names or quote code. `language` is auto-detected from extension. 120s timeout per call (MCP spec limit) — use `max_tokens` for large files. Up to 5 analysis calls in parallel. On bad fixes, revert via `git checkout`. Update ledger `fix_status` after each file. Fall back to `caa-fix-agent` if externalizer unavailable. **Fix agent params:** `TODO_FILE`, `ASSIGNED_TODOS`, `FILES`, `CHECKPOINT_PATH`, `REPORT_PATH`. Checkpoint after each fix. Harmonization: preserve existing + add new.
**P7 Fix-verify**: `FIXED_FILES`, `ORIGINAL_TODOS`, `FIX_REPORT`, `TODO_FILE`, `REFERENCE_STANDARD`, `REPORT_PATH`. Verdict: PASS/FAIL/REGRESSION.

All agents end with: `REPORTING RULES: Write details to report file. Return ONLY: "[DONE/FAILED] {task} - {summary}. Report: {path}". Max 2 lines.`

## Fix Agent Worktree Merge-Back (USE_WORKTREES only)

When `USE_WORKTREES=true` and `FIX_ENABLED=true`, Phase 6 fix agents each work in isolated worktrees on separate branches. After ALL Phase 6 agents complete:

1. Merge each agent's branch back to the current branch sequentially (in domain assignment order)
2. If a merge conflict occurs, STOP and escalate to the user
3. After successful merge, remove the worktree: `git worktree remove {path}`
4. Run Phase 7 (fix verification) on the merged result

## Loop Termination

- Gap-fill: stops when 0 missed files or 3 iterations reached
- Fix loop: stops when all verifiers PASS or `PASS_NUMBER > MAX_FIX_PASSES`
- Agent retry: max 3 retries per agent; after 3, escalate
- Escalation: If gap-fill completes 3 iterations with <100% coverage, write a WARNING to the final report header listing uncovered files. If MAX_FIX_PASSES is reached with still-failing verifications, the final report MUST be marked 'INCOMPLETE - {N} unresolved issues after {MAX_FIX_PASSES} passes' and the user must be notified.
