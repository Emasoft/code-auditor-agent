# TRDD-7e364ace — Bug-detection completeness from PR-Review corpus

**TRDD ID:** `7e364ace-1fd3-41ed-abc8-1ab96c02c935`
**Filename:** `design/tasks/TRDD-7e364ace-1fd3-41ed-abc8-1ab96c02c935-bug-detection-completeness.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)
**Status:** In progress (step 1-4 baseline shipped)
**Source inventories:**
- `docs_dev/codex-comparison/FULL-PR-REVIEW-INVENTORY.md` (216-idea PR-Review corpus, Themes A-Z)
- `docs_dev/codex-comparison/FULL-INVENTORY-300PLUS.md` (1452-row cross-plugin sweep across 30+ marketplaces; 117 NEW techniques in 18 clusters; final 24-step structure derived from data)

## Mission (verbatim from user)

> "this is a plugin with only one mission: catch all bugs. it must use all
> possible techniques, but the result must be that not a single error,
> shortcoming, vulnerability, inconsistencies, bottleneck or anything else
> found in those 300+ skills files should escape it!"
>
> "it must do it using the minimum amount of tokens and delegating to
> scripts and linters as much work as possible, but not so much that the
> detection ability is lost!"
>
> "each phase/step must not be too complex! the agents (and the
> llm-externalizer) must not make too much work because they will end
> allucinating and being confused by the too many directives. So keep the
> new checks from the 300+ skills in new steps/phases, aggregate those
> similar but not too many.. since now we have 4 steps, we will likely
> end with 12-15 steps/phases.. so you must catalogue and categorize the
> steps according to priority and importance, and order them from 1 to
> 16 or 20 based on that. Once you do this, make the command accept a
> parameter called 'code-analysis-depth' that goes from 1 to 16, so each
> value represents the step to reach.. for example depth 4 means the
> current 4 steps.. step 5 the new step with a new category.. and so on,
> till 16 or 20 that will include all steps, for a complete scan that
> will not miss any bug. be very smart in developing the pipeline and
> remember to lint between each step."

## Governing constraints

1. **DETECTION COMPLETENESS** — every detection technique extracted from
   the corpus (216 ideas → ~95 bug-detection-relevant) is encoded.
2. **TOKEN ECONOMY** — every deterministic rule (regex / AST / linter /
   scanner / schema diff) lives in a script. Agents spend LLM tokens
   only on judgment residue.
3. **SINGLE-RESPONSIBILITY STEPS** — each step / agent does ONE thing well.
   Agent prompts capped at ~200 lines. No agent gets a 50-item checklist.
4. **MODEL POLICY (HARD INVARIANT)** — agents inside this plugin run on
   Claude models only (Sonnet or Opus). Any external-model review
   (Codex, GPT-X, Gemini, local models, etc.) is invoked through the
   `llm-externalizer` MCP plugin — never inlined into a CAA agent.
   No matter what other plugins or skill corpora suggest, this plugin
   does not embed external-LLM clients of its own.

## Step ordering (0 → 23, by priority/ROI, derived from data)

Each step is a self-contained pipeline stage, sequenced by ROI per token.
The PR-review command accepts `--code-analysis-depth N` (default `4`,
range `1..23`). Step 0 is always-on (it's a gate, not a check). Steps
`1..N` run; steps `N+1..23` stay dormant.

Steps 1-4 are the current pipeline (already shipped). Steps 0 and 5-23
are new. The step count grew from 20 (initial draft) to 24 (one gate +
23 numbered) after the 1452-row cross-plugin consolidation surfaced four
distinct clusters not present in the original PR-Review corpus: multi-
tenant data isolation, concurrency hazards, database/query/migration
correctness, and the domain-detection gate.

### Tier 0 — Always-on gate (script)

| # | Step | Owner | Source |
|---|---|---|---|
| 0 | **Domain detection pre-flight** — detect languages, frameworks, file-types (Python, JS/TS, Go, Rust, Swift, Elixir, Solidity, GraphQL, JWT, Docker, SQL/migrations, frontend, MCP, tenancy markers, prompt-template usage); emit `domains_detected.json` so conditional specialist steps know to fire | `scripts/prereview/detect_languages_and_domains.py` | gate (cluster N0) |

### Tier I — Baseline LLM judgment (current pipeline)

These four steps run by default; they require structural LLM judgment that
no script can replace.

| # | Step | Owner | Source |
|---|---|---|---|
| 1 | **Code correctness swarm** — per-file structural correctness, AWC sub-checklist, layer/confidence fields | `caa-code-correctness-agent` (existing) | F-001, F-004, F-005, F-006 |
| 2 | **Claim verification + linked-issue** — every PR-description and commit-message claim verified; linked-issue acceptance-criteria table | `caa-claim-verification-agent` (existing) | F-002 |
| 3 | **Skeptical holistic review** — UX, breaking changes, design judgment, documentation accuracy | `caa-skeptical-reviewer-agent` (existing) | (CAA original) |
| 4 | **Security review** — OWASP / CWE / attacker-perspective | `caa-security-review-agent` (existing) | H1, H13 |

### Tier II — Deterministic pre-flight (zero LLM cost)

These steps are pure scripts. They run fast and emit findings the LLM swarm
later reads instead of re-grepping. Step 5 alone is expected to land the
biggest detection-recall delta per token.

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 5 | **Linter & scanner pre-flight** — wrap available external tools (ruff, mypy, eslint, biome, gofmt, govet, clippy, hadolint, markdownlint, sqlfluff, codespell, gitleaks, trufflehog, semgrep, bandit, trivy, pip-audit, npm-audit, govulncheck); filter output to PR-touched files only; emit structured JSON | `scripts/prereview/run_linters.py` | A2, B5, G11-13, I9, J*-mechanical, Q6, H6 |
| 6 | **Cross-layer drift detector** — env-var ↔ docs drift, schema ↔ model drift, generated-file checksum drift, orphan-caller scan, removed-state-no-replacement, UI-only-security probe | `scripts/prereview/cross_layer.py` + existing `caa-cross-layer-auditor-agent` (judgment residue) | E1-E10, Q1, Q5 |

### Tier III — Newly inserted high-ROI detector clusters

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 7 | **Multi-tenant data-isolation** — tenant_id missing from query predicates / cache keys / module-level state shared across tenants / row-level-security gaps | `scripts/prereview/multi_tenant.py` + agent residue | N11.1-N11.4 |
| 8 | **Silent-failure hunter** — AST: empty catches, broad catches, catch-and-only-log, `?.` over fallible calls, fallback-to-mock-in-prod (script) + agent judges retry-without-user-feedback / fallback in error-pathway / missing context | `scripts/prereview/silent_failure.py` + `caa-silent-failure-hunter-agent` (NEW) | J1-J11 |
| 9 | **Concurrency hazards** — un-awaited promises/coroutines/Tasks, goroutine leaks, lock-order violations, atomicity violations, async cancellation safety, channel send-after-close, reentrancy hazards | `scripts/prereview/concurrency.py` + `caa-concurrency-reviewer-agent` (NEW) | N1.1-N1.8 |

### Tier IV — Code-quality scanners (mostly deterministic)

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 10 | **Complexity & dead-code scanner** — fn-too-long (>20 lines), too-many-branches (>5), too-many-parameters (>3), cyclomatic complexity (>10), nested-loop depth, unused imports, unused exports, unreachable code, orphan symbols | `scripts/prereview/complexity.py` | M3, M4, M5, N2 (perf), N12.1-N12.4, P4, G13 |
| 11 | **Agent-written-code extensions** — inconsistent style with nearby code (linter delta), excessive dependencies (parse manifest vs actual imports), unused abstractions, hardcoded values that should be config | `scripts/prereview/awc_extensions.py` + extend `caa-code-correctness-agent` AWC checklist | G11-G14 |
| 12 | **Comment & docstring quality** — docstring-param mismatch (mechanical), comment-vs-code factual contradiction (script grep + agent judgment), completeness, long-term value, misleading elements | `scripts/prereview/docstring_diff.py` + `caa-comment-quality-agent` (NEW) | L1-L6 |

### Tier V — Per-class detection (script-heavy + slim agent)

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 13 | **Test-quality scanner** — mock-replaces-SUT, no-assertion tests, `assert True`, DAMP naming, test-pyramid imbalance, regression-test-for-every-fix, feature-flag both-states tested, property-based / fuzz gap, codec round-trip gap | `scripts/prereview/test_quality.py` + agent judgment | I1-I12, E9, N13.1-N13.3 |
| 14 | **Performance + memory + energy** — N+1 heuristic, nested loops > depth 2, large-allocations-in-hot-paths, large-files-fully-read, missing memoisation, retain cycles, energy regressions on mobile | `scripts/prereview/performance.py` + `caa-performance-review-agent` (NEW) | P1-P5, N5.1-N5.6 |
| 15 | **Database / query / migration correctness** — N+1, missing indexes, schema drift, missing reverse migration, FK / NOT NULL constraints, credit-ledger / accounting invariants | `scripts/prereview/database.py` + `caa-database-reviewer-agent` (NEW) | N15.1-N15.8 |

### Tier VI — Pure judgment (agent-only, narrow checklist)

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 16 | **Type-design analyzer** — 4-dimensional invariant rating (encapsulation, expression, usefulness, enforcement); anti-pattern catalogue; "make illegal states unrepresentable". Fires only when the diff adds a new public type | `caa-type-design-analyzer-agent` (NEW) | K1-K8 |
| 17 | **Architecture pattern consistency** — new code follows existing module patterns; polyglot boundaries; data-structure consistency; API-design consistency; inherits-from-different-base | `caa-architecture-consistency-agent` (NEW) | N3-N8 |
| 18 | **Pre-mortem / risk analyzer** — Tiger / Paper-Tiger / Elephant taxonomy with mandatory `mitigation_checked: "what was NOT found"` evidence on every Tiger; verify-before-flagging gate | `caa-pre-mortem-agent` (NEW) | O1-O8 |

### Tier VII — Operational, domain specialists, deep dive

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 19 | **Operational / deployment** — rollback plan, migration forward+reverse, release annotations, cross-platform compat, generated-files-updated, CI / build / formatter / lint passing | `scripts/prereview/operational.py` + agent residue | Q3-Q8 |
| 20 | **Domain specialists, high-frequency** — fires only when `domains_detected` contains the marker. GraphQL, JWT, REST API design, Docker hardening, prompt-injection / LLM-output safety, web-frontend (a11y / web-vitals / XSS / CSP) | `caa-graphql-reviewer-agent`, `caa-jwt-reviewer-agent`, `caa-api-design-reviewer-agent`, `caa-docker-reviewer-agent`, `caa-prompt-injection-reviewer-agent`, `caa-frontend-reviewer-agent` (all NEW) | T1, T2, H9, H10, Y6, N8, N10, N14 |
| 21 | **Domain specialists, lower-frequency** — fires only when its marker is detected. iOS/Swift-native (SwiftUI, Core Data, CryptoKit), Elixir/Phoenix-native (OTP, GenServer, supervisors), Solidity smart-contract (slither-class checks), MCP-server security (tool-call auth, command injection in tool wrappers), i18n, l10n, monorepo, logging | `caa-ios-reviewer-agent`, `caa-elixir-reviewer-agent`, `caa-solidity-reviewer-agent`, `caa-mcp-server-reviewer-agent`, `caa-i18n-reviewer-agent`, `caa-l10n-reviewer-agent`, `caa-monorepo-reviewer-agent`, `caa-logging-reviewer-agent` (all NEW) | N4, N6, N7, N9, T3-T5, Y8-Y9 |
| 22 | **Function-level deep-dive** — per-function 15-question checklist (callers, mutated state, dep-failure paths, contract drift, error paths) + similar-function-already-exists via `mcp__llm-externalizer__search_existing_implementations` | `caa-function-deep-dive-agent` (NEW) | D3, N16.1-N16.6 |
| 23 | **Second-opinion verification loop** — Opus agent re-reviews the consolidated CAA output as a hostile maintainer; PASS-2 verifies PASS-1 findings actually addressed. For a non-Claude consensus the user invokes `llm-externalizer` (ensemble of 3 models) on the report file separately | `caa-second-opinion-agent` (NEW, Opus) — external models NOT embedded; delegated to llm-externalizer | S1, S4-S6, S9, N17.1-N17.5 |

## Default depth: 4 (current behavior)

Step 0 (domain detection) always runs as a gate (zero LLM cost). Default
`--code-analysis-depth 4` preserves current token costs (steps 1-4). Users
opting into deeper scans accept the additional cost.

| Preset | Depth | Steps run | Adds |
|---|---|---|---|
| `quick` | 4 | 1-4 | Current behavior. PR sanity check. |
| `standard` | 10 | 1-10 | Linters, cross-layer (+ripple+nil), multi-tenant, silent-failure, concurrency, complexity |
| `deep` | 15 | 1-15 | AWC extensions, comment quality, test quality, performance, database |
| `thorough` | 19 | 1-19 | Type-design, architecture, pre-mortem, operational |
| `full` | 23 | 1-23 | Every step. No bug escapes. Domain specialists, function deep-dive, Opus second-opinion |

## Token-economy invariants (do not violate)

1. Agents NEVER re-grep what scripts already produced. Each agent's first
   action is `Read <reports/caa-prereview/<ts>.json>`.
2. Each agent prompt ≤ 200 lines.
3. Each agent's checklist is single-responsibility. No 50-item dumping
   ground.
4. Specialist agents (steps 17-18) fire ONLY when their domain is
   detected by `scripts/prereview/detect_languages_and_domains.py`.
5. Linter output is filtered to PR-touched files only.
6. Steps 5-12 (script-heavy) run in parallel via `concurrent.futures`.
7. Each step that produces findings writes its own per-step JSON section
   in `reports/caa-prereview/<ts>.json` so downstream agents Read only
   the section they need.

## Linting discipline (per user directive: "lint between each step")

After every implementation step:

```bash
cd code-auditor-agent
uv run python scripts/validate_plugin.py . --strict
```

Must return exit 0 before progressing to the next step. Commit after each
step. No batched multi-step commits.

## Command interface

```bash
/caa-pr-review --code-analysis-depth N <pr-number>
# Aliases:
/caa-pr-review --depth N <pr-number>
/caa-pr-review --preset quick|standard|deep|thorough|full <pr-number>
```

Internal: `caa-pr-review-skill/SKILL.md` reads `--code-analysis-depth` (or
maps the preset → integer), iterates steps `1..N`, surfaces per-step report
paths.

## Execution order (implementation phases)

1. **Update `caa-pr-review-skill/SKILL.md`** to accept `--code-analysis-depth`
   and run only `1..N` steps. Default = 4. Re-lint.
2. **Implement step 5** — linter wrapper script + JSON output schema. Test
   on Flask PR #57 benchmark. Re-lint.
3. **Step 6** — extend cross-layer to script-first / agent-residue split.
4. **Step 7** — silent-failure hunter (script + agent).
5. ...continue through step 20, one at a time, re-linting after each.

After every step lands, re-run the n=5 multi-run experiment scorer on the
benchmark (`docs_dev/codex-comparison/multirun/score.py`) and append the
new-step findings to the inventory.

## Verification (per step)

- Unit tests under `tests/prereview/` for each script (fixture in,
  expected JSON out, byte-identical).
- Each new agent: golden-fixture test confirming MUST-FIX / SHOULD-FIX
  findings on Flask PR #57.
- End-to-end: re-run the canonical benchmark at every depth (4 / 8 / 12 /
  15 / 20) and confirm:
  - Recall non-decreasing as depth grows
  - Token-cost growth roughly linear in depth (not exponential)
  - Each step's finding count documented in
    `docs_dev/codex-comparison/depth-recall-curve.md`

## Out of scope (per user)

- Theme R (GitHub thread automation: post comments / resolve / link issues).
- Theme V (PR-description generation).
- Theme W (session rituals, TTS, metrics dashboards).
- Theme X (custom rule-set config UI).
- Theme Z (workflow/devops dev-time guidance).
- Mermaid sequence-diagram rendering (the underlying flow tracing IS in
  scope; just no visual artifact).

## Status tracker

| Step | Status | Commit |
|---|---|---|
| 0 — domain detection gate | ✅ shipped | d9a48d4 |
| 1 — code-correctness | ✅ shipped | (TRDD-60f53034) |
| 2 — claim-verification | ✅ shipped | (TRDD-60f53034) |
| 3 — skeptical | ✅ shipped | (CAA-original) |
| 4 — security | ✅ shipped | (CAA-original) |
| 5 — linter pre-flight | ✅ shipped | c9ca3d2 |
| 6 — cross-layer drift + ripple-effect + null safety | ✅ script-first split shipped (env-var drift, generated-file detection, orphan-naming scan); existing caa-cross-layer-auditor-agent still owns schema/UI-authz/removed-state judgment | dcc35e1 |
| 7 — multi-tenant data isolation (NEW) | ✅ script shipped (query predicates, cache keys, module state, fn signatures); agent residue pending | 0b2bd72 |
| 8 — silent-failure hunter | ✅ script shipped (Python AST: bare/broad except, empty handler, log-only handler, TODO-in-handler; JS/TS regex: empty catch, console-only catch, ?. over fallible chain; universal mock-fallback); agent residue pending | 5de0ffc |
| 9 — concurrency hazards (NEW) | ✅ script shipped (Python AST: detached create_task/ensure_future/run_in_executor; JS/TS: floating promise + Promise.all-no-catch; Go: goroutine-no-sync + channel-send-after-close); agent residue pending | 445e134 |
| 10 — complexity & dead-code | ✅ script shipped (Python AST: fn-too-long, too-many-branches/params, McCabe complexity, nest-depth, unused imports, orphan module defs, unreachable code; JS/TS brace-balance fn-length) | 8420e44 |
| 11 — AWC extensions | ✅ script shipped (Python/Node UNDECLARED_DEP + UNUSED_DEP cross-check with pyproject/requirements/package.json/Cargo.toml/go.mod; HARDCODED_URL/IP/PATH/PORT + MAGIC_NUMBER) | dca072c |
| 12 — comment & docstring quality | ✅ script shipped (Python AST: Google/NumPy/Sphinx docstring-param mismatch + ghost params + trivial-docstring detection; inline comment-vs-numeric-literal contradiction heuristic); agent residue pending | 2bbf2bd |
| 13 — test quality | ✅ script shipped (Python AST: NO_ASSERTION_TEST, ASSERT_TRUE_LITERAL, MOCK_REPLACES_SUT_HEURISTIC; JS/TS regex: JS_EXPECT_TRUE, JS_EXPECT_TRUTHY, JS_NO_ASSERTION); test-pyramid imbalance heuristic + property-based gap deferred to agent | ee77889 |
| 14 — performance + memory + energy | ⬜ pending | — |
| 15 — database / query / migration (NEW) | ⬜ pending | — |
| 16 — type-design analyzer | ⬜ pending | — |
| 17 — architecture pattern consistency | ⬜ pending | — |
| 18 — pre-mortem risk analyzer | ⬜ pending | — |
| 19 — operational / deployment | ⬜ pending | — |
| 20 — domain specialists (HF) | ⬜ pending | — |
| 21 — domain specialists (LF) | ⬜ pending | — |
| 22 — function-level deep-dive | ⬜ pending | — |
| 23 — Opus second-opinion verification loop | ⬜ pending (external models via llm-externalizer only) | — |
