---
name: caa-scan
description: >
  Whole-codebase (or explicit-scope) scan-only audit via the shared caa-engine: map (one
  opus auditor per file) → filter (adversarial verify) → reduce (one consolidated audit
  report). No fixes, no git writes. Final report → reports/code-auditor-agent/. Whole-repo
  runs are expensive — the command estimates cost and confirms before a large swarm.
argument-hint: "[path/glob ...] [conc=N] [component=NAME] [min-severity=SEV] [lenses=...]"
---

# Codebase Scan (ultracode)

## Usage

```
/caa-scan                       # whole codebase (after a cost-estimate confirmation)
/caa-scan scripts/ skills/      # only these paths/globs
/caa-scan scripts/publish.py conc=2 # a single file, low concurrency
/caa-scan src/chat component=chat-browser-audit min-severity=MAJOR lenses=docs/ui-invariants.md
```

`$ARGUMENTS` (optional): one or more paths/globs to scope the scan (default: whole repo);
`conc=N` max concurrent opus auditors (default 6);
`component=NAME` land the reports in `reports/code-auditor-agent/NAME/` (per-feature subfolder);
`min-severity=CRITICAL|MAJOR|MINOR` render only that tier+ in the markdown (findings.json keeps ALL);
`lenses=p1,p2` extra project-invariant rule files every auditor must also apply;
`template=path` a report-template file the reduce step follows;
`no-project-lenses` disable the automatic CLAUDE.md/.claude/rules ingestion (see Step B2).

## Orchestrator contract

### Step A — effort + model guard
```bash
echo "effort=${CLAUDE_EFFORT:-unknown}"
```
`max`/`xhigh` → proceed; lower/`unknown` → tell the user to `/effort max` (or `xhigh`) and STOP.

### Step B — resolve the scope
```bash
ROOT="$(git rev-parse --show-toplevel)"
RUN_ID="$(date +%s)-$$"        # namespaces the engine temp dir — concurrent runs never collide
```
- If paths/globs were given → expand them to existing source files under `$ROOT`.
- Else (whole repo) → `git -C "$ROOT" ls-files`, then EXCLUDE: gitignored paths, `docs/`,
  dependencies/vendored trees, fixtures and intentionally-flawed sample files, `reports/`,
  `reports_dev/`, `*_dev/`, build output, and binaries. Include source in any language plus
  `skills/`, `commands/`, `agents/`, reference `.md`, YAML workflows, and config files.
- Resolve all to ABSOLUTE paths. Empty set → report and stop.

### Step B2 — project lenses (auto-ingest the repo's own rules)
Unless `no-project-lenses` was passed: collect the TARGET repo's own invariant files —
`$ROOT/CLAUDE.md` (if present) plus every `$ROOT/.claude/rules/*.md` — and append any
`lenses=…` paths the user gave. Pass the list as `projectLenses` in Step D and note them in
your summary ("audited against N project lens files"). The project's own rules are the most
important lenses for a project-aware audit; this makes them first-class criteria.

### Step C — cost guard (whole-repo / large scopes)
Each file costs roughly ~300k subagent tokens at xhigh (map+filter). If the resolved set has
**more than 8 files** AND no explicit scope was given, surface the count and an estimate
("~N files × ~300k ≈ … tokens") and ask the user to confirm or narrow the scope before
launching. (An explicit path/glob scope is treated as already-confirmed intent.)

### Step D — run the shared engine
```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js",
  args: {
    root: "<ABS_REPO_ROOT>",
    files: ["<abs>", ...],
    mode: "scan",
    scopeLabel: "<whole | the given scope>",
    reportType: "audit",
    reportSuffix: "scan",
    conc: 6,
    component: "<component= value, omit if not given>",
    minSeverity: "<min-severity= value, omit if not given>",
    projectLenses: ["<Step B2 paths>", ...],
    reportTemplate: "<template= value, omit if not given>",
    runId: "<RUN_ID>"
  }
})
```

### Step E — present
Read `finalReport`'s `SUMMARY:` line; report the severity counts, any non-verified files, the
absolute report path, AND the structured `findingsJson` path (one record per finding including
refuted/downgraded — pipe it into your own renderer if you need a custom format). If `reduce`
is "failed", `finalReport` is null — say so explicitly. Then purge the per-run temp dir the
engine returned: `rm -rf "<result.tmpDir>"`.

## RULES
- **opus only** (engine pins it); `$CLAUDE_EFFORT` ≥ xhigh (prefer max). Never sonnet/haiku.
- **Single source of truth:** all audit logic is in `scripts/workflows/caa-engine.js`; this command only resolves scope + config.
- **Scan-only** (no edits/git). For fixes use the scan-and-fix command (worktree-isolated, separate phase).
- **Cost-aware:** confirm before large unscoped swarms. **Final report → `reports/code-auditor-agent/`;** temp purged in Step E.
- **Never** use llm-externalizer.
