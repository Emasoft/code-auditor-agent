---
name: caa-pr-review-and-fix-skill
description: >
  Use when reviewing and fixing PRs with automated iterative resolution.
  Trigger with "review and fix the PR", "audit and fix the PR", "pre-merge review and fix".
version: 3.1.14
author: Emasoft
license: MIT
tags:
  - caa-pr-review
  - code-audit
  - claim-verification
  - quality-gate
  - auto-fix
---

# PR Review And Fix

## Overview

Iterative review-and-fix pipeline that combines two procedures in a loop until zero issues remain:

1. **PROCEDURE 1 -- Code Review**: Six-phase PR review pipeline (correctness swarm -> claim verification -> skeptical review -> security review -> merge + dedup -> present results) that produces a merged findings report.
2. **PROCEDURE 2 -- Code Fix**: Swarm of fixing agents (dynamically selected from available agents) that resolve all findings from PROCEDURE 1, then run tests to verify no regressions.

The loop runs until PROCEDURE 1 finds zero issues, or the maximum pass limit (25) is reached.

```
+---------------------------------------------------+
|  PASS N (N starts at 1, max 25)                   |
|                                                   |
|  1. PROCEDURE 1 -- Review                         |
|     Phase 1: Code Correctness Swarm (parallel)    |
|     Phase 2: Claim Verification (sequential)      |
|     Phase 3+4: Skeptical + Security (parallel)    |
|     Phase 5: Merge Reports                        |
|     Phase 6: Present Results                      |
|                                                   |
|  2. If zero issues -> DONE (write final report)   |
|     If N > 25   -> STOP (escalate to user)         |
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
- The merge script at `${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-reports.py` must exist
- ${CLAUDE_PLUGIN_ROOT} must be set by the Claude Code plugin loader. Verify it is non-empty before running any scripts.
- If `USE_WORKTREES=true`: Git working tree must be clean (no uncommitted changes). Run `git status` to verify.

## Parameters

| Param | Req | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `PR_NUMBER` | Y | string | -- | GitHub PR number or branch name |
| `MAX_PASSES` | N | int | `25` | Maximum review-fix loop iterations |
| `REPORT_DIR` | N | path | `docs_dev/` | Output directory for all reports |
| `MERGE_SCRIPT` | N | path | `${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-reports.py` | Path to merge script |
| `USE_WORKTREES` | N | bool | false | Run agent swarms in isolated git worktrees. Prevents concurrent file conflicts and gives each agent a clean snapshot. |

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

This pipeline automates the four complementary review perspectives AND the fix cycle:

| Phase | Agent | What it catches | Analogy |
|-------|-------|-----------------|---------|
| 1 | Code Correctness (swarm) | Per-file bugs, type errors, logic errors | Microscope |
| 2 | Claim Verification (single) | PR description lies, missing implementations | Fact-checker |
| 3 | Skeptical Review (single) | UX concerns, cross-file issues, design judgment | Telescope |
| 4 | Security Review (`caa-security-review-agent`) | Vulnerabilities, secrets, injection flaws, auth issues | Scanner |

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
RUN_ID = first 8 hex characters from python3 -c "import uuid; print(uuid.uuid4().hex[:8])"
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
     Manual intervention required. See: docs_dev/caa-pr-review-and-fix-escalation-{timestamp}.md"
```

## Report Naming Convention

All reports use **UUID-based filenames** to prevent file overwrites between concurrent agents,
and **agent-prefixed finding IDs** to prevent ID collisions between parallel agents.

| Report | Filename |
|--------|----------|
| Correctness (per-domain) | `docs_dev/caa-correctness-P{N}-R{RUN_ID}-{uuid}.md` |
| Claim verification | `docs_dev/caa-claims-P{N}-R{RUN_ID}-{uuid}.md` |
| Security review | `docs_dev/caa-security-P{N}-R{RUN_ID}-{uuid}.md` |
| Skeptical review | `docs_dev/caa-review-P{N}-R{RUN_ID}-{uuid}.md` |
| Agent manifest | `docs_dev/caa-agents-P{N}-R{RUN_ID}.json` |
| Merged intermediate | `docs_dev/caa-pr-review-P{N}-intermediate-{timestamp}.md` |
| Final dedup report | `docs_dev/caa-pr-review-P{N}-{timestamp}.md` |
| Fix checkpoint (per-domain) | `docs_dev/caa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` |
| Fix summary (per-domain) | `docs_dev/caa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `docs_dev/caa-tests-outcome-P{N}.md` |
| Lint outcome | `docs_dev/caa-lint-outcome-P{N}.md` |
| Lint summary (JSON) | `docs_dev/megalinter-P{N}/lint-summary.json` |
| Lint fixes | `docs_dev/caa-lint-fixes-P{N}.md` |
| Recovery log | `docs_dev/caa-recovery-log-P{N}.md` |
| Final clean report | `docs_dev/caa-pr-review-and-fix-FINAL-{timestamp}.md` |
| Escalation (if max reached) | `docs_dev/caa-pr-review-and-fix-escalation-{timestamp}.md` |

### UUID Filename Generation

Each agent generates a UUID at startup and uses it in its output filename:

```bash
UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
REPORT_PATH="docs_dev/caa-correctness-P${PASS}-R${RUN_ID}-${UUID}.md"
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
Phase 4 (single): SC-P1-001, SC-P1-002, ... (no agent prefix needed)
```

The orchestrator assigns prefixes at spawn time using this algorithm:

```
domains = sorted(list of domains with changed files)
for i, domain in enumerate(domains):
    agent_prefix = f"A{i:X}"  # A0, A1, A2, ..., AF, A10, ...
    finding_id_prefix = f"CC-P{PASS_NUMBER}-{agent_prefix}"
```

This guarantees zero ID collisions because:
1. Each agent has a unique prefix (A0, A1, ...) within the pass
2. Each pass has a unique number (P1, P2, ...)
3. UUIDs in filenames prevent file-level collisions

**Before each pass**, run the pre-pass cleanup protocol (see Procedure 1 reference). Do NOT delete merged reports or fix summaries from previous passes -- they form the audit trail.

The merge script v2 uses pass-specific and run-specific glob patterns, so prior-pass and prior-run files are automatically excluded.

---

## Worktree Mode

When `USE_WORKTREES=true`, agents run in isolated git worktrees via `isolation: "worktree"` in the Agent tool. This is useful for large PRs with many domains where concurrent agents might otherwise see each other's in-progress changes.

### How It Works

1. **Before spawning**, resolve `ABSOLUTE_REPORT_DIR = $(pwd)/docs_dev/` (or `$(pwd)/{REPORT_DIR}` if custom). All agents write reports to this absolute path so reports are accessible from the main worktree after agent completion.

2. **Review agents** (Phase 1-4, dedup): Each gets a clean, isolated snapshot of the repo. They read code from their worktree but write reports to the main `REPORT_DIR`. Since they make no code changes, worktrees are auto-cleaned after completion.

3. **Fix agents** (Procedure 2): Each gets an isolated worktree on a separate branch. They modify code in their worktree and write reports to the main `REPORT_DIR`. After ALL fix agents complete, the orchestrator merges their branches back to the current branch sequentially:
   ```
   for each completed fix agent worktree:
     git merge --no-edit {worktree_branch}
     # If merge conflict: resolve manually or escalate to user
   ```

4. **Spawning pattern addition**: When USE_WORKTREES is true, add `isolation: "worktree"` to every Task() call. The agent prompt must include `REPORT_DIR: {ABSOLUTE_REPORT_DIR}` so the agent writes reports outside its worktree. See `procedure-1-review.md` and `procedure-2-fix.md` in the references directory for the complete spawning patterns with worktree support.

### Prerequisites for Worktree Mode

- Git repository must be in a clean state (no uncommitted changes)
- Sufficient disk space for N worktree copies (one per concurrent agent)
- The `REPORT_DIR` must be an absolute path accessible from all worktrees

### When NOT to Use Worktrees

- Small PRs with 1-3 domains (overhead outweighs benefit)
- When disk space is limited
- When agents don't modify code (review-only mode with `caa-pr-review-skill`)

---

## PROCEDURE 1 -- Code Review

Six-phase review pipeline: correctness swarm, claim verification, skeptical review, security review, then merge + dedup, then present results.

See [Procedure 1: Code Review](references/procedure-1-review.md) for full protocol.

**Contents:**
- How to clean up stale artifacts before starting a new pass
- How to build the agent manifest for parallel spawning
- How to spawn the correctness swarm across file domains
- How to verify claims against actual implementation
- How to run the security review (`caa-security-review-agent`)
- How to run the skeptical external review
- How to merge reports and deduplicate findings
- How to present the review verdict to the user

### Review Checklist

Copy this checklist and track your progress:

- [ ] PR diff obtained and domain classification done
- [ ] Agent manifest written to disk
- [ ] Pre-pass cleanup completed (stale files archived)
- [ ] Phase 1: All correctness agents spawned and completed
- [ ] Phase 2: Claim verification agent completed
- [ ] Phase 3: Skeptical reviewer completed
- [ ] Phase 4: Security review agent (`caa-security-review-agent`) completed
- [ ] Phase 5: Merge script + dedup agent completed
- [ ] Phase 6: Final report presented to user

---

## PROCEDURE 2 -- Code Fix

Dynamic agent swarm that resolves all findings, runs tests, lints, and commits.

See [Procedure 2: Code Fix](references/procedure-2-fix.md) for full protocol.

**Reference file sections (procedure-2-fix.md):**
- [Agent Selection (Dynamic)](references/procedure-2-fix.md#agent-selection-dynamic) -- How to select and assign fix agents dynamically
- [Fix Protocol](references/procedure-2-fix.md#fix-protocol) -- How to implement fixes with the 15-step protocol
- [Linting Step (Docker Required)](references/procedure-2-fix.md#linting-step-docker-required) -- How to run MegaLinter and handle lint errors
- [Commit After Fixes](references/procedure-2-fix.md#commit-after-fixes) -- How to commit verified fixes
- [Procedure 2 Output](references/procedure-2-fix.md#procedure-2-output) -- What Procedure 2 produces
- [Procedure 2 Checklist](references/procedure-2-fix.md#procedure-2-checklist) -- Completion checklist for the fix cycle

### Fix Checklist

Copy this checklist and track your progress:

- [ ] Merged review report read and issues grouped by domain
- [ ] Best available agent type selected for each domain
- [ ] Fix agents spawned and all completed
- [ ] Cross-check: every issue addressed (FIXED or NOT FIXED)
- [ ] Tests executed and all passing
- [ ] Docker availability checked for linting
- [ ] If Docker available: MegaLinter executed and clean (or lint-fix cycles done)
- [ ] All fixes committed with descriptive commit message

---

## Loop Termination

After PROCEDURE 2 completes and fixes are committed, increment the pass counter and run PROCEDURE 1 again:

```
PASS_NUMBER = PASS_NUMBER + 1

if PASS_NUMBER > MAX_PASSES (25):
    STOP. Write escalation report:
    "Maximum pass limit reached. {remaining_count} issues persist after {MAX_PASSES} passes.
     Review: docs_dev/caa-pr-review-P{last_pass}-{timestamp}.md
     Manual intervention required."
    Present to user and exit.

Run PROCEDURE 1 with new PASS_NUMBER.

if PROCEDURE 1 finds ZERO issues (all severities -- MUST-FIX, SHOULD-FIX, NIT):
    Write final report: docs_dev/caa-pr-review-and-fix-FINAL-{timestamp}.md
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
- Pass 1 review: docs_dev/caa-pr-review-P1-{timestamp}.md
- Pass 1 fixes: docs_dev/caa-fixes-done-P1-{domain}.md
- ...
- Final clean review: docs_dev/caa-pr-review-P{N}-{timestamp}.md

### All Fixes Applied
1. [CC-P1-001] {title} -- {file} (Pass 1)
2. [SR-P1-003] {title} -- {file} (Pass 1)
3. [CC-P2-001] {title} -- {file} (Pass 2)
...
```

---

## Instructions

Follow the iterative review-fix protocol strictly:

1. Initialize `PASS_NUMBER = 1`, `MAX_PASSES = 25`.
2. Run **PROCEDURE 1** (Phases 1-6): spawn correctness swarm, claim verification, skeptical review, security review (`caa-security-review-agent`), merge reports, present results.
3. If zero issues found -> write final report and exit.
4. If `PASS_NUMBER > MAX_PASSES` -> write escalation report and exit.
5. Run **PROCEDURE 2**: spawn fix agents per domain, run tests, fix regressions, lint (if Docker available), fix lint errors, commit.
6. Increment `PASS_NUMBER`, go to step 2.

Each step's details are documented in the reference files for PROCEDURE 1 and PROCEDURE 2.

---

## Output

The pipeline produces these deliverables across all passes:

| Deliverable | Location | When |
|-------------|----------|------|
| Per-pass review report (deduplicated) | `docs_dev/caa-pr-review-P{N}-{timestamp}.md` | After each Procedure 1 |
| Per-domain fix summaries | `docs_dev/caa-fixes-done-P{N}-{domain}.md` | After each Procedure 2 |
| Test outcome per pass | `docs_dev/caa-tests-outcome-P{N}.md` | After each test run |
| Lint outcome per pass | `docs_dev/caa-lint-outcome-P{N}.md` | After each lint run (Docker only) |
| Lint summary JSON | `docs_dev/megalinter-P{N}/lint-summary.json` | After each lint run (Docker only) |
| Recovery log | `docs_dev/caa-recovery-log-P{N}.md` | When agent failures occur |
| Final report (zero issues) | `docs_dev/caa-pr-review-and-fix-FINAL-{timestamp}.md` | Pipeline completion |
| Escalation report (max passes) | `docs_dev/caa-pr-review-and-fix-escalation-{timestamp}.md` | If limit reached |

**Key outputs for the user:**
- **Final report** summarizes all passes, all fixes applied, and final verdict (APPROVE)
- **Escalation report** lists remaining unresolved issues if the pass limit was reached
- **Per-pass review reports** provide the detailed audit trail of findings and resolutions

---

## Model Selection Rules

- **Opus/Sonnet ONLY** for all code analysis, review, fix, reasoning, and audit tasks
- **Haiku PROHIBITED** for code analysis and code fixing — it hallucinates on complex code and causes error loops
- Haiku is acceptable ONLY for: running shell commands, file moves, formatting, and simple maintenance
- When spawning subagents for code review or code fix: always specify `model: opus` or `model: sonnet`

## CRITICAL RULES

1. **NEVER skip Phases 2, 3, or 4.** The correctness swarm alone is insufficient. It will miss
   claimed-but-not-implemented features, security vulnerabilities, cross-file inconsistencies,
   and UX concerns. Phases 2, 3, and 4 are what make this pipeline catch 100% of issues.

2. **Phase order matters.** Phase 1 (parallel) -> Phase 2 (sequential) -> Phase 3 and Phase 4 (run in parallel with each other, both sequential internally).
   Later phases can reference earlier reports to avoid duplicate work, but they must NOT
   skip their own checks.

3. **Each agent writes to a UUID-named file.** Agents return only 1-2 lines to the orchestrator.
   Full findings go in the report files. This prevents context flooding AND file collisions.

4. **Two-stage merge: script + AI agent.** The Python merge script (v2) does simple concatenation.
   The `caa-dedup-agent` does semantic deduplication. NEVER rely on the merge script alone
   for dedup -- it deliberately does NOT deduplicate.

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
   Phase 2/3/4 single agents use `CV-P{N}-{NNN}`, `SR-P{N}-{NNN}`, and `SC-P{N}-{NNN}`.
   This eliminates ID collisions between parallel correctness agents.

10. **UUID-based report filenames.** All agent output files MUST include a UUID:
    `caa-{phase}-P{N}-{uuid}.md`. This prevents file overwrites between concurrent agents.

11. **Same line, different bugs = KEEP BOTH.** The dedup agent must never merge findings
    that describe different issues at the same code location. Two bugs at line 42 are
    two bugs, not one.

12. **Merge script verifies before deleting.** The v2 merge script deletes source files
    only after verifying the intermediate file exists and is non-empty. (The merged
    output extracts only severity-section content, so byte-size comparison is not used.)
    This prevents data loss from partial writes or filesystem errors.

13. **Linting is conditional on Docker.** The MegaLinter step runs ONLY if Docker is installed
    and the daemon is running. If Docker is unavailable, skip linting entirely and proceed to
    commit. Never fail a pass because Docker is missing -- linting is an enhancement, not a gate.

14. **Lint-fix loop is separate from the pass counter.** Within a single pass, the lint->fix
    cycle can iterate up to 3 times. These iterations do NOT increment the main pass number.
    Only the outer review->fix loop increments the pass counter.

---

## Error Handling

- If any Phase 1 agent fails, re-run it for that domain only (with a new UUID)
- If Phase 2, 3, or 4 fails, re-run that phase (single agents, new UUID)
- If merge script exits code 2 (missing reports, invalid dir, or empty merged file), investigate (source files are preserved)
- If dedup agent reports MUST-FIX > 0, proceed to PROCEDURE 2; if dedup fails, re-run on same intermediate
- If `gh` CLI not authenticated, stop and ask user to run `gh auth login`
- If fix agent fails, re-run for that domain; if tests fail, spawn domain agents to investigate
- If max passes reached, write escalation report and stop
- Docker/lint failures: skip MegaLinter and proceed to commit (linting is enhancement, not gate). If lint-fix loop exhausts 3 attempts, escalate to user

---

## Agent Recovery Protocol

Protocol for recovering from agent crashes, timeouts, API errors, and context compaction losses.

See [Agent Recovery Protocol](references/agent-recovery.md) for full protocol.

**Reference TOC:**
- [How to detect agent failure modes](references/agent-recovery.md#failure-modes--detection)
- [Step 1: How to detect the loss](references/agent-recovery.md#step-1-detect-the-loss)
- [Step 2: How to verify the loss](references/agent-recovery.md#step-2-verify-the-loss)
- [Step 3: How to clean up partial artifacts](references/agent-recovery.md#step-3-clean-up-partial-artifacts)
- [Step 4: How to re-spawn the task](references/agent-recovery.md#step-4-re-spawn-the-task)
- [Step 5: How to record the failure](references/agent-recovery.md#step-5-record-the-failure)
- [How to handle special cases](references/agent-recovery.md#special-cases)
- [Agent recovery checklist](references/agent-recovery.md#agent-recovery-checklist)

### Recovery Checklist

- [ ] Failure detected and classified; loss verified (output file checked)
- [ ] Partial artifacts cleaned up; replacement agent spawned with new UUID
- [ ] Recovery log entry written; if 3 consecutive failures: escalated to user

---

## Lessons Learned

See [Lessons Learned](references/lessons-learned.md) for all 13 lessons with full context (swarm blind spots, PR description lies, absence bugs, cross-file consistency, UX judgment, stranger's perspective, regression loops, clean diffs, lint catches, stale file isolation, rate limit checkpoints, line drift, ephemeral task IDs).

---

## Resources

- Merge script: `${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-reports.py`
- Dedup agent: `${CLAUDE_PLUGIN_ROOT}/agents/caa-dedup-agent.md`
- Security review agent: `${CLAUDE_PLUGIN_ROOT}/agents/caa-security-review-agent.md`
- Other agents: `${CLAUDE_PLUGIN_ROOT}/agents/`
- Report output directory: `docs_dev/`

## Examples

See [examples.md](references/examples.md) for usage examples.
