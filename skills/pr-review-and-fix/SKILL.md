---
name: pr-review-and-fix
description: >
  Use when reviewing PRs, auditing code, or running pre-merge quality gates.
  Trigger with "review and fix the PR", "review and fix PR", "audit and fix the PR", "pre-merge review and fix".
version: 3.0.0
author: Emasoft
license: MIT
tags:
  - pr-review
  - code-audit
  - claim-verification
  - quality-gate
  - auto-fix
---

# PR Review And Fix

## Overview

Iterative review-and-fix pipeline that combines two procedures in a loop until zero issues remain:

1. **PROCEDURE 1 -- Code Review**: Three-phase PR review (correctness swarm -> claim verification -> skeptical review) that produces a merged findings report.
2. **PROCEDURE 2 -- Code Fix**: Swarm of fixing agents (dynamically selected from available agents) that resolve all findings from PROCEDURE 1, then run tests to verify no regressions.

The loop runs until PROCEDURE 1 finds zero issues, or the maximum pass limit (25) is reached.

```
+---------------------------------------------------+
|  PASS N (N starts at 1, max 25)                   |
|                                                   |
|  1. PROCEDURE 1 -- Review                         |
|     Phase 1: Code Correctness Swarm (parallel)    |
|     Phase 2: Claim Verification (sequential)      |
|     Phase 3: Skeptical Review (sequential)        |
|     Phase 4: Merge Reports                        |
|     Phase 5: Present Results                      |
|                                                   |
|  2. If zero issues -> DONE (write final report)   |
|     If N > 10   -> STOP (escalate to user)         |
|                                                   |
|  3. PROCEDURE 2 -- Fix                            |
|     Fix all findings from merged report           |
|     Run tests, fix regressions                    |
|     Lint (if Docker available), fix lint errors    |
|     Commit fixes                                  |
|                                                   |
|  4. N = N + 1, go to step 1                       |
|                                                   |
+---------------------------------------------------+
```

## Prerequisites

- `gh` CLI installed and authenticated (for `gh pr view`, `gh pr diff`)
- The PR must exist on GitHub (need PR number or branch name)
- `docs_dev/` directory must exist for report output. Create it if missing, and ensure it is in `.gitignore`.
- The merge script at `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh` must be executable

## Use When

- Before pushing a PR to an upstream repository
- After completing a feature branch and wanting a pre-merge quality gate
- When asked to "review and fix the PR", "audit and fix the PR", or "pre-merge review and fix"
- When you want automated iterative fixing instead of manual fix cycles

## Why This Exists

In a real incident, 20+ specialized audit agents checked a 40-file PR and found zero issues.
A single external reviewer then immediately found 3 real bugs -- including a function that
claimed to populate 4 fields but actually populated zero of them. The audit swarm checked
code correctness per-file; the reviewer checked claims against reality.

This pipeline automates the three complementary review perspectives AND the fix cycle:

| Phase | Agent | What it catches | Analogy |
|-------|-------|-----------------|---------|
| 1 | Code Correctness (swarm) | Per-file bugs, type errors, security | Microscope |
| 2 | Claim Verification (single) | PR description lies, missing implementations | Fact-checker |
| 3 | Skeptical Review (single) | UX concerns, cross-file issues, design judgment | Telescope |

After review, a swarm of fixing agents resolves all findings. Then the review runs again to verify the fixes and catch any regressions. This continues until zero issues remain.

---

## Pass Counter Management

Before the first pass, initialize:

```
PASS_NUMBER = 1
MAX_PASSES = 25
```

At the start of EACH pass (including the first), generate a unique run ID:

```
RUN_ID = first 8 characters of uuidgen (lowercase)
# Example: RUN_ID = "a1b2c3d4"
```

The run ID scopes ALL report filenames for this pass invocation, preventing
stale files from prior interrupted runs from contaminating the merge.

After each PROCEDURE 2 completes:

```
PASS_NUMBER = PASS_NUMBER + 1
if PASS_NUMBER > MAX_PASSES:
    STOP -- write escalation report and present to user:
    "Maximum pass limit (25) reached. {N} issues remain unresolved.
     Manual intervention required. See: docs_dev/pr-review-and-fix-escalation-{timestamp}.md"
```

## Report Naming Convention

All reports use **UUID-based filenames** to prevent file overwrites between concurrent agents,
and **agent-prefixed finding IDs** to prevent ID collisions between parallel agents.

| Report | Filename |
|--------|----------|
| Correctness (per-domain) | `docs_dev/amcaa-correctness-P{N}-R{RUN_ID}-{uuid}.md` |
| Claim verification | `docs_dev/amcaa-claims-P{N}-R{RUN_ID}-{uuid}.md` |
| Skeptical review | `docs_dev/amcaa-review-P{N}-R{RUN_ID}-{uuid}.md` |
| Agent manifest | `docs_dev/amcaa-agents-P{N}-R{RUN_ID}.json` |
| Merged intermediate | `docs_dev/pr-review-P{N}-intermediate-{timestamp}.md` |
| Final dedup report | `docs_dev/pr-review-P{N}-{timestamp}.md` |
| Fix checkpoint (per-domain) | `docs_dev/amcaa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` |
| Fix summary (per-domain) | `docs_dev/amcaa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `docs_dev/amcaa-tests-outcome-P{N}.md` |
| Lint outcome | `docs_dev/amcaa-lint-outcome-P{N}.md` |
| Lint summary (JSON) | `docs_dev/megalinter-P{N}/lint-summary.json` |
| Lint fixes | `docs_dev/amcaa-lint-fixes-P{N}.md` |
| Recovery log | `docs_dev/amcaa-recovery-log-P{N}.md` |
| Final clean report | `docs_dev/pr-review-and-fix-FINAL-{timestamp}.md` |
| Escalation (if max reached) | `docs_dev/pr-review-and-fix-escalation-{timestamp}.md` |

### UUID Filename Generation

Each agent generates a UUID at startup and uses it in its output filename:

```bash
UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
REPORT_PATH="docs_dev/amcaa-correctness-P${PASS}-R${RUN_ID}-${UUID}.md"
```

The combination of RUN_ID + UUID provides two levels of isolation:
- **RUN_ID** scopes files to a single pipeline invocation (prevents stale file pollution)
- **UUID** prevents collisions between concurrent agents within the same run

### Agent-Prefixed Finding IDs

**Finding IDs** include the pass number AND a unique agent prefix to avoid collisions:

```
Phase 1 (swarm): Each correctness agent gets a unique prefix A0, A1, A2, ...
  Agent 0: CC-P1-A0-001, CC-P1-A0-002, ...
  Agent 1: CC-P1-A1-001, CC-P1-A1-002, ...
  Agent 2: CC-P1-A2-001, CC-P1-A2-002, ...

