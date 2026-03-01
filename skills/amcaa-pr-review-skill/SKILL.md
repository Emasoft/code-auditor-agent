---
name: amcaa-pr-review-skill
description: >
  Use when reviewing PRs, auditing code, or running pre-merge quality gates.
  Trigger with "review the PR", "check the PR", "audit the PR", "pre-merge review".
version: 2.0.0
author: Emasoft
license: MIT
tags:
  - amcaa-pr-review
  - code-audit
  - claim-verification
  - quality-gate
---

# PR Review

## Overview

Three-phase PR review that catches what standard code audits miss. Spawns specialized agents
in sequence: correctness swarm, claim verification, skeptical review — then merges findings.

## Prerequisites

- `gh` CLI installed and authenticated (for `gh pr view`, `gh pr diff`)
- The PR must exist on GitHub (need PR number or branch name)
- `docs_dev/` directory must exist for report output
- The merge script at `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh` must be executable
- $CLAUDE_PLUGIN_ROOT must be set by the Claude Code plugin loader. Verify it is non-empty before running any scripts.
- If `USE_WORKTREES=true`: Git working tree must be clean (no uncommitted changes)

## Parameters

| Param | Req | Type | Default | Description |
|-------|-----|------|---------|-------------|
| `PR_NUMBER` | Y | int | -- | GitHub PR number or branch name |
| `REPORT_DIR` | N | path | `docs_dev/` | Output directory for all reports |
| `MERGE_SCRIPT` | N | path | `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh` | Path to merge script |
| `USE_WORKTREES` | N | bool | false | Run agent swarms in isolated git worktrees for isolation |

### Worktree Mode

When `USE_WORKTREES=true`, agents run in isolated git worktrees. Before spawning, resolve `ABSOLUTE_REPORT_DIR = $(pwd)/docs_dev/`. Pass this absolute path in every agent prompt and add `isolation: "worktree"` to every Task() call. Since this skill is review-only (no code modifications), worktrees are auto-cleaned after each agent completes.

## Use when

- Before pushing a PR to an upstream repository
- After completing a feature branch and wanting a pre-merge quality gate
- When asked to "review the PR", "check the PR", "audit the PR", or "pre-merge review"
- After a swarm of code audit agents has already run (this catches what they miss)

## Why this exists

In a real incident, 20+ specialized audit agents checked a 40-file PR and found zero issues.
A single external reviewer then immediately found 3 real bugs — including a function that
claimed to populate 4 fields but actually populated zero of them. The audit swarm checked
code correctness per-file; the reviewer checked claims against reality.

This pipeline automates the three complementary review perspectives needed to catch 100% of
issues:

| Phase | Agent | What it catches | Analogy |
|-------|-------|-----------------|---------|
| 1 | Code Correctness (swarm) | Per-file bugs, type errors, security | Microscope |
| 2 | Claim Verification (single) | PR description lies, missing implementations | Fact-checker |
| 3 | Skeptical Review (single) | UX concerns, cross-file issues, design judgment | Telescope |

## Protocol

> **Maintenance Note:** This protocol is also used by `amcaa-pr-review-and-fix-skill` via `references/procedure-1-review.md`. When updating shared steps below, also update that reference file. Key differences: this skill uses single-pass (P1 hardcoded, no RUN_ID), while pr-review-and-fix uses multi-pass (variable PASS_NUMBER, with RUN_ID).

### Prerequisites

Before starting, gather:
1. The PR number (or branch name)
2. The PR description text
3. The list of changed files grouped by domain

### Phase 1: Code Correctness Swarm

Spawn **one `amcaa-code-correctness-agent` per domain** in parallel.

