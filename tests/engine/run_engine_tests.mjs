#!/usr/bin/env node
// Deterministic tests for scripts/workflows/caa-engine.js.
//
// The engine is a Claude Code Workflow-DSL script: plain JS that uses the DSL globals
// (args, agent, parallel, log, phase) and a TOP-LEVEL return. This harness executes the REAL
// engine body inside an async wrapper, injecting a scripted agent() at the one external
// boundary (the LLM). Everything else — arg validation, the ramped rate-limit pool, path
// validation, lens gating, cache-prefix discipline, reduce retry, result shape — runs for
// real. Live engine runs (TRDD-d94a7c5e) validated the LLM side; these tests pin the
// orchestration logic so regressions are caught in milliseconds, not 1M-token reruns.
//
// Run:  node tests/engine/run_engine_tests.mjs        (exit 0 = all pass)

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const ENGINE_PATH = resolve(HERE, '../../scripts/workflows/caa-engine.js')
const ROOT = '/repo' // engine never touches the fs itself — agents do — so a fake root is fine

// ── DSL harness ──────────────────────────────────────────────────────────────
const engineSource = readFileSync(ENGINE_PATH, 'utf8').replace(/^export /m, '')

async function runEngine(args, agentImpl, opts = {}) {
  const calls = [] // every agent() invocation: {prompt, label, phase, model, seq}
  const logs = []
  const phases = []
  let active = 0
  let maxActive = 0
  let seq = 0
  const agent = (prompt, o = {}) => {
    const call = { prompt, label: o.label, phase: o.phase, model: o.model, seq: seq++ }
    calls.push(call)
    active++
    maxActive = Math.max(maxActive, active)
    return new Promise((res, rej) => {
      setTimeout(async () => {
        try {
          res(await agentImpl(call))
        } catch (e) {
          rej(e)
        } finally {
          active--
        }
      }, opts.agentDelayMs ?? 1)
    })
  }
  // Mirror the real DSL: parallel() is a barrier; a throwing thunk resolves to null.
  const parallel = (thunks) => Promise.all(thunks.map((t) => Promise.resolve().then(t).catch(() => null)))
  const log = (m) => logs.push(String(m))
  const phase = (t) => phases.push(String(t))
  const fn = new Function(
    'args', 'agent', 'parallel', 'log', 'phase', 'budget',
    "'use strict'; return (async () => {\n" + engineSource + '\n})()'
  )
  const result = await fn(args, agent, parallel, log, phase, opts.budget || { total: null, spent: () => 0, remaining: () => Infinity })
  return { result, calls, logs, phases, maxActive }
}

// Default scripted agent: obeys the engine's I/O contract (returns the exact report path the
// prompt assigned). Individual tests override behaviors via the table argument.
function contractAgent(table = {}) {
  return async (call) => {
    const p = call.prompt
    const hook = table[call.label] || (call.label && table[call.label.split(':')[0]])
    if (hook) {
      const out = hook(call)
      if (out !== undefined) return out
    }
    // CGCP infrastructure agents (TRDD-0b67b18d): the pre-calibration probe + the sleeper backoff.
    // Mocked → instant, so the suite never actually sleeps. Probe → healthy unless a test overrides.
    if (call.label === 'precal-probe') return 'OK'
    if (call.label.startsWith('backoff:')) return 'SLEPT'
    const tmp = (p.match(/mkdir -p "([^"]+)"/) || [])[1]
    if (call.label.startsWith('map:')) {
      const file = p.slice(p.lastIndexOf('\n') + 1)
      return tmp + '/' + file.replaceAll('/', '__') + '.map.md'
    }
    if (call.label.startsWith('verify:')) {
      const src = (p.match(/source_file=(\S+)/) || [])[1]
      return tmp + '/' + src.replaceAll('/', '__') + '.verified.md'
    }
    if (call.label.startsWith('fix:')) {
      const src = (p.match(/source_file=(\S+)/) || [])[1]
      return tmp + '/' + src.replaceAll('/', '__') + '.fix.md'
    }
    if (call.label.startsWith('fixverify:')) {
      const src = (p.match(/source_file=(\S+)/) || [])[1]
      return tmp + '/' + src.replaceAll('/', '__') + '.fixverify.md'
    }
    if (call.label === 'lens:claim-verification') return tmp + '/__pr-claim.md'
    if (call.label === 'lens:cross-layer') return tmp + '/__pr-xlayer.md'
    if (call.label === 'lens:skeptical') return tmp + '/__pr-skeptic.md'
    if (call.label.startsWith('reduce:')) {
      const m = p.match(/write (?:the report |)to (\S+\.md)/)
      const path = (m ? m[1] : ROOT + '/reports/code-auditor-agent/UNKNOWN.md').replace('$TS', '20260611_150000+0200')
      return path
    }
    // domain lens agents have label '<key>:<basename>'
    const dm = p.match(/Write findings to (\S+)\/([a-z0-9-]+)__<slug>\.domain\.md/)
    if (dm) {
      const file = p.slice(p.lastIndexOf('\n') + 1)
      return dm[1] + '/' + dm[2] + '__' + file.replaceAll('/', '__') + '.domain.md'
    }
    throw new Error('contractAgent: unhandled label ' + call.label)
  }
}

