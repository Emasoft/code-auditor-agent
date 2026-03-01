---
name: pr-review
description: >
  Use when reviewing PRs, auditing code, or running pre-merge quality gates.
  Trigger with "review the PR", "check the PR", "audit the PR", "pre-merge review".
version: 2.0.0
author: Emasoft
license: MIT
tags:
  - pr-review
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

      IMPORTANT — UUID FILENAME:
      Generate a UUID for your output file:
        UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
      Write your report to: docs_dev/amcaa-correctness-P1-${UUID}.md

      Audit these files for code correctness. Read every file completely.
      Use finding IDs starting with {FINDING_ID_PREFIX}-001.
      (e.g., CC-P1-A0-001, CC-P1-A0-002, ...)

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
    FINDING_ID_PREFIX: CV-P1

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    Write your report to: docs_dev/amcaa-claims-P1-${UUID}.md

    Extract every factual claim from the PR description and commit messages.
    Verify each claim against the actual code.
    Use finding IDs starting with CV-P1-001.

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
    DIFF: (save `gh pr diff {number}` to docs_dev/pr-diff.txt and provide path)
    CORRECTNESS_REPORTS: docs_dev/amcaa-correctness-P1-*.md
    CLAIMS_REPORT: docs_dev/amcaa-claims-P1-*.md
    FINDING_ID_PREFIX: SR-P1

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    Write your report to: docs_dev/amcaa-review-P1-${UUID}.md

    Review this PR as an external maintainer who has never seen the codebase.
    Read the full diff holistically. Check for UX concerns, breaking changes,
    cross-file consistency, and design judgment issues.
    Use finding IDs starting with SR-P1-001.

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
bash $CLAUDE_PLUGIN_ROOT/scripts/amcaa-merge-reports-v2.sh docs_dev/ 1
```

This produces an intermediate report at `docs_dev/pr-review-P1-intermediate-{timestamp}.md`.
The v2 script verifies merged file integrity and deletes source files after verification.

**Stage 2: Deduplicate (AI agent — semantic analysis)**

```
Task(
  subagent_type: "amcaa-dedup-agent",
  prompt: """
    INTERMEDIATE_REPORT: docs_dev/pr-review-P1-intermediate-{timestamp}.md
    PASS_NUMBER: 1
    OUTPUT_PATH: docs_dev/pr-review-P1-{timestamp}.md

    Read the intermediate merged report.
    Deduplicate findings semantically (see agent instructions).
    Produce the final report at OUTPUT_PATH with accurate counts and verdict.

    REPORTING RULES:
    - Write ALL detailed output to the OUTPUT_PATH file
    - Return to orchestrator ONLY: "[DONE/FAILED] dedup - {raw}→{dedup} ({removed} removed). Verdict: {VERDICT}. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true
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

### Full report: docs_dev/pr-review-P1-{timestamp}.md
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
   (`uuidgen | tr '[:upper:]' '[:lower:]'`). This eliminates file overwrites between
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
- Intermediate merged report: `docs_dev/pr-review-P1-intermediate-{timestamp}.md`
- Final deduplicated report: `docs_dev/pr-review-P1-{timestamp}.md`

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

This protocol applies to ALL agents spawned by the orchestrator: correctness swarm, claim verification,
skeptical review, and dedup agent. When an agent is lost for any reason, the orchestrator MUST follow
these steps to ensure the task is completed and no corrupt artifacts remain.

### Failure Modes & Detection

| Failure Mode | Detection Signal |
|---|---|
| **Crash / OOM** | Task tool returns error, empty result, or agent process dies mid-execution |
| **Out of tokens** | Agent returns truncated output, `[MAX TURNS]`, or incomplete report file |
| **API errors** | Agent returns "overloaded", rate limit (429), server error (500), or auth failure |
| **Connection errors** | Task tool hangs then returns timeout or network error |
| **Timeout** | Agent does not return within deadline (review agents: 10 min, dedup agent: 5 min) |
| **Lost during compaction** | Orchestrator's context was summarized; agent task ID no longer in memory and no result was ever received |
| **Broken reference** | TaskOutput returns "agent not found" or "invalid task ID" |
| **ID collision** | Two agents wrote to overlapping filenames (prevented by UUID filenames — verify if suspected) |
| **Version collision** | Agent used stale plugin/agent definition cached from a prior session; writes wrong format or wrong pass prefix |

### Step 1: Detect the Loss

The orchestrator MUST mentally track every spawned agent with these fields:

```
taskId:        string    // Task tool's returned ID
agentType:     string    // "correctness" | "claims" | "skeptical" | "dedup"
domain:        string    // Domain label (e.g., "governance-core") or "N/A" for single agents
outputPath:    string    // Expected report file path (with UUID)
findingPrefix: string    // e.g., "CC-P1-A2" — for re-spawn consistency
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
LOST_FILE="docs_dev/amcaa-correctness-P1-a1b2c3d4.md"

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

### Step 5: Record the Failure

Append an entry to the recovery log (either in the merged report or
a separate `docs_dev/amcaa-recovery-log-P{N}.md` file):

```markdown
### Agent Recovery Log

| Time | Agent Type | Domain | Failure Mode | Lost File | Action Taken |
|------|-----------|--------|-------------|-----------|-------------|
| 14:23 | correctness | governance-core | timeout (12 min) | P1-a1b2c3d4.md (0 bytes, deleted) | Re-spawned → P1-e5f6g7h8.md |
| 14:25 | claims | N/A | API 429 | P1-i9j0k1l2.md (partial, deleted) | 30s cooldown → re-spawned |
```

### Special Cases

**Lost during context compaction:**

The orchestrator's context was summarized and one or more agent task IDs were lost.

1. List ALL `amcaa-*-P{N}-*.md` files in `docs_dev/` for the current pass number
2. Build the expected agent roster: which domains should have correctness reports? Was claims run? Was skeptical run? Was dedup run?
3. For each expected report that is missing: check if a complete file exists under a different-than-expected UUID (the agent may have written it but the ID was lost)
4. For each truly missing report: re-spawn from scratch (Step 4)

**Agent wrote report with wrong pass number (version/cache collision):**

If an agent writes a report with `P2` instead of `P1` (stale prompt from a cached agent definition):

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

1. **Swarms are microscopes.** Great at per-file correctness. Blind to the big picture.
2. **PR descriptions lie.** Not maliciously — authors believe they implemented what they described.
   The gap between intent and implementation is the #1 source of missed bugs.
3. **Absence is the hardest bug to find.** A missing field assignment produces no error, no warning,
   no test failure. The code compiles and runs fine. Only a claim verifier or skeptical reviewer
   will notice that `fromLabel` is declared in the type but never set in the return statement.
4. **Cross-file consistency requires holistic view.** Version "0.22.5" in JSON-LD but "0.22.4"
   in prose HTML — each file is internally valid, but together they're inconsistent.
5. **UX judgment is not a code concern.** Auto-copying clipboard on text selection is technically
   correct code. Whether it's a good idea requires a different kind of thinking.
6. **The stranger's perspective is irreplaceable.** Twenty agents who know the codebase missed
   what one agent pretending to be a stranger caught immediately. Fresh eyes see what familiarity
   blinds you to.
