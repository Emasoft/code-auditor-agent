# Procedure 2: Code Fix

## Table of Contents

- [Agent Selection (Dynamic)](#agent-selection-dynamic)
- [Fix Protocol](#fix-protocol)
- [Linting Step (Docker Required)](#linting-step-docker-required)
- [Commit After Fixes](#commit-after-fixes)
- [Procedure 2 Output](#procedure-2-output)
- [Procedure 2 Checklist](#procedure-2-checklist)

Swarm of fixing agents that resolve all findings from Procedure 1, run tests, lint, and commit.

**Worktree mode:** When `USE_WORKTREES=true`, each fix agent runs in an isolated git worktree via `isolation: "worktree"`. This prevents concurrent agents from modifying the same files. After all fix agents complete, the orchestrator merges their worktree branches back sequentially. See the parent SKILL.md for full worktree protocol.

## Agent Selection (Dynamic)

This plugin does NOT hardcode any specific agent types for code fixing. Different users
have different agents installed. Instead, the orchestrator should **dynamically choose
the best available agent** for each fix domain.

**Selection protocol:**

1. Check what agent types are available in the current Claude Code instance
   (the Task tool description lists all available `subagent_type` values).
2. For each domain's fix task, pick the most suitable agent based on its description.
   Prefer agents that mention code fixing, TDD, refactoring, or the domain's language.
3. If no specialized agent matches, use `general-purpose` -- it is always available in
   every Claude Code installation and has access to Read, Edit, Write, Bash, Grep, Glob,
   and all other standard tools needed to implement fixes.

**Selection heuristics** (examples -- adapt to what's actually available):

| Fix need | Look for agents that mention... | Fallback |
|----------|--------------------------------|----------|
| Code bugs / logic fixes | "TDD", "refactoring", "implementation" | `general-purpose` |
| Lint / format issues | "linting", "formatting", "code fixer" | `general-purpose` |
| Security fixes | "security", "vulnerability" | `general-purpose` |
| Test failures | "test execution", "validation" | `general-purpose` |
| Documentation fixes | "documentation", "lightweight fixes" | `general-purpose` |

**Key rule:** Never assume a specific agent exists. Always verify availability first,
and always fall back to `general-purpose` if the preferred agent is not found.

## Fix Protocol

### Fix Dispatch Ledger (Compaction-Safe Tracking)

The orchestrator MUST maintain a persistent **Fix Dispatch Ledger** on disk. This file maps each review agent's report to the exact source files it scanned, enabling crash recovery and compaction survival.

**Ledger path:** `{REPORT_DIR}/caa-fix-dispatch-P{PASS_NUMBER}-R{RUN_ID}.json`

**When to create:** During PROCEDURE 1 setup, when the orchestrator divides the PR into domains and assigns file groups to review agents. At this point you already know which files go to which agent — record that mapping immediately.

**When to update:** After each review agent completes, update its entry with the report path and set `agent_status: "completed"`. Write the updated ledger to disk after every change.

**Format:**

```json
{
  "run_id": "{RUN_ID}",
  "pass_number": 1,
  "created_at": "ISO timestamp",
  "entries": [
    {
      "domain": "server",
      "agent": "caa-code-correctness-agent",
      "report": "docs_dev/caa-pr-review-P1-abc123.md",
      "files": ["src/server.ts", "src/routes.ts", "src/middleware.ts"],
      "agent_status": "completed",
      "fix_status": "pending",
      "fixed_at": null,
      "error": null
    }
  ]
}
```

**fix_status lifecycle:** `pending` → `in_progress` → `done` | `failed` | `skipped` (no findings in report)

**Crash recovery:** On restart, read the ledger from disk. Skip entries with `fix_status: "done"` or `"skipped"`. Retry entries with `fix_status: "in_progress"` or `"failed"` (revert files first via `mcp__llm-externalizer__revert_file` or git checkout). Resume from the first `pending` entry.

### LLM Externalizer Fix Protocol (Preferred When Available)

When the `llm-externalizer` MCP is available, use it instead of spawning full fix agents. The externalizer is cheaper, faster, and avoids consuming orchestrator context tokens.

**Availability check:** At the start of PROCEDURE 2, call `mcp__llm-externalizer__discover`. If it succeeds, use the externalizer protocol below. If it fails or the MCP is not configured, fall back to the standard fix agent protocol (spawning pattern section below).

**CRITICAL RULES:**
- **Do NOT merge review reports** before sending to the externalizer. Process each review agent's report individually against its own file list. Merging loses the file-to-agent mapping and overwhelms the external LLM with too much context.
- **ALWAYS include project context** in `instructions`. The external LLM has ZERO knowledge of your project. Always say: what the project is, what language/framework, what this file does, and any relevant interfaces/types.
- **Do NOT use line numbers** in fix instructions — they are unreliable. Instead, reference function names, variable names, string literals, or quote the exact code snippet that needs fixing.
- **One report at a time.** Read the dispatch ledger, pick one entry, read its report, extract per-file issues, and fix files individually or in small batches (up to 5 parallel calls).

**Fix dispatch algorithm:**

1. Read the Fix Dispatch Ledger from disk
2. For each entry with `fix_status: "pending"`:
   a. Set `fix_status: "in_progress"`, write ledger to disk
   b. Read the review report at `entry.report`
   c. Parse the report: extract per-file findings (group by file path). Each finding needs: function/class name, a quote of the broken code, what is wrong, what the correct behavior should be
   d. Write per-file fix instructions to a temporary .md file (e.g., `docs_dev/caa-fix-instructions-{domain}-{file}.md`) — one file per source file to fix
   e. For each file in `entry.files` that has findings:
      - Call `mcp__llm-externalizer__fix_code` with:
        - `input_files_paths`: absolute path to the source file
        - `instructions`: project context + summary of what to fix
        - `instructions_files_paths`: path to the per-file fix instructions .md file (loads instructions from disk, saves orchestrator context)
      - Up to 5 `fix_code` calls can run in parallel — launch multiple at once
      - If `fix_code` succeeds: note file as fixed
      - If `fix_code` fails: call `mcp__llm-externalizer__revert_file` with `input_files_paths` to restore the `.externbak` backup, note as failed
   f. For files with no findings: set as `"skipped"`
   g. Update `fix_status` to `"done"` (all files fixed or skipped) or `"failed"` (any file failed), write ledger to disk
3. For entries that failed: fall back to spawning a fix agent for that domain (see spawning pattern below)

**Batch optimization:** For entries with 3+ files that share the same set of issues (e.g., lint fixes), use `mcp__llm-externalizer__batch_fix` with `input_files_paths` as an array and `instructions` containing the common issues. The tool processes files in parallel on OpenRouter. Use `answer_mode: 0` for per-file reports.

**When to fall back to fix agents:** If `discover` fails (externalizer unavailable), OR if `fix_code` fails on >50% of files in an entry, switch to the full fix agent protocol for all remaining entries.

### Fix Steps

1. Read the merged review report from PROCEDURE 1: `docs_dev/caa-pr-review-P{PASS_NUMBER}-{timestamp}.md`
2. Build the list of issues to fix, grouped by domain. Extract the checklist from the merged report.
3. **Check LLM Externalizer availability** via `mcp__llm-externalizer__discover`. If available, use the LLM Externalizer Fix Protocol above (read dispatch ledger, process reports one by one). Skip to step 6 after externalizer completes.
4. **Fallback (no externalizer):** For each domain, select the best available agent type (see Agent Selection above). Spawn one fixing agent per domain in parallel. If a domain has more than 5 files to fix, split into groups of max 5 files and spawn separate agents. Group files involved in the same issue together.
5. Give each agent its domain-specific subset of the checklist from the merged report. The agent must track which issues it resolved. Wait for all fixing agents to complete and save their partial reports.
6. Read all fix reports (from externalizer or agents) and cross-check against the full checklist from the merged review report. Verify every entry has been addressed.
7. Spawn an agent to run all tests to verify fixes did not break functionality or cause regressions.
8. If tests fail, spawn a fixing agent (best available or `general-purpose`) for each domain involved in the failures to investigate and fix the root cause.
9. Repeat the test-fix cycle at most 3 times. If tests still fail after 3 attempts, note unresolved test failures in the fix report and proceed to the linting step.
10. Write fix summary and test results reports.
11. **Linting step (Docker required).** Check if Docker is available: `command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1`. If Docker is NOT available, skip linting with a note: "Docker not available -- MegaLinter step skipped." and proceed to commit.
12. If Docker IS available, run the MegaLinter linter script (see "Linting Step" section below). Parse the `lint-summary.json` output.
13. If the linter reports errors (`has_errors: true` in the summary JSON), spawn fix agents to address the lint errors (one agent per domain, reading the MegaLinter logs for specifics). After fixes, re-run the linter.
14. Repeat lint -> fix cycles until the linter exits with 0 errors, or 3 consecutive lint-fix attempts fail (escalate to user if so).
15. Write lint results report.

**Spawning pattern for fix agents:**

```
Task(
  subagent_type: "{best_available_agent_for_domain, fallback: 'general-purpose'}",
  prompt: """
    TASK: Fix review findings for domain {domain_name}
    PASS: {PASS_NUMBER}
    RUN_ID: {RUN_ID}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}
    REVIEW_REPORT: docs_dev/caa-pr-review-P{PASS_NUMBER}-{timestamp}.md
    CHECKPOINT_FILE: docs_dev/caa-checkpoint-P{PASS_NUMBER}-R{RUN_ID}-{domain_name}.json

    Fix these specific issues from the review report:
    {checklist_subset_for_this_domain}

    CHECKPOINT PROTOCOL:
    Before starting, check if CHECKPOINT_FILE exists. If it does, read it to see
    which findings were already fixed by a prior agent attempt. Verify those fixes
    are actually applied in the code. Skip confirmed fixes, continue with remaining.

    For each issue:
    1. Read the file and understand the problem
    2. Implement the fix
    3. Write a checkpoint entry to CHECKPOINT_FILE (JSON with finding ID + status)
    4. Mark the issue as DONE in your report

    Checkpoint entry format (append to findings array in the JSON file):
    {"id": "SF-001", "status": "fixed", "file": "AgentProfileTab.tsx", "timestamp": "ISO"}

    Write your fix report to: {ABSOLUTE_REPORT_DIR}/caa-fixes-done-P{PASS_NUMBER}-{domain_name}.md

    SELF-VERIFICATION CHECKLIST:
    Before returning your result, copy this checklist into your report file and mark each item.
    Do NOT return until all items are addressed.

    ```
    ## Self-Verification

    - [ ] I read the merged review report and identified ALL issues assigned to my domain
    - [ ] For each issue, I read the FULL file and understood the problem BEFORE attempting a fix
    - [ ] I made the MINIMAL fix required (no over-engineering, no unnecessary refactoring)
    - [ ] I did NOT change code unrelated to the assigned issues
    - [ ] I did NOT add new features, abstractions, or "improvements" beyond what was requested
    - [ ] I avoided introducing new lint warnings, type errors, or compilation issues (final verification by test runner)
    - [ ] For each issue, I re-read the modified code and traced the logic to verify the fix resolves the problem
    - [ ] I did NOT break any existing function signatures, return types, or API contracts
    - [ ] I preserved existing test expectations unless the fix explicitly required changing them (documented in report)
    - [ ] My fix report lists ALL assigned issues with their original finding IDs
    - [ ] Each issue is marked: FIXED (with description of change) or NOT FIXED (with reason)
    - [ ] The fixed/total count in my return message matches the actual counts in the report
    - [ ] My return message to the orchestrator is exactly 1-2 lines (no code blocks, no verbose output, full details in report file only)
    ```

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] fix-{domain} - {M}/{N} issues fixed. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

**Spawning pattern for test agent:**

```
Task(
  subagent_type: "{best_available_test_agent, fallback: 'general-purpose'}",
  prompt: """
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    Run the full test suite for the project.
    Determine the test command from package.json, Makefile, or project conventions
    (e.g., `yarn test`, `npm test`, `pytest`, `go test ./...`).
    Write results to: {ABSOLUTE_REPORT_DIR}/caa-tests-outcome-P{PASS_NUMBER}.md

    SELF-VERIFICATION CHECKLIST:
    Before returning your result, copy this checklist into your report file and mark each item.
    Do NOT return until all items are addressed.

    ```
    ## Self-Verification

    - [ ] I determined the correct test command from the project configuration
    - [ ] I ran the FULL test suite (not a subset, unless explicitly instructed otherwise)
    - [ ] I captured the test runner's output to the report file (summary line + all failure details; pipe to file if output exceeds terminal buffer)
    - [ ] I did NOT modify any source files or test files
    - [ ] I did NOT skip, disable, or comment out any failing tests
    - [ ] For each failure, I included: test name, file path, and error message/stack trace (N/A if all tests passed)
    - [ ] I counted passed/failed/skipped tests accurately from the test runner output
    - [ ] I verified my pass/fail counts by cross-checking with the test runner's summary line
    - [ ] If ALL tests passed, I confirmed this with the test runner's exit code (0 = success)
    - [ ] If tests FAILED, I listed each failing test with enough context to diagnose the issue
    - [ ] The passed/total count in my return message matches the actual test runner output
    - [ ] My return message to the orchestrator is exactly 1-2 lines (no code blocks, no verbose output, full details in report file only)
    ```

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] tests - {passed}/{total} pass. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

## Linting Step (Docker Required)

This step runs **only if Docker is available** on the host machine. If Docker is not installed
or the Docker daemon is not running, skip this entire section and proceed to "Commit After Fixes".

**Docker availability check:**

```bash
# Returns 0 if Docker is available and daemon is running
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
```

If the check fails, log: `"[SKIP] MegaLinter step -- Docker not available."` and proceed to commit.

**Linter script location:** `${CLAUDE_PLUGIN_ROOT}/scripts/universal_pr_linter.py`

The script uses MegaLinter inside Docker to lint the entire codebase. It runs in `--plugin-mode`
which lints the working directory directly (no temp copy) with APPLY_FIXES=none (read-only --
MegaLinter never modifies your files).

**Spawning pattern for lint agent:**

```
Task(
  subagent_type: "general-purpose",
  prompt: """
    TASK: Run MegaLinter on the project
    PASS: {PASS_NUMBER}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    1. Check Docker availability:
       command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
       If Docker is NOT available, write "[SKIP] Docker not available" to the report and return immediately.

    2. Run the linter:
       uv run ${CLAUDE_PLUGIN_ROOT}/scripts/universal_pr_linter.py \
         {PROJECT_ROOT} \
         --plugin-mode \
         --all \
         --report-dir {ABSOLUTE_REPORT_DIR}/megalinter-P{PASS_NUMBER} \
         --summary-json {ABSOLUTE_REPORT_DIR}/megalinter-P{PASS_NUMBER}/lint-summary.json \
         --no-pull

       NOTE: On first run, omit --no-pull so Docker pulls the MegaLinter image.
       On subsequent runs within the same pass, use --no-pull to skip the pull.

    3. Read the summary JSON at {ABSOLUTE_REPORT_DIR}/megalinter-P{PASS_NUMBER}/lint-summary.json
       Key fields:
       - has_errors (bool): true if any linter reported errors
       - error_count (int): number of linters that failed
       - error_linters (string[]): names of failed linters
       - report_dir (string): path to full MegaLinter reports

    4. Write your report to: {ABSOLUTE_REPORT_DIR}/caa-lint-outcome-P{PASS_NUMBER}.md
       Include: exit code, error count, failed linter names, report directory path.

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/SKIP] lint - exit {code}, {N} linter errors. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

**If lint errors exist (exit code non-zero):**

Spawn fix agents to address lint issues. Each lint fix agent receives the MegaLinter logs
for its domain's linters. The log files are at `docs_dev/megalinter-P{N}/linters_logs/ERROR-{LINTER}.log`.

```
Task(
  subagent_type: "{best_available_agent_for_domain, fallback: 'general-purpose'}",
  prompt: """
    TASK: Fix lint errors reported by MegaLinter
    PASS: {PASS_NUMBER}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}
    LINT_REPORT: {ABSOLUTE_REPORT_DIR}/megalinter-P{PASS_NUMBER}/lint-summary.json

    The following linters reported errors: {error_linters_list}

    For each failed linter, read the error log at:
      {ABSOLUTE_REPORT_DIR}/megalinter-P{PASS_NUMBER}/linters_logs/ERROR-{LINTER_NAME}.log

    Fix ONLY the errors (not warnings). Make minimal changes to resolve lint issues.
    Do NOT refactor, restructure, or add features -- only fix what the linter flagged as errors.

    Write your fix report to: {ABSOLUTE_REPORT_DIR}/caa-lint-fixes-P{PASS_NUMBER}.md

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] lint-fix - {M}/{N} linter errors fixed. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

**Lint-fix loop:** After the lint fix agent completes, re-run the linter. Repeat until:
- Linter exits with 0 errors -> proceed to commit
- 3 consecutive lint-fix attempts fail to reduce the error count -> stop and escalate:
  `"MegaLinter errors persist after 3 fix attempts. {N} linter errors remain. Manual intervention required."`

**Important:** The lint-fix loop counts are SEPARATE from the main pass counter. A single pass
can have multiple lint-fix iterations without incrementing the pass number. Only the outer
review-fix loop increments the pass counter.

## Worktree Merge-Back (USE_WORKTREES only)

When `USE_WORKTREES=true`, after all fix agents complete, merge their branches back:

```
for each completed fix agent:
  worktree_branch = {branch name returned by the Agent tool}
  git merge --no-edit {worktree_branch}
  if merge conflict:
    # Try auto-resolve with 'git checkout --theirs' for non-overlapping changes
    # If conflicts persist, escalate to user:
    # "Merge conflict between fix agents for {domain1} and {domain2}. Manual resolution required."
  git worktree remove {worktree_path}  # Clean up the worktree
```

**Order matters:** Merge domains in the same order they were assigned to fix agents. This maintains a predictable merge order.

**If a merge fails:** Do NOT continue merging other branches. Stop and escalate to the user with the conflicting file list.

## Commit After Fixes

After all fixes pass tests AND linting is clean (or Docker unavailable), commit the changes:

```bash
git add {modified_files}
git commit -m "fix: pass {PASS_NUMBER} -- resolve {count} review findings

Issues fixed:
- [CC-P{N}-001] {title}
- [SR-P{N}-003] {title}
..."
```

This creates a rollback point and ensures subsequent passes see a clean diff.

## Procedure 2 Output

- Per-domain fix summaries: `docs_dev/caa-fixes-done-P{N}-{domain}.md`
- Test outcome: `docs_dev/caa-tests-outcome-P{N}.md`
- Lint outcome: `docs_dev/caa-lint-outcome-P{N}.md` (if Docker available)
- Lint summary JSON: `docs_dev/megalinter-P{N}/lint-summary.json` (if Docker available)
- Lint fixes: `docs_dev/caa-lint-fixes-P{N}.md` (if lint errors were fixed)

---

## Model Selection Rules

- **Opus/Sonnet ONLY** for all code fixing, test analysis, lint analysis, and reasoning tasks
- **Haiku PROHIBITED** for code fixing and analysis — it hallucinates on complex code and causes error loops
- Haiku is acceptable ONLY for: running shell commands, file moves, formatting, and simple maintenance
- When spawning subagents for fix, test, or lint phases: always specify `model: opus` or `model: sonnet`

## Procedure 2 Checklist

Copy this checklist and track your progress:

- [ ] Merged review report read and issues grouped by domain
- [ ] Best available agent type selected for each domain
- [ ] Fix agents spawned (one per domain, max 5 files each)
- [ ] All fix agents completed and reports collected
- [ ] Cross-check: every issue in the review report addressed (FIXED or NOT FIXED with reason)
- [ ] Test agent spawned and tests executed
- [ ] All tests passing (or test-fix cycles completed)
- [ ] Docker availability checked for linting
- [ ] If Docker available: MegaLinter executed
- [ ] If lint errors: lint-fix cycle completed (max 3 attempts)
- [ ] All fixes committed with descriptive commit message
