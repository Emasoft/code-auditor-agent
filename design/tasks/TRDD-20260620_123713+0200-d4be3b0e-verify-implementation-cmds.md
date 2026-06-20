---
trdd-id: d4be3b0e-53fd-4a3f-84d3-0c73e89d5242
title: Add /caa-verify-implementation + /caa-verify-implementation-and-fix (fix-as-you-go)
column: dev
created: 2026-06-20T12:37:13+0200
updated: 2026-06-20T14:05:00+0200
current-owner: caa
assignee: caa
priority: 3
severity: MEDIUM
effort: L
labels: [engine, command, verify, fix-as-you-go, spec-compliance]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
publish-target: emasoft-plugins
publish-channel: stable
test-requirements: [unit, lint]
audit-requirements: []
review-requirements: [code-review]
runtime-targets: [macos, linux]
impacts: [public-api]
attempts: 0
last-test-result: not-run
implementation-commits: []
external-refs: []
---

# Add /caa-verify-implementation + /caa-verify-implementation-and-fix

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-20

> **STATUS 2026-06-20:** implementation DONE (engine SPECFIX mode + 2 commands +
> simple-scan fallback + README + tests; 35/35 harness, 269 pytest, ruff, CPV
> --strict exit 0). PAUSED after implementation for the estimate-based calibration
> (TRDD-e78886a9, now also DONE) per the USER, to ship together. Dogfood
> `wf_a366e52a-970` on the GT-style fixture `/tmp/caa-verify-fixture/` (calc.py R2
> VIOLATED + util.py R3 PARTIAL) — **DOGFOOD PASS**: `SUMMARY: 2 FIXED, 0
> STILL-VIOLATED, 0 UNIMPLEMENTED of 3 clauses`. Fix-as-you-go edited both files in
> the map read (divide→raise ValueError @calc.py:10 w/ spec comment; clamp→+upper
> bound @util.py:4-5, re-executed), adversarial verifier confirmed, calibration ran
> arithmetically (RPM-binding, maxConc 2, no probe). 5 agents / ~2.4 min. Evidence:
> reports/code-auditor-agent/verify-impl-and-calibration-proof/ (gitignored). NEXT:
> commit both features + ship via publish.py (USER version bump).

- **Goal (USER order):** add two commands. (1) `/caa-verify-implementation` —
  verify a TRDD or a generic spec is correctly + completely implemented.
  (2) `/caa-verify-implementation-and-fix` — same, plus **fix-as-you-go**: the
  agent that DISCOVERS a wrong/missing part FIXES/COMPLETES it in the SAME turn
  (one read of the file — never read the code twice). USER pointed at
  `~/.claude/commands/workflow-verified-implement.md` as an example whose many
  flaws my version must beat.
- **CRITICAL SCOPE (USER clarification 2026-06-20):** these commands are NOT
  implement-from-scratch tools. **The implementation must ALREADY EXIST.** They
  VERIFY an existing implementation against its TRDD/spec and FIX/COMPLETE its
  gaps (wrong → fixed, incomplete → completed, a missing piece that belongs in the
  existing code → added). This is the OPPOSITE of the example, which BUILDS a
  feature from a spec. So fix-as-you-go COMPLETES an existing implementation; it
  must NOT scaffold a brand-new feature/file from the spec. If a requirement has
  NO implementation at all (nothing to verify/complete), the command REPORTS it as
  unimplemented — it does not build it (that is `/workflow-verified-implement`'s
  job, a different tool). "Fix the issues in the implementation", never "create the
  implementation."
