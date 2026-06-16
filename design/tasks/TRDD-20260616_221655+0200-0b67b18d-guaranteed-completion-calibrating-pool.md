---
trdd-id: 0b67b18d-56cc-4a2e-97f1-0ca0249aabdf
title: Guaranteed-completion self-calibrating pool — ultracode workflows must never fail on rate-limits
column: dev
created: 2026-06-16T22:16:55+0200
updated: 2026-06-16T22:16:55+0200
current-owner: claude-caa-session
assignee: claude-caa-session
priority: 1
severity: HIGH
effort: L
labels: [ultracode, workflow, rate-limit, calibration, reliability, caa-engine]
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
external-refs: []
---

# Guaranteed-completion self-calibrating pool — ultracode workflows must never fail on rate-limits

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-06-16

> **USER GOAL (2026-06-16, /goal):** "identify the shortcomings of both methods, find solutions to
> every one. In NO case must the ultracode workflow fail. Integrate a dynamic calibration algorithm
> to keep the token rate below the rate limits — pre-calibrate, calibrate on the run, adapt to
> changing server speeds — the ultracode workflows must be GUARANTEED to execute to the end, no
> exceptions." A session Stop-hook enforces this until met.
>
> **The two "methods" compared (2026-06-16):**
> - **B = CAA's engine** `scripts/workflows/caa-engine.js` (`runPool`, the shared map→filter→reduce pool).
> - **A = the user's command** `~/.claude/commands/workflow-verified-scan-and-fix.md` (its inline `runPool`).
> - (A throwaway naive `parallel(8)` comparison workflow that DIED entirely on a server RL is the
>   worst case — no ramp/throttle/retry — and is the proof the problem is real.)
>
> **THE LOAD-BEARING INSIGHT (makes the guarantee possible):** the Workflow DSL has NO
> `sleep`/`setTimeout`/`Date.now`/`Math.random` — so neither pool can actually WAIT for a server
> rate-limit to clear; their "backoff" (re-queue behind the others at a lower cap) introduces NO
> real time when the WHOLE queue is rate-limited (re-queue behind an empty/all-RL queue at cap=1 =
> immediate retry). **But a sub-AGENT has Bash → it can `sleep N` and `date +%s`.** So real timed
> backoff = dispatch a cheap (haiku) sleeper agent whose wall-clock runtime IS the wait. This is the
> missing primitive both methods lack.

## Shortcomings (both methods share these unless noted)

| # | Shortcoming | A (user cmd) | B (caa-engine) | Severity |
|---|---|---|---|---|
| S1 | **Bounded RL retries → ABANDONMENT.** After `retries`/`maxRetries`=3 an RL'd item becomes `rate-limit-exhausted` and is dropped (reported, never completed). Violates "no exceptions". | yes | yes (`runPool:347-348`) | CRITICAL |
| S2 | **No REAL backoff.** Re-queue-behind-others is the only "wait"; with the DSL having no sleep, a full-queue RL storm cycles the re-queues with ~0 real delay → the bounded retries burn out before the server limit clears. | yes | yes (`runPool:341-348`) | CRITICAL |
| S3 | **No pre-calibration.** Both start cap=1 and ramp +1, but neither PROBES the server first; a cold run into an already-limiting server wastes the first wave on RL. | yes | yes | MAJOR |
| S4 | **No adaptive token-rate control.** Cap is the only lever; there is no measurement of server latency/throughput to keep the token RATE under the limit, and no adaptation to changing server speed mid-run. | yes | yes | MAJOR |
| S5 | **Genuine (non-RL) agent hiccups not retried.** A transient non-RL `*-failed` (e.g. a one-off missed report path) is recorded as terminal, never re-attempted. | yes | yes (`mapAudit:274` etc.) | MINOR |
| S6 | **AIMD increase too timid / decrease fixed.** `cap++` additive-increase is fine; but the halue is a plain `/2` with no streak gating, so a single spurious RL needlessly halves a healthy run. | yes | yes (`runPool:342`) | MINOR |
| S7 (B only) | **Reduce + PR-lens single calls** retry only ONCE (`reduceCall:423`) then surface `(reduce failed after retry)` — a long RL outage still loses the consolidated report. | n/a | yes | MAJOR |

The throwaway naive workflow adds S0 (no pool at all) — not a "method", just the proof.

## Solution — the CGCP (Calibrated Guaranteed-Completion Pool)

A single pool that REPLACES `runPool` (and the reduce/PR single-calls reuse its backoff). Properties:

1. **Real timed backoff via a sleeper agent (fixes S2).**
   `backoff(sec)` = `await agent("Run exactly: sleep <sec>; echo SLEPT — return only SLEPT", {model:'haiku', label:'backoff:<sec>s'})`.
   The sleeper does zero audit work (minimal tokens) and its wall-clock runtime IS the wait. haiku
   (cheapest) — it is INFRASTRUCTURE, not an audit agent, so the opus-only audit invariant does not
   apply to it. ONE global sleeper per RL wave (not per item) to avoid a sleeper-storm.

2. **Unbounded RL retries with EXPONENTIAL backoff (fixes S1) → the guarantee.**
   RL retries are NOT capped. On each RL wave: `backoffSec = min(MAXB, backoffSec*2)` (e.g. 20→40→
   80→160→300, cap 300s), `await backoff(backoffSec)` before resuming. A server RL is by definition
   transient ("temporarily limiting"); cumulative exponential waits eventually exceed the outage T,
   so every item EVENTUALLY gets a non-RL attempt and completes. (Genuine non-RL failures use a
   SMALL bounded retry — S5 — then surface as a real defect; they are NOT "rate-limit exceptions".)

3. **Pre-calibration probe (fixes S3).**
   Before the main run: ONE haiku probe ("reply OK", timed via `date +%s`). RL → start cap=1 +
   initial `backoff(MAXB/4)`; OK + fast → start cap=2; OK + slow → start cap=1. Sets the starting
   point so a cold run into a limiting server does not waste the first wave.

4. **AIMD adaptive concurrency + on-the-run recalibration (fixes S4/S6).**
   Additive-increase: after `RAMP_OK` (e.g. 3) consecutive clean settles, `cap = min(maxCap, cap+1)`.
   Multiplicative-decrease: on an RL wave, `cap = max(1, floor(cap/2))` (streak-gated so a lone RL
   amid health does not over-cut). `backoffSec` DECAYS toward base on sustained success. This is the
   classic TCP-congestion AIMD applied to the token rate — it converges on the max sustainable rate
   and tracks changing server speed. Optionally measure sleeper/probe latency to bias the cap.

5. **Budget-aware hard ceiling (the ONLY legitimate stop).**
   If `budget.total` is set, stop dispatching NEW work when `budget.remaining() < perAgentEstimate`
   and surface "stopped at budget ceiling" (the Workflow contract throws past `budget.total`). With
   no budget set, retries are unbounded (full guarantee for transient RL). The agent-count 1000
   backstop is ample: exponential backoff makes per-item retries few.

6. **Reduce / PR-lens calls use the same backoff loop (fixes S7).** Replace the retry-ONCE with the
   unbounded-RL + exponential-sleeper-backoff loop so a long outage cannot lose the consolidated report.

### Guarantee argument

For any TRANSIENT server rate-limit (the only kind the API issues — "not your usage limit ·
temporarily limiting"): unbounded retries × real exponential backoff (sleeper agents) ⇒ the
inter-retry wait grows without bound (capped per-wave at MAXB but REPEATED), so the total elapsed
wait exceeds the outage duration T ⇒ a retry lands post-clearance ⇒ the item completes. Therefore
every item completes. The only non-completion is (a) a GENUINE deterministic agent/input bug
(surfaced as a real finding, not an RL exception — correctly out of scope of "rate-limit must never
fail"), or (b) the user's own `budget.total` ceiling (their explicit choice). Neither is an
"ultracode workflow failed on rate-limit".

## Plan (phases)

1. **Implement CGCP in `caa-engine.js`** — add `precalibrate()`, `backoff(sec)`, rewrite `runPool` →
   `runCalibratedPool`; route the reduce/PR single-calls through the same backoff. Keep the worker
   contract ({rateLimited} | result) unchanged. `node --check`.
2. **Test** — `node --check`; run a spec-dogfood / impl-dogfood to confirm the engine still completes;
   add a unit-style harness that simulates RL returns to prove unbounded-retry + sleeper-backoff +
   AIMD converge (mock worker that returns {rateLimited} N times then succeeds → asserts completion).
3. **CPV --strict gate** must stay exit 0 (caa-engine.js is scanned; the sleeper prompt must not trip
   a detector; `date`/`sleep` in an agent PROMPT string is data, not exec).
4. **Port the CGCP to the user's command** `workflow-verified-scan-and-fix.md` (same pattern, inline).
5. **Verify the guarantee** (the RL-simulation test passes; document the argument). Commit; ships next release.

## Constraints (carry from TRDD-d94a7c5e)
opus-only for AUDIT agents (sleeper/probe are haiku infrastructure — allowed); never llm-externalizer;
byte-identical cache-prefix discipline preserved; reports → reports/code-auditor-agent/; markdownlint-clean.

## Notes and lessons learned
