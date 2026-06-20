---
trdd-id: e78886a9-2d1e-4892-a53a-0270979fe33a
title: Estimate-based concurrency calibration — replace the server-probing precalibrate
column: published
created: 2026-06-20T13:50:35+0200
updated: 2026-06-20T14:20:00+0200
current-owner: caa
assignee: caa
priority: 2
severity: MEDIUM
effort: M
labels: [engine, calibration, rate-limit, cgcp, tokens]
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
impacts: []
attempts: 0
last-test-result: pass
implementation-commits: [f36d37b, 3b96d25]
published-version: 4.4.0
published-at: 2026-06-20T14:18:00+0200
external-refs: [github.com/Emasoft/code-auditor-agent/releases/tag/v4.4.0]
---

# Estimate-based concurrency calibration

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-20

- **Goal (USER):** the old `precalibrate()` PROBED the server (one "reply OK"
  agent) to detect rate-limiting. The USER flagged probe/trigger-the-limit
  calibration (in their personal example commands) as token-wasteful, and wants a
  PROACTIVE estimate: per-agent token/req footprint × concurrency vs known Anthropic
  rate-limit tiers (lowest tier to be safe, tunable), so the engine stays under the
  limit BY DESIGN and never probes.
- **DONE (2026-06-20):** `precalibrate()` → `estimateCalibrate()` in
  `scripts/workflows/caa-engine.js`. Pure arithmetic, ZERO agents, ZERO RL risk.
  `cap = floor( SAFETY × min(RPM/req, ITPM/in, OTPM/out) )`, clamped to the
  structural cap `CONC`; the result is `gMaxConc`, the ceiling EVERY runPool wave
  uses (so the AIMD ramp can never exceed it). Surfaced as `result.calibration =
  {byRpm,byItpm,byOtpm,binding,maxConc}`. All-opus ⇒ ONE shared Opus bucket governs
  the pool.
- **Numbers (Tier-1 Opus, the lowest published tier as the safe anchor; ALL tunable
  args):** ceilings `ceilRpm=50, ceilItpm=500000, ceilOtpm=80000`; per-agent
  footprint `reqPerAgent=8, inPerAgent=60000, outPerAgent=8000`; `rlSafety=0.8`. At
  defaults the BINDING ceiling is **RPM**: `floor(0.8 × 50/8) = 5` (a test pins
  this). RPM, not tokens, binds at Tier-1.
- **THE HONEST CAVEAT (documented in-code):** the API per-minute tiers are a
  CONSERVATIVE PROXY, not the real wall. Claude Code Pro/Max OAuth throttles on a
  **5-hour rolling window + short burst limiter**, not a published per-minute TPM
  bucket. So: (1) the cap protects the per-minute BURST, not the 5h-window TOTAL
  (which is `files × per-file cost`, governed separately by the per-turn
  `budget.total`/`budgetTripped` — kept SEPARATE from the concurrency cap on purpose;
  folding it in would over-throttle); (2) Pro/Max has more headroom than a Tier-1
  key, so the conservative default may under-utilize — hence every value is tunable.
  The load-bearing unknown is **`reqPerAgent`** (RPM binds); worth empirical
  auto-tune later from real telemetry (`budget.spent()` + agent_count + duration).
- **Safety net retained:** the runtime unbounded-RL sleeper-backoff CGCP stays — if
  the estimate is wrong (e.g. a partly-spent window), the pool degrades gracefully
  (back off + retry, never abandon), just slower. The estimate makes hitting the
  limit RARE; the backoff handles the rare miss.
- **Tests (tests/engine/run_engine_tests.mjs):** 4 new — no-probe/pure-arithmetic;
  RPM-binds-at-Tier-1→cap5; tight-ceiling caps below requested conc + pool respects
  it; tunable widens to requested conc. Updated `conc_is_clamped_to_16` (wide
  ceilings so the estimate doesn't pre-cap below 16 — the structural clamp is what's
  under test). Removed the dead `precal-probe` mock handler. 35/35 green.
- **NEXT:** ships together with the verify-implementation commands (TRDD-d4be3b0e),
  which were PAUSED for this. Resume: CPV --strict → one verify-and-fix dogfood
  (exercises this calibration too) → publish.py (USER version bump).
- **Engine anchors:** constants L376-398; `estimateCalibrate()` L431; call site
  L529; runPool waves use `gMaxConc` (L532/567/804); result `calibration:` L926.

## Why (the user's flaw report)

The user's personal `workflow-verified-{implement,scan-and-fix}` commands waste
tokens probing for the rate limit + retrying into it. The CAA engine's
`precalibrate()` was already cheap (one probe, not full-unit calibration) and the
RL-rejected retries are cheap — but PROBING at all is avoidable. Estimate-based
calibration removes the probe entirely and picks a safe concurrency from known
limits, so the limit is rarely hit. (The personal commands are handled by another
agent; this TRDD is CAA-engine-only, per the user.)

## The formula

```
byRpm  = ceilRpm  / reqPerAgent
byItpm = ceilItpm / inPerAgent
byOtpm = ceilOtpm / outPerAgent
gMaxConc = clamp( floor( rlSafety × min(byRpm, byItpm, byOtpm) ), 1, CONC )
```
The DSL forbids `Date.now()`, so the model is the conservative worst case: a whole
wave bursts its work inside ONE minute. `min()` picks the binding ceiling (RPM at
Tier-1). `gMaxConc` is the ceiling; the AIMD pool starts at `min(gMaxConc,2)` and
ramps up TO `gMaxConc`, never beyond.

## Approval log

- 2026-06-20T13:50:35+0200 — USER ordered estimate-based calibration to replace
  wall-probing (Tier-1 anchor, tunable, lowest-tier-safe), CAA-engine-only. Tier-1
  Opus numbers supplied by the USER (relayed from a research agent). Tier-0 in-scope
  engine work; release version-bump surfaced to USER before publish.py.