Phase 2 (single): CV-P1-001, CV-P1-002, ... (no agent prefix needed)
Phase 3 (single): SR-P1-001, SR-P1-002, ... (no agent prefix needed)
```

The orchestrator assigns prefixes at spawn time using this algorithm:

```
domains = sorted(list of domains with changed files)
for i, domain in enumerate(domains):
    agent_prefix = "A" + hex(i).upper()  # A0, A1, A2, ..., AF, A10, ...
    finding_id_prefix = f"CC-P{PASS_NUMBER}-{agent_prefix}"
```

This guarantees zero ID collisions because:
1. Each agent has a unique prefix (A0, A1, ...) within the pass
2. Each pass has a unique number (P1, P2, ...)
3. UUIDs in filenames prevent file-level collisions

**Before each pass**, run the pre-pass cleanup protocol (see below). Do NOT delete merged reports or fix summaries from previous passes -- they form the audit trail.

The merge script v2 uses pass-specific and run-specific glob patterns, so prior-pass and prior-run files are automatically excluded.

---

## PROCEDURE 1 -- Code Review

### Pre-Pass Cleanup (MANDATORY)

Before spawning ANY agents, run this cleanup to prevent stale file pollution:

```bash
# Archive any leftover phase reports from prior interrupted runs of the SAME pass
mkdir -p docs_dev/archive
for f in docs_dev/amcaa-correctness-P${PASS_NUMBER}-*.md \
         docs_dev/amcaa-claims-P${PASS_NUMBER}-*.md \
         docs_dev/amcaa-review-P${PASS_NUMBER}-*.md \
         docs_dev/amcaa-agents-P${PASS_NUMBER}-*.json \
         docs_dev/amcaa-checkpoint-P${PASS_NUMBER}-*.json; do
  [ -f "$f" ] && mv "$f" docs_dev/archive/
done
# Also archive any stale intermediate reports for this pass
for f in docs_dev/pr-review-P${PASS_NUMBER}-intermediate-*.md; do
  [ -f "$f" ] && mv "$f" docs_dev/archive/