// ── Tiny test framework with the mandated result table ──────────────────────
const tests = []
const test = (name, doc, fn) => tests.push({ name, doc, fn })
const eq = (a, b, msg) => { if (a !== b) throw new Error((msg || 'assert.eq') + ': expected ' + JSON.stringify(b) + ', got ' + JSON.stringify(a)) }
const ok = (v, msg) => { if (!v) throw new Error(msg || 'assert.ok failed') }

const BASE = { root: ROOT, files: [ROOT + '/a.py', ROOT + '/b.py'], runId: 'test-run' }

// ── Tests ────────────────────────────────────────────────────────────────────
test('arg_validation_rejects_bad_input', 'Engine fail-fasts on missing/relative root, relative files, and unknown mode/lensSet/reportType/minSeverity enums', async () => {
  for (const [args, frag] of [
    [{}, 'ABSOLUTE repo root'],
    [{ root: 'rel', files: ['/x.py'] }, 'ABSOLUTE repo root'],
    [{ root: ROOT, files: ['x.py'] }, 'ABSOLUTE path'],
    [{ ...BASE, mode: 'fix' }, "unknown mode 'fix'"],
    [{ ...BASE, lensSet: 'audit' }, "unknown lensSet 'audit'"],
    [{ ...BASE, reportType: 'verdict' }, "unknown reportType 'verdict'"],
    [{ ...BASE, minSeverity: 'MAYOR' }, "unknown minSeverity 'MAYOR'"],
  ]) {
    const { result } = await runEngine(args, contractAgent())
    ok(result && result.error && result.error.includes(frag), 'expected error containing "' + frag + '", got: ' + JSON.stringify(result))
  }
})

test('pr_plus_fix_combo_rejected', 'lensSet pr + mode scan-and-fix is rejected (fixers would edit files before the PR lenses read them)', async () => {
  const { result } = await runEngine({ ...BASE, lensSet: 'pr', mode: 'scan-and-fix' }, contractAgent())
  ok(result.error && result.error.includes("cannot be combined"), 'expected combo rejection, got: ' + JSON.stringify(result))
})

test('happy_scan_result_shape', 'A clean 2-file scan returns verified=2, extracted finalReport path, derived findings.json, reduce ok, per-run tmpDir', async () => {
  const { result } = await runEngine(BASE, contractAgent({
    reduce: () => 'All done! The consolidated report lives at ' + ROOT + '/reports/code-auditor-agent/20260611_150000+0200-scan.md.', // prose-wrapped on purpose
  }))
  eq(result.verified, 2, 'verified')
  eq(result.problems.length, 0, 'problems')
  eq(result.reduce, 'ok', 'reduce status')
  eq(result.finalReport, ROOT + '/reports/code-auditor-agent/20260611_150000+0200-scan.md', 'extractPath must strip prose + trailing punctuation')
  eq(result.findingsJson, ROOT + '/reports/code-auditor-agent/20260611_150000+0200-scan.findings.json', 'findingsJson derived from finalReport')
  ok(result.tmpDir.endsWith('/reports_dev/.caa-engine-tmp/test-run'), 'tmpDir is per-run namespaced: ' + result.tmpDir)
})

