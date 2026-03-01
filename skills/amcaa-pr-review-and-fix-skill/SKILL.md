---
name: amcaa-pr-review-and-fix-skill
description: >
  Use when reviewing PRs, auditing code, or running pre-merge quality gates.
  Trigger with "review and fix the PR", "review and fix PR", "audit and fix the PR", "pre-merge review and fix".
version: 3.0.0
author: Emasoft
license: MIT
tags:
  - amcaa-pr-review
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
     Manual intervention required. See: docs_dev/amcaa-pr-review-and-fix-escalation-{timestamp}.md"
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
| Merged intermediate | `docs_dev/amcaa-pr-review-P{N}-intermediate-{timestamp}.md` |
| Final dedup report | `docs_dev/amcaa-pr-review-P{N}-{timestamp}.md` |
| Fix checkpoint (per-domain) | `docs_dev/amcaa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` |
| Fix summary (per-domain) | `docs_dev/amcaa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `docs_dev/amcaa-tests-outcome-P{N}.md` |
| Lint outcome | `docs_dev/amcaa-lint-outcome-P{N}.md` |
| Lint summary (JSON) | `docs_dev/megalinter-P{N}/lint-summary.json` |
| Lint fixes | `docs_dev/amcaa-lint-fixes-P{N}.md` |
| Recovery log | `docs_dev/amcaa-recovery-log-P{N}.md` |
| Final clean report | `docs_dev/amcaa-pr-review-and-fix-FINAL-{timestamp}.md` |
| Escalation (if max reached) | `docs_dev/amcaa-pr-review-and-fix-escalation-{timestamp}.md` |

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

**Before each pass**, run the pre-pass cleanup protocol (see Procedure 1 reference). Do NOT delete merged reports or fix summaries from previous passes -- they form the audit trail.

The merge script v2 uses pass-specific and run-specific glob patterns, so prior-pass and prior-run files are automatically excluded.

---

## PROCEDURE 1 -- Code Review

Three-phase review: correctness swarm, claim verification, skeptical review, then merge + dedup.

See [Procedure 1: Code Review](references/procedure-1-review.md) for full protocol.

**Contents:**
- Pre-Pass Cleanup (MANDATORY)
- Agent Manifest
- Phase 1: Code Correctness Swarm (parallel agents per domain)
- Phase 2: Claim Verification (single agent)
- Phase 3: Skeptical Review (single agent)
- Phase 4: Merge Reports + Deduplicate (bash script + AI dedup agent)
- Phase 5: Present Results to user

### Review Checklist

Copy this checklist and track your progress:

- [ ] PR diff obtained and domain classification done
- [ ] Agent manifest written to disk
- [ ] Pre-pass cleanup completed (stale files archived)
- [ ] Phase 1: All correctness agents spawned and completed
- [ ] Phase 2: Claim verification agent completed
- [ ] Phase 3: Skeptical reviewer completed
- [ ] Phase 4: Merge script + dedup agent completed
- [ ] Phase 5: Final report presented to user

---

## PROCEDURE 2 -- Code Fix

Dynamic agent swarm that resolves all findings, runs tests, lints, and commits.

See [Procedure 2: Code Fix](references/procedure-2-fix.md) for full protocol.

**Contents:**
- Agent Selection (dynamic, based on available agents)
- Fix Protocol (15-step process)
- Fix agent spawning pattern with self-verification checklist
- Test agent spawning pattern with self-verification checklist
- Linting Step (Docker required, MegaLinter)
- Lint-fix loop (max 3 attempts)
- Commit After Fixes

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
     Review: docs_dev/amcaa-pr-review-P{last_pass}-{timestamp}.md
     Manual intervention required."
    Present to user and exit.

Run PROCEDURE 1 with new PASS_NUMBER.

if PROCEDURE 1 finds ZERO issues (all severities -- MUST-FIX, SHOULD-FIX, NIT):
    Write final report: docs_dev/amcaa-pr-review-and-fix-FINAL-{timestamp}.md
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
- Pass 1 review: docs_dev/amcaa-pr-review-P1-{timestamp}.md
- Pass 1 fixes: docs_dev/amcaa-fixes-done-P1-{domain}.md
- ...
- Final clean review: docs_dev/amcaa-pr-review-P{N}-{timestamp}.md

### All Fixes Applied
1. [CC-P1-001] {title} -- {file} (Pass 1)
2. [SR-P1-003] {title} -- {file} (Pass 1)
3. [CC-P2-001] {title} -- {file} (Pass 2)
...
```

---

## Output

The pipeline produces these deliverables across all passes:

| Deliverable | Location | When |
|-------------|----------|------|
| Per-pass review report (deduplicated) | `docs_dev/amcaa-pr-review-P{N}-{timestamp}.md` | After each Procedure 1 |
| Per-domain fix summaries | `docs_dev/amcaa-fixes-done-P{N}-{domain}.md` | After each Procedure 2 |
| Test outcome per pass | `docs_dev/amcaa-tests-outcome-P{N}.md` | After each test run |
| Lint outcome per pass | `docs_dev/amcaa-lint-outcome-P{N}.md` | After each lint run (Docker only) |
| Lint summary JSON | `docs_dev/megalinter-P{N}/lint-summary.json` | After each lint run (Docker only) |
| Recovery log | `docs_dev/amcaa-recovery-log-P{N}.md` | When agent failures occur |
| Final report (zero issues) | `docs_dev/amcaa-pr-review-and-fix-FINAL-{timestamp}.md` | Pipeline completion |
| Escalation report (max passes) | `docs_dev/amcaa-pr-review-and-fix-escalation-{timestamp}.md` | If limit reached |

**Key outputs for the user:**
- **Final report** summarizes all passes, all fixes applied, and final verdict (APPROVE)
- **Escalation report** lists remaining unresolved issues if the pass limit was reached
- **Per-pass review reports** provide the detailed audit trail of findings and resolutions

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
    commit. Never fail a pass because Docker is missing -- linting is an enhancement, not a gate.

14. **Lint-fix loop is separate from the pass counter.** Within a single pass, the lint->fix
    cycle can iterate up to 3 times. These iterations do NOT increment the main pass number.
    Only the outer review->fix loop increments the pass counter.

---

## Error Handling

- If any Phase 1 agent fails, re-run it for that domain only (with a new UUID)
- If Phase 2 or 3 fails, re-run that phase (they are single agents, new UUID)
- If the merge script (v2) exits with code 2, there's a fatal error -- investigate
- If the dedup agent reports MUST-FIX > 0, proceed to PROCEDURE 2
- If the dedup agent fails, re-run it with the same intermediate report
- If `gh` CLI is not authenticated, stop and ask the user to run `gh auth login`
- If a fix agent fails, re-run for that domain only
- If tests fail after fixes, spawn domain-specific agents to investigate and fix
- If max passes reached, write escalation report and stop
- If merge byte-size verification fails, do NOT delete source files -- investigate
- If Docker is not available, skip MegaLinter entirely -- log "[SKIP]" and proceed to commit
- If the MegaLinter Docker image pull fails, skip linting for this pass (don't block the pipeline)
- If the linter script crashes (Python error, not lint errors), log the error and skip linting
- If lint-fix loop exhausts 3 attempts without reducing error count, stop the lint loop and escalate to user -- proceed to commit with lint errors noted in the pass report

---

## Agent Recovery Protocol

Protocol for recovering from agent crashes, timeouts, API errors, and context compaction losses.

See [Agent Recovery Protocol](references/agent-recovery.md) for full protocol.

**Contents:**
- Failure Modes & Detection (crash, OOM, API errors, timeout, compaction loss, collisions)
- Step 1: Detect the Loss (agent tracking fields)
- Step 2: Verify the Loss (file completeness checks)
- Step 3: Clean Up Partial Artifacts (including fix agent uncommitted changes)
- Step 4: Re-Spawn the Task (new UUID, same prompt, max 3 retries)
- Step 5: Record the Failure (recovery log)
- Special Cases: compaction recovery, wrong pass number, domain collision, missing test report

### Recovery Checklist

Copy this checklist and track your progress:

- [ ] Failure detected and classified
- [ ] Loss verified (output file checked)
- [ ] Partial artifacts cleaned up
- [ ] Replacement agent spawned with new UUID
- [ ] Recovery log entry written
- [ ] If 3 consecutive failures: escalated to user

---

## Lessons Learned (Baked Into This Pipeline)

Key insights from real incidents that shaped this pipeline's design.

See [Lessons Learned](references/lessons-learned.md) for all 13 lessons with full context.

**Summary:**
1. Swarms are microscopes -- blind to the big picture
2. PR descriptions lie -- intent vs. implementation gap
3. Absence is the hardest bug -- missing fields produce no errors
4. Cross-file consistency requires holistic view
5. UX judgment is not a code concern
6. The stranger's perspective is irreplaceable
7. Fixes introduce regressions -- review-fix loop is essential
8. Commit between passes for clean diffs
9. Linting catches what reviewers and tests miss
10. Stale files poison the pipeline -- use Run ID isolation
11. Agent rate limits are inevitable -- use checkpoint files
12. Line numbers drift across passes -- always re-verify
13. Task IDs are ephemeral -- use on-disk agent manifest

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

Each step's details are documented in the reference files for PROCEDURE 1 and PROCEDURE 2.

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
