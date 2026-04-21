# Report Naming Convention

## Table of Contents

- [Canonical Pattern](#canonical-pattern)
- [Main-Root Resolution (Worktree-Safe)](#main-root-resolution-worktree-safe)
- [Timestamp Format](#timestamp-format)
- [PIPELINE_TS vs Per-Agent TS](#pipeline_ts-vs-per-agent-ts)
- [Filename Table](#filename-table)
- [Agent-Prefixed Finding IDs](#agent-prefixed-finding-ids)
- [Pre-Pass Cleanup](#pre-pass-cleanup)

## Canonical Pattern

EVERY file this plugin writes under `reports/code-auditor/` MUST follow:

```
$MAIN_ROOT/reports/code-auditor/<ts±tz>-<slug>.<ext>
```

- `$MAIN_ROOT` — absolute path to the MAIN project root, NEVER a worktree path
- `reports/` — hard-coded folder name, must be gitignored in the user's project
- `code-auditor/` — this plugin's component subdirectory
- `<ts±tz>` — local time + GMT offset, compact form: `%Y%m%d_%H%M%S%z` → `20260421_183012+0200`
- `<slug>` — descriptive identifier (type, pass, run id, agent prefix, uuid as needed)
- `<ext>` — `.md`, `.json`, or `.txt` depending on content

**This is the same rule applied to every agent, skill, tool, and script across every project. No carve-outs, no per-tool exceptions.** Reports, ledgers, manifests, checkpoints, queues, intermediate files, final files — all live under the same canonical path.

Gitignore: both `$MAIN_ROOT/reports/` and `$MAIN_ROOT/reports_dev/` MUST be gitignored in every project where this plugin runs. Reports contain private data (PR diffs, commit history, absolute paths, internal discussion, possibly secrets that happened to appear in logs); committing them is a leak.

## Main-Root Resolution (Worktree-Safe)

Inside a worktree, `$(pwd)` resolves to the worktree path, not the main project. Reports MUST land in the MAIN project's `reports/` — never the worktree's — so artifacts survive worktree cleanup and stay in one place across parallel agents.

Canonical shell prologue (paste into every orchestrator spawn path and every script that writes reports):

```bash
# Primary: git worktree list — the first line is always the MAIN checkout,
# even when the shell is running inside a linked worktree.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  MAIN_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
# Fallback 1: CLAUDE_PROJECT_DIR (Claude Code sets this to the
# originally-opened project path, unchanged across worktrees).
elif [ -n "${CLAUDE_PROJECT_DIR}" ]; then
  MAIN_ROOT="${CLAUDE_PROJECT_DIR}"
else
  echo "ERROR: cannot resolve MAIN_ROOT (not a git repo, CLAUDE_PROJECT_DIR unset)" >&2
  exit 1
fi
ABSOLUTE_REPORT_DIR="${MAIN_ROOT}/reports/code-auditor"
mkdir -p "${ABSOLUTE_REPORT_DIR}"
```

## Timestamp Format

```bash
TS="$(date +%Y%m%d_%H%M%S%z)"
# Examples:
#   20260421_183012+0200   (Rome, CEST)
#   20260421_123012-0500   (New York, EST)
#   20260421_163012+0000   (UTC)
```

Rules:
- **Local time**, never UTC (`date -u` forbidden) — humans need to tie reports to their workday without timezone arithmetic.
- **`%z`** appended — a bare `YYYYMMDD_HHMMSS` is ambiguous across machines, worktrees, and shared filesystems.
- **Compact `±HHMM`** — no colon (Windows filesystems reject `±HH:MM`).

## PIPELINE_TS vs Per-Agent TS

The orchestrator uses TWO timestamps — one shared across the pipeline, one per agent spawn. Both follow the same `%Y%m%d_%H%M%S%z` format; they differ only in scope.

| Timestamp | Scope | Used for |
|-----------|-------|----------|
| `PIPELINE_TS` | Computed ONCE at pipeline start; shared by all coordination files for that pipeline run | Fix Dispatch Ledger, agent manifest, run manifest, per-group file lists, gap-fill queue, PR description / commits cache, checkpoints |
| Per-agent `TS` | Computed at each agent spawn | Every agent's output file (correctness, claims, review, security, audit, verify, gapfill, consolidated, fixverify, fix-summary, test-outcome, lint-outcome, recovery-log, intermediate, final, escalation, TODO) |

**Why both are needed:**
- Coordination files (ledger, manifest) need a stable path within a pipeline run so the orchestrator, fix agents, and fix-verifiers all open the exact same file. `PIPELINE_TS` gives every coordination file a consistent timestamp — the orchestrator records each path in memory at creation and passes it as an explicit argument to every downstream agent. Agents never re-compute `PIPELINE_TS` — they always receive it via the prompt.
- Per-agent output files are independent; each gets a fresh timestamp so `ls -t` lists them in real completion order.

**Orchestrator prologue:**

```bash
# --- at pipeline start ---
PIPELINE_TS="$(date +%Y%m%d_%H%M%S%z)"   # ONE per pipeline run
RUN_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex[:8])")
PASS_NUMBER=1

# Coordination paths (record these in memory and thread through every agent):
LEDGER="${ABSOLUTE_REPORT_DIR}/${PIPELINE_TS}-caa-fix-dispatch-P${PASS_NUMBER}-R${RUN_ID}.json"
MANIFEST="${ABSOLUTE_REPORT_DIR}/${PIPELINE_TS}-caa-agents-P${PASS_NUMBER}-R${RUN_ID}.json"
RUN_MANIFEST="${ABSOLUTE_REPORT_DIR}/${PIPELINE_TS}-caa-manifest-R${RUN_ID}.json"
GAPFILL_QUEUE="${ABSOLUTE_REPORT_DIR}/${PIPELINE_TS}-caa-gapfill-queue-P${PASS_NUMBER}-R${RUN_ID}.txt"
PR_DESC_FILE="${ABSOLUTE_REPORT_DIR}/${PIPELINE_TS}-caa-pr-desc-P${PASS_NUMBER}-R${RUN_ID}.txt"
PR_COMMITS_FILE="${ABSOLUTE_REPORT_DIR}/${PIPELINE_TS}-caa-pr-commits-P${PASS_NUMBER}-R${RUN_ID}.json"

# --- at each agent spawn ---
TS="$(date +%Y%m%d_%H%M%S%z)"            # fresh per agent
UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
REPORT_PATH="${ABSOLUTE_REPORT_DIR}/${TS}-caa-correctness-P${PASS_NUMBER}-R${RUN_ID}-${UUID}.md"
# Pass LEDGER, MANIFEST, REPORT_PATH as explicit arguments in the agent prompt.
```

**Recovery after compaction:** Coordination files are discovered via glob `*-caa-fix-dispatch-P${PASS_NUMBER}-R${RUN_ID}.json` (one match per pass-run). Since `RUN_ID` + `PASS_NUMBER` uniquely identify a pipeline run, the glob pattern returns at most one file, and the orchestrator re-reads it to restore state.

## Filename Table

Every file this plugin writes uses `<ts±tz>-<slug>.<ext>`. No exceptions.

| File | Pattern (relative to `$MAIN_ROOT/reports/code-auditor/`) | Timestamp |
|------|---------------------------------------------------------|-----------|
| Correctness (per-domain) | `<TS>-caa-correctness-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Claim verification | `<TS>-caa-claims-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Security review | `<TS>-caa-security-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Skeptical review | `<TS>-caa-review-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Audit findings | `<TS>-caa-audit-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Verification | `<TS>-caa-verify-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Gap-fill | `<TS>-caa-gapfill-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Consolidated (per-domain) | `<TS>-caa-consolidated-{domain}.md` | per-agent |
| Fix verify | `<TS>-caa-fixverify-P{N}-R{RUN_ID}-{uuid}.md` | per-agent |
| Merged intermediate | `<TS>-caa-pr-review-P{N}-intermediate.md` | merge-time |
| Final dedup report | `<TS>-caa-pr-review-P{N}.md` | dedup-time |
| Audit FINAL | `<TS>-caa-audit-FINAL.md` | merge-time |
| Fix summary (per-domain) | `<TS>-caa-fixes-done-P{N}-{domain}.md` | per-agent |
| Test outcome | `<TS>-caa-tests-outcome-P{N}.md` | per-agent |
| Per-group fix issues | `<PIPELINE_TS>-caa-fix-group-{GROUP_ID}.md` | pipeline-start |
| Per-group lint | `<TS>-caa-lint-group-{GROUP_ID}.md` | per-agent |
| Per-group security | `<TS>-caa-security-group-{GROUP_ID}.md` | per-agent |
| Per-group review | `<TS>-caa-review-group-{GROUP_ID}.md` | per-agent |
| Lint outcome (joined) | `<TS>-caa-lint-outcome-P{N}.md` | per-agent |
| Recovery log | `<TS>-caa-recovery-log-P{N}.md` | per-agent |
| PR review final | `<TS>-caa-pr-review-and-fix-FINAL.md` | pipeline-end |
| Escalation (max-passes reached) | `<TS>-caa-pr-review-and-fix-escalation.md` | pipeline-end |
| TODO file | `<TS>-TODO-{scope}-changes.md` | per-agent |
| **Fix Dispatch Ledger** | `<PIPELINE_TS>-caa-fix-dispatch-P{N}-R{RUN_ID}.json` | pipeline-start |
| **Agent manifest** | `<PIPELINE_TS>-caa-agents-P{N}-R{RUN_ID}.json` | pipeline-start |
| **Run manifest** | `<PIPELINE_TS>-caa-manifest-R{RUN_ID}.json` | pipeline-start |
| **Fix checkpoint (per-domain)** | `<PIPELINE_TS>-caa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` | pipeline-start |
| **Per-group file list** | `<PIPELINE_TS>-caa-group-{GROUP_ID}.txt` | pipeline-start |
| **Gap-fill queue** | `<PIPELINE_TS>-caa-gapfill-queue-P{N}-R{RUN_ID}.txt` | pipeline-start |
| **PR description cache** | `<PIPELINE_TS>-caa-pr-desc-P{N}-R{RUN_ID}.txt` | pipeline-start |
| **PR commits cache** | `<PIPELINE_TS>-caa-pr-commits-P{N}-R{RUN_ID}.json` | pipeline-start |

Agents honor the explicit `REPORT_PATH`, `LEDGER_PATH`, etc. they receive — they do NOT regenerate timestamps themselves (orchestrator-generated paths and agent-written paths must not diverge).

## Agent-Prefixed Finding IDs

**Finding IDs** include the pass number AND a unique agent prefix to avoid collisions:

```
Phase 1 (swarm): Each correctness agent gets a unique prefix A0, A1, A2, ...
  Agent 0: CC-P1-A0-001, CC-P1-A0-002, ...
  Agent 1: CC-P1-A1-001, CC-P1-A1-002, ...
  Agent 2: CC-P1-A2-001, CC-P1-A2-002, ...

Phase 2 (single): CV-P1-001, CV-P1-002, ...
Phase 3 (single): SR-P1-001, SR-P1-002, ...
Phase 4 (single): SC-P1-001, SC-P1-002, ...
```

The orchestrator assigns prefixes at spawn time:

```
domains = sorted(list of domains with changed files)
for i, domain in enumerate(domains):
    agent_prefix = f"A{i:X}"  # A0, A1, A2, ..., AF, A10, ...
    finding_id_prefix = f"CC-P{PASS_NUMBER}-{agent_prefix}"
```

This guarantees zero ID collisions because each agent has a unique prefix within the pass, each pass has a unique number, and UUIDs in filenames prevent file-level collisions.

## Pre-Pass Cleanup

Before each pass, run the pre-pass cleanup protocol (see `procedure-1-review.md`). The merge scripts use glob patterns that tolerate the `<ts±tz>-` prefix, so both prefixed and non-prefixed files are discovered — old runs are not orphaned. The merge scripts scope by `P{N}` and `R{RUN_ID}` to isolate prior-pass and prior-run files automatically.