test('cache_prefix_byte_identical', 'All map prompts share a byte-identical prefix; the ONLY varying part is the target path, appended last', async () => {
  const { calls } = await runEngine(BASE, contractAgent())
  const maps = calls.filter((c) => c.label.startsWith('map:'))
  eq(maps.length, 2, 'map agent count')
  for (const c of maps) {
    const file = 'map:'.length ? c.label.slice(4) : ''
    ok(c.prompt.endsWith(file), 'map prompt must END with the target path')
    eq(c.model, 'opus', 'map model pinned to opus')
  }
  const pre0 = maps[0].prompt.slice(0, maps[0].prompt.length - maps[0].label.slice(4).length)
  const pre1 = maps[1].prompt.slice(0, maps[1].prompt.length - maps[1].label.slice(4).length)
  eq(pre0, pre1, 'map prefix must be byte-identical across the swarm')
})

test('rate_limited_file_requeued_then_succeeds', 'A map agent returning rate-limit text gets re-queued (the re-queue IS the backoff) and the file still completes', async () => {
  let first = true
  const { result, logs } = await runEngine(BASE, contractAgent({
    'map:/repo/a.py': () => {
      if (first) { first = false; return 'API Error: Server is temporarily limiting requests. Please retry.' }
      return undefined // fall through to the contract default (valid path)
    },
  }))
  eq(result.verified, 2, 'both files must end verified despite the transient rate limit')
  ok(logs.some((l) => l.includes('re-queued /repo/a.py')), 'pool must log the re-queue')
})

test('path_containing_429_is_not_rate_limited', 'A file named like migrations/0429_add_field.py must NOT be misread as a 429 rate-limit (regression: bare /429/ substring match)', async () => {
  const args = { ...BASE, files: [ROOT + '/migrations/0429_add_field.py'] }
  const { result } = await runEngine(args, contractAgent())
  eq(result.verified, 1, '0429 file must be audited, not re-queued to exhaustion')
  eq(result.problems.length, 0, 'no rate-limit-exhausted entry for the 0429 file')
})

test('rate_limit_unbounded_retry_guarantees_completion', 'A file that rate-limits 6× (FAR past the old 3-retry cap) still completes — RL retries are now UNBOUNDED with a real sleeper-backoff; NO file is ever abandoned as rate-limit-exhausted (TRDD-0b67b18d S1/S2 — the guarantee)', async () => {
  let n = 0
  const { result, calls } = await runEngine(BASE, contractAgent({
    'map:/repo/b.py': () => { n++; return n <= 6 ? 'API Error: Server is temporarily limiting requests' : undefined },
  }))
  eq(result.verified, 2, 'both files complete despite 6 consecutive rate-limits on b.py')
  eq(result.problems.length, 0, 'NO file abandoned — rate-limit-exhausted must never occur under the guarantee')
  ok(n > 6, 'b.py was retried past all 6 rate-limits (n=' + n + ')')
  ok(calls.some((c) => c.label.startsWith('backoff:')), 'a real sleeper-backoff agent fired on the RL waves')
})

test('pr_lens_rate_limited_then_succeeds', 'A PR lens that rate-limits 4× is retried UNBOUNDED with a real sleeper-backoff (TRDD-0b67b18d S7 / MAJ-20) and still ends "done" — a transient RL no longer drops the entire lens', async () => {
  let n = 0
  const { result, calls } = await runEngine({ ...BASE, lensSet: 'pr' }, contractAgent({
    'lens:skeptical': () => { n++; return n <= 4 ? 'API Error: Server is temporarily limiting requests' : undefined },
  }))
  eq(result.prReport.skepticalLens, 'done', 'the skeptical lens must end "done" despite 4 transient rate-limits')
  ok(n > 4, 'the lens was retried past all 4 rate-limits (n=' + n + ')')
  ok(calls.some((c) => c.label.startsWith('backoff:')), 'a real sleeper-backoff fired on the lens RL waves')
})

