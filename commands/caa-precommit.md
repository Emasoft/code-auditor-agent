---
name: caa-precommit
description: >
  Pre-commit gate — ultracode scan-only audit of the STAGED files only, via the shared
  caa-engine (map: one opus auditor per file → filter: adversarial verify → reduce: one
  consolidated gate report). PASS only when no CRITICAL/MAJOR survives; otherwise FAIL with
  the blocking findings. Fast, no fixes, no git writes. Final report → reports/code-auditor-agent/.
argument-hint: "[conc=N]"
---

# Pre-Commit Gate (ultracode)

## Usage

```
/caa-precommit            # gate the staged files, scan-only
/caa-precommit conc=4     # cap concurrent opus auditors (default 4 — staged sets are small)
```

This is the pre-commit specialization of the CAA ultracode engine: it audits ONLY what is
staged (`git diff --cached`), so it is fast enough to run before a commit. It is the
interactive companion to a `pre-commit` hook — PASS/FAIL verdict + one consolidated report;
never edits files, never runs git writes.

Also accepts the shared engine knobs — `component=NAME`, `min-severity=SEV`, `lenses=p1,p2`,
`no-project-lenses` — same semantics as `/caa-scan` (map to `component` / `minSeverity` /
`projectLenses` in the Step C args; auto-ingest CLAUDE.md + .claude/rules/*.md as
projectLenses unless `no-project-lenses`).

## Orchestrator contract — run EXACTLY these steps

### Step A — effort + model guard (opus-only, xhigh floor)
This engine ONLY works on opus at high reasoning effort.

```bash
echo "effort=${CLAUDE_EFFORT:-unknown}"
```
- `max` or `xhigh` → proceed.
- anything lower (or `unknown`) → tell the user: "caa-precommit needs `/effort max` (or at
  least `xhigh`) — ultracode pairs xhigh with workflow permission. Raise effort and re-run."
  then STOP. Never run below xhigh. (The engine pins `model:'opus'`; effort is inherited.)

### Step B — resolve the staged scope
```bash
ROOT="$(git rev-parse --show-toplevel)"
RUN_ID="$(date +%s)-$$"        # namespaces the engine temp dir — concurrent runs never collide
git -C "$ROOT" diff --cached --name-only --diff-filter=ACMR
```
Keep existing source files only (drop deletions, binaries, gitignored paths). Resolve each
to an ABSOLUTE path. If the staged set is empty → report "nothing staged to gate" and stop.

### Step C — run the shared engine (Workflow tool)
Call the Workflow tool pointing at the bundled engine, passing `args` as a real JSON object
(NOT a string). `conc` defaults to 4 (override from `$ARGUMENTS`):

```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js",
  args: {
    root: "<ABS_REPO_ROOT>",
    files: ["<abs path 1>", "<abs path 2>", ...],   // the resolved staged set
    mode: "scan",
    scopeLabel: "precommit",
    reportType: "gate",
    reportSuffix: "precommit-gate",
    runId: "<RUN_ID>",
    conc: 4
  }
})
```

The engine writes intermediates to a per-run temp dir (returned as `tmpDir`) and the ONE
consolidated gate report to `reports/code-auditor-agent/<TS>-precommit-gate.md`. It returns
`{scanned, verified, problems[], reduce, finalReport, findingsJson, tmpDir, ...}` —
`finalReport` is null when `reduce` is "failed" (report that explicitly).

### Step D — present the verdict
Read the first line of `finalReport` (`VERDICT: PASS` / `VERDICT: FAIL (…)`). Tell the user
the verdict, the CRITICAL/MAJOR counts, any non-verified files, and the absolute report path.
On FAIL: instruct the user to resolve the blocking findings and re-run before committing. Then
delete the per-run temp dir the engine returned: `rm -rf "<result.tmpDir>"`.

## RULES
- **opus only** (engine pins `model:'opus'`); require `$CLAUDE_EFFORT` ≥ xhigh (prefer max). Never sonnet/haiku.
- **Single source of truth:** the audit logic lives ONLY in `scripts/workflows/caa-engine.js`; this command just resolves scope + config. Never duplicate the engine here.
- **Scan-only:** no edits, no git writes. (Fix mode is a separate command/phase with worktree isolation.)
- **Final report ALWAYS → `reports/code-auditor-agent/`;** intermediates in the deletable temp dir, purged in Step D.
- **Never** use llm-externalizer. The engine is robust by construction (`.catch` + rate-limit re-queue; cap-then-report).
