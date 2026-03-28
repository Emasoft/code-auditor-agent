# Instructions

## Table of Contents
- [Phase Steps](#phase-steps)
- [Parameters](#parameters)
- [Pipeline](#pipeline)
- [Report Naming](#report-naming)
- [Finding IDs](#finding-ids)
- [Spawning Patterns](#spawning-patterns)
- [Fix Agent Worktree Merge-Back](#fix-agent-worktree-merge-back-use_worktrees-only--discouraged)
- [Loop Termination](#loop-termination)

## Phase Steps

Follow these steps to run the audit pipeline:

1. Set `SCOPE_PATH` to the directory to audit and `REFERENCE_STANDARD` to the compliance doc path. Verify `REFERENCE_STANDARD` file exists and is non-empty before proceeding. If not, STOP with error: 'REFERENCE_STANDARD not found or empty at {path}.'
2. Generate a `RUN_ID` (8 lowercase hex chars: `uuid4().hex[:8]`) and set `PASS_NUMBER=1`
3. Run Phase 0: **Automated file grouping via Python script.** Use `scripts/caa-collect-context.py` (or Bash) to:
   a. Inventory all text files in SCOPE_PATH (source, config, CI/CD, metadata, prompt definitions).
   b. Classify files by domain (language, directory, dependency cluster).
   c. Triage with grep patterns to tag LIKELY_VIOLATION vs LIKELY_CLEAN.
   d. **Group files into fix-ready batches of 3-4** — files in the same directory or dependency chain go together. Each group gets a unique GROUP_ID.
   e. Write the **Fix Dispatch Ledger** to `{REPORT_DIR}/caa-fix-dispatch-P{PASS_NUMBER}-R{RUN_ID}.json` — maps GROUP_ID → file list, so every downstream step (externalizer, agents, fix agents) uses the SAME grouping.
   f. Write per-group file lists to `{REPORT_DIR}/caa-group-{GROUP_ID}.txt` (one absolute path per line) for direct passing to the externalizer's `input_files_paths`.

   If zero files found, STOP with error. **File type coverage** MUST include ALL text files:
   - Source: `.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, `.rb`, `.sh`, `.bash`
   - Config: `.yaml`, `.yml`, `.toml`, `.json`, `.xml`, `.ini`, `.cfg`
   - Prompts: `.md` in `agents/`, `skills/`, `commands/`
   - CI/CD: `.github/workflows/*.yml`, `Dockerfile`
   - Metadata: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`

   Route config/metadata to code-correctness, prompt `.md` to security-review, CI/CD to both.

4. Run Phase 1: **Per-group analysis.** For each group from Phase 0:
   a. **Preferred (externalizer available):** Call `mcp__plugin_llm-externalizer_llm-externalizer__check_against_specs` with `spec_file_path` (REFERENCE_STANDARD) and `input_files_paths` (the group's file list from `caa-group-{GROUP_ID}.txt`). This produces a per-group violation report that maps directly to the fix agent assignment. Up to 5 groups can be processed in parallel.
   b. **Fallback (no externalizer):** Spawn `caa-domain-auditor-agent` for each group (concurrency 20).
   c. **Key principle:** The grouping from Phase 0 is reused in ALL downstream phases — consolidation, TODO generation, and fix dispatch. No re-reading or re-grouping needed.
5. Run Phase 2: spawn `caa-verification-agent` to cross-check all Phase 1 reports (concurrency 10)
6. Run Phase 3: gap-fill missed files, re-verify, loop max 3 times until 100% coverage
7. Run Phase 4: consolidate per-domain reports. **Consolidation externalizer option:** If `llm-externalizer` MCP is available, prefer `mcp__plugin_llm-externalizer_llm-externalizer__chat` with `input_files_paths` (the 3-5 report files), `instructions` (project context + consolidation instructions including dedup-by-file+line+type rules and output format), `system` ("Senior code auditor specializing in compliance review"), and `temperature: 0.3`. 115s timeout per call, auto-retries on truncation. Fall back to spawning `caa-consolidation-agent` if externalizer unavailable or reports exceed 5 (hierarchical merge)
8. Run Phase 4b: spawn `caa-security-review-agent` (MANDATORY, never skip) against all audited files. The security agent runs automated tools (trufflehog, bandit, osv-scanner, etc.) and performs manual vulnerability analysis. Its findings are appended to the consolidated reports before TODO generation.
9. Run Phase 5: generate `TODO-{scope}-changes.md` per domain with file:line:evidence triples. **TODO externalizer option:** If `llm-externalizer` MCP is available, prefer `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (consolidated report) and `instructions` (TODO format template + priority rules + dependency ordering instructions). The `language` is auto-detected from file extension. 115s timeout per call, auto-retries on truncation. Fall back to spawning `caa-todo-generator-agent` if externalizer unavailable or cross-scope dependencies are complex
10. If `FIX_ENABLED=true`: run Phase 6 (apply fixes) and Phase 7 (verify fixes), loop until all PASS or max passes. **Phase 6 uses pre-grouped dispatch — zero redundant reads.**
   a. Read the Fix Dispatch Ledger from Phase 0. Each entry has GROUP_ID → file list + consolidated report path + TODO file path.
   b. **Externalizer fix guidance (preferred):** For each group, call `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (the group's source files), `instructions` (project context + the group's TODO items), and `scan_secrets: true`. The externalizer returns per-file fix guidance. Up to 5 groups in parallel.
   c. **Spawn one fix agent per group:** Each `caa-fix-agent` receives ONLY: its group's `TODO_FILE`, `ASSIGNED_TODOS`, `FILES` (3-4 files), `CHECKPOINT_PATH`, `REPORT_PATH`, and the externalizer's fix guidance report (if available). The agent reads ONLY its assigned files — no codebase scanning, no redundant reads.
   d. On bad fixes, revert via `git checkout` on affected files. Update ledger `fix_status` after each group. The ledger survives context compactions — on crash/restart, resume from the first `pending` entry.
11. Run Phase 8: run `scripts/caa-merge-audit-reports.py` to join all per-group reports into `caa-audit-FINAL-{timestamp}.md`. The orchestrator does NOT read the final report — the script outputs a summary line with finding counts and the file path. Present the summary to the user. If the user requests details, THEN read specific sections on demand.

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
| 0 | Prep: Python script inventory, domain classify, grep triage, group files (3-4 per group), write manifest + per-group file lists | orchestrator | -- |
| 1 | Discovery: audit each batch | `caa-domain-auditor-agent` | 20 |
| 2 | Verification: verify each Phase 1 report + missed-file detection | `caa-verification-agent` | 10 |
| 3 | Gap-fill: audit missed files, re-verify, loop max 3x | `caa-domain-auditor-agent` + verifier | 20 |
| 4 | Consolidation: merge per-domain (max 5 inputs/agent, hierarchical if more) | `caa-consolidation-agent` | 5 |
| 4b | Security scan: vulnerabilities, secrets, dependency CVEs (MANDATORY) | `caa-security-review-agent` | 1 |
| 5 | TODO generation: actionable TODO-{scope}-changes.md per domain | `caa-todo-generator-agent` | 5 |
| 6 | Fix (if FIX_ENABLED): implement TODOs with checkpoints | `caa-fix-agent` | 20 |
| 7 | Fix verify (if FIX_ENABLED): verify fixes, loop to P6 if FAILs | `caa-fix-verifier-agent` | 20 |
| 8 | Final report: compile stats, link artifacts | orchestrator | -- |

**Gap-fill queue consumption:** Before running Phase 3, use a Python script (or `grep -l POTENTIALLY_MISSED {REPORT_DIR}/caa-verify-*.md`) to extract missed file paths from Phase 2 reports WITHOUT reading them into agent context. The script outputs a flat list of missed files. These MUST be added to the Phase 3 re-audit file list along with any gap-fill files identified during Phase 0 inventory.

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
| Per-group file list | `caa-group-{GROUP_ID}.txt` |
| Per-group security | `caa-security-group-{GROUP_ID}.md` |
| Per-group review | `caa-review-group-{GROUP_ID}.md` |
| Per-group lint | `caa-lint-group-{GROUP_ID}.md` |
| Per-group fix issues | `caa-fix-group-{GROUP_ID}.md` |
| Final | `caa-audit-FINAL-{timestamp}.md` |

## Finding IDs

Format: `{PREFIX}-P{PASS}-{AGENT_PREFIX}-{SEQ}` where PREFIX=DA/VE/GF/FV, AGENT_PREFIX=A0..AF..A10.., SEQ=001+. Consolidation uses `CA-{DOMAIN}-{SEQ}` (no PASS/AGENT_PREFIX since it operates per-domain).

**Deterministic suffix assignment:** Domain-to-AGENT_SUFFIX mapping MUST be alphabetically sorted and stable across passes. Sort domains alphabetically, then assign A0, A1, A2... in that order. This prevents finding ID collisions between passes.

## Spawning Patterns

**Worktree mode (DISCOURAGED — explicit opt-in only):** Only use when `USE_WORKTREES=true` is explicitly passed by the user. Default is non-worktree mode with serialized execution, which preserves tool intelligence (.tldr/, .serena/cache/, .claude/ are gitignored and NOT copied to worktrees). The Phase 0 file grouping + per-group dispatch already prevents agent conflicts without worktrees. If worktrees are forced: resolve `ABSOLUTE_REPORT_DIR = $(pwd)/{REPORT_DIR}` before spawning. Pass this absolute path as `REPORT_DIR` in every agent prompt and add `isolation: "worktree"` to every Task() call. For Phase 6 fix agents, after all complete, merge worktree branches back sequentially (see below). **WARNING:** Merging worktree branches frequently causes conflicts — prefer default mode.

All agents receive: `REFERENCE_STANDARD, REPORT_PATH`. Phase 1-3 agents also receive: `SCOPE_PATH, VIOLATION_TYPES, PASS, RUN_ID, AGENT_PREFIX, FINDING_ID_PREFIX`. Additional per-phase params:

**P1 Discovery**: `FILES` (max 4), `TRIAGE_STATUS` (LIKELY_VIOLATION/LIKELY_CLEAN). Report to `caa-audit-*`.
**P2 Verify**: `AUDIT_REPORT` path, `DOMAIN_FILES` list. 3 checks: violation claims, clean claims, missed files. Report to `caa-verify-*`.
**P3 Gap-fill**: Same as P1 but `TRIAGE_STATUS=MISSED`, prefix=GF, report to `caa-gapfill-*`.
**P4 Consolidate**: If externalizer available, call `mcp__plugin_llm-externalizer_llm-externalizer__chat` with `input_files_paths` (report paths, max 5), `instructions` (consolidation instructions: merge, dedup by file+line+type, classify as VIOLATION/RECORD_KEEPING/FALSE_POSITIVE, output to `{OUTPUT_PATH}`), `system` ("Senior code auditor specializing in compliance review"), and `temperature: 0.3`. Fallback: spawn `caa-consolidation-agent` with `INPUT_REPORTS` (max 5 paths), `DOMAIN_NAME`, `OUTPUT_PATH`.
**P4b Security**: `DOMAIN=all-audited-files`, `FILES=ALL` (or list from manifest), `PASS=PASS_NUMBER`, `RUN_ID`, `FINDING_ID_PREFIX=SC-P{N}`, `REPORT_DIR`. Single instance. Runs automated security tools (trufflehog, bandit, osv-scanner) and manual vulnerability analysis. This phase is MANDATORY — never skip it. Append security findings to consolidated reports before TODO generation. **Externalizer pre-scan:** Before spawning the security agent, optionally call `mcp__plugin_llm-externalizer_llm-externalizer__scan_folder` with `folder_path` (the SCOPE_PATH), `extensions` ([".py", ".ts", ".js", ".yml", ".yaml", ".json"]), `scan_secrets: true`, `use_gitignore: true`, `max_files: 500`, and `instructions` ("Find security vulnerabilities: hardcoded secrets, injection vectors, unsafe deserialization, command injection, path traversal. Project context: {brief description}"). This pre-scan catches low-hanging issues cheaply before the full security agent runs.
**Security scope:** Pass FILES = the complete file inventory from Phase 0 (all files in scope, not just those that had findings in Phase 1-3).
**P5 TODO**: If externalizer available, call `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (consolidated report) and `instructions` (TODO format template + priority rules + dependency ordering). Fallback: spawn `caa-todo-generator-agent` with `CONSOLIDATED_REPORT`, `SCOPE_NAME`, `TODO_PREFIX`, `OUTPUT_PATH`. Each TODO must have file:line:evidence triple.
**P6 Fix**: Read the Fix Dispatch Ledger. For each group with pending TODOs: (1) If externalizer available, call `mcp__plugin_llm-externalizer_llm-externalizer__code_task` with `input_files_paths` (the group's source files only — NOT the whole codebase), `instructions` (project context + the group's TODO items), `scan_secrets: true` → produces per-group fix guidance. Up to 5 groups in parallel. (2) Spawn one `caa-fix-agent` per group with: `TODO_FILE` (the group's TODO), `ASSIGNED_TODOS` (IDs for this group), `FILES` (3-4 files from Phase 0 grouping), `CHECKPOINT_PATH`, `REPORT_PATH`, and optionally the externalizer's fix guidance file. The agent reads ONLY its assigned files. On bad fixes, revert via `git checkout`. Update ledger `fix_status`. Harmonization: preserve existing + add new.
**P7 Fix-verify**: `FIXED_FILES`, `ORIGINAL_TODOS`, `FIX_REPORT`, `TODO_FILE`, `REFERENCE_STANDARD`, `REPORT_PATH`. Verdict: PASS/FAIL/REGRESSION.

All agents end with: `REPORTING RULES: Write details to report file. Return ONLY: "[DONE/FAILED] {task} - {summary}. Report: {path}". Max 2 lines.`

## Fix Agent Worktree Merge-Back (USE_WORKTREES only — DISCOURAGED)

**STRONGLY DISCOURAGED.** The default Phase 0 file grouping already prevents agent conflicts by assigning non-overlapping file sets to each fix agent. Worktrees add these costs:
- **Tool intelligence loss:** `.tldr/`, `.serena/cache/`, `.claude/` are gitignored — agents lose semantic navigation and fall back to raw file reading with massive token waste.
- **Merge conflicts:** Each worktree creates a branch. Merging branches back frequently causes conflicts that require manual resolution.
- **Disk and time overhead:** N worktree copies for N concurrent agents.

Use worktrees ONLY when explicitly requested via `USE_WORKTREES=true` AND concurrent agents modify overlapping files (rare with proper Phase 0 grouping).

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