test('unknown_domain_lens_is_surfaced', 'An unknown domainLenses key (e.g. skeptical, which is holistic) is reported in result.unknownLenses + the log, never a silent no-op', async () => {
  const args = { ...BASE, files: [ROOT + '/Dockerfile'], domainLenses: ['skeptical', 'docker'] }
  const { result, logs, calls } = await runEngine(args, contractAgent())
  ok(result.unknownLenses && result.unknownLenses.includes('skeptical'), 'unknownLenses must list skeptical')
  ok(logs.some((l) => l.includes('unknown domainLenses')), 'warning must be logged')
  ok(calls.some((c) => c.label === 'docker:Dockerfile'), 'the known docker lens must still fire')
  eq(result.domain.pairs, 1, 'exactly one (file × lens) pair')
})

test('domain_findings_flow_into_fixers', 'In scan-and-fix mode the fixer prompt carries the file\'s domain-lens report paths (regression: fixers ignored stack-specific findings)', async () => {
  const args = { ...BASE, files: [ROOT + '/Dockerfile'], mode: 'scan-and-fix', domainLenses: ['docker'] }
  const { result, calls } = await runEngine(args, contractAgent())
  const fix = calls.find((c) => c.label === 'fix:/repo/Dockerfile')
  ok(fix, 'fixer must run')
  ok(fix.prompt.includes('domain_findings=') && fix.prompt.includes('docker__'), 'fixer prompt must list the docker domain report path')
  eq(result.fixReport.fixed, 1, 'fix-verified count')
})

test('reduce_rate_limit_unbounded_retry_then_ok', 'A reduce that rate-limits 4× (past the old retry-once) still recovers — the reduce now retries UNBOUNDED with a real sleeper-backoff so a transient outage never loses the consolidated report (TRDD-0b67b18d S7)', async () => {
  let n = 0
  const { result, calls } = await runEngine(BASE, contractAgent({
    reduce: () => { n++; return n <= 4 ? 'API Error: Server is temporarily limiting requests.' : undefined },
  }))
  eq(result.reduce, 'ok', 'reduce recovers after 4 rate-limits (unbounded retry)')
  ok(result.finalReport && result.finalReport.endsWith('-scan.md'), 'finalReport present after the backoff retries')
  ok(calls.some((c) => c.label.startsWith('backoff:')), 'reduce fired a real sleeper-backoff between retries')
})

test('reduce_genuine_failure_is_bounded_then_fails_clean', 'A reduce that fails for a NON-rate-limit reason (empty return, never RL) is bounded-retried (≤3) then cleanly fails — genuine failures are NOT retried forever (only rate-limits are), so a deterministic bug cannot hang the run', async () => {
  const { result } = await runEngine(BASE, contractAgent({
    reduce: () => '', // empty return = genuine failure (not a path, not an RL signal)
  }))
  eq(result.reduce, 'failed', 'genuine (non-RL) reduce failure ends failed after the small bounded retry')
  eq(result.finalReport, null, 'finalReport null on genuine failure')
})

test('reduce_transient_rate_limit_recovers_on_retry', 'A reduce that rate-limits ONCE succeeds on its single retry', async () => {
  let n = 0
  const { result } = await runEngine(BASE, contractAgent({
    reduce: () => {
      n++
      if (n === 1) return 'overloaded, please retry'
      return undefined // contract default: the real path
    },
  }))
  eq(result.reduce, 'ok', 'reduce recovers')
  ok(result.finalReport && result.finalReport.endsWith('-scan.md'), 'finalReport present after retry')
})

test('pr_lensset_runs_three_lenses_and_diff_aware_map', 'pr lensSet fires claim-verification + cross-layer + skeptical once-per-run, makes the map prompts diff-aware, and the reduce merges four sources', async () => {
  const args = { ...BASE, lensSet: 'pr', reportType: 'pr-comment', reportSuffix: 'pr-9-review', diffFile: '/tmp/pr9.diff', descFile: '/tmp/pr9.desc', prNumber: '9', lensDir: '/plug/scripts/workflows/lenses' }
  const { result, calls } = await runEngine(args, contractAgent())
  for (const lens of ['lens:claim-verification', 'lens:cross-layer', 'lens:skeptical']) ok(calls.some((c) => c.label === lens), lens + ' must run')
  const skeptic = calls.find((c) => c.label === 'lens:skeptical')
  ok(skeptic.prompt.includes('/plug/scripts/workflows/lenses/skeptical.lens.md'), 'skeptical lens reads its spec from lensDir')
  const map = calls.find((c) => c.label.startsWith('map:'))
  ok(map.prompt.includes('PR CONTEXT') && map.prompt.includes('/tmp/pr9.diff'), 'map prompts must be diff-aware in pr mode')
  const red = calls.filter((c) => c.label === 'reduce:pr-comment').pop()
  ok(red.prompt.includes('FOUR sources') && red.prompt.includes('__pr-skeptic.md'), 'pr reduce merges the skeptical lens')
  eq(result.prReport.skepticalLens, 'done', 'skeptical lens status in result')
  eq(result.prReport.reduce, 'ok', 'pr reduce status')
  ok(result.prReport.report.endsWith('-pr-9-review.md'), 'pr report path extracted')
})

