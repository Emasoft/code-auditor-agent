# Protocol

## Table of Contents

- [Maintenance Note](#maintenance-note)
- [Prerequisites](#prerequisites)
- [Phase 1: Code Correctness Swarm](#phase-1-code-correctness-swarm)
- [Phase 2: Claim Verification](#phase-2-claim-verification)
- [Phase 3 + Phase 4 (Parallel)](#phase-3--phase-4-run-in-parallel)
  - [Phase 3: Skeptical Review](#phase-3-skeptical-review)
  - [Phase 4: Security Review](#phase-4-security-review)
- [Phase 5: Merge Reports + Deduplicate](#phase-5-merge-reports--deduplicate)
- [Phase 6: Present Results](#phase-6-present-results)

## Maintenance Note

This protocol is also used by `caa-pr-review-and-fix-skill` via `references/procedure-1-review.md`. When updating shared steps below, also update that reference file. Key differences: this skill uses single-pass (P1 hardcoded, no RUN_ID), while pr-review-and-fix uses multi-pass (variable PASS_NUMBER, with RUN_ID).

## Prerequisites

Before starting, gather:
1. The PR number (or branch name)
2. The PR description text
3. The list of changed files grouped by domain

## Phase 1: Code Correctness Swarm

Spawn **one `caa-code-correctness-agent` per domain** in parallel.

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
| docs | `docs/**`, `README.md`. If `.md` files are agent definitions or skill files (in `agents/`, `skills/`, `commands/` dirs), also route to security-review for prompt injection scanning. |
| tests | `tests/**` |
| config | `package.json`, `version.json`, `*.config.*`. Route to code-correctness for syntax validation AND to security-review for secrets check. |

**Prefix assignment:**

```
domains = sorted(list of domains with changed files)
for i, domain in enumerate(domains):
    AGENT_PREFIX = f"A{i:X}"    # A0, A1, A2, ..., AF, A10
    FINDING_ID_PREFIX = "CC-P1-{AGENT_PREFIX}"
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
      AGENT_PREFIX: {AGENT_PREFIX}
      FINDING_ID_PREFIX: CC-P1-{AGENT_PREFIX}
      REPORT_DIR: {ABSOLUTE_REPORT_DIR}
      DIFF: {git_diff_for_domain}  # (optional — provides the git diff for the domain's changed files, enabling targeted auditing of changed regions)

      IMPORTANT — UUID FILENAME:
      Generate a UUID for your output file:
        UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
      Write your report to: {ABSOLUTE_REPORT_DIR}/caa-correctness-P1-${UUID}.md

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
    FINDING_ID_PREFIX: CV-P1
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/caa-claims-P1-${UUID}.md

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

## Phase 3 + Phase 4 (run in parallel)

### Phase 3: Skeptical Review

Spawn **one `caa-skeptical-reviewer-agent`** (single instance).

This agent needs:
- The full PR diff (get via `gh pr diff {number}`)
- The PR description
- Optionally, the Phase 1 and Phase 2 reports for cross-reference

**Spawning pattern:**

```
Task(
  subagent_type: "caa-skeptical-reviewer-agent",
  prompt: """
    PR_NUMBER: {pr_number}
    PR_DESCRIPTION: (provide the text or path)
    DIFF: (save `gh pr diff {number}` to {ABSOLUTE_REPORT_DIR}/pr-diff.txt and provide path)
    CORRECTNESS_REPORTS: {ABSOLUTE_REPORT_DIR}/caa-correctness-P1-*.md
    CLAIMS_REPORT: {ABSOLUTE_REPORT_DIR}/caa-claims-P1-*.md
    FINDING_ID_PREFIX: SR-P1
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/caa-review-P1-${UUID}.md

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

> **Phase 3 and Phase 4 run in parallel.** Spawn both agents immediately after Phase 2 completes,
> then wait for BOTH before proceeding to Phase 5 (merge).

### Phase 4: Security Review

Spawn **one `caa-security-review-agent`** (single instance, runs in parallel with Phase 3).

This agent needs:
- The full PR diff
- Access to the full codebase
- Access to dependency files (package.json, pyproject.toml, requirements.txt)

**Spawning pattern:**

```
Task(
  subagent_type: "caa-security-review-agent",
  prompt: """
    PR_NUMBER: {pr_number}
    DOMAIN: all-changed-files
    FILES: {all_changed_files}
    FINDING_ID_PREFIX: SC-P1
    REPORT_DIR: {ABSOLUTE_REPORT_DIR}

    IMPORTANT — UUID FILENAME:
    Generate a UUID for your output file:
      UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
    Write your report to: {ABSOLUTE_REPORT_DIR}/caa-security-P1-${UUID}.md

    Perform a deep security review of all changed files.
    Check for OWASP Top 10, injection attacks, secrets exposure, auth bypasses,
    dependency vulnerabilities, and attack surface analysis.
    Use finding IDs starting with SC-P1-001.

    REPORTING RULES:
    - Write ALL detailed output to the report file
    - Return to orchestrator ONLY: "[DONE/FAILED] security-review - brief result. Report: {path}"
    - Max 2 lines back to orchestrator
  """,
  run_in_background: true,
  isolation: "worktree"  # Only when USE_WORKTREES=true; omit this line otherwise
)
```

**Wait for both Phase 3 and Phase 4 to complete before proceeding to Phase 5.**

## Phase 5: Merge Reports + Deduplicate

After all 4 phases complete, run the **two-stage merge pipeline**:

**Stage 1: Merge (Python script — simple concatenation, no dedup)**

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/caa-merge-reports.py --quiet ${REPORT_DIR} 1
```

This produces an intermediate report at `${REPORT_DIR}/caa-pr-review-P1-intermediate-{timestamp}.md`.
The v2 script verifies merged file integrity and deletes source files after verification.
The script collects all report files matching: `caa-correctness-P{N}-*.md`, `caa-claims-P{N}-*.md`,
`caa-review-P{N}-*.md`, and `caa-security-P{N}-*.md`.

**Stage 2: Deduplicate (AI agent — semantic analysis)**

```
Task(
  subagent_type: "caa-dedup-agent",
  prompt: """
    INTERMEDIATE_REPORT: {ABSOLUTE_REPORT_DIR}/caa-pr-review-P1-intermediate-{timestamp}.md
    PASS_NUMBER: 1
    OUTPUT_PATH: {ABSOLUTE_REPORT_DIR}/caa-pr-review-P1-{timestamp}.md
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

## Phase 6: Present Results

Read the **final deduplicated report** (NOT the intermediate) and present a summary using the format in [review-complete.md](review-complete.md).
