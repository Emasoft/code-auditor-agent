---
name: caa-audit-codebase-cmd
description: >
  Run a full codebase audit against a reference standard. Discovers all files, triages with
  grep, audits in parallel batches, verifies findings, fills gaps, consolidates per-domain,
  and generates actionable TODO files. Optionally applies fixes with verification loop.
trigger:
  - "/audit-codebase"
  - "audit the codebase"
  - "run code audit"
  - "compliance audit"
  - "decoupling audit"
parameters:
  - name: scope
    description: Directory path to audit
    required: true
  - name: standard
    description: Path to reference standard document
    required: true
  - name: types
    description: "Comma-separated violation types (default HARDCODED_API,HARDCODED_GOVERNANCE,DIRECT_DEPENDENCY,HARDCODED_PATH,MISSING_ABSTRACTION)"
    required: false
  - name: fix
    description: Enable fix phases (6-7)
    required: false
    default: "false"
  - name: todo-only
    description: Stop after Phase 5 (generate TODOs, don't fix)
    required: false
    default: "false"
  - name: grep-patterns
    description: Path to file with custom grep patterns (one per line)
    required: false
  - name: report-dir
    description: "Directory for reports (default: reports/code-auditor/)"
    required: false
    default: "reports/code-auditor/"
  - name: max-fix-passes
    description: "Maximum fix-verify iterations (default 5)"
    required: false
    default: "5"
  - name: worktrees
    description: Run agent swarms in isolated git worktrees
    required: false
    default: "false"
  - name: extended
    description: >
      Add scenario-walker + assumption-auditor swarms (TRDD-6857f67f).
      Runs caa-scenario-generator-skill to emit scenarios.json, then dispatches
      caa-scenario-walker-agent (one per scenario or cluster) and
      caa-assumption-auditor-agent (one per high-risk file). Adds end-to-end
      scenario coverage and per-file assumption coverage that line-level
      review structurally cannot reach. Slower but catches architectural /
      UX / protocol defects.
    required: false
    default: "false"
  - name: no-scenarios
    description: Inside extended mode, disable the scenario-walker swarm (keep assumption auditor only)
    required: false
    default: "false"
  - name: no-assumptions
    description: Inside extended mode, disable the assumption-auditor swarm (keep scenario walker only)
    required: false
    default: "false"
  - name: skip-linked-issue
    description: >
      Skip the linked-issue verification step in caa-claim-verification-agent.
      Use when `gh` is not authenticated or when the PR has no associated
      GitHub issues.
    required: false
    default: "false"
  - name: agent-written-code
    description: >
      Explicitly enable the agent-written code sub-checklist in
      caa-code-correctness-agent. The orchestrator also AUTO-DETECTS this mode
      when the PR description mentions Claude/Codex/Cursor/Copilot/GPT-N/Gemini/Aider/Continue/Cline;
      or when the PR author matches `*[bot]` (e.g., claude[bot], copilot[bot]);
      or when a commit in the PR has `Co-authored-by: claude` or similar. To
      FORCE-DISABLE the mode, use the inverse `--no-agent-written-code` flag.
    required: false
    default: "false"
  - name: no-agent-written-code
    description: >
      Disable agent-written code detection even if auto-detection would trigger.
    required: false
    default: "false"
  - name: skip-cross-layer-audit
    description: >
      Skip the caa-cross-layer-auditor-agent pass that hunts cross-file mismatches
      (env-var name drift, default-value drift, schema-vs-code mismatch, removed-API-
      still-called, hidden ops prerequisites). Use for very small PRs where cross-layer
      mismatches are unlikely. Runs ONCE per audit (not per domain) since findings span
      the whole repo. See TRDD-60f53034 §3.5.
    required: false
    default: "false"
---

# Codebase Audit & Fix

This command launches the `caa-codebase-audit-and-fix-skill` skill pipeline.

## Usage

```
/audit-codebase --scope ./plugins/my-plugin --standard ./docs/compliance-rules.md
/audit-codebase --scope ./src --standard ./standards/api-rules.md --fix
/audit-codebase --scope ./plugins/amcos --standard ./docs/decoupling-standard.md --todo-only --types HARDCODED_API,DIRECT_DEPENDENCY

# Extended review — adds scenario walker + assumption auditor (TRDD-6857f67f)
/audit-codebase --scope ./plugins/my-plugin --standard ./docs/compliance-rules.md --extended
```

**When to use:** When auditing a GitHub PR, the linked-issue verification step
automatically extracts `Fixes #NNN` references from the PR description and
checks the issue's acceptance criteria against the diff.

**Normal vs extended (TRDD-6857f67f §4.0):**

| Mode | What runs |
|---|---|
| Normal (default) | Today's pipeline: correctness + domain + security + claim-verification + skeptical-review |
| Extended (`--extended`) | Normal pipeline PLUS caa-scenario-generator-skill (emit scenarios.json) PLUS caa-scenario-walker-agent swarm PLUS caa-assumption-auditor-agent swarm |

The three audit families (line-level, scenario-level, assumption-level)
run in parallel; their reports converge at consolidation. Consolidation
merges findings that point at the SAME defect from multiple angles into
ONE finding with up to three evidence frames preserved.

Two finer-grained flags allow partial extended runs:
- `--extended --no-scenarios` → assumption auditor only
- `--extended --no-assumptions` → scenario walker only

These exist for debugging and partial rollback. If extended produces
too many false positives, disabling one branch helps localize the noise.

## What Happens

1. **Phase 0**: Inventories all files, classifies by domain, triages with grep
2. **Phase 1**: Spawns parallel auditor agents (3-4 files each), including
   caa-code-correctness-agent for line-level correctness checks
3. **Phase 1b** (unless `--skip-cross-layer-audit`): Dispatches
   **caa-cross-layer-auditor-agent** ONCE per audit (not per domain) — this agent
   hunts cross-file mismatches that single-file auditors structurally cannot detect:
   env-var name drift, default-value drift, schema-vs-code mismatch, removed-API-
   still-called, hidden ops prerequisites. Findings span the whole repo by definition.
   See TRDD-60f53034 §3.5.

   **Invocation** (single agent dispatch, not a per-domain swarm):

   | Input | Source |
   |---|---|
   | `PR_NUMBER` | From PR context |
   | `PR_DESCRIPTION_FILE` | Path to file containing PR body |
   | `DIFF_FILE` | Path to unified diff of the PR |
   | `REPO_PATH` | `--scope` directory |
   | `REPORT_PATH` | Under `--report-dir` (e.g. `<report-dir>/cross-layer/CL-P0-A0-cross-layer.md`) |
   | `AGENT_PREFIX` | Recommended: `CL-P0-A0` |

4. **Phase 2**: Verification swarm cross-checks all audit reports
5. **Phase 3**: Gap-fill audits missed files (iterative until 100% coverage)
6. **Phase 4**: Consolidation per domain (dedup, severity harmonization).
   **NOTE (cross-layer findings):** caa-cross-layer-auditor-agent emits findings
   with `Layer: structural` by definition. These findings cite MULTIPLE files
   (in a `Related files:` section), and consolidation MUST preserve all
   related-file references — never collapse a cross-layer finding to a single
   file or drop the `Related files:` block. See TRDD-60f53034 §3.5.
7. **Phase 4b**: Security review — spawns caa-security-review-agent for vulnerability, secrets, and dependency scanning
8. **Phase 4c** (if `--extended`): Invokes caa-scenario-generator-skill on the
   scope to emit scenarios.json + detected-types.json. Then spawns the
   caa-scenario-walker-agent swarm (one per scenario or cluster) — each agent
   plays the actor_role from its scenario and walks the static call graph for
   divergences. In parallel, spawns the caa-assumption-auditor-agent swarm
   (one per high-risk file from the triage in Phase 0). Reports from these
   swarms feed into Phase 4 consolidation as `scenario_divergence` and
   `unguarded_assumption` finding categories, which cross-merge with
   line-level findings into single multi-evidence findings.
9. **Phase 5**: Generates actionable TODO files per scope. When merged
   findings have multiple evidence frames (line + scenario + assumption),
   the TODO entry includes optional sections surfacing each frame so the fix
   agent picks the clearest framing.
10. **Phase 6** (if `--fix`): Applies fixes from TODOs
11. **Phase 7** (if `--fix`): Verifies fixes, loops if regressions found
12. **Phase 8**: Final merged report
- When `--worktrees` is enabled, each agent swarm runs in isolated git worktrees. Fix agent branches are merged back sequentially after completion.

**NOTE (BLOCKER short-circuit):** If caa-claim-verification-agent emits a BLOCKER
(functional completeness failed), the orchestrator MUST skip all downstream
phases (Phase 2..N) and emit a final report containing only the BLOCKER and
the original claim-verification output. The user can re-run with the BLOCKER
acknowledged after the PR author addresses the unmet criteria.

The `--skip-linked-issue` flag bypasses the linked-issue verification sub-step
within caa-claim-verification-agent but does NOT disable the BLOCKER
short-circuit for other claim-verification failures.

**NOTE (agent-written code detection in Phase 1):** The orchestrator MUST check
three conditions before invoking caa-code-correctness-agent: (a) explicit
`--agent-written-code`, (b) `--no-agent-written-code` (force off), (c)
auto-detection from PR description / author / co-authored-by. The agent
invocation should set the `AGENT_WRITTEN_CODE_MODE` environment variable or
equivalent parameter to true/false accordingly.

Auto-detection precedence (highest to lowest):
1. `--no-agent-written-code` — force OFF regardless of other signals
2. `--agent-written-code` — force ON regardless of auto-detection
3. Auto-detection signals:
   - PR description mentions Claude / Codex / Cursor / Copilot / GPT-N /
     Gemini / Aider / Continue / Cline
   - PR author matches `*[bot]` pattern (claude[bot], copilot[bot], etc.)
   - Any commit in the PR has `Co-authored-by: claude` or similar agent
     attribution trailer

When `AGENT_WRITTEN_CODE_MODE=true`, caa-code-correctness-agent activates the
agent-written code sub-checklist (over-engineering, hallucinated APIs, drift
from spec, etc.) in addition to its normal correctness checks.

## Reports

All reports written to `--report-dir` (default: reports/code-auditor/).
See the `caa-codebase-audit-and-fix-skill` skill for report naming conventions.