test('failed_pr_lens_reported_not_silently_dropped', 'A PR lens that never writes its report ends as lens-failed and the reduce prompt marks it unavailable (regression: the wf_84d7eafb silent gap)', async () => {
  const args = { ...BASE, lensSet: 'pr', reportType: 'pr-comment', diffFile: '/tmp/d.diff', descFile: '/tmp/d.desc' }
  const { result, calls } = await runEngine(args, contractAgent({
    'lens:claim-verification': () => 'done', // violates the contract: no report path
  }))
  eq(result.prReport.claimLens, 'lens-failed', 'claim lens status')
  const red = calls.filter((c) => c.label === 'reduce:pr-comment').pop()
  ok(red.prompt.includes('claim-verification lens lens-failed'), 'reduce prompt must carry the unavailability')
})

test('fix_mode_zero_verified_returns_stub', 'scan-and-fix where no file verifies returns an explicit fixReport stub instead of a silent null', async () => {
  const { result } = await runEngine({ ...BASE, mode: 'scan-and-fix' }, contractAgent({
    map: () => 'I could not produce a report, sorry.',
  }))
  eq(result.verified, 0, 'nothing verified')
  ok(result.fixReport && result.fixReport.note && result.fixReport.note.includes('nothing to fix'), 'explicit stub note')
})

test('conc_is_clamped_to_16', 'conc=999 must not unleash an unbounded swarm: observed concurrency stays ≤16 (the clamp)', async () => {
  const files = Array.from({ length: 40 }, (_, i) => ROOT + '/f' + i + '.py')
  const { maxActive } = await runEngine({ root: ROOT, files, runId: 'clamp', conc: 999 }, contractAgent(), { agentDelayMs: 3 })
  ok(maxActive <= 16, 'maxActive=' + maxActive + ' must be ≤ 16')
})

test('budget_ceiling_is_the_only_stop_under_forever_rate_limit', 'Safety valve: under a pathological NEVER-clearing rate-limit, a set budget.total makes the pool mark remaining items budget-stopped and RESOLVE (never hang, never abandon-as-exhausted) — the sole legitimate non-completion (TRDD-0b67b18d)', async () => {
  let probes = 0
  const budget = { total: 200000, spent: () => probes * 80000, remaining: () => Math.max(0, 200000 - probes * 80000) }
  const { result } = await runEngine(BASE, contractAgent({
    map: () => { probes++; return 'API Error: Server is temporarily limiting requests' }, // never clears
  }), { budget })
  ok(Array.isArray(result.problems), 'engine RESOLVED (did not hang) under forever-RL + budget')
  eq(result.verified, 0, 'nothing verified under a never-clearing limit')
  ok(result.problems.length >= 1 && result.problems.every((p) => p && p.status === 'budget-stopped'), 'remaining items are budget-stopped (the legitimate stop), never rate-limit-exhausted')
})

test('sleeper_backoff_survives_its_own_rate_limit', 'The closed gap: even when the SLEEPER agent\'s own dispatch is rate-limited, backoff() retries the dispatch until one actually runs `sleep` — so a real wait still happens and the run completes (TRDD-0b67b18d hardening)', async () => {
  let mapN = 0, bN = 0
  const { result } = await runEngine(BASE, contractAgent({
    'map:/repo/b.py': () => { mapN++; return mapN <= 2 ? 'temporarily limiting requests' : undefined },
    backoff: () => { bN++; return bN === 1 ? 'API Error: temporarily limiting' : 'SLEPT' }, // sleeper itself RL'd once
  }))
  eq(result.verified, 2, 'both files complete despite the sleeper being rate-limited on its first dispatch')
  ok(bN >= 2, 'backoff() retried its sleeper dispatch past the sleeper\'s OWN rate-limit (dispatches=' + bN + ')')
})