- **DESIGN (decided):**
  - `/caa-verify-implementation` = a TRDD-aware WRAPPER over the EXISTING engine
    `task: spec-compliance` (no engine change). It enumerates the spec/TRDD's
    requirement clauses and classifies each audited file's clauses
    IMPLEMENTED/VIOLATED/PARTIAL; the reduce computes MISSING (no file implements
    it). TRDD-awareness: if arg 1 is a TRDD, default the file scope to the TRDD's
    `implementation-commits` changed files (so it checks exactly what claims to
    implement it), and pass the TRDD as the specFile.
  - `/caa-verify-implementation-and-fix` = `task: spec-compliance` + a NEW engine
    `mode: scan-and-fix` with FIX-AS-YOU-GO: the per-file MAP agent classifies AND
    in the same turn fixes every VIOLATED/PARTIAL clause and adds every MISSING
    clause that BELONGS in that file — one read, edit in place. A DIFFERENT
    verifier re-reads + confirms each fix. Reduce reports fixed / still-violated /
    still-missing-needs-new-file.
- **WHY better than the example** (the flaws it fixes): single canonical engine
  (vs hand-authored JS each run); CGCP unbounded-RL guaranteed completion (vs the
  example's bounded RL → `rate-limit-exhausted` abandons work); **fix-as-you-go
  single-read** (vs example's execute→verify→relaunch multi-read, AND vs CAA's own
  review scan-and-fix which scans then RE-reads in a separate fixer); structured
  findings.json + markdown; adversarial filter (different reviewer); TRDD-aware
  scope; dual-path (ultracode + simple-scan) opus-pinned cost-aware.
- **NEXT ACTION:** Phase 1 — engine. Add to `scripts/workflows/caa-engine.js`:
  (a) allow `task==='spec-compliance' && mode==='scan-and-fix'` (the validation at
  L132 already allows mode=scan-and-fix; ensure no rule rejects spec+fix); (b)
  `SPEC_FIX_MAP_PREFIX` (classify+fix-as-you-go, edit in place, one file) selected
  when spec-compliance+scan-and-fix; (c) `SPEC_FIXV_PREFIX` (different reviewer
  confirms each fix is real+correct+regression-free and the clause is now
  IMPLEMENTED); (d) a spec-fix branch: map-and-fix → verify → reduce (3 phases, NO
  separate fixer — that is the single-read win); (e) a spec-fix reduce
  ("…-fix.md" + findings.json: clause_id, status fixed|violated|missing|implemented,
  file, evidence, what_changed). Keep all-opus, CGCP, report-path discipline,
  never-llm-externalizer.
- **Phase 2:** `commands/caa-verify-implementation.md` (wrapper over spec-compliance,
  TRDD-aware) + `commands/caa-verify-implementation-and-fix.md` (spec-compliance +
  mode scan-and-fix). Model on `commands/caa-spec-audit.md` (verify) +
  `commands/caa-scan-and-fix.md` (fix safety/Step-B). Dual-path; the simple-scan
  fallback must also support spec-compliance+scan-and-fix (check
  `scripts/workflows/caa-simple-scan.md`).
- **Phase 3:** tests in `tests/engine/run_engine_tests.mjs` — spec-fix fires
  map-and-fix (NOT a separate fix phase), verify confirms, reduce path; spec-fix
  survives RL; arg validation. Keep the existing suite green. Plus a TRDD-frontmatter
  test if a command-shape test harness exists.
- **Phase 4:** node --check + harness + pytest + ruff + CPV --strict (watch the
  skillaudit CRED_ENV_READ FP — keep new prompt prose free of literal
  `.env`/secret-read tokens, per cpv-skillaudit-nit-on-script-prompt-strings) +
  real-agent dogfood on a seeded spec-vs-impl fixture (verify catches a MISSING +
  a VIOLATED; verify-and-fix fixes them in one read) → TRDD bookkeeping → surface
  the version-bump decision to USER before publish.py.
- **Engine insertion points (verified 2026-06-20):** mode validation L132; spec
  task-requires-specFile L147; `SPEC_MAP_PREFIX` L244; `MAP_PREFIX` selector L268;
  `SPEC_VERIFY_PREFIX` L292; `FILTER_PREFIX` selector L308; review fix branch L667.
- **Durable artifacts:** the example `~/.claude/commands/workflow-verified-implement.md`;
  `commands/caa-spec-audit.md`; `commands/caa-scan-and-fix.md`; the engine.

## The example's flaws (USER said "many flaws; yours must be much better")

`~/.claude/commands/workflow-verified-implement.md`:
1. Orchestrator must hand-author a Workflow JS script every invocation — fragile,
   non-reusable, drifts. CAA's model is ONE canonical engine all commands call.
2. Bounded RL retry (~7 tries → `rate-limit-exhausted` terminal) ABANDONS a unit on
   a long outage. CAA's CGCP is unbounded-RL with a real sleeper backoff + AIMD +
   budget ceiling — it NEVER abandons for a transient limit.
3. `execute → verify → relaunch-with-feedback` reads the code MULTIPLE times
   (executor reads, verifier re-reads, relaunch reads again). The USER's explicit
   requirement is fix-as-you-go: discover and fix in ONE read.
4. Manual disjoint-scope unit assembly + waves — heavy orchestration burden. CAA's
   engine isolates one file per agent (no shared-file conflict) automatically.
5. Only a `.report.md`; no machine-readable findings. CAA emits findings.json too.
6. No TRDD-awareness — generic "units". A TRDD carries acceptance criteria, a file
   list, and `implementation-commits` that pin exactly what to verify.

## Fix-as-you-go (the load-bearing new semantics)

In `task: spec-compliance, mode: scan-and-fix`, the per-file agent, in ONE turn /
ONE read of its file:
1. reads the spec/TRDD, enumerates the clauses RELEVANT to this file;
2. classifies each: IMPLEMENTED / VIOLATED / PARTIAL / (MISSING-but-belongs-here);
3. immediately FIXES every VIOLATED clause and COMPLETES every PARTIAL clause by
   editing the EXISTING code IN PLACE (root-cause only; no hacks/fallbacks;
   fail-fast). It COMPLETES a gap the existing file should already cover; it does
   NOT scaffold a brand-new feature from the spec (that is out of scope — the
   implementation must already exist).
4. re-reads its own edit to confirm validity; writes a per-file fix report.
A DIFFERENT verifier then re-reads the file + the report and confirms each fix is
real, correct, regression-free, and the clause is now genuinely IMPLEMENTED.
The reduce consolidates: clauses now-implemented (incl. fixed/completed),
still-VIOLATED (fix failed), and **UNIMPLEMENTED** — a requirement with no existing
implementation anywhere in scope. Unimplemented requirements are REPORTED as gaps
for human follow-up (or `/workflow-verified-implement`), never blindly built from
the spec — these commands complete an existing implementation, they don't create
one. One file per agent ⇒ parallel in-place edits never conflict; never commits
(user reviews the diff).

## Test plan

- `tests/engine/run_engine_tests.mjs` (mocked agent, deterministic): spec-fix
  fires a map-and-fix label (NOT a separate `fix:` phase), the verify label runs,
  the spec-fix reduce path is produced and returned; spec-fix survives a transient
  RL; arg-validation (spec+fix requires specFile). Keep all existing tests green.
- Real-agent dogfood (out of CI): a seeded repo with a SPEC.md (e.g. 4 clauses) +
  code that IMPLEMENTS 2, VIOLATES 1, MISSES 1. `/caa-verify-implementation` must
  report 1 VIOLATING + 1 MISSING; `/caa-verify-implementation-and-fix` must fix the
  VIOLATED clause and add the MISSING-but-belongs-here clause in ONE read each, and
  re-verify clean.
- Gates: node --check, pytest (engine wrapper + prereview), ruff, CPV --strict (0).

## Approval log

- 2026-06-20T12:37:13+0200 — USER ordered the two commands ("you must add…"),
  citing the example to beat. Authored at column: dev (Tier-0 in-scope feature on
  CAA-owned files). Release version-bump surfaced to USER before publish.py.
