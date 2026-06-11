---
name: caa-delta
description: >
  Recheck recent changes — scan-only audit of files changed since a git ref (default
  origin/main…HEAD), via the shared caa-engine (map → filter → reduce). Optionally traces
  direct dependents of the changed files. No fixes, no git writes. Final report →
  reports/code-auditor-agent/.
argument-hint: "[ref] [deps] [conc=N]"
---

# Delta Audit (ultracode)

## Usage

```
/caa-delta                  # files changed vs origin/main (or HEAD~1 if no upstream)
/caa-delta HEAD~5           # files changed in the last 5 commits
/caa-delta origin/main deps # changed files PLUS their direct dependents
```

`$ARGUMENTS` (optional): a git `ref` (base to diff against; default `origin/main`, fallback
`HEAD~1`); `deps` to also include direct dependents of the changed files; `conc=N` (default 6).
Also accepts the shared engine knobs — `component=NAME`, `min-severity=SEV`, `lenses=p1,p2`,
`template=path`, `no-project-lenses` — same semantics as `/caa-scan` (map to `component` /
`minSeverity` / `projectLenses` / `reportTemplate` in the Step C args).

## Orchestrator contract

### Step A — choose the execution path, then guard effort
```bash
echo "effort=${CLAUDE_EFFORT:-unknown}   caa_ultracode=${CAA_ULTRACODE:-auto}"
```
Pick the path per `scripts/workflows/caa-simple-scan.md` ("When this path runs"):
- **SIMPLE-SCAN** if you do NOT have the `Workflow` tool, OR `CAA_ULTRACODE` ∈ {0,off,false,no}.
  Effort guard does NOT apply — go to Step B and run the fallback at Step C.
- **ULTRACODE** otherwise. Effort guard applies: `max`/`xhigh` → proceed; lower/`unknown` → tell the
  user to `/effort max` (or `xhigh`) and STOP (or set `CAA_ULTRACODE=0` for the simple scan).

### Step B — resolve the delta scope
```bash
ROOT="$(git rev-parse --show-toplevel)"
RUN_ID="$(date +%s)-$$"        # namespaces the engine temp dir — concurrent runs never collide
REF="${1:-origin/main}"; git -C "$ROOT" rev-parse --verify "$REF" >/dev/null 2>&1 || REF="HEAD~1"
git -C "$ROOT" diff "$REF"...HEAD --name-only --diff-filter=ACMR
```
Keep existing source files only (drop deletions, binaries, gitignored, `reports*/`, fixtures).
If `deps` was passed, additionally include files that import/reference the changed files
(use Serena `find_referencing_symbols` or grep for imports of each changed module). Resolve
all to ABSOLUTE paths. Empty set → report "no changes since `<ref>`" and stop.

### Step C — run the audit (ultracode engine, or simple-scan fallback)

**ULTRACODE path** — run the shared engine:
```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js",
  args: {
    root: "<ABS_REPO_ROOT>",
    files: ["<abs>", ...],
    mode: "scan",
    scopeLabel: "delta-since-<ref>",
    reportType: "audit",
    reportSuffix: "delta",
    runId: "<RUN_ID>",
    conc: 6
  }
})
```
If the `Workflow(...)` call throws for a nesting/availability reason, fall through to simple-scan.

**SIMPLE-SCAN path** — follow `${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-simple-scan.md` with:
```
{ root: "<ABS_REPO_ROOT>", files: ["<abs>", ...],
  lensDir: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/lenses", projectLenses: ["<lenses>", ...],
  reportType: "audit", reportSuffix: "delta", scopeLabel: "delta-since-<ref>",
  diffRef: "<ref>", mode: "scan" }
```
Same report shape → `reports/code-auditor-agent/`; Step D reads it identically.

### Step D — present
Report `finalReport`'s `SUMMARY:` counts, any non-verified files, and the absolute report
path (if `reduce` is "failed", `finalReport` is null — say so explicitly). Then purge the
per-run temp dir the engine returned: `rm -rf "<result.tmpDir>"`.

## RULES
- **opus only** (engine pins it); `$CLAUDE_EFFORT` ≥ xhigh (prefer max). Never sonnet/haiku.
- **Dual-path:** ultracode engine when `Workflow` is available and `CAA_ULTRACODE` is not disabled;
  else the **simple-scan fallback** (`scripts/workflows/caa-simple-scan.md`). Effort guard = ultracode only.
- **Single source of truth:** audit logic is ONLY in `scripts/workflows/caa-engine.js`; this command resolves the delta scope + config.
- **Scan-only** (no edits/git). **Final report → `reports/code-auditor-agent/`;** temp purged in Step D.
- **NOT a substitute for a full audit** — a delta misses defects in unchanged files that the change interacts with; `deps` mitigates but does not eliminate this. **Never** use llm-externalizer.
