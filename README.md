# code-auditor-agent

<!--BADGES-START-->
[![CI](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-4.3.0-blue)](https://github.com/Emasoft/code-auditor-agent)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
<!--BADGES-END-->

**Version:** 4.3.0
**License:** MIT
**Author:** Emasoft

Ultracode code-review engine for Claude Code. ONE deterministic map → filter → reduce
workflow (`scripts/workflows/caa-engine.js`, run by the Workflow tool) drives every
operation over swarms of opus agents: pre-commit gating, whole-codebase or scoped scans,
delta rechecks, scan-and-fix with per-fix adversarial verification, and GitHub PR review
with claim-verification, cross-layer, and skeptical whole-diff lenses — plus 21 distilled
domain lenses (docker, solidity, iOS, GraphQL, elixir, frontend, monorepo, i18n, l10n,
JWT, prompt-injection, logging, MCP-server, API design, type design, assumptions,
function contracts, pre-mortem, architecture consistency, scenario-walk, skeptical).
**Every finding is adversarially verified by a second, independent reviewer before it is
reported** — refuted and downgraded findings are listed with the evidence that killed
them, never silently dropped.

---

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Components](#components)
- [Reports](#reports)
- [Engine reference](#engine-reference)
- [Advanced ultracode](#advanced-ultracode)
- [Development](#development)
- [License](#license)

---

## Installation

**Requirements:** Claude Code v2.1.154 or later (the Workflow tool) with `uv`/`uvx` and opus
access at session effort `xhigh` or `max` for the **ultracode** path. Without the Workflow tool
(ultracode disabled in settings/env), or with `CAA_ULTRACODE=0`, the commands fall back to a
**simple inline scan** at any effort — same reports, lower fidelity (no agent swarm). See
[Ultracode vs. simple-scan fallback](#ultracode-vs-simple-scan-fallback).

Install from the `emasoft-plugins` marketplace:

```text
/plugin install code-auditor-agent@emasoft-plugins
```

After installing, run `/reload-plugins` to activate without restarting.

| Scope | Command | Use case |
|-------|---------|----------|
| User (default) | `/plugin install code-auditor-agent@emasoft-plugins` | Personal use across all projects |
| Project | `claude plugin install code-auditor-agent@emasoft-plugins --scope project` | Shared with team via `.claude/settings.json` |
| Local | `claude plugin install code-auditor-agent@emasoft-plugins --scope local` | Project-specific, gitignored |

For local development, launch Claude Code with the plugin directory:

```bash
claude --plugin-dir /path/to/code-auditor-agent
```

### Team Setup

Add the marketplace to your project's `.claude/settings.json` so team members get
prompted to install it automatically:

```json
{
  "extraKnownMarketplaces": {
    "emasoft-plugins": {
      "source": {
        "source": "github",
        "repo": "Emasoft/emasoft-plugins"
      }
    }
  },
  "enabledPlugins": {
    "code-auditor-agent@emasoft-plugins": true
  }
}
```

## Usage

Raise the session effort first — the engine is opus-only and every command halts below
`xhigh`:

```text
/effort max
```

Then pick the command that matches the job:

| You want to… | Command |
|---|---|
| Gate the STAGED files before a commit (PASS/FAIL verdict) | `/caa-precommit` |
| Audit the whole repo, or an explicit path/glob, scan-only | `/caa-scan [paths...]` |
| Recheck only the files changed since a git ref (+ dependents) | `/caa-delta [ref] [deps]` |
| Audit AND apply root-cause fixes (in place, fix-verified) | `/caa-scan-and-fix [paths...]` |
| Review a GitHub PR (ready-to-post review comment) | `/caa-pr-review <pr-number>` |
| Audit a codebase against a spec / requirements doc (MISSING + VIOLATING) | `/caa-spec-audit <spec> [paths...]` |
| Compare candidate implementations of one task against a fixed input | `/caa-impl-compare <input> <impl...>` |

Examples:

```text
/caa-precommit
/caa-scan scripts/ skills/ min-severity=MAJOR
/caa-scan src/chat component=chat-audit lenses=docs/invariants.md
/caa-delta origin/main deps
/caa-scan-and-fix scripts/foo.py
/caa-pr-review 206
/caa-spec-audit design/requirements/PRRD.md src/
/caa-impl-compare bench/contract.md impls/v1.py impls/v2.py
```

Shared knobs (all commands): `conc=N` concurrent auditors (default 6, max 16);
`component=NAME` sub-folder for the reports; `min-severity=SEV` body filter;
`lenses=p1,p2` extra project rule files every auditor must apply; `template=path`
report template; `no-project-lenses` to skip the automatic `CLAUDE.md` +
`.claude/rules/*.md` ingestion.

Cost note: each audited file costs roughly 300k subagent tokens at `xhigh`
(map + adversarial verify). Whole-repo scans estimate the cost and ask for
confirmation before launching a large swarm.

## How it works

```text
files ──► MAP one opus auditor per file (byte-identical cached prompt; target path last)
      ──► FILTER adversarial verifier per file (different reviewer; refutes/downgrades FPs)
      ──► DOMAIN stack-specific lens audits (file × active lens; specs in scripts/workflows/lenses/)
      ──► REDUCE one consolidated report + findings.json
   fix mode adds: FIX (one exclusive fixer per file, root-cause only) ──► FIX-VERIFY ──► fix report
   pr lens-set adds: CLAIM-VERIFICATION + CROSS-LAYER + SKEPTICAL (once-per-run, whole-diff)
```

Robustness is built into the engine: every agent call is failure-wrapped, rate limits
re-queue the file at a halved concurrency cap (the re-queue IS the backoff), reduce
steps retry once and report a `failed` status instead of polluting results, returned
report paths are validated (a lens that writes no report is reported as failed, never
silently dropped), and concurrent runs are isolated by per-run temp namespaces.
The engine itself is covered by a deterministic mock-DSL test suite
(`tests/engine/run_engine_tests.mjs`) that executes the real engine body with a
scripted agent boundary.

## Components

- **Commands** — review: `/caa-precommit`, `/caa-scan`, `/caa-delta`, `/caa-scan-and-fix`,
  `/caa-pr-review`; plus `/caa-spec-audit` (codebase vs a spec → MISSING + VIOLATING) and
  `/caa-impl-compare` (rank implementations vs a fixed input) — two legacy redirect aliases
  remain. Thin wrappers: they resolve the scope/config, then invoke the shared engine.
- **Engine** — `scripts/workflows/caa-engine.js`, the single source of truth for all
  audit logic.
- **Domain lenses** — `scripts/workflows/lenses/*.lens.md`, 21 compact specialist
  checklists distilled from the former reviewer agents. `/caa-pr-review` activates them
  via the deterministic detector `scripts/prereview/detect_languages_and_domains.py`.
- **Skills** — `caa-codebase-audit-and-fix-skill`, `caa-pr-review-skill`,
  `caa-pr-review-and-fix-skill` (trigger surfaces pointing at the commands),
  `caa-scenario-generator-skill` (scenario JSON for the scenario-walk lens),
  `ecaa-self-test-24` (recall + precision efficacy gate over seeded-bug fixtures).
- **Role agent** — `agents/code-auditor-agent-main-agent.md` + `code-auditor-agent.agent.toml`
  for headless `claude --agent code-auditor-agent-main-agent` dispatch.

## Reports

Intermediates go to a deletable per-run temp dir. The ONE consolidated report always
lands in the audited repo at:

```text
reports/code-auditor-agent/[<component>/]<YYYYMMDD_HHMMSS±HHMM>-<suffix>.md
reports/code-auditor-agent/[<component>/]<YYYYMMDD_HHMMSS±HHMM>-<suffix>.findings.json
```

`findings.json` carries one record per finding INCLUDING refuted/downgraded ones:
`{id, file, line, severity, title, evidence, status, confidence, suggested_fix,
lens_source, verification_note}` — pipe it into your own tooling or renderers.
`reports/` must be gitignored in the audited repo.

## Engine reference

`Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js", args})`:

| arg | meaning |
|---|---|
| `root`, `files[]` | absolute repo root + absolute file paths (required) |
| `task` | `review` (default) \| `spec-compliance` \| `impl-compare` — selects the workflow shape |
| `specFile` | spec/requirements doc (required for `spec-compliance`); sits in the cached prefix |
| `inputSpec` | fixed input/contract/harness (required for `impl-compare`); `files[]` are the candidates |
| `mode` | `scan` (default) \| `scan-and-fix` (review task only) |
| `lensSet` | `combined` (default) \| `pr` (adds the three once-per-run PR lenses) |
| `reportType` | `audit` \| `gate` \| `pr-comment` |
| `reportSuffix`, `scopeLabel`, `component`, `minSeverity`, `reportTemplate` | report shaping |
| `projectLenses[]` | project rule files every auditor must also apply |
| `domainLenses[]`, `lensDir` | active lens keys + the PLUGIN's lens dir (`${CLAUDE_PLUGIN_ROOT}/scripts/workflows/lenses`) |
| `diffFile`, `descFile`, `prNumber` | PR inputs (pr lens-set) |
| `runId` | unique id namespacing the temp dir (wrappers pass `$(date +%s)-$$`) |
| `conc` | max concurrent opus agents, clamped to [1,16] (default 6) |

Unknown enum values and relative paths fail fast with an explanatory error; unknown
`domainLenses` keys are surfaced in the result, the log, and the report.

### Ultracode vs. simple-scan fallback

Every command runs one of two ways:

- **Ultracode** (default when available): the Workflow-tool engine above — a map→filter→reduce
  opus swarm with an adversarial verify pass. Needs the `Workflow` tool and session effort
  `xhigh`/`max`.
- **Simple-scan fallback** (`scripts/workflows/caa-simple-scan.md`): a single-pass inline review —
  the same lenses and the **same report contract** (`SUMMARY` / `VERDICT` lines, `findings.json`,
  reports under `reports/code-auditor-agent/`), but no agent swarm and no separate adversarial
  filter. Lower fidelity; runs at any effort, anywhere.

A command takes the **simple-scan** path when the `Workflow` tool is unavailable (ultracode
disabled in Claude Code settings/env, or a nested agent session) **or** when `CAA_ULTRACODE` is set
to `0` / `off` / `false` / `no`. Otherwise it uses **ultracode**, and if a `Workflow` call fails for
a nesting/availability reason it recovers into the simple scan rather than erroring. Set
`CAA_ULTRACODE=0` to force the cheap path even when ultracode is available.

## Advanced ultracode

Caching and the three task shapes. The engine is ONE parameterized `map → (filter) → reduce` pipeline that runs **three task shapes**,
all sharing the pool, the rate-limit backoff, and the cache discipline (single source of truth):

- **`review`** — code audit (the five review commands above).
- **`spec-compliance`** — each file classified against `specFile`; the reduce emits **MISSING**
  (spec clauses no file implements) and **VIOLATING** (code that contradicts a clause).
- **`impl-compare`** — each candidate in `files[]` evaluated against the fixed `inputSpec`; the
  reduce **ranks** the candidates and names a winner.

**The cache law CAA is engineered around.** The Anthropic API caches on `(model, exact prompt
prefix)` — any two requests with the same model and prefix read the same cache, and a change
anywhere in the prefix recomputes everything after it. So every map/filter prompt is built as
**a byte-identical shared prefix followed by one per-agent suffix appended LAST**: the heavy shared
content (the review criteria, or the spec, or the fixed input) lives in the cached prefix, and only
the single target path varies. Across N agents the first warms the cache and the rest read it.

A corollary from the [sub-agent docs](https://code.claude.com/docs/en/prompt-caching): a **fork**
sub-agent shares the main session's cache, but a **named** sub-agent (what the Workflow tool spawns)
builds its own — so the cross-agent saving here comes from this identical-prefix design, not from
fork-sharing. `impl-compare` is the clearest illustration: the input is cached once and only the
candidate script changes — *cache the input, vary the script*.

## Development

```bash
uv sync --extra dev
uv run pytest                          # full suite (includes the engine mock-DSL tests)
node tests/engine/run_engine_tests.mjs # engine tests directly
uv run ruff check .
```

Validation: this plugin vendors **no** local validator scripts — validation always
invokes the [CPV](https://github.com/Emasoft/claude-plugins-validation) plugin remotely
(the same gate runs in the pre-commit/pre-push hooks, CI, and the publish pipeline):

```bash
uvx --from git+https://github.com/Emasoft/claude-plugins-validation --with pyyaml \
  cpv-remote-validate plugin . --verbose --strict
```

Releases go ONLY through the publish pipeline (the pre-push hook blocks direct pushes):

```bash
uv run python scripts/publish.py --patch   # or --minor / --major
```

Install the git hooks once with `uv run python scripts/setup_git_hooks.py`.

## License

MIT — see [LICENSE](LICENSE).
