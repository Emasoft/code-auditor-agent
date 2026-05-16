# TRDD-7e364ace — Bug-detection completeness from PR-Review corpus

**TRDD ID:** `7e364ace-1fd3-41ed-abc8-1ab96c02c935`
**Filename:** `design/tasks/TRDD-7e364ace-1fd3-41ed-abc8-1ab96c02c935-bug-detection-completeness.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)
**Status:** In progress (step 1-4 baseline shipped)
**Source inventory:** `docs_dev/codex-comparison/FULL-PR-REVIEW-INVENTORY.md`

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

## Step ordering (1 → 20, by priority/ROI)

Each step is a self-contained pipeline stage, sequenced by ROI per token.
The PR-review command accepts `--code-analysis-depth N` (default `4`,
range `1..20`). Steps `1..N` run; steps `N+1..20` stay dormant.

Steps 1-4 are the current pipeline (already shipped). Steps 5-20 are new.

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
| 7 | **Silent-failure hunter** — AST: empty catches, broad catches, catch-and-only-log, `?.` over fallible calls, fallback-to-mock-in-prod (script-detected) + agent judges retry-without-user-feedback / fallback in error-pathway / missing context | `scripts/prereview/silent_failure.py` + `caa-silent-failure-hunter-agent` (NEW) | J1-J11 |

### Tier III — Code-quality scanners (still mostly deterministic)

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 8 | **Complexity & dead-code scanner** — fn-too-long (>20 lines), too-many-branches (>5), too-many-parameters (>3), cyclomatic complexity (>10), nested-loop depth, unused imports, unused exports, unreachable code | `scripts/prereview/complexity.py` | M3, M4, M5, N2, P4, G13 |
| 9 | **Agent-written-code extensions** — inconsistent style with nearby code (linter delta), excessive dependencies (parse manifest vs actual imports), unused abstractions, hardcoded values that should be config | `scripts/prereview/awc_extensions.py` + extend `caa-code-correctness-agent` AWC checklist | G11, G12, G13, G14 |
| 10 | **Comment & docstring quality** — docstring-param mismatch (mechanical), comment-vs-code factual contradiction (script grep + agent judgment), completeness, long-term value, misleading elements | `scripts/prereview/docstring_diff.py` + `caa-comment-quality-agent` (NEW) | L1-L6 |

### Tier IV — Per-class detection (script-heavy + slim agent)

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 11 | **Test-quality scanner** — mock-replaces-SUT, no-assertion tests, `assert True`, test-naming-too-short (DAMP), test-pyramid imbalance, regression-test-for-every-fix, feature-flag both-states tested | `scripts/prereview/test_quality.py` + agent judgment | I1-I11, E9 |
| 12 | **Performance review** — N+1 heuristic (DB query inside loop), nested loops > depth 2, large-allocations-in-hot-paths, large-files-fully-read, missing memoisation | `scripts/prereview/performance.py` + `caa-performance-review-agent` (NEW) | P1-P5 |

### Tier V — Pure judgment (agent-only, narrow checklist)

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 13 | **Type-design analyzer** — 4-dimensional invariant rating (encapsulation, expression, usefulness, enforcement); anti-pattern catalogue; "make illegal states unrepresentable". Fires only when the diff adds a new public type | `caa-type-design-analyzer-agent` (NEW) | K1-K8 |
| 14 | **Architecture pattern consistency** — new code follows existing module patterns; polyglot boundaries; data-structure consistency; API-design consistency; inherits-from-different-base | `caa-architecture-consistency-agent` (NEW) | N3-N8 |
| 15 | **Pre-mortem / risk analyzer** — Tiger / Paper-Tiger / Elephant taxonomy with mandatory `mitigation_checked: "what was NOT found"` evidence on every Tiger; verify-before-flagging gate | `caa-pre-mortem-agent` (NEW) | O1-O8 |

### Tier VI — Operational, domain specialists, deep dive

| # | Step | Owner | Source IDs |
|---|---|---|---|
| 16 | **Operational / deployment** — rollback plan, migration forward+reverse, release annotations, cross-platform compat, generated-files-updated, CI / build / formatter / lint passing | `scripts/prereview/operational.py` + agent residue | Q3-Q8 |
| 17 | **Domain specialists, high-frequency** — fire only when `domains_detected` contains the marker. GraphQL: query complexity, N+1 via DataLoader, persisted queries, schema versioning. JWT: alg whitelist, kid, none-rejection, claims (iss/aud/exp/nbf/sub), rotation, JWKS. REST API: URL structure, status codes, pagination, versioning, OpenAPI alignment. DB: indexes, transactions, migration up+down, connection pooling, integrity constraints | `caa-graphql-reviewer-agent`, `caa-jwt-reviewer-agent`, `caa-api-design-reviewer-agent`, `caa-database-reviewer-agent` (all NEW) | T1, T2, H9, H10, Y6, Y7 |
| 18 | **Domain specialists, lower-frequency** — Docker: pinned versions, non-root, multi-stage, health checks, no-`latest`. i18n: hardcoded strings, RTL, text-expansion, namespace. l10n: regional variants, fallback chains, Intl.* usage. monorepo: workspace boundaries, shared-package discipline, build-cache validity. logging: env-aware verbosity, structured, no-sensitive-data, error-IDs | `caa-docker-reviewer-agent`, `caa-i18n-reviewer-agent`, `caa-l10n-reviewer-agent`, `caa-monorepo-reviewer-agent`, `caa-logging-reviewer-agent` (all NEW) | T3, T4, T5, Y8, Y9 |
| 19 | **Function-level deep dive** — for each changed function: 15-question checklist (callers, mutated state, dep-failure paths, similar function exists, contract drift, error paths). Slow; only run at high depth | `caa-function-deep-dive-agent` (NEW) | D3 |
| 20 | **Second-opinion verification loop** — Opus agent re-reviews the consolidated CAA output as a hostile maintainer; if the user wants a non-Claude second opinion they invoke `llm-externalizer` separately on the report file. Two passes: PASS-1 fresh review, PASS-2 verifies PASS-1 findings actually addressed | `caa-second-opinion-agent` (NEW, Opus) — Codex/external models NOT embedded; delegated to llm-externalizer when the user asks | S1, S4-S6, S9 (S2-S3, S7-S8, S10 dropped — Codex-CLI-specific) |

## Default depth: 4 (current behavior)

Default is `--code-analysis-depth 4` to preserve current token costs. Users
opting into deeper scans accept the additional cost. Recommended presets:

| Preset | Depth | Use-case |
|---|---|---|
| `quick` | 4 | Current behavior. PR sanity check. |
| `standard` | 8 | Adds linters, cross-layer, silent-failure, complexity. |
| `deep` | 12 | Adds AWC extensions, comment quality, test quality, performance. |
| `thorough` | 15 | Adds type-design, architecture, pre-mortem. |
| `full` | 20 | Every step. No bug escapes. |

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
| 1 — code-correctness | ✅ shipped | (TRDD-60f53034) |
| 2 — claim-verification | ✅ shipped | (TRDD-60f53034) |
| 3 — skeptical | ✅ shipped | (CAA-original) |
| 4 — security | ✅ shipped | (CAA-original) |
| 5 — linter pre-flight | ⬜ pending | — |
| 6 — cross-layer drift | ⬜ pending (caa-cross-layer-auditor-agent already exists; needs script-first split) | — |
| 7 — silent-failure | ⬜ pending | — |
| 8 — complexity | ⬜ pending | — |
| 9 — AWC extensions | ⬜ pending | — |
| 10 — comment quality | ⬜ pending | — |
| 11 — test quality | ⬜ pending | — |
| 12 — performance | ⬜ pending | — |
| 13 — type-design | ⬜ pending | — |
| 14 — architecture consistency | ⬜ pending | — |
| 15 — pre-mortem | ⬜ pending | — |
| 16 — operational | ⬜ pending | — |
| 17 — domain specialists (HF) | ⬜ pending | — |
| 18 — domain specialists (LF) | ⬜ pending | — |
| 19 — function deep-dive | ⬜ pending | — |
| 20 — Opus second-opinion verification loop | ⬜ pending (external models via llm-externalizer only) | — |
