---
trdd-id: 3d971f72-7726-41cd-9029-5257ec65f2ec
title: Advanced ultracode workflows — spec-compliance + impl-compare + reference-plugin patterns
column: design
created: 2026-06-13T18:49:06+0200
updated: 2026-06-13T18:49:06+0200
current-owner: claude-caa-session
assignee: claude-caa-session
priority: 2
severity: MEDIUM
effort: XL
labels: [ultracode, workflow, spec-compliance, impl-compare, cache, reference-plugin]
task-type: feature
parent-trdd: TRDD-d94a7c5e
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, integration]
review-requirements: [human-review]
runtime-targets: [macos, linux]
impacts: [public-api]
external-refs: ["https://code.claude.com/docs/en/sub-agents.md", "https://code.claude.com/docs/en/prompt-caching.md", "https://code.claude.com/docs/en/changelog.md"]
---

# Advanced ultracode workflows — spec-compliance + impl-compare + reference-plugin patterns

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-06-13

> **Origin:** user directive (2026-06-13) — "make CAA a reference plugin for the advanced use of
> ultracode workflows (preserve the simple-scan fallback). Add: (1) a spec/requirements-compliance
> workflow reporting MISSING + VIOLATING elements; (2) a parallel-implementation-compare workflow
> (cache the INPUT, vary the SCRIPT). Study the changelog + sub-agents docs; be smarter."
>
> **Research (DONE, durable):** `reports/code-auditor-agent/20260613_184256+0200-ultracode-subagent-cache-research.md`.
> Pivotal correction: **FORKS share the main cache; NAMED (non-fork) sub-agents each build their OWN
> separate cache** (user's premise was inverted). The Workflow `agent()` spawns NAMED sub-agents
> (separate caches) — so the cross-agent token lever is **identical-PREFIX matching** (API caches on
> `(model, exact prefix)`; "any two requests with the same model and prefix read the same cache"),
> NOT fork-sharing. Put SHARED content FIRST (byte-identical prefix), per-agent content LAST.
>
> **Engine audit (DONE):** `scripts/workflows/caa-engine.js` (577 lines) ALREADY implements the
> cache-prefix invariant correctly (every prefix byte-identical, target path appended LAST —
> lines 27-28,175-208,216-226,299-306,384-396,485-513). Flat map→filter→(domain)→(fix)→reduce pool
> with ramped RL backoff. PR lenses run **INLINE not via agentType** (line 475-478: wrapping
> specialist agents broke the I/O contract — a load-bearing lesson for the new modes: prefer inline
> prompts over agentType wrapping). No nested agents yet.
>
> **NEXT ACTION:** build Phase 1 (spec-compliance) — see plan below.

## Architecture decision

**ONE parameterized engine** (extend `caa-engine.js`), NOT separate engine scripts. Rationale: the
Workflow DSL has no FS/import access, so separate scripts would DUPLICATE the ~40-line pool/RL/
extractPath/cache-prefix machinery → violates single-source-of-truth. All three workflows fit the
same `map → (filter) → reduce` shape, differing only in (a) the constant PREFIX, (b) the per-agent
SUFFIX, (c) the reduce contract. Add a `task` arg: `review` (default — current scan/scan-and-fix/pr)
| `spec-compliance` | `impl-compare`. Each new task adds ~1 prefix + ~1 reduce branch + arg
validation; the machinery stays single-source. Fallback (`caa-simple-scan.md`) gets a matching
single-pass spec per new task. **NEVER use agentType wrapping** for the new modes (engine lesson).

## Phase 1 — spec-compliance workflow (`/caa-spec-audit`)

- New args: `specFile` (abs path to the spec/requirements doc). `files[]` = code files in scope.
- Engine: `task:'spec-compliance'`. Constant SPEC_PREFIX = "read the spec at <specFile>; for the ONE
  target file, list which spec clauses it IMPLEMENTS, which it VIOLATES, and which it is relevant-to
  but OMITS; tag each by a stable clause id" — `specFile` in the cache-shared prefix, target file
  LAST. Filter = verify compliance findings. Reduce = TWO lists: **MISSING** (clauses NO file in
  scope implements — computed globally by cross-referencing every map report's clause tags) +
  **VIOLATING** (code contradicting a clause), each clause↔code cited; plus a coverage table.
- `commands/caa-spec-audit.md` — thin wrapper: resolve specFile + scope, dual-path (engine OR
  simple-scan fallback per the §detection rule), present.
- `caa-simple-scan.md` — add a `spec-compliance` mode (single-pass: read spec, walk each file,
  emit MISSING + VIOLATING).
- Test: engine accepts the new args + reportType without error; a tiny dogfood (spec file + 1-2
  code files) yields the MISSING/VIOLATING contract.

## Phase 2 — parallel implementation-compare workflow (`/caa-impl-compare`)

- New args: `inputSpec` (abs path: the shared INPUT + contract + optional test harness),
  `implementations[]` (candidate scripts — these replace `files[]` as the per-agent suffix).
- Engine: `task:'impl-compare'`. Constant INPUT_PREFIX = "the FIXED input/contract/harness is at
  <inputSpec> (read it FIRST); evaluate the ONE candidate implementation against it — correctness vs
  expected output, edge-case handling, performance characteristics, code quality; run it if safe" —
  **inputSpec in the cache-shared prefix (the user's "cache the input"), candidate impl LAST (the
  "vary the script")**. Filter = adversarially verify each correctness claim. Reduce = a RANKING
  MATRIX (impl | correctness | edge-cases | perf | quality | verdict) naming the best + why, flagging
  failures. This is the headline cache-pattern reference (identical heavy prefix, tiny varying suffix).
- `commands/caa-impl-compare.md` + a `caa-simple-scan.md` impl-compare single-pass fallback. Test.

## Phase 3 — reference-plugin patterns + docs

- Reference doc (shipped) documenting the cache-prefix law, fork-vs-named cache table, the
  cross-agent prefix-caching pattern, and when to use nested agents (2.1.172) — so CAA teaches
  advanced ultracode. Update README with the 2 new commands + `CAA_ULTRACODE` fallback note.
- EVALUATE (do not necessarily adopt): nested-agent option for impl-compare (coordinator → per-impl
  tester → per-case sub-tester, intermediate output off main context) gated behind a flag; the flat
  pool stays default. Skill-injection via subagent `skills:` field — only if it beats inline prompts
  (engine lesson says inline won for the PR lenses).

## Constraints (carry from TRDD-d94a7c5e)

opus-only agents; effort inherited (never switch model/effort mid-run — cache invalidation); final
consolidated report → `reports/code-auditor-agent/`; never llm-externalizer; fallback preserved for
every mode; markdownlint-clean (CPV scans `scripts/workflows/` + `design/`).

## Notes and lessons learned