Group changed files by domain. Common domain splits:

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
    FINDING_ID_PREFIX = "CC-P1-{AGENT_PREFIX}"
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
      AGENT_PREFIX: {AGENT_PREFIX}
      FINDING_ID_PREFIX: CC-P1-{AGENT_PREFIX}
      REPORT_DIR: {ABSOLUTE_REPORT_DIR}

      IMPORTANT — UUID FILENAME:
      Generate a UUID for your output file:
        UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
      Write your report to: {ABSOLUTE_REPORT_DIR}/amcaa-correctness-P1-${UUID}.md

      Audit these files for code correctness. Read every file completely.
      Use finding IDs starting with {FINDING_ID_PREFIX}-001.
      (e.g., CC-P1-A0-001, CC-P1-A0-002, ...)

      REPORTING RULES:
      - Write ALL detailed output to the report file
      - Return to orchestrator ONLY: "[DONE/FAILED] correctness-{domain} - brief result. Report: {path}"
      - Max 2 lines back to orchestrator
    """,
    run_in_background: true,
    isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
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
    FINDING_ID_PREFIX: CV-P1
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/amcaa-claims-P1-${UUID}.md

    Extract every factual claim from the PR description and commit messages.
    Verify each claim against the actual code.
    Use finding IDs starting with CV-P1-001.

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] claim-verification - brief result. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

**Wait for Phase 2 to complete before proceeding.**

Phase 2 runs AFTER Phase 1 so it can optionally reference correctness findings
to avoid duplicating effort. However, it MUST NOT skip its own verification —
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
    DIFF: (save `gh pr diff {number}` to {ABSOLUTE_REPORT_DIR}/pr-diff.txt and provide path)
    CORRECTNESS_REPORTS: {ABSOLUTE_REPORT_DIR}/amcaa-correctness-P1-*.md
    CLAIMS_REPORT: {ABSOLUTE_REPORT_DIR}/amcaa-claims-P1-*.md
    FINDING_ID_PREFIX: SR-P1
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/amcaa-review-P1-${UUID}.md

    Review this PR as an external maintainer who has never seen the codebase.
    Read the full diff holistically. Check for UX concerns, breaking changes,
    cross-file consistency, and design judgment issues.
    Use finding IDs starting with SR-P1-001.

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] skeptical-review - Verdict: X, brief result. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

### Phase 4: Merge Reports + Deduplicate

After all 3 phases complete, run the **two-stage merge pipeline**:

**Stage 1: Merge (bash script — simple concatenation, no dedup)**

```bash
bash $CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh ${REPORT_DIR} 1
```

This produces an intermediate report at `${REPORT_DIR}/amcaa-pr-review-P1-intermediate-{timestamp}.md`.
The v2 script verifies merged file integrity and deletes source files after verification.

**Stage 2: Deduplicate (AI agent — semantic analysis)**

```
Task(
  subagent_type: "amcaa-dedup-agent",
  prompt: """
    INTERMEDIATE_REPORT: {ABSOLUTE_REPORT_DIR}/amcaa-pr-review-P1-intermediate-{timestamp}.md
    PASS_NUMBER: 1
    OUTPUT_PATH: {ABSOLUTE_REPORT_DIR}/amcaa-pr-review-P1-{timestamp}.md
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    Read the intermediate merged report.
    Deduplicate findings semantically (see agent instructions).
    Produce the final report at OUTPUT_PATH with accurate counts and verdict.

    REPORTING RULES:
    - Write ALL detailed output to the OUTPUT_PATH file
    - Return to orchestrator ONLY: "[DONE/FAILED] dedup - {raw}→{dedup} ({removed} removed). Verdict: {VERDICT}. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

### Phase 5: Present Results

Read the **final deduplicated report** (NOT the intermediate) and present a summary:

```
## PR Review Complete

**Verdict:** {REQUEST CHANGES / APPROVE WITH NITS / APPROVE}
**Dedup:** {raw_count} raw → {dedup_count} unique ({removed} duplicates removed)
**MUST-FIX:** {count} | **SHOULD-FIX:** {count} | **NIT:** {count}

### Must-Fix Issues:
1. [MF-001] {title} — {file:line} (Original: CC-P1-A0-001, SR-P1-002)
2. [MF-002] {title} — {file:line} (Original: CV-P1-003)

### Should-Fix:
1. [SF-001] {title} (Original: CC-P1-A1-005)

### Full report: docs_dev/amcaa-pr-review-P1-{timestamp}.md
```

## CRITICAL RULES

1. **NEVER skip Phase 2 and 3.** The correctness swarm alone is insufficient. It will miss
   claimed-but-not-implemented features, cross-file inconsistencies, and UX concerns.
   Phase 2 and 3 are what make this pipeline catch 100% of issues.

2. **Phase order matters.** Phase 1 (parallel) → Phase 2 (sequential) → Phase 3 (sequential).
   Later phases can reference earlier reports to avoid duplicate work, but they must NOT
   skip their own checks.

3. **Each agent writes to a UUID-named file.** Agents return only 1-2 lines to the orchestrator.
   Full findings go in the report files. This prevents context flooding and file collisions.

4. **Two-stage merge pipeline.** Stage 1 (bash script) concatenates without dedup.
   Stage 2 (amcaa-dedup-agent) performs semantic deduplication. The bash script handles
   simple concatenation; the AI agent handles complex same-line-different-bug decisions.

5. **Agent prefix assignment.** Each Phase 1 agent gets a unique hex prefix (A0, A1, ...)
   assigned by the orchestrator at spawn time. Finding IDs use this prefix (CC-P1-A0-001,
   CC-P1-A1-001) to guarantee global uniqueness within a pass.

6. **UUID filenames prevent collisions.** Each agent generates a UUID for its output file
   (`python3 -c "import uuid; print(uuid.uuid4())"`). This eliminates file overwrites between
   concurrent agents.

7. **Same line ≠ same bug.** Two findings at the same file:line are only duplicates if they
   describe the same root cause. The dedup agent uses semantic analysis, not just line
   number matching.

8. **Re-run after fixes.** After fixing issues, re-run the full pipeline to verify the fixes
   are correct and didn't introduce new issues.

9. **The v2 merge script deletes source files only after verifying the intermediate file's
   byte size equals or exceeds the sum of inputs.** If verification fails, source files are
   preserved for manual inspection.

## Quick Reference

