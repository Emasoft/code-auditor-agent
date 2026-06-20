---
name: caa-verify-implementation-and-fix
description: >
  Verify an EXISTING implementation against a TRDD/spec AND repair it FIX-AS-YOU-GO via the shared
  caa-engine (task=spec-compliance, mode=scan-and-fix): each per-file opus agent classifies its file's
  spec clauses AND, in the SAME read, corrects every VIOLATED clause and completes every PARTIAL one in
  place — one read, no separate fixer. A different verifier confirms each fix; the reduce reports FIXED /
  STILL-VIOLATED / UNIMPLEMENTED. Edits files in the working tree (never commits). It completes an
  existing implementation; it never scaffolds one from the spec. Reports → reports/code-auditor-agent/.
argument-hint: "<trdd-or-spec-file> [path/glob ...] [conc=N] [component=NAME]"
---

# Verify implementation & fix (ultracode, fix-as-you-go)

Verify an **already-built** implementation against its TRDD/spec and, in the SAME pass, FIX what is
wrong and COMPLETE what is unfinished — the code is read ONCE (no audit-now-fix-later double read). It
completes an EXISTING implementation; a requirement with no implementation at all is REPORTED, never
built from scratch (that is `/workflow-verified-implement`'s job). For read-only verification use
`/caa-verify-implementation`.

## Usage

```
/caa-verify-implementation-and-fix design/tasks/TRDD-…-feature.md      # verify + repair a TRDD's impl
/caa-verify-implementation-and-fix docs/REQUIREMENTS.md src/ lib/      # verify + repair code vs the spec
/caa-verify-implementation-and-fix api-contract.md src/api conc=4
```

`$ARGUMENTS`: FIRST token = the **TRDD or spec/requirements file** (required); remaining tokens scope the
code. `conc=N` (default 6); `component=NAME` lands reports in `reports/code-auditor-agent/NAME/`.

## Orchestrator contract

### Step A — choose the execution path, then guard effort
```bash
echo "effort=${CLAUDE_EFFORT:-unknown}   caa_ultracode=${CAA_ULTRACODE:-auto}"
```
Pick the path per `scripts/workflows/caa-simple-scan.md` ("When this path runs"):
- **SIMPLE-SCAN** if you do NOT have the `Workflow` tool, OR `CAA_ULTRACODE` ∈ {0,off,false,no}. Effort
  guard does NOT apply — go to Step B and run the fallback (mode `scan-and-fix`) at Step D.
- **ULTRACODE** otherwise. Effort guard applies: `max`/`xhigh` → proceed; lower/`unknown` → tell the user
  to `/effort max` (or `xhigh`) and STOP (or set `CAA_ULTRACODE=0` for the simple verify-and-fix).

### Step B — resolve the spec/TRDD + scope (TRDD-aware) AND safety-guard (THIS EDITS FILES)
```bash
ROOT="$(git rev-parse --show-toplevel)"
RUN_ID="$(date +%s)-$$"        # namespaces the engine temp dir — concurrent runs never collide
git -C "$ROOT" status --porcelain
```
- Resolve the spec/TRDD file + the code scope EXACTLY as in `/caa-verify-implementation` Step B
  (TRDD-aware: a TRDD with no explicit scope defaults to the files its `implementation-commits:` touched;
  else explicit tokens, else whole-repo minus gitignored/docs/deps/fixtures/reports/binaries/the spec).
  Resolve all to ABSOLUTE paths. Empty code set → report and stop.
- **The agents edit files IN PLACE.** Confirm the working tree is clean (or the user is on a
  throwaway/feature branch) so the diff is reviewable and revertible. If there are uncommitted changes,
  warn and ask the user to commit/stash or confirm before proceeding. Recommend (do not force) a
  dedicated branch. One file per agent ⇒ parallel in-place edits never conflict; do NOT hand-roll
  per-file worktrees.

### Step C — cost guard (whole-repo / large scopes)
As in `/caa-verify-implementation` Step C (each file ≈ 300k tok for verify, plus the in-place fix +
fix-verify). Confirm or narrow large whole-repo-default scopes before launching.

### Step D — run verify+fix (ultracode engine, or simple-scan fallback)

**ULTRACODE path** — run the shared engine in spec-compliance fix-as-you-go mode:
```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js",
  args: {
    root: "<ABS_REPO_ROOT>",
    files: ["<abs code file>", ...],
    task: "spec-compliance",
    mode: "scan-and-fix",
    specFile: "<ABS_SPEC_OR_TRDD_FILE>",
    scopeLabel: "<whole | TRDD-scoped | the given scope> vs <spec/TRDD basename>",
    reportSuffix: "verify-fix",
    conc: 6,
    component: "<component= value, omit if not given>",
    runId: "<RUN_ID>"
  }
})
```
The engine runs map-and-fix (each agent classifies AND repairs/completes its ONE file in place against
the spec) → filter (a different agent verifies each fix) → reduce (one report `…-verify-fix.md` +
`…-verify-fix.findings.json`: FIXED / STILL-VIOLATED / UNIMPLEMENTED). It returns
`{finalReport, findingsJson, specFix:true, verified, problems[], tmpDir, ...}`. If the `Workflow(...)`
call throws for a nesting/availability reason, fall through to simple-scan.

**SIMPLE-SCAN path** — follow `${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-simple-scan.md` with
`task: "spec-compliance", mode: "scan-and-fix"`: it classifies each file against the spec and applies
the SAME in-place fix-as-you-go repairs (one pass, no fixer swarm), re-reads to confirm no regression,
and writes the report:
```
{ root: "<ABS_REPO_ROOT>", files: ["<abs code file>", ...],
  task: "spec-compliance", specFile: "<ABS_SPEC_OR_TRDD_FILE>", mode: "scan-and-fix",
  reportSuffix: "verify-fix", scopeLabel: "<scope> vs <spec/TRDD basename>",
  component: "<component= value, omit if not given>" }
```
Both write to `reports/code-auditor-agent/`; the same in-place-edit / never-commit rules apply.

### Step E — present + verify
Read `finalReport`'s `SUMMARY:` line ("SUMMARY: <f> FIXED, <v> STILL-VIOLATED, <u> UNIMPLEMENTED of <t>
spec clauses across <n> files"); report those counts and BOTH report paths (a null `finalReport` with
`reduce: "failed"` means that consolidation rate-limited out — say so). Lead with what was **FIXED**,
then **STILL-VIOLATED** (fix failed — needs attention), then **UNIMPLEMENTED** (genuine gaps NOT built —
offer `/workflow-verified-implement` for those). Then show `git -C "$ROOT" diff --stat` so the user can
review the applied edits, and recommend running the project's tests/build. Do NOT commit or push — the
user reviews the diff first. Purge the per-run temp dir: `rm -rf "<result.tmpDir>"`.

## RULES
- **opus only** (engine pins it); `$CLAUDE_EFFORT` ≥ xhigh (prefer max). Never sonnet/haiku.
- **Fix-as-you-go:** the discovering agent fixes/completes in the SAME read — one file per agent, edited
  IN PLACE (no separate fixer re-reading the file, no merge-back). **NEVER commit/push** — the user reviews.
- **Completes an EXISTING implementation** — root-cause fixes only (no hacks/workarounds/bypasses, no
  unrequested fallbacks, fail-fast). It NEVER scaffolds a feature from the spec; a wholly-unimplemented
  requirement is REPORTED as a gap, not built.
- **Dual-path:** ultracode engine when `Workflow` is available and `CAA_ULTRACODE` is not disabled; else
  the simple-scan fallback (`scripts/workflows/caa-simple-scan.md`, spec-compliance + `scan-and-fix`).
- **Single source of truth:** all logic is in `scripts/workflows/caa-engine.js`; this command resolves spec/TRDD + scope + safety.
- **Final reports → `reports/code-auditor-agent/`;** temp purged in Step E. **Never** use llm-externalizer.
