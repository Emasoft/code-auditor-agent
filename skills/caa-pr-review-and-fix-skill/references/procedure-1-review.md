# Procedure 1: Code Review

> **Maintenance Note:** The review protocol below is shared with `caa-pr-review-skill` via its `SKILL.md` Protocol section (which inlines a single-pass variant). When updating shared steps here, also update that skill. Key differences: this file supports multi-pass (variable PASS_NUMBER, with RUN_ID), while pr-review-skill uses single-pass (P1 hardcoded, no RUN_ID).

Four-phase review pipeline: correctness swarm, claim verification, skeptical review + security review (parallel), then merge + dedup.

**Worktree mode:** When `USE_WORKTREES=true`, resolve `ABSOLUTE_REPORT_DIR = $(pwd)/docs_dev/` before spawning any agents. Pass this absolute path in every agent prompt. Add `isolation: "worktree"` to every Task() call. See the parent SKILL.md for full worktree protocol.

## Table of Contents

- [Pre-Pass Cleanup (MANDATORY)](#pre-pass-cleanup-mandatory)
- [Agent Manifest](#agent-manifest)
- [Prerequisites](#prerequisites)
- [Phase 1: Code Correctness Swarm](#phase-1-code-correctness-swarm)
- [Phase 2: Claim Verification](#phase-2-claim-verification)
- [Phase 3: Skeptical Review](#phase-3-skeptical-review)
- [Phase 4: Security Review](#phase-4-security-review)
- [Phase 5: Merge Reports + Deduplicate](#phase-5-merge-reports--deduplicate)
- [Phase 6: Present Results](#phase-6-present-results)
- [Procedure 1 Checklist](#procedure-1-checklist)

## Pre-Pass Cleanup (MANDATORY)

Before spawning ANY agents, run this cleanup to prevent stale file pollution:

```bash
# Archive any leftover phase reports from prior interrupted runs of the SAME pass
mkdir -p docs_dev/archive
for f in docs_dev/caa-correctness-P${PASS_NUMBER}-*.md \
         docs_dev/caa-claims-P${PASS_NUMBER}-*.md \
         docs_dev/caa-review-P${PASS_NUMBER}-*.md \
         docs_dev/caa-security-P${PASS_NUMBER}-*.md \
         docs_dev/caa-agents-P${PASS_NUMBER}-*.json \
         docs_dev/caa-checkpoint-P${PASS_NUMBER}-*.json; do
  [ -f "$f" ] && mv "$f" docs_dev/archive/
done
# Also archive any stale intermediate reports for this pass
for f in docs_dev/caa-pr-review-P${PASS_NUMBER}-intermediate-*.md; do
  [ -f "$f" ] && mv "$f" docs_dev/archive/
done
```

This ensures a clean slate. Files are archived (not deleted) for audit purposes.

## Agent Manifest

After determining domains and generating RUN_ID, write an agent manifest file:

```
docs_dev/caa-agents-P{N}-R{RUN_ID}.json
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
    "review": {"status": "pending"},
    "security": {"status": "pending"}
  }
}
```

This manifest survives context compaction and enables recovery of lost agent task IDs
by checking which expected output files exist on disk.

## Prerequisites

Before starting, gather:
1. The PR number (or branch name)
2. The PR description text
3. The list of changed files grouped by domain

## Phase 1: Code Correctness Swarm

Spawn **one `caa-code-correctness-agent` per domain** in parallel.

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
    subagent_type: "caa-code-correctness-agent",
    prompt: """
      DOMAIN: {domain_name}
      FILES: {file_list}
      PASS: {PASS_NUMBER}
      RUN_ID: {RUN_ID}
      AGENT_PREFIX: {AGENT_PREFIX}
      FINDING_ID_PREFIX: CC-P{PASS_NUMBER}-{AGENT_PREFIX}
      REPORT_DIR: {ABSOLUTE_REPORT_DIR}

      IMPORTANT — UUID FILENAME:
      Generate a UUID for your output file:
        UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
      Write your report to: {ABSOLUTE_REPORT_DIR}/caa-correctness-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

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
    run_in_background: true,
    isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
  )
```

**Wait for all Phase 1 agents to complete before proceeding.**

## Phase 2: Claim Verification

Spawn **one `caa-claim-verification-agent`** (single instance, not a swarm).

This agent needs:
- The full PR description (get via `gh pr view {number} --json body --jq .body`)
- All commit messages (get via `gh pr view {number} --json commits`)
- Access to the full codebase to verify claims

**Spawning pattern:**

```
Task(
  subagent_type: "caa-claim-verification-agent",
  prompt: """
    PR_NUMBER: {pr_number}
    PR_DESCRIPTION: (read from `gh pr view {number} --json body --jq .body`)
    COMMIT_MESSAGES: (read from `gh pr view {number} --json commits`)
    PASS: {PASS_NUMBER}
    RUN_ID: {RUN_ID}
    FINDING_ID_PREFIX: CV-P{PASS_NUMBER}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/caa-claims-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

    Extract every factual claim from the PR description and commit messages.
    Verify each claim against the actual code.
    Use finding IDs starting with {FINDING_ID_PREFIX}-001.
    (e.g., CV-P1-001, CV-P1-002, ...)

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
to avoid duplicating effort. However, it MUST NOT skip its own verification --
correctness agents check different things than claim verification.

## Phase 3: Skeptical Review

Spawn **one `caa-skeptical-reviewer-agent`** (single instance).

This agent needs:
- The full PR diff (get via `gh pr diff {number}`)
- The PR description
- Optionally, the Phase 1 and Phase 2 reports for cross-reference

**Spawn Phase 3 and Phase 4 in parallel. Wait for BOTH to complete before proceeding to Phase 5.**

**Spawning pattern:**

```
Task(
  subagent_type: "caa-skeptical-reviewer-agent",
  prompt: """
    PR_NUMBER: {pr_number}
    PR_DESCRIPTION: (provide the text or path)
    DIFF: (save `gh pr diff {number}` to docs_dev/pr-diff.txt and provide path)
    CORRECTNESS_REPORTS: {ABSOLUTE_REPORT_DIR}/caa-correctness-P{PASS_NUMBER}-R{RUN_ID}-*.md
    CLAIMS_REPORT: {ABSOLUTE_REPORT_DIR}/caa-claims-P{PASS_NUMBER}-R{RUN_ID}-*.md
    PASS: {PASS_NUMBER}
    RUN_ID: {RUN_ID}
    FINDING_ID_PREFIX: SR-P{PASS_NUMBER}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/caa-review-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

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
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

## Phase 4: Security Review

Spawn **one `caa-security-review-agent`** (single instance, runs in parallel with Phase 3).

**Spawning pattern:**

```
Task(
  subagent_type: "caa-security-review-agent",
  prompt: """
    DOMAIN: all-changed-files
    FILES: {all_changed_files_list}
    PASS: {PASS_NUMBER}
    RUN_ID: {RUN_ID}
    FINDING_ID_PREFIX: SC-P{PASS_NUMBER}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/caa-security-P{PASS_NUMBER}-R{RUN_ID}-${UUID}.md

    Perform a deep security review of all changed files.
    Check OWASP Top 10, injection attacks, secrets exposure, auth bypasses,
    dependency vulnerabilities, and attack surface analysis.
    Use finding IDs starting with {FINDING_ID_PREFIX}-001.
    (e.g., SC-P1-001, SC-P1-002, ...)

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] security-review - brief result. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

**Wait for BOTH Phase 3 and Phase 4 to complete before proceeding to Phase 5.**

## Phase 5: Merge Reports + Deduplicate

After all 4 phases complete, run the **two-stage merge pipeline**:

**Stage 1: Merge (Python script -- simple concatenation, no dedup)**

```bash
uv run $CLAUDE_PLUGIN_ROOT/scripts/caa-merge-reports.py ${REPORT_DIR} ${PASS_NUMBER} ${RUN_ID}
```

This produces an intermediate report at `docs_dev/caa-pr-review-P{N}-intermediate-{timestamp}.md`.
The merge script:
- When RUN_ID is provided, only collects files matching `caa-*-P{N}-R{RUN_ID}-*.md`
- When RUN_ID is omitted, collects all `caa-*-P{N}-*.md` files (legacy mode)
- Skips files with `-STALE` in the name
- Skips checkpoint, agent manifest, recovery, lint, fix, and test files
- Sorts by phase (correctness -> claims -> review)
- Concatenates severity sections WITHOUT deduplication
- Reports raw finding counts
- Verifies merged file integrity (byte-size check)
- Deletes original source files only after successful merge verification
- Always exits 0 (dedup agent determines final verdict)

**Stage 2: Deduplicate (AI agent -- semantic analysis)**

```
Task(
  subagent_type: "caa-dedup-agent",
  prompt: """
    INTERMEDIATE_REPORT: {ABSOLUTE_REPORT_DIR}/caa-pr-review-P{PASS_NUMBER}-intermediate-{timestamp}.md
    PASS_NUMBER: {PASS_NUMBER}
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}
    OUTPUT_PATH: {ABSOLUTE_REPORT_DIR}/caa-pr-review-P{PASS_NUMBER}-{timestamp}.md

    Read the intermediate merged report.
    Deduplicate findings semantically (see agent instructions).
    Produce the final report at OUTPUT_PATH with accurate counts and verdict.

    REPORTING RULES:
    - Write ALL detailed output to the OUTPUT_PATH file
    - Return to orchestrator ONLY: "[DONE/FAILED] dedup - {raw}->{dedup} findings ({removed} removed). Verdict: {VERDICT}. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

Wait for the dedup agent to complete. The dedup agent produces:
- Final report: `docs_dev/caa-pr-review-P{N}-{timestamp}.md`
- Verdict: REQUEST CHANGES / APPROVE WITH NITS / APPROVE
- Deduplication log showing which findings were merged and why

## Phase 6: Present Results

Read the **final deduplicated report** (NOT the intermediate) and present a summary to the user:

```
## PR Review Pass {PASS_NUMBER} Complete

**Verdict:** {REQUEST CHANGES / APPROVE WITH NITS / APPROVE}
**Dedup:** {raw_count} raw -> {dedup_count} unique ({removed} duplicates removed)
**MUST-FIX:** {count} | **SHOULD-FIX:** {count} | **NIT:** {count}

### Must-Fix Issues:
1. [MF-001] {title} -- {file:line} (Original: CC-P{N}-A0-001, SR-P{N}-002)
2. [MF-002] {title} -- {file:line} (Original: CV-P{N}-003)

### Should-Fix:
1. [SF-001] {title} (Original: CC-P{N}-A1-005)

### Full report: docs_dev/caa-pr-review-P{N}-{timestamp}.md
```

---

## Procedure 1 Checklist

Copy this checklist and track your progress:

- [ ] PR diff obtained and domain classification done
- [ ] Agent manifest written to disk
- [ ] Pre-pass cleanup completed (stale files archived)
- [ ] Phase 1: All correctness agents spawned with unique prefixes and UUIDs
- [ ] Phase 1: All correctness agents completed successfully
- [ ] Phase 2: Claim verification agent spawned and completed
- [ ] Phase 3: Skeptical reviewer agent spawned and completed
- [ ] Phase 4: Security review agent spawned and completed
- [ ] Phase 5 Stage 1: Merge script executed successfully
- [ ] Phase 5 Stage 2: Dedup agent completed with verdict
- [ ] Phase 6: Final report summary presented to user