test('runid_fallback_is_deterministic_hash', 'Without runId the tmp namespace falls back to a deterministic args-hash (distinct args ⇒ distinct dirs)', async () => {
  const a1 = { root: ROOT, files: [ROOT + '/a.py'] }
  const a2 = { root: ROOT, files: [ROOT + '/b.py'] }
  const r1 = (await runEngine(a1, contractAgent())).result
  const r1b = (await runEngine(a1, contractAgent())).result
  const r2 = (await runEngine(a2, contractAgent())).result
  eq(r1.tmpDir, r1b.tmpDir, 'same args ⇒ same dir (resume-stable)')
  ok(r1.tmpDir !== r2.tmpDir, 'different args ⇒ different dirs')
  ok(r1.runId.startsWith('r'), 'fallback runId is hash-derived')
})

test('mkdir_paths_are_quoted_for_spaces', 'Every bash mkdir the prompts instruct is double-quoted so a repo root containing spaces cannot split the path', async () => {
  const args = { root: '/Users/jane doe/repo', files: ['/Users/jane doe/repo/a.py'], runId: 'sp' }
  const { calls } = await runEngine(args, contractAgent({
    map: (c) => ((c.prompt.match(/mkdir -p "([^"]+)"/) || [])[1]) + '/__a.map.md'.replace('__a', '__Users__jane doe__repo__a.py'),
    verify: (c) => ((c.prompt.match(/mkdir -p "([^"]+)"/) || [])[1]) + '/__Users__jane doe__repo__a.py.verified.md',
  }))
  for (const c of calls) {
    if (c.prompt.includes('mkdir -p ')) ok(/mkdir -p "/.test(c.prompt), c.label + ': mkdir path must be quoted')
  }
})

test('gate_verdict_rule_selected', 'reportType=gate injects the PASS/FAIL verdict rule into the reduce prompt; audit injects the SUMMARY rule', async () => {
  const g = await runEngine({ ...BASE, reportType: 'gate' }, contractAgent())
  ok(g.calls.filter((c) => c.label.startsWith('reduce:')).pop().prompt.includes('VERDICT: PASS'), 'gate verdict rule present')
  const a = await runEngine(BASE, contractAgent())
  ok(a.calls.filter((c) => c.label.startsWith('reduce:')).pop().prompt.includes('SUMMARY: <c> CRITICAL'), 'audit summary rule present')
})

// ── Runner with the mandated unicode table ───────────────────────────────────
const pad = (s, n) => (s + ' '.repeat(n)).slice(0, n)
const rows = []
let failed = 0
for (const t of tests) {
  try {
    await t.fn()
    rows.push([t.name, 'PASS', t.doc])
  } catch (e) {
    failed++
    rows.push([t.name, 'FAIL', t.doc])
    console.error('\nFAIL ' + t.name + ': ' + (e && e.message) + '\n' + (e && e.stack ? e.stack.split('\n').slice(1, 3).join('\n') : ''))
  }
}
const W1 = Math.max(...rows.map((r) => r[0].length), 4) + 1
const W3 = Math.max(...rows.map((r) => r[2].length), 11) + 1
const line = (l, m, r, h) => l + h.repeat(W1 + 2) + m + h.repeat(8) + m + h.repeat(W3 + 2) + r
console.log(line('┏', '┳', '┓', '━'))
console.log('┃ ' + pad('Test', W1) + ' ┃ ' + pad('Status', 6) + ' ┃ ' + pad('Description', W3) + ' ┃')
console.log(line('┡', '╇', '┩', '━'))
for (const [n, s, d] of rows) console.log('│ ' + pad(n, W1) + ' │ ' + pad(s, 6) + ' │ ' + pad(d, W3) + ' │')
console.log(line('└', '┴', '┘', '─'))
console.log(rows.length - failed + '/' + rows.length + ' passed.' + (failed ? '  ' + failed + ' FAILED.' : '  All green.'))
process.exit(failed ? 1 : 0)
