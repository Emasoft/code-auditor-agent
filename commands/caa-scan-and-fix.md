---
name: caa-scan-and-fix
description: >
  Scan AND fix — ultracode audit that also applies fixes, via the shared caa-engine:
  map (audit) → filter (verify) → reduce (scan report) → fix (one opus fixer edits its ONE
  file in place) → fix-verify (different reviewer confirms each fix, no regressions) → final
  fix report. Edits files in the working tree. Final reports → reports/code-auditor-agent/.
argument-hint: "[path/glob ...] [conc=N]"
---

# Scan & Fix (ultracode)

## Usage

```
/caa-scan-and-fix scripts/foo.py          # scan + fix one file
/caa-scan-and-fix scripts/ skills/         # scan + fix these paths/globs
/caa-scan-and-fix                          # whole repo (cost + safety confirmation required)
```

`$ARGUMENTS` (optional): paths/globs to scope (default whole repo); `conc=N` (default 6).
Also accepts the shared engine knobs — `component=NAME`, `min-severity=SEV`, `lenses=p1,p2`,
`template=path`, `no-project-lenses` — with the same semantics as `/caa-scan` (pass them
through as `component` / `minSeverity` / `projectLenses` / `reportTemplate` in Step D's args;
auto-ingest CLAUDE.md + .claude/rules/*.md as projectLenses unless `no-project-lenses`).

## Orchestrator contract

### Step A — choose the execution path, then guard effort
```bash
echo "effort=${CLAUDE_EFFORT:-unknown}   caa_ultracode=${CAA_ULTRACODE:-auto}"
```
Pick the path per `scripts/workflows/caa-simple-scan.md` ("When this path runs"):
- **SIMPLE-SCAN** if you do NOT have the `Workflow` tool, OR `CAA_ULTRACODE` ∈ {0,off,false,no}.
  Effort guard does NOT apply — go to Step B and run the fallback (mode `scan-and-fix`) at Step D.
- **ULTRACODE** otherwise. Effort guard applies: `max`/`xhigh` → proceed; lower/`unknown` → tell the
  user to `/effort max` (or `xhigh`) and STOP (or set `CAA_ULTRACODE=0` for the simple scan-and-fix).

### Step B — safety guard (THIS COMMAND EDITS FILES)
```bash
ROOT="$(git rev-parse --show-toplevel)"
RUN_ID="$(date +%s)-$$"        # namespaces the engine temp dir — concurrent runs never collide
git -C "$ROOT" status --porcelain
```
- The fixers edit files **in place** in the working tree. Confirm the working tree is clean (or
  the user is on a throwaway/feature branch) so the diff is reviewable and revertible. If there
  are uncommitted changes, warn and ask the user to commit/stash or confirm before proceeding.
- Recommend (do not force) running on a dedicated branch. Run-level worktree isolation, if the
  user wants it, is left to the harness/session — do NOT hand-roll per-file worktrees (each fixer
  owns exactly one file, so parallel in-place edits never conflict).

### Step C — resolve the scope
As in `/caa-scan` Step B (explicit paths/globs, else whole-repo `git ls-files` minus
gitignored/docs/deps/fixtures/reports/binaries). Resolve to ABSOLUTE paths. Apply the same
**cost + confirmation** guard for large unscoped sets (each file ≈ 300k tok for scan, plus fix+verify).

### Step D — run scan+fix (ultracode engine, or simple-scan fallback)

**ULTRACODE path** — run the shared engine in fix mode:
```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js",
  args: {
    root: "<ABS_REPO_ROOT>",
    files: ["<abs>", ...],
    mode: "scan-and-fix",
    scopeLabel: "<scope>",
    reportType: "audit",
    reportSuffix: "scan",
    runId: "<RUN_ID>",
    conc: 6
  }
})
```
The engine runs map→filter→reduce (scan report `…-scan.md`) then fix→fix-verify→reduce
(fix report `…-scan-fix.md`), both in `reports/code-auditor-agent/`. Domain-lens findings
(when `domainLenses` is passed) are fed to the fixers too. It returns
`{finalReport, fixReport:{fixed, ofVerified, problems[], report, reduce}, tmpDir, ...}`.
If the `Workflow(...)` call throws for a nesting/availability reason, fall through to simple-scan.

**SIMPLE-SCAN path** (Step A chose it, or the Workflow call was unavailable) — follow `${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-simple-scan.md` with
`mode: "scan-and-fix"`: it writes the scan report, then applies the SAME root-cause fixes in place
(one pass, no fixer swarm), re-reads each file to confirm no regression, and writes the fix report:
```
{ root: "<ABS_REPO_ROOT>", files: ["<abs>", ...],
  lensDir: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/lenses", projectLenses: ["<lenses>", ...],
  reportType: "audit", reportSuffix: "scan", scopeLabel: "<scope>", mode: "scan-and-fix" }
```
Both reports → `reports/code-auditor-agent/`; the same in-place-edit / never-commit rules apply.

### Step E — present + verify
Report: scan summary, files fixed / verified, any unresolved files, and BOTH report paths
(a null `report` with `reduce: "failed"` means that consolidation step rate-limited out —
say so explicitly). Then show the user `git -C "$ROOT" diff --stat` so they can review the
applied edits, and recommend running the project's tests/build. Do NOT commit or push — the
user reviews first. Purge the per-run temp dir the engine returned: `rm -rf "<result.tmpDir>"`.

## RULES
- **opus only** (engine pins it); `$CLAUDE_EFFORT` ≥ xhigh (prefer max). Never sonnet/haiku.
- **Dual-path:** ultracode engine when `Workflow` is available and `CAA_ULTRACODE` is not disabled;
  else the **simple-scan fallback** (`scripts/workflows/caa-simple-scan.md`, `scan-and-fix` mode). This
  execution-path fallback is the user-requested feature — distinct from the "no unrequested fallbacks"
  rule below, which forbids adding fallback CODE to the FIXES. Effort guard = ultracode only.
- **Single source of truth:** all logic is in `scripts/workflows/caa-engine.js`; this command resolves scope + config + safety.
- **Edits in place, one file per fixer** (no conflict, no merge-back). **NEVER commit/push** — the user reviews the diff.
- **Root-cause fixes only** — no hacks/workarounds/bypasses; no unrequested fallbacks; fail-fast.
- **Final reports → `reports/code-auditor-agent/`;** temp purged in Step E. **Never** use llm-externalizer.
