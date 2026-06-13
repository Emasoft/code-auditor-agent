---
name: caa-impl-compare
description: >
  Compare multiple candidate implementations of the same task against ONE fixed input/contract via
  the shared caa-engine (task=impl-compare): map (one opus evaluator per candidate, scoring
  correctness/edge-cases/performance/quality) → filter (adversarial verify of each correctness
  verdict) → reduce (a ranking matrix naming the winner). The fixed input is cache-shared across
  every candidate; only the candidate script varies. No edits, no git writes. Final report →
  reports/code-auditor-agent/.
argument-hint: "<input-spec-file> <impl1> <impl2> [impl3 ...] [conc=N] [component=NAME]"
---

# Implementation compare (ultracode)

## Usage

```
/caa-impl-compare contract.md sort_a.py sort_b.py sort_c.py    # rank 3 sorts vs the same contract
/caa-impl-compare bench/input-and-expected.md impls/v1.js impls/v2.js conc=2 component=parser-race
```

`$ARGUMENTS`: the FIRST token is the **input/contract file** (required) — the fixed input(s), the
task contract, and the expected output/behavior every candidate must satisfy (optionally a test
harness). Remaining tokens are the **candidate implementation files** to compare (≥2 expected).
`conc=N` max concurrent opus evaluators (default 6); `component=NAME` → reports under
`reports/code-auditor-agent/NAME/`.

## Orchestrator contract

### Step A — choose the execution path, then guard effort
```bash
echo "effort=${CLAUDE_EFFORT:-unknown}   caa_ultracode=${CAA_ULTRACODE:-auto}"
```
Pick the path per `scripts/workflows/caa-simple-scan.md` ("When this path runs"):
- **SIMPLE-SCAN** if you do NOT have the `Workflow` tool, OR `CAA_ULTRACODE` ∈ {0,off,false,no}.
  The effort guard does NOT apply — go to Step B and run the fallback at Step D.
- **ULTRACODE** otherwise. Effort guard applies: `max`/`xhigh` → proceed; lower/`unknown` → tell the
  user to `/effort max` (or `xhigh`) and STOP — or to set `CAA_ULTRACODE=0` for the lower-fidelity
  simple comparison at any effort.

### Step B — resolve the input/contract + the candidates
```bash
ROOT="$(git rev-parse --show-toplevel)"
RUN_ID="$(date +%s)-$$"        # namespaces the engine temp dir — concurrent runs never collide
```
- The first `$ARGUMENTS` token is the input/contract file → resolve to an ABSOLUTE path. It MUST
  exist and be readable; if missing or not given, report and STOP (there is nothing to compare against).
- Remaining tokens → expand to existing candidate implementation files under `$ROOT`, resolved to
  ABSOLUTE paths. Fewer than 2 candidates → report (a comparison needs ≥2) and stop.

### Step C — cost guard
Each candidate costs roughly ~300k subagent tokens at xhigh (map+filter). If **more than 8
candidates** were resolved, surface the count + an estimate and ask the user to confirm before launching.

### Step D — run the comparison (ultracode engine, or simple-scan fallback)

**ULTRACODE path** — run the shared engine with the impl-compare task:
```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js",
  args: {
    root: "<ABS_REPO_ROOT>",
    files: ["<abs candidate impl>", ...],
    task: "impl-compare",
    inputSpec: "<ABS_INPUT_CONTRACT_FILE>",
    scopeLabel: "<N> impls vs <input basename>",
    reportSuffix: "impl-compare",
    conc: 6,
    component: "<component= value, omit if not given>",
    runId: "<RUN_ID>"
  }
})
```
If this `Workflow(...)` call throws for a nesting/availability reason, fall through to the
simple-scan path below instead of failing.

**SIMPLE-SCAN path** — follow `${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-simple-scan.md` with:
```
{ root: "<ABS_REPO_ROOT>", files: ["<abs candidate impl>", ...],
  task: "impl-compare", inputSpec: "<ABS_INPUT_CONTRACT_FILE>",
  reportSuffix: "impl-compare", scopeLabel: "<N> impls vs <input basename>",
  component: "<component= value, omit if not given>", mode: "scan" }
```
It writes the same report shape to `reports/code-auditor-agent/` — Step E reads it identically.

### Step E — present
Read `finalReport`'s `SUMMARY:` line ("SUMMARY: <p> of <n> implementations PASS correctness;
winner: <impl basename>"); report the winner + why, the pass/fail count, the ranking table's top
rows, the absolute report path, AND the structured `findingsJson` path (one record per
implementation). If `reduce` is "failed", `finalReport` is null — say so. Then purge the per-run
temp dir: `rm -rf "<result.tmpDir>"`.

## RULES
- **opus only** (engine pins it); `$CLAUDE_EFFORT` ≥ xhigh (prefer max) for the ultracode path. Never sonnet/haiku.
- **Dual-path:** ultracode engine when the `Workflow` tool is available and `CAA_ULTRACODE` is not
  disabled; otherwise the **simple-scan fallback** (`scripts/workflows/caa-simple-scan.md`, impl-compare
  mode — single-pass, same report shape). The opus/effort guard applies only to the ultracode path.
- **Single source of truth:** all logic is in `scripts/workflows/caa-engine.js` (task=impl-compare); this command only resolves the input + candidates.
- **Safe execution:** candidates may be RUN against the fixed input only in a sandboxed /tmp copy and only when self-contained + non-destructive; untrusted/network/destructive code is reasoned about statically, never executed. Never edit a candidate.
- **Cost-aware:** confirm before large candidate sets. **Final report → `reports/code-auditor-agent/`;** temp purged in Step E.
- **Never** use llm-externalizer.