```
# Full pipeline
/pr-review 206

# Just claim verification (fastest, catches the most common misses)
# Spawn amcaa-claim-verification-agent manually

# Just skeptical review (for a quick holistic check)
# Spawn amcaa-skeptical-reviewer-agent manually
```

## Instructions

Follow the 5-phase protocol strictly:

1. Gather the PR number, description, and list of changed files grouped by domain.
2. Assign unique prefixes (A0, A1, ...) to each domain. Spawn one `amcaa-code-correctness-agent` per domain in parallel (Phase 1 swarm). Each agent generates a UUID for its output filename.
3. Wait for all Phase 1 agents to complete before proceeding.
4. Spawn a single `amcaa-claim-verification-agent` with the PR description and commit messages (Phase 2). Agent generates UUID filename.
5. Wait for Phase 2 to complete before proceeding.
6. Spawn a single `amcaa-skeptical-reviewer-agent` with the full diff and earlier reports (Phase 3). Agent generates UUID filename.
7. Wait for Phase 3 to complete.
8. Run the two-stage merge: `bash $CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh docs_dev/ 1` (Stage 1), then spawn `amcaa-dedup-agent` on the intermediate report (Stage 2).
9. Read the final deduplicated report and present the verdict summary to the user.
10. If MUST-FIX issues exist, do NOT push the PR until issues are resolved and pipeline re-run.

## Output

The pipeline produces:
- Per-domain correctness reports: `docs_dev/amcaa-correctness-P1-{uuid}.md` (deleted after merge verification)
- Claim verification report: `docs_dev/amcaa-claims-P1-{uuid}.md` (deleted after merge verification)
- Skeptical review report: `docs_dev/amcaa-review-P1-{uuid}.md` (deleted after merge verification)
- Intermediate merged report: `docs_dev/amcaa-pr-review-P1-intermediate-{timestamp}.md`
- Final deduplicated report: `docs_dev/amcaa-pr-review-P1-{timestamp}.md`

Final report includes: verdict (APPROVE/REQUEST CHANGES/APPROVE WITH NITS), all
deduplicated issues with severity (MUST-FIX/SHOULD-FIX/NIT), deduplication log, and
original finding ID cross-references.

## Error Handling

- If any Phase 1 agent fails, re-run it for that domain only (UUID filename avoids collision)
- If Phase 2 or 3 fails, re-run that phase (they are single agents)
- If the merge script exits with code 2, there was an input error (missing reports, invalid dir)
- If the merge script's byte-size verification fails, source files are preserved — investigate manually
- If the dedup agent fails, re-run it on the intermediate report (it's idempotent)
- If `gh` CLI is not authenticated, stop and ask the user to run `gh auth login`

---

## Agent Recovery Protocol

See [Agent Recovery Protocol](references/agent-recovery.md) for full recovery procedures.

**Contents:**
- How to detect agent failures (crash, OOM, timeout, API errors, compaction loss)
- How to track agents using manifest fields (taskId, domain, outputPath, status)
- How to verify whether an agent's output was lost or corrupted
- How to clean up partial artifacts from failed agents
- How to re-spawn a failed task with a new UUID (max 3 retries)
- How to record failures in the recovery log
- How to handle special cases: compaction recovery, wrong pass number, domain collision

### Recovery Checklist

Copy this checklist and track your progress:

- [ ] Check all agent reports exist in docs_dev/
- [ ] Verify merge script produced intermediate report
- [ ] Confirm dedup agent produced final report
- [ ] Record any agent failures in recovery log
- [ ] Escalate to user after 3 consecutive failures for same task

---

## Examples

```
# Full pipeline on PR 206
User: "review PR 206"
→ Skill activates, runs all 5 phases, presents merged verdict

# Quick claim check only
User: "just verify the claims in PR 206"
→ Spawn only amcaa-claim-verification-agent

# Re-run after fixes
User: "re-run the PR review"
→ Full pipeline again to verify fixes didn't introduce new issues
```

## Resources

- Merge script (v2): `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh`
- Merge script (v1, legacy): `$CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports.sh`
- Dedup agent: `$CLAUDE_PLUGIN_ROOT/agents/amcaa-dedup-agent.md`
- Agents: `$CLAUDE_PLUGIN_ROOT/agents/`
- Report output directory: `docs_dev/`

## Lessons Learned (Baked Into This Pipeline)

See [Lessons Learned](references/lessons-learned.md) for the full list with context.

**Contents:**
- Why swarms miss the big picture and how verification compensates
- Why PR descriptions cannot be trusted as implementation evidence
- How to catch absence bugs that produce no errors
- Why cross-file consistency requires holistic review agents
- Why UX judgment requires a separate review phase
- Why the stranger's perspective catches what familiarity misses

### Lessons Checklist

Copy this checklist and track your progress:

- [ ] All three phases (correctness, claims, skeptical) are included in every review
- [ ] PR description claims are verified against actual code, not trusted at face value
- [ ] Cross-file consistency is checked (version strings, shared constants, API contracts)