done
```

This ensures a clean slate. Files are archived (not deleted) for audit purposes.

### Agent Manifest

After determining domains and generating RUN_ID, write an agent manifest file:

```
docs_dev/amcaa-agents-P{N}-R{RUN_ID}.json
```

```json
{
  "pass": 7,
  "runId": "a1b2c3d4",
  "launchedAt": "2026-02-22T22:00:00Z",
  "domains": [
    {"name": "api-agents", "prefix": "A0", "files": ["..."], "status": "pending"},
    {"name": "api-other", "prefix": "A1", "files": ["..."], "status": "pending"}
  ],
  "phases": {
    "correctness": {"status": "pending", "agents": []},
    "claims": {"status": "pending"},
    "review": {"status": "pending"}
  }
}
```

This manifest survives context compaction and enables recovery of lost agent task IDs
by checking which expected output files exist on disk.

### Prerequisites

Before starting, gather:
1. The PR number (or branch name)
2. The PR description text
3. The list of changed files grouped by domain

### Phase 1: Code Correctness Swarm

Spawn **one `amcaa-code-correctness-agent` per domain** in parallel.

Group changed files by domain. Examine the project files to identify the domains of the various source files. Examples of domain splits for a common TypeScript app:

| Domain | File patterns |
|--------|--------------|
| shell-scripts | `*.sh`, `install-*.sh`, `update-*.sh` |
| agent-registry | `lib/agent-registry.ts`, `types/agent.ts` |
| messaging | `lib/messageQueue.ts`, `app/api/messages/**` |
| terminal | `hooks/useTerminal.ts`, `components/TerminalView.tsx` |
| ui-components | `components/*.tsx`, `app/page.tsx` |
| api-routes | `app/api/**/*.ts` |
| memory | `lib/consolidate.ts`, `lib/cozo-*.ts` |
| docs | `docs/**`, `README.md` |
| tests | `tests/**` |
| config | `package.json`, `version.json`, `*.config.*` |

**Prefix assignment:**

```
domains = sorted(list of domains with changed files)
for i, domain in enumerate(domains):
    AGENT_PREFIX = "A" + hex(i).upper()    # A0, A1, A2, ..., AF, A10
    FINDING_ID_PREFIX = "CC-P{PASS_NUMBER}-{AGENT_PREFIX}"
    # Each agent also generates its own UUID for the filename
```

**Spawning pattern:**

```
For each domain with changed files (using assigned AGENT_PREFIX):
  Task(
    subagent_type: "amcaa-code-correctness-agent",
    prompt: """
      DOMAIN: {domain_name}
      FILES: {file_list}
      PASS: {PASS_NUMBER}
      RUN_ID: {RUN_ID}
      AGENT_PREFIX: {AGENT_PREFIX}
      FINDING_ID_PREFIX: CC-P{PASS_NUMBER}-{AGENT_PREFIX}

      IMPORTANT — UUID FILENAME:
      Generate a UUID for your output file:
        UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
      Write your report to: docs_dev/amcaa-correctness-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

      Audit these files for code correctness. Read every file completely.
      Use finding IDs starting with {FINDING_ID_PREFIX}-001.
      (e.g., CC-P1-A0-001, CC-P1-A0-002, ...)

      LINE NUMBER VERIFICATION:
      After identifying each finding, re-read the file at the cited line number
      to confirm the code you're referencing is actually at that line. If prior
      fix passes have shifted the code, update your line reference to the ACTUAL
      current location. Never cite stale line numbers.

      REPORTING RULES:
      - Write ALL detailed output to the report file
      - Return to orchestrator ONLY: "[DONE/FAILED] correctness-{domain} - brief result. Report: {path}"
      - Max 2 lines back to orchestrator
    """,
    run_in_background: true
  )
```

**Wait for all Phase 1 agents to complete before proceeding.**

### Phase 2: Claim Verification

Spawn **one `amcaa-claim-verification-agent`** (single instance, not a swarm).

This agent needs:
- The full PR description (get via `gh pr view {number} --json body --jq .body`)
- All commit messages (get via `gh pr view {number} --json commits`)
- Access to the full codebase to verify claims

**Spawning pattern:**

```
Task(
  subagent_type: "amcaa-claim-verification-agent",
  prompt: """
    PR_NUMBER: {pr_number}
    PR_DESCRIPTION: (read from `gh pr view {number} --json body --jq .body`)
    COMMIT_MESSAGES: (read from `gh pr view {number} --json commits`)
    PASS: {PASS_NUMBER}
    RUN_ID: {RUN_ID}
    FINDING_ID_PREFIX: CV-P{PASS_NUMBER}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    Write your report to: docs_dev/amcaa-claims-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

    Extract every factual claim from the PR description and commit messages.
    Verify each claim against the actual code.
    Use finding IDs starting with {FINDING_ID_PREFIX}-001.
    (e.g., CV-P1-001, CV-P1-002, ...)

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] claim-verification - brief result. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true
)
```

**Wait for Phase 2 to complete before proceeding.**

Phase 2 runs AFTER Phase 1 so it can optionally reference correctness findings
to avoid duplicating effort. However, it MUST NOT skip its own verification --
correctness agents check different things than claim verification.

### Phase 3: Skeptical Review

Spawn **one `amcaa-skeptical-reviewer-agent`** (single instance).

This agent needs:
- The full PR diff (get via `gh pr diff {number}`)
- The PR description
- Optionally, the Phase 1 and Phase 2 reports for cross-reference

**Spawning pattern:**

```
Task(
  subagent_type: "amcaa-skeptical-reviewer-agent",
  prompt: """
    PR_NUMBER: {pr_number}
    PR_DESCRIPTION: (provide the text or path)
    DIFF: (save `gh pr diff {number}` to docs_dev/pr-diff.txt and provide path)
    CORRECTNESS_REPORTS: docs_dev/amcaa-correctness-P{PASS_NUMBER}-R{RUN_ID}-*.md
    CLAIMS_REPORT: docs_dev/amcaa-claims-P{PASS_NUMBER}-R{RUN_ID}-*.md
    PASS: {PASS_NUMBER}
    RUN_ID: {RUN_ID}
    FINDING_ID_PREFIX: SR-P{PASS_NUMBER}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    Write your report to: docs_dev/amcaa-review-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

    Review this PR as an external maintainer who has never seen the codebase.
    Read the full diff holistically. Check for UX concerns, breaking changes,
    cross-file consistency, and design judgment issues.
    Use finding IDs starting with {FINDING_ID_PREFIX}-001.
    (e.g., SR-P1-001, SR-P1-002, ...)

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] skeptical-review - Verdict: X, brief result. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true
)
```

### Phase 4: Merge Reports + Deduplicate

After all 3 phases complete, run the **two-stage merge pipeline**:

**Stage 1: Merge (bash script — simple concatenation, no dedup)**

```bash
bash $CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh docs_dev/ ${PASS_NUMBER} ${RUN_ID}
```

This produces an intermediate report at `docs_dev/pr-review-P{N}-intermediate-{timestamp}.md`.
The v2 script:
- When RUN_ID is provided, only collects files matching `amcaa-*-P{N}-R{RUN_ID}-*.md`
- When RUN_ID is omitted, collects all `amcaa-*-P{N}-*.md` files (legacy mode)
- Skips files with `-STALE` in the name
- Skips checkpoint, agent manifest, recovery, lint, fix, and test files
- Sorts by phase (correctness → claims → review)
- Concatenates severity sections WITHOUT deduplication
- Reports raw finding counts
- Verifies merged file integrity (byte-size check)
- Deletes original source files only after successful merge verification
- Always exits 0 (dedup agent determines final verdict)

**Stage 2: Deduplicate (AI agent — semantic analysis)**

```
Task(
  subagent_type: "amcaa-dedup-agent",
  prompt: """
    INTERMEDIATE_REPORT: docs_dev/pr-review-P{PASS_NUMBER}-intermediate-{timestamp}.md
    PASS_NUMBER: {PASS_NUMBER}
    OUTPUT_PATH: docs_dev/pr-review-P{PASS_NUMBER}-{timestamp}.md

    Read the intermediate merged report.
    Deduplicate findings semantically (see agent instructions).
    Produce the final report at OUTPUT_PATH with accurate counts and verdict.

    REPORTING RULES:
    - Write ALL detailed output to the OUTPUT_PATH file
    - Return to orchestrator ONLY: "[DONE/FAILED] dedup - {raw}→{dedup} findings ({removed} removed). Verdict: {VERDICT}. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true
)
```

Wait for the dedup agent to complete. The dedup agent produces:
- Final report: `docs_dev/pr-review-P{N}-{timestamp}.md`
- Verdict: REQUEST CHANGES / APPROVE WITH NITS / APPROVE
- Deduplication log showing which findings were merged and why

### Phase 5: Present Results

Read the **final deduplicated report** (NOT the intermediate) and present a summary to the user:

```
## PR Review Pass {PASS_NUMBER} Complete

**Verdict:** {REQUEST CHANGES / APPROVE WITH NITS / APPROVE}
**Dedup:** {raw_count} raw → {dedup_count} unique ({removed} duplicates removed)
**MUST-FIX:** {count} | **SHOULD-FIX:** {count} | **NIT:** {count}

### Must-Fix Issues:
1. [MF-001] {title} -- {file:line} (Original: CC-P{N}-A0-001, SR-P{N}-002)
2. [MF-002] {title} -- {file:line} (Original: CV-P{N}-003)

### Should-Fix:
1. [SF-001] {title} (Original: CC-P{N}-A1-005)

### Full report: docs_dev/pr-review-P{N}-{timestamp}.md
```

---

## PROCEDURE 2 -- Code Fix

### Agent Selection (Dynamic)

This plugin does NOT hardcode any specific agent types for code fixing. Different users
have different agents installed. Instead, the orchestrator should **dynamically choose
the best available agent** for each fix domain.

**Selection protocol:**

1. Check what agent types are available in the current Claude Code instance
   (the Task tool description lists all available `subagent_type` values).
2. For each domain's fix task, pick the most suitable agent based on its description.
   Prefer agents that mention code fixing, TDD, refactoring, or the domain's language.
3. If no specialized agent matches, use `general-purpose` — it is always available in
   every Claude Code installation and has access to Read, Edit, Write, Bash, Grep, Glob,
   and all other standard tools needed to implement fixes.

**Selection heuristics** (examples — adapt to what's actually available):

| Fix need | Look for agents that mention... | Fallback |
|----------|--------------------------------|----------|
| Code bugs / logic fixes | "TDD", "refactoring", "implementation" | `general-purpose` |
| Lint / format issues | "linting", "formatting", "code fixer" | `general-purpose` |
| Security fixes | "security", "vulnerability" | `general-purpose` |
| Test failures | "test execution", "validation" | `general-purpose` |
| Documentation fixes | "documentation", "lightweight fixes" | `general-purpose` |

**Key rule:** Never assume a specific agent exists. Always verify availability first,
and always fall back to `general-purpose` if the preferred agent is not found.

### Fix Protocol

1. Read the merged review report from PROCEDURE 1: `docs_dev/pr-review-P{PASS_NUMBER}-{timestamp}.md`
2. Build the list of issues to fix, grouped by domain. Extract the checklist from the merged report.
3. For each domain, select the best available agent type (see Agent Selection above). Spawn one fixing agent per domain in parallel. If a domain has more than 5 files to fix, split into groups of max 5 files and spawn separate agents. Group files involved in the same issue together.
4. Give each agent its domain-specific subset of the checklist from the merged report. The agent must track which issues it resolved.
5. Wait for all fixing agents to complete and save their partial reports.
6. Read all fix reports and cross-check against the full checklist from the merged review report. Verify every entry has been addressed.
7. Spawn an agent to run all tests to verify fixes did not break functionality or cause regressions.
8. If tests fail, spawn a fixing agent (best available or `general-purpose`) for each domain involved in the failures to investigate and fix the root cause.
9. Repeat test -> fix cycles until all tests pass.
10. Write fix summary and test results reports.
11. **Linting step (Docker required).** Check if Docker is available: `which docker && docker info >/dev/null 2>&1`. If Docker is NOT available, skip linting with a note: "Docker not available — MegaLinter step skipped." and proceed to commit.
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
    REVIEW_REPORT: docs_dev/pr-review-P{PASS_NUMBER}-{timestamp}.md
    CHECKPOINT_FILE: docs_dev/amcaa-checkpoint-P{PASS_NUMBER}-R{RUN_ID}-{domain_name}.json

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

    Write your fix report to: docs_dev/amcaa-fixes-done-P{PASS_NUMBER}-{domain_name}.md

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
  run_in_background: true
)
```

**Spawning pattern for test agent:**

```
Task(
  subagent_type: "{best_available_test_agent, fallback: 'general-purpose'}",
  prompt: """
    Run the full test suite for the project.
    Determine the test command from package.json, Makefile, or project conventions
    (e.g., `yarn test`, `npm test`, `pytest`, `go test ./...`).
    Write results to: docs_dev/amcaa-tests-outcome-P{PASS_NUMBER}.md

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
  run_in_background: true
)
```

### Linting Step (Docker Required)

This step runs **only if Docker is available** on the host machine. If Docker is not installed
or the Docker daemon is not running, skip this entire section and proceed to "Commit After Fixes".

**Docker availability check:**

```bash
# Returns 0 if Docker is available and daemon is running
which docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
```

If the check fails, log: `"[SKIP] MegaLinter step — Docker not available."` and proceed to commit.

**Linter script location:** `$CLAUDE_PLUGIN_ROOT/scripts/universal_pr_linter.py`

The script uses MegaLinter inside Docker to lint the entire codebase. It runs in `--plugin-mode`
which lints the working directory directly (no temp copy) with APPLY_FIXES=none (read-only —
MegaLinter never modifies your files).

**Spawning pattern for lint agent:**

```
Task(
  subagent_type: "general-purpose",
  prompt: """
    TASK: Run MegaLinter on the project
    PASS: {PASS_NUMBER}

    1. Check Docker availability:
       which docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
       If Docker is NOT available, write "[SKIP] Docker not available" to the report and return immediately.

    2. Run the linter:
       python3 $CLAUDE_PLUGIN_ROOT/scripts/universal_pr_linter.py \
         {PROJECT_ROOT} \
         --plugin-mode \
         --all \
         --report-dir docs_dev/megalinter-P{PASS_NUMBER} \
         --summary-json docs_dev/megalinter-P{PASS_NUMBER}/lint-summary.json \
         --no-pull

       NOTE: On first run, omit --no-pull so Docker pulls the MegaLinter image.
       On subsequent runs within the same pass, use --no-pull to skip the pull.

    3. Read the summary JSON at docs_dev/megalinter-P{PASS_NUMBER}/lint-summary.json
       Key fields:
       - has_errors (bool): true if any linter reported errors
       - error_count (int): number of linters that failed
       - error_linters (string[]): names of failed linters
       - report_dir (string): path to full MegaLinter reports

    4. Write your report to: docs_dev/amcaa-lint-outcome-P{PASS_NUMBER}.md
       Include: exit code, error count, failed linter names, report directory path.

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/SKIP] lint - exit {code}, {N} linter errors. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true
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
    LINT_REPORT: docs_dev/megalinter-P{PASS_NUMBER}/lint-summary.json

    The following linters reported errors: {error_linters_list}

    For each failed linter, read the error log at:
      docs_dev/megalinter-P{PASS_NUMBER}/linters_logs/ERROR-{LINTER_NAME}.log

    Fix ONLY the errors (not warnings). Make minimal changes to resolve lint issues.
    Do NOT refactor, restructure, or add features — only fix what the linter flagged as errors.

    Write your fix report to: docs_dev/amcaa-lint-fixes-P{PASS_NUMBER}.md

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] lint-fix - {M}/{N} linter errors fixed. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true
)
```

**Lint-fix loop:** After the lint fix agent completes, re-run the linter. Repeat until:
- Linter exits with 0 errors → proceed to commit
- 3 consecutive lint-fix attempts fail to reduce the error count → stop and escalate:
  `"MegaLinter errors persist after 3 fix attempts. {N} linter errors remain. Manual intervention required."`

**Important:** The lint-fix loop counts are SEPARATE from the main pass counter. A single pass
can have multiple lint-fix iterations without incrementing the pass number. Only the outer
review-fix loop increments the pass counter.

### Commit After Fixes

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

### Output

- Per-domain fix summaries: `docs_dev/amcaa-fixes-done-P{N}-{domain}.md`
- Test outcome: `docs_dev/amcaa-tests-outcome-P{N}.md`
- Lint outcome: `docs_dev/amcaa-lint-outcome-P{N}.md` (if Docker available)
- Lint summary JSON: `docs_dev/megalinter-P{N}/lint-summary.json` (if Docker available)
- Lint fixes: `docs_dev/amcaa-lint-fixes-P{N}.md` (if lint errors were fixed)

---

## Loop Termination

After PROCEDURE 2 completes and fixes are committed, increment the pass counter and run PROCEDURE 1 again:

```
PASS_NUMBER = PASS_NUMBER + 1

if PASS_NUMBER > MAX_PASSES (25):
    STOP. Write escalation report:
    "Maximum pass limit reached. {remaining_count} issues persist after {MAX_PASSES} passes.
     Review: docs_dev/pr-review-P{last_pass}-{timestamp}.md
     Manual intervention required."
    Present to user and exit.

Run PROCEDURE 1 with new PASS_NUMBER.

if PROCEDURE 1 finds ZERO issues (all severities -- MUST-FIX, SHOULD-FIX, NIT):
    Write final report: docs_dev/pr-review-and-fix-FINAL-{timestamp}.md
    Present final summary to user and exit.
else:
    Run PROCEDURE 2 with the new findings.
    Loop back to increment PASS_NUMBER.
```

### Final Report Format

When the loop terminates with zero issues:

```
## PR Review And Fix -- Final Report

**Total passes:** {PASS_NUMBER}
**Final verdict:** APPROVE -- zero issues remaining

### Pass History

| Pass | Issues Found | Issues Fixed | Tests | Lint |
|------|-------------|-------------|-------|------|
| 1    | {count}     | {count}     | {passed}/{total} | {clean/N errors/skipped} |
| 2    | {count}     | {count}     | {passed}/{total} | {clean/N errors/skipped} |
| ...  | ...         | ...         | ...   | ...  |
| {N}  | 0           | --          | {passed}/{total} | {clean/skipped} |

### Reports Generated
- Pass 1 review: docs_dev/pr-review-P1-{timestamp}.md
- Pass 1 fixes: docs_dev/amcaa-fixes-done-P1-{domain}.md
- ...
- Final clean review: docs_dev/pr-review-P{N}-{timestamp}.md

### All Fixes Applied
1. [CC-P1-001] {title} -- {file} (Pass 1)
2. [SR-P1-003] {title} -- {file} (Pass 1)
3. [CC-P2-001] {title} -- {file} (Pass 2)
...
```

---

## CRITICAL RULES

1. **NEVER skip Phase 2 and 3.** The correctness swarm alone is insufficient. It will miss
   claimed-but-not-implemented features, cross-file inconsistencies, and UX concerns.
   Phase 2 and 3 are what make this pipeline catch 100% of issues.

2. **Phase order matters.** Phase 1 (parallel) -> Phase 2 (sequential) -> Phase 3 (sequential).
   Later phases can reference earlier reports to avoid duplicate work, but they must NOT
   skip their own checks.

3. **Each agent writes to a UUID-named file.** Agents return only 1-2 lines to the orchestrator.
   Full findings go in the report files. This prevents context flooding AND file collisions.

4. **Two-stage merge: script + AI agent.** The bash merge script (v2) does simple concatenation.
   The `amcaa-dedup-agent` does semantic deduplication. NEVER rely on the merge script alone
   for dedup — it deliberately does NOT deduplicate.

5. **Dedup agent determines the verdict.** The merge script always exits 0. The dedup agent's
   final report contains the accurate counts and verdict.

6. **Fix ALL severities, not just MUST-FIX.** The loop terminates only when zero issues
   remain -- including SHOULD-FIX and NIT. This ensures a clean codebase.

7. **Commit after each fix pass.** This creates rollback points and ensures clean diffs
   for subsequent review passes.

8. **Maximum 25 passes.** If issues persist after 25 passes, stop and escalate to the user.
   Infinite loops waste resources and indicate a deeper architectural problem.

9. **Agent-prefixed finding IDs.** Phase 1 agents MUST use unique prefixes:
   `CC-P{N}-A{hex_index}-{NNN}` (e.g., `CC-P1-A0-001`, `CC-P1-A1-001`).
   Phase 2/3 single agents use `CV-P{N}-{NNN}` and `SR-P{N}-{NNN}`.
   This eliminates ID collisions between parallel correctness agents.

10. **UUID-based report filenames.** All agent output files MUST include a UUID:
    `amcaa-{phase}-P{N}-{uuid}.md`. This prevents file overwrites between concurrent agents.

11. **Same line, different bugs = KEEP BOTH.** The dedup agent must never merge findings
    that describe different issues at the same code location. Two bugs at line 42 are
    two bugs, not one.

12. **Merge script verifies before deleting.** The v2 merge script deletes source files
    only after verifying the intermediate file's byte size equals the sum of inputs.
    This prevents data loss from partial writes or filesystem errors.

13. **Linting is conditional on Docker.** The MegaLinter step runs ONLY if Docker is installed
    and the daemon is running. If Docker is unavailable, skip linting entirely and proceed to
    commit. Never fail a pass because Docker is missing — linting is an enhancement, not a gate.

14. **Lint-fix loop is separate from the pass counter.** Within a single pass, the lint→fix
    cycle can iterate up to 3 times. These iterations do NOT increment the main pass number.
    Only the outer review→fix loop increments the pass counter.

---

## Error Handling

- If any Phase 1 agent fails, re-run it for that domain only (with a new UUID)
- If Phase 2 or 3 fails, re-run that phase (they are single agents, new UUID)
- If the merge script (v2) exits with code 2, there's a fatal error — investigate
- If the dedup agent reports MUST-FIX > 0, proceed to PROCEDURE 2
- If the dedup agent fails, re-run it with the same intermediate report
- If `gh` CLI is not authenticated, stop and ask the user to run `gh auth login`
- If a fix agent fails, re-run for that domain only
- If tests fail after fixes, spawn domain-specific agents to investigate and fix
- If max passes reached, write escalation report and stop
- If merge byte-size verification fails, do NOT delete source files — investigate
- If Docker is not available, skip MegaLinter entirely — log "[SKIP]" and proceed to commit
- If the MegaLinter Docker image pull fails, skip linting for this pass (don't block the pipeline)
- If the linter script crashes (Python error, not lint errors), log the error and skip linting
- If lint-fix loop exhausts 3 attempts without reducing error count, stop the lint loop and escalate to user — proceed to commit with lint errors noted in the pass report

---

## Agent Recovery Protocol

This protocol applies to ALL agents spawned by the orchestrator: correctness swarm, claim verification,
skeptical review, dedup, fix agents, and test runner. When an agent is lost for any reason, the
orchestrator MUST follow these steps to ensure the task is completed and no corrupt artifacts remain.

### Failure Modes & Detection

| Failure Mode | Detection Signal |
|---|---|
| **Crash / OOM** | Task tool returns error, empty result, or agent process dies mid-execution |
| **Out of tokens** | Agent returns truncated output, `[MAX TURNS]`, or incomplete report file |
| **API errors** | Agent returns "overloaded", rate limit (429), server error (500), or auth failure |
| **Connection errors** | Task tool hangs then returns timeout or network error |
| **Timeout** | Agent does not return within deadline (review agents: 10 min, fix agents: 15 min, test runner: 20 min) |
| **Lost during compaction** | Orchestrator's context was summarized; agent task ID no longer in memory and no result was ever received |
| **Broken reference** | TaskOutput returns "agent not found" or "invalid task ID" |
| **ID collision** | Two agents wrote to overlapping filenames (prevented by UUID filenames — verify if suspected) |
| **Version collision** | Agent used stale plugin/agent definition cached from a prior session; writes wrong format or wrong pass prefix |

### Step 1: Detect the Loss

The orchestrator MUST mentally track every spawned agent with these fields:

```
taskId:        string    // Task tool's returned ID
agentType:     string    // "correctness" | "claims" | "skeptical" | "dedup" | "fix" | "test"
domain:        string    // Domain label (e.g., "governance-core") or "N/A" for single agents
outputPath:    string    // Expected report file path (with UUID)
findingPrefix: string    // e.g., "CC-P3-A2" — for re-spawn consistency
launchedAt:    timestamp // When the agent was spawned
status:        string    // "running" | "done" | "failed" | "lost"
```

An agent is **LOST** if ANY of these are true:

- Task tool returned an error, empty string, or exception
- Agent returned a result but its expected output file does not exist
- Agent returned but its output file is incomplete (see Step 2)
- Agent's task ID cannot be resolved (TaskOutput returns error)
- Agent has been running longer than its deadline without returning
- Context compaction occurred and the agent's task ID is no longer in the orchestrator's working memory

### Step 2: Verify the Loss

Before cleanup, verify that the agent truly failed (not just slow or communication-disrupted):

1. **Check if output file exists** at the expected `outputPath`
2. **If file exists, check completeness:**
   - File size > 0 bytes
   - File contains the `## Self-Verification` section (the agent's checklist)
   - File does not end mid-sentence or with an unclosed code block
   - File has valid markdown structure matching the agent's output format
3. **If file is COMPLETE** → the agent finished its work despite the communication failure.
   Mark as "done" and use the file. No re-spawn needed.
4. **If file is INCOMPLETE or MISSING** → the agent truly failed. Proceed to Step 3.

### Step 3: Clean Up Partial Artifacts

Delete ONLY the lost agent's artifacts. NEVER touch files from other agents or other passes.

```bash
# Identify the lost agent's output file by its UUID
LOST_FILE="docs_dev/amcaa-correctness-P3-a1b2c3d4.md"

# Verify it belongs to the lost agent (filename contains the UUID assigned to that agent)
# Then delete the partial file
rm -f "$LOST_FILE"
```

**Cleanup rules:**

- Delete partial report files (missing Self-Verification section at the end)
- Delete zero-byte files created by the lost agent
- Delete files with incomplete markdown (unclosed code blocks, truncated mid-sentence)
- **NEVER** delete files from a different agent (different UUID in filename)
- **NEVER** delete files from a different pass (different `P{N}` prefix)
- **NEVER** delete the intermediate merge report or final report from a completed phase
- If unsure whether a file belongs to the lost agent, **leave it** — the merge script and dedup agent handle extras gracefully

**Fix agent special case — uncommitted source changes:**

If a fix agent crashed AFTER editing source files but BEFORE the orchestrator committed:

1. Run `git diff` to see what the lost agent changed
2. Run `git stash` to save the partial changes safely
3. Re-spawn the fix agent from scratch (Step 4) — it will re-read the original files and apply its own fixes
4. After the replacement fix agent succeeds and the orchestrator commits, drop the stash: `git stash drop`
5. **NEVER** commit partial fix agent changes — they may be incomplete and introduce bugs

### Step 4: Re-Spawn the Task

Create a NEW agent with a NEW UUID for the exact same task:

1. **Generate a new UUID** for the replacement agent's output filename
2. **Copy the original prompt EXACTLY** — same domain, same files, same finding ID prefix, same pass number
3. **Update only the output path** to use the new UUID
4. **Spawn the replacement agent**

**Re-spawn rules:**

- Always use a **NEW UUID** (prevents filename collision with the deleted partial file)
- Use the **SAME finding ID prefix** (ensures finding ID continuity for the domain)
- Use the **SAME pass number** (the replacement is part of the same pass, not a new pass)
- If the same task fails **3 consecutive times**, **STOP** and escalate to the user:
  ```
  "Agent {type} for domain {domain} failed 3 times.
   Last error: {error_summary}.
   Manual intervention required."
  ```
- Between retries, wait **30 seconds** (API rate limit cooldown, transient error recovery)
- For fix agents: verify `git status` is clean before re-spawning (Step 3 cleanup must be complete)

### Step 5: Record the Failure

Append an entry to the recovery log in the pass audit trail (either in the merged report or
a separate `docs_dev/amcaa-recovery-log-P{N}.md` file):

```markdown
### Agent Recovery Log

| Time | Agent Type | Domain | Failure Mode | Lost File | Action Taken |
|------|-----------|--------|-------------|-----------|-------------|
| 14:23 | correctness | governance-core | timeout (12 min) | P3-a1b2c3d4.md (0 bytes, deleted) | Re-spawned → P3-e5f6g7h8.md |
| 14:25 | fix | api-routes | API 429 | P3-i9j0k1l2.md (partial, deleted) | 30s cooldown → re-spawned |
| 14:40 | test | N/A | OOM | P3-m3n4o5p6.md (missing) | Re-spawned |
```

### Special Cases

**Lost during context compaction:**

The orchestrator's context was summarized and one or more agent task IDs were lost.

1. Read the agent manifest file: `docs_dev/amcaa-agents-P{N}-R{RUN_ID}.json`
   - This file records all spawned agents, their domains, prefixes, and expected outputs
   - It survives context compaction because it's on disk
2. For each agent in the manifest, check if its output file exists and is complete
   - File exists and has `## Self-Verification` section → agent completed successfully
   - File exists but incomplete → agent died mid-execution (Step 3 cleanup)
   - File missing → agent never wrote output (re-spawn needed)
3. If the manifest file itself was lost (extreme case), fall back to glob-based recovery:
   - List ALL `amcaa-*-P{N}-R{RUN_ID}-*.md` files in `docs_dev/`
   - Read first 5 lines of each to identify domain from the report header
   - Cross-reference with the expected domain list
4. For each truly missing report: re-spawn from scratch (Step 4)
5. For fix agents: check `git log` for the most recent fix commit — if fixes were already committed, the fix agent completed successfully even though its task ID was lost
6. For fix agents: also check checkpoint file `docs_dev/amcaa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` to see which findings were already resolved

**Agent wrote report with wrong pass number (version/cache collision):**

If an agent writes a report with `P2` instead of `P3` (stale prompt from a cached agent definition):

1. The merge script's glob `amcaa-*-P{N}*.md` will correctly EXCLUDE it (it won't match the current pass)
2. Check if the content is actually from the current pass (correct files audited, correct finding prefixes)
3. If content is correct but filename is wrong: rename the file to the correct pass prefix
4. If content is from a genuinely different pass: delete it and re-spawn

**Multiple correctness agents for the same domain (domain label collision):**

UUID filenames prevent file-level collision. But if two agents were accidentally given the same domain:

1. Both will produce separate UUID-named files — no file collision occurs
2. The merge script will concatenate BOTH files into the intermediate report
3. The dedup agent will handle any duplicate findings between them
4. Note the duplication in the recovery log, but no data loss occurs

**Test runner left no report but tests actually ran:**

If the test runner crashed after running tests but before writing its report:

1. Check the test command's exit code from the shell (if available in bash history)
2. Check for test runner output in stdout/stderr (the Task tool may have captured partial output)
3. Check for test framework artifacts (e.g., `junit.xml`, `.vitest-result.json`, coverage reports)
4. If evidence shows tests passed: note this in the audit trail and proceed
5. If unclear: re-run the test suite (tests are read-only and idempotent — safe to re-run)

---

## Resources

- Merge script v2: `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh`
- Merge script v1 (legacy): `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports.sh`
- Dedup agent: `$CLAUDE_PLUGIN_ROOT/agents/amcaa-dedup-agent.md`
- Other agents: `$CLAUDE_PLUGIN_ROOT/agents/`
- Report output directory: `docs_dev/`

## Instructions

Follow the iterative review-fix protocol strictly:

1. Initialize `PASS_NUMBER = 1`, `MAX_PASSES = 25`.
2. Run **PROCEDURE 1** (Phases 1-5): spawn correctness swarm, claim verification, skeptical review, merge reports, present results.
3. If zero issues found -> write final report and exit.
4. If `PASS_NUMBER >= MAX_PASSES` -> write escalation report and exit.
5. Run **PROCEDURE 2**: spawn fix agents per domain, run tests, fix regressions, lint (if Docker available), fix lint errors, commit.
6. Increment `PASS_NUMBER`, go to step 2.

Each step's details are documented in the PROCEDURE 1 and PROCEDURE 2 sections above.

## Examples

```
# Full review-and-fix pipeline on PR 206
User: "review and fix PR 206"
-> Pass 1: Review finds 8 issues (3 MUST-FIX, 4 SHOULD-FIX, 1 NIT)
-> Pass 1: Fix agents resolve all 8 issues, tests pass, commit
-> Pass 2: Review finds 2 new issues (regressions from fixes)
-> Pass 2: Fix agents resolve 2 issues, tests pass, commit
-> Pass 3: Review finds 0 issues
-> Final report presented: "APPROVE -- zero issues after 3 passes"
```

## Lessons Learned (Baked Into This Pipeline)

1. **Swarms are microscopes.** Great at per-file correctness. Blind to the big picture.
2. **PR descriptions lie.** Not maliciously -- authors believe they implemented what they described.
   The gap between intent and implementation is the #1 source of missed bugs.
3. **Absence is the hardest bug to find.** A missing field assignment produces no error, no warning,
   no test failure. The code compiles and runs fine. Only a claim verifier or skeptical reviewer
   will notice that `fromLabel` is declared in the type but never set in the return statement.
4. **Cross-file consistency requires holistic view.** Version "0.22.5" in JSON-LD but "0.22.4"
   in prose HTML -- each file is internally valid, but together they're inconsistent.
5. **UX judgment is not a code concern.** Auto-copying clipboard on text selection is technically
   correct code. Whether it's a good idea requires a different kind of thinking.
6. **The stranger's perspective is irreplaceable.** Twenty agents who know the codebase missed
   what one agent pretending to be a stranger caught immediately. Fresh eyes see what familiarity
   blinds you to.
7. **Fixes introduce regressions.** A single fix pass is never enough. The review-fix loop
   catches regressions that manual fix-and-ship workflows miss.
8. **Commit between passes.** Without commits, the diff for subsequent review passes includes
   both the original changes AND the fixes, confusing the reviewers. Clean commits let each
   review pass focus on what changed since the last fix.
9. **Linting catches what reviewers and tests miss.** AI reviewers focus on logic and design;
   tests verify behavior. Neither catches style violations, unused imports, type annotation gaps,
   or language-specific anti-patterns that static analysis tools flag. MegaLinter covers 50+
   linters across all languages in a single Docker run — a cheap safety net that's worth the
   Docker dependency when available.
10. **Stale files poison the pipeline.** When a pass is interrupted and restarted, leftover
    report files from the prior run get merged into the new run's intermediate report. This
    inflates finding counts, adds duplicate/contradictory findings, and wastes dedup agent
    tokens. Run ID isolation and pre-pass cleanup are defense-in-depth against this.
11. **Agent rate limits are inevitable.** Fix agents can die mid-execution when API rate limits
    hit. Without checkpoints, the orchestrator must manually verify which fixes were applied
    and which weren't. Checkpoint files make recovery automatic.
12. **Line numbers drift across passes.** After multiple fix passes, line numbers in the codebase
    shift. Review agents must verify their cited line numbers against the actual current file
    content, not rely on stale mental models from prior reads.
13. **Task IDs are ephemeral.** When the orchestrator's context is compacted, background agent
    task IDs are lost. An on-disk agent manifest file survives compaction and enables recovery
    without the fragile glob+read-first-5-lines pattern.
