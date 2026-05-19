# code-auditor-agent

<!--BADGES-START-->
[![CI](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-3.4.4-blue)](https://github.com/Emasoft/code-auditor-agent)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
<!--BADGES-END-->

**Version:** 3.4.4
**License:** MIT
**Author:** Emasoft

Configurable PR review pipeline (24 steps across 7 tiers, scaled by `--code-analysis-depth N`, default 4) and 10-phase codebase audit pipeline for Claude Code. PR review baseline (depth=4): code correctness swarm, claim verification, skeptical external review, security analysis with deduplication — plus an iterative fix loop for automated resolution. Deeper depths add 20 additional detectors covering linters/scanners, cross-layer drift, multi-tenancy, silent failures, concurrency, complexity, dependencies, comments, tests, performance, databases, type design, architecture, pre-mortem risk, operational gaps, domain specialists, function-level deep-dive, and an Opus second-opinion verification loop — see [Bug-Detection Depth Tiers](#bug-detection-depth-tiers). Codebase audit: file inventory, grep triage, parallel discovery swarm, verification, gap-fill, per-domain consolidation, TODO generation, and optional fix loop with verification.

---

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [Agents](#agents)
- [Skills](#skills)
- [Commands](#commands)
- [Scripts](#scripts)
- [PR Review Pipeline](#pr-review-pipeline)
- [Bug-Detection Depth Tiers](#bug-detection-depth-tiers)
- [Codebase Audit Pipeline](#codebase-audit-pipeline)
- [Report Naming Convention](#report-naming-convention)
- [CI/CD](#cicd)
- [Development](#development)
- [License](#license)

---

## Installation

**Requirements:** Claude Code v2.1.94 or later.

Install from the `emasoft-plugins` marketplace:

```text
/plugin install code-auditor-agent@emasoft-plugins
```

After installing, run `/reload-plugins` to activate without restarting.

Choose an installation scope:

| Scope | Command | Use case |
|-------|---------|----------|
| User (default) | `/plugin install code-auditor-agent@emasoft-plugins` | Personal use across all projects |
| Project | `claude plugin install code-auditor-agent@emasoft-plugins --scope project` | Shared with team via `.claude/settings.json` |
| Local | `claude plugin install code-auditor-agent@emasoft-plugins --scope local` | Project-specific, gitignored |

To uninstall: `/plugin uninstall code-auditor-agent@emasoft-plugins`. Use `--keep-data` to preserve persistent audit state in `${CLAUDE_PLUGIN_DATA}`.

For local development, launch Claude Code with the plugin directory:

```bash
claude --plugin-dir /path/to/code-auditor-agent
```

### Team Setup

Add the marketplace to your project's `.claude/settings.json` so team members get prompted to install it automatically:

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

---

## Features

- **11 specialized agents** across two pipelines (PR review + codebase audit)
- **3 skills** with progressive disclosure, reference documentation, and explicit `allowed-tools` declarations
- **Tool safety enforcement** via `disallowedTools` frontmatter — all 10 read-only agents are blocked from using Edit/NotebookEdit, preventing accidental source code modification
- **Per-group dispatch** — Phase 0 Python script groups files into non-overlapping batches; each downstream step (externalizer, agents, fix agents) reuses the same grouping. Fix agents receive ONLY their assigned files — zero redundant reads
- **LLM Externalizer integration** — offloads per-group code analysis (correctness, functionality, adversarial review), consolidation, TODO generation, and fix guidance to cheaper external LLMs via GROUP markers (115s timeout, auto-retry on truncation)
- **Worktree isolation** — optional `USE_WORKTREES=true` for concurrent agent swarms (discouraged: default per-group dispatch already prevents conflicts without worktree overhead)
- **Persistent plugin data** — uses `${CLAUDE_PLUGIN_DATA}` for audit state (Fix Dispatch Ledger, agent checkpoints) that survives plugin updates and context compactions
- **Code intelligence tools** — agents use Serena MCP (`find_symbol`, `find_referencing_symbols`), Grepika (`search`, `refs`, `outline`), and TLDR (`structure`, `search`) when available for semantic code navigation instead of raw file reading

### Plugin Environment Variables

These variables are referenced inside the plugin (skills, agents, hooks):

| Variable | Purpose |
|----------|---------|
| `${CLAUDE_PLUGIN_ROOT}` | Absolute path to plugin installation directory. Used to reference bundled scripts and configs. Changes on plugin update. |
| `${CLAUDE_PLUGIN_DATA}` | Persistent directory for plugin state (`~/.claude/plugins/data/code-auditor-agent/`). Survives plugin updates. Used for Fix Dispatch Ledger, agent checkpoints. Deleted on uninstall unless `--keep-data` is passed. |
| `${CLAUDE_SKILL_DIR}` | Absolute path to the current skill's directory. Used in SKILL.md to reference `references/` subdirectories. |
| `${CLAUDE_SESSION_ID}` | Current Claude Code session ID. Useful for session-scoped report filenames. |

### Recommended Claude Code Environment Variables

These Claude Code env vars are useful when running this plugin (set them in your shell or `~/.claude/settings.json`):

| Variable | Recommended | Why |
|----------|-------------|-----|
| `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE` | `1` | Keep marketplace cache when offline (added v2.1.90). |
| `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` | `1` | Strip Anthropic and cloud credentials from subprocess env (added v2.1.98). Recommended when fix-agent runs build/test commands. |
| `CLAUDE_CODE_CERT_STORE` | `system` (default) or `bundled` | TLS CA store. Default trusts OS CA bundle. Set to `bundled` for hermetic environments (added v2.1.101). |
| `CLAUDE_CODE_SCRIPT_CAPS` | `{"publish.py": 5}` | Cap how many times a script can be invoked per session (added v2.1.98). |
| `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS` | `0` | Keep built-in git workflow instructions. The plugin's fix-agent and publish.py rely on them. |
| `OTEL_LOG_TOOL_DETAILS` | `1` | Include `tool_parameters` in OpenTelemetry traces (added v2.1.85, default off). Useful for auditing external scans. |

---

## Agents

This plugin provides 13 agents, split across two pipelines + the
extended-review extension (TRDD-6857f67f).

### PR Review Pipeline Agents

| Agent | Purpose | Concurrency |
|-------|---------|-------------|
| `caa-code-correctness-agent` | Per-file correctness audit (type safety, logic, security, shell scripts) | Swarm (one per domain) |
| `caa-claim-verification-agent` | Verifies PR description claims against actual code | Single instance |
| `caa-skeptical-reviewer-agent` | Holistic review as an external maintainer (UX, breaking changes, consistency) | Single instance |
| `caa-security-review-agent` | Deep security review (OWASP, injections, secrets, attack surface) | Single instance |
| `caa-dedup-agent` | Semantic deduplication of merged review findings | Single instance |

### Codebase Audit Pipeline Agents

| Agent | Purpose | Concurrency |
|-------|---------|-------------|
| `caa-domain-auditor-agent` | Per-domain file auditing against reference standard | Swarm (one per batch) |
| `caa-verification-agent` | Cross-checks audit reports for accuracy, finds missed files | Swarm (one per report) |
| `caa-consolidation-agent` | Merges per-domain findings, deduplicates, harmonizes severity | Up to 5 |
| `caa-security-review-agent` | Deep security scan: OWASP, secrets, dependency CVEs (Phase 4b) | Single instance |
| `caa-todo-generator-agent` | Generates actionable TODO files from consolidated findings | Up to 5 |
| `caa-fix-agent` | Implements TODO fixes with checkpoint tracking | Swarm (one per domain) |
| `caa-fix-verifier-agent` | Verifies fixes were applied correctly, detects regressions | Swarm (one per fix report) |

### Extended Review Agents (TRDD-6857f67f)

Activated by `/audit-codebase --extended` and `/pr-review --extended`.
Adds end-to-end scenario coverage and per-file assumption coverage that
line-level review cannot reach. Designed to work for ANY software type
the scenario generator recognises (web, CLI, library, mobile, firmware,
RTOS, Linux kernel module, FPGA, browser extension, IaC, data pipeline,
ML training, distributed system, etc., plus an `unknown_software`
fallback).

| Agent | Purpose | Concurrency |
|-------|---------|-------------|
| `caa-scenario-walker-agent` | Type-blind scenario executor: consumes scenarios.json, plays the actor role, walks the static call graph, flags divergences between intended and actual behaviour | Swarm (one per scenario or cluster, ≤15 parallel) |
| `caa-assumption-auditor-agent` | Extracts implicit assumptions across 10 families (input shape, ordering, idempotency, auth state, network/IO, numerical, concurrency, data model, encoding, time/clock); generates adversarial inputs per assumption | Swarm (one per high-risk file) |

The two new agents share an additive integration with consolidation/
dedup/todo-gen: findings from line-level + scenario + assumption agents
that point at the SAME defect get merged into ONE finding with all three
evidence frames preserved.

---

## Skills

| Skill | Purpose |
|-------|---------|
| `caa-pr-review-skill` | Six-phase PR review pipeline: correctness swarm, claim verification, skeptical review, security analysis, merge + dedup |
| `caa-pr-review-and-fix-skill` | PR review with iterative fix loop: review, fix, re-test, re-review until clean |
| `caa-codebase-audit-and-fix-skill` | Full 10-phase codebase audit: discovery, verify, gap-fill, consolidate, security scan, TODOs, fix, verify fixes |
| `caa-scenario-generator-skill` | (Extended review) Deterministic discovery: classifies the codebase into one of ~70 software types and emits scenarios.json — universal schema covering HTTP routes, CLI commands, ISR vectors, syscall handlers, FPGA top ports, etc. Consumed by `caa-scenario-walker-agent` |

### `caa-pr-review-skill` (review only)

Review a PR without modifying code. Runs the six-phase pipeline and presents a verdict.

```text
review PR 206
```

### `caa-pr-review-and-fix-skill` (review + iterative fix loop)

Review a PR AND automatically fix all findings. Loops until zero issues remain (max 25 passes).

```text
review and fix PR 206
```

Each pass runs the PR Review Pipeline (six-phase review) then a fix cycle (fix swarm + tests + commit). The loop terminates when a review pass finds zero issues or 25 passes are reached.

Fix agents are dynamically selected from whatever agents are available in the user's Claude Code instance, with `general-purpose` as the universal fallback.

### Worktree Mode (Optional)

All three skills support an optional `USE_WORKTREES=true` parameter that runs agent swarms in isolated git worktrees. This is useful for:

- **Large PRs** with many domains where concurrent agents might see each other's in-progress changes
- **Fix pipelines** where multiple fix agents modify code simultaneously
- **Isolation guarantees** — each agent gets a clean, independent snapshot of the repo

To enable: include "use worktrees" or "with worktrees" in your request:

```text
review and fix PR 206 with worktrees
/audit-codebase --scope ./src --standard ./docs/rules.md --fix --worktrees
```

Requirements: clean git state, sufficient disk space for worktree copies.

### `caa-codebase-audit-and-fix-skill` (full codebase audit)

Run a comprehensive 10-phase codebase audit with optional automatic fix application.

```text
/audit-codebase
```

---

## Commands

| Command | Trigger | Purpose |
|---------|---------|---------|
| `caa-audit-codebase-cmd` | `/audit-codebase` | Full codebase audit — every file, no exceptions. Configurable scope, standard, and fix mode |
| `caa-delta-audit-cmd` | `/delta-audit` | Incremental audit of changed files since a git ref. NOT a substitute for full audit |

---

## Scripts

### Pipeline Scripts

| Script | Purpose |
|--------|---------|
| `caa-merge-reports.py` | Concatenates phase reports into intermediate merged report (UUID-aware) |
| `caa-merge-audit-reports.py` | Python merger for codebase audit reports |
| `caa-generate-todos.py` | Converts consolidated findings into skeleton TODO files |
| `caa-collect-context.py` | Pre-gathers PR info, file context, or codebase overview for agents |
| `universal_pr_linter.py` | Runs MegaLinter via Docker for PR linting |

### Publishing and Infrastructure Scripts (in `scripts/`)

| Script | Purpose |
|--------|---------|
| `publish.py` | Unified 4-phase publish pipeline (pre-flight, validate, audit, push) with atomic rollback |
| `bump_version.py` | Semantic version bumping across `plugin.json` and `pyproject.toml` |
| `check_version_consistency.py` | Verifies version strings match across all config files |
| `setup_git_hooks.py` | Installs pre-commit and pre-push hooks from git-hooks/ |
| `setup_plugin_pipeline.py` | Configures plugin CI/CD pipeline and validates structure |
| `setup_marketplace_automation.py` | Sets up marketplace notification workflow and metadata |
| `update_marketplace_metadata.py` | Updates marketplace.json with current plugin metadata |
| `lint_files.py` | Runs ruff linting and mypy type checking on Python sources |
| `gitignore_filter.py` | Filters file lists through .gitignore rules for validation |
| `smart_exec.py` | Intelligent script executor with timeout and error handling |

### Git Hooks (in `git-hooks/`)

| Hook | Purpose |
|------|---------|
| `pre-commit` | Runs plugin validation via CPV remote execution before each commit |
| `pre-push` | Runs full plugin validation before pushing to remote |

Install hooks with `uv run python scripts/setup_git_hooks.py`.

---

## PR Review Pipeline

The PR review pipeline (Procedure 1) runs six phases:

```
Phase 1: Spawn correctness agents (one per domain, parallel swarm)
Phase 2: Spawn claim verification agent
Phase 3: Spawn skeptical reviewer agent
Phase 4: Spawn security review agent (parallel with Phase 3)
Phase 5: Merge reports via caa-merge-reports.py + dedup agent
Phase 6: Present final report
```

**Phase 1 -- Code Correctness Swarm.** One `caa-code-correctness-agent` is spawned per code domain (e.g., Python files, shell scripts, TypeScript files). Each agent audits files in its domain for type safety errors, logic bugs, security vulnerabilities, and shell script correctness. Agents run in parallel as a swarm.

**Phase 2 -- Claim Verification.** A single `caa-claim-verification-agent` reads the PR description and cross-references every claim (e.g., "adds retry logic", "fixes race condition") against the actual diff. Claims that cannot be verified in the code are flagged.

**Phase 3 -- Skeptical Review.** A single `caa-skeptical-reviewer-agent` performs a holistic review from the perspective of an external maintainer. It evaluates UX impact, breaking changes, API consistency, and architectural concerns that per-file audits miss.

**Phase 4 -- Security Review.** A single `caa-security-review-agent` performs deep security analysis of all changed files. It checks for OWASP Top 10 vulnerabilities, injection attacks, secrets exposure, authentication bypasses, dependency CVEs, and attack surface analysis. Runs in parallel with Phase 3.

**Phase 5 -- Merge + Dedup.** The `caa-merge-reports.py` script concatenates all phase reports into an intermediate merged report. Then `caa-dedup-agent` performs semantic deduplication, removing findings that are duplicates or subsets of other findings.

**Phase 6 -- Final Report.** The deduplicated report is presented as the final verdict.

When using `caa-pr-review-and-fix-skill`, a fix cycle follows each review pass:

```
Fix Cycle (Procedure 2, only if issues found):
  Fix all findings (parallel, one agent per domain)
  Run tests, fix regressions
  Commit fixes
  Loop back to Phase 1 with incremented pass counter
```

---

## Bug-Detection Depth Tiers

The PR review skill accepts `--code-analysis-depth N` (or `--preset
quick|standard|deep|thorough|full`) to scale how thoroughly the diff
is audited. Default depth is **4** — the four original steps. Twenty
more steps cover specific categories of bugs; each one is independent,
so `--code-analysis-depth 10` runs steps 0–10 and leaves 11–23
dormant.

### What each step checks for

**Step 0 — Domain detection.** Looks at the project's files and works
out what's in play: Python, JavaScript, Docker, GraphQL, a database, a
mobile app, etc. Does no bug-finding itself — it tells the rest of the
pipeline which specialised checks should wake up later.

**Step 1 — Code-correctness swarm.** Reads every changed file and
looks for plain old bugs: a function called with the wrong arguments,
a variable used before it's defined, a typo in an attribute name, an
off-by-one in a loop, an unhandled branch. The kind of bug a careful
reviewer would spot reading the diff line by line.

**Step 2 — Claim & linked-issue verification.** Reads the PR
description and the linked issue, then checks the code actually does
what the description claims. Catches mismatches like "this PR adds
retry logic" when the diff has no retry, or "fixes issue #42" when
the actual cause was never touched.

**Step 3 — Skeptical holistic review.** Plays the role of an outside
maintainer looking at the PR from 10,000 feet. Asks: is this a
breaking change for callers? Does the new API behave the same way as
the existing ones? Is there an obvious UX issue? Does the docs page
need updating? Things no per-file check would catch.

**Step 4 — Security review.** Hunts for the classic security holes:
SQL injection, cross-site scripting, hardcoded passwords, secrets
leaking into logs, unsafe deserialisation, command injection, weak
crypto, missing auth on a new endpoint. Covers the OWASP Top 10.

**Step 5 — Linter & scanner pre-flight.** Runs every available
off-the-shelf linter on the changed files (ruff, mypy, eslint, gofmt,
clippy, hadolint, sqlfluff, trivy, semgrep, gitleaks, and ~10 more)
and rolls up the results. Cheap way to catch style violations, type
errors, dead code, unsafe patterns, and many CVE-grade
vulnerabilities.

**Step 6 — Cross-layer drift detector.** Catches cases where one layer
of the codebase changed and the layer next to it didn't. Examples: a
new environment variable added to the code but not to the docs; an
auto-generated file that should have been regenerated but wasn't; a
function renamed but two old call sites still reference the old name.

**Step 7 — Multi-tenant data isolation.** For apps that host multiple
customers on the same database, checks that every new query, cache
key, or shared piece of state includes the tenant identifier. Catches
the bug where tenant A can accidentally read tenant B's data.

**Step 8 — Silent-failure hunter.** Finds places where the code
swallows errors quietly: an empty `except` block, a `try`/`catch`
that just logs and moves on as if nothing happened, an optional chain
like `x?.y` over an operation that really shouldn't fail silently, a
fallback that quietly uses a mock when the real service is down. The
bugs you only notice in production when the metrics look weird.

**Step 9 — Concurrency hazards.** Looks at async code for the bugs
that only show up under load: a coroutine started but never awaited,
a JavaScript promise that's left dangling, a goroutine that leaks,
two locks taken in the wrong order, an "atomic" operation that isn't,
a channel that gets a send after it was closed.

**Step 10 — Complexity & dead-code scanner.** Flags functions that
are too long, have too many branches, take too many arguments, or are
buried inside deep nesting. Also flags imports that are never used,
exports nobody imports, code paths that can't be reached, and helper
functions nobody calls — leftovers from old refactors.

**Step 11 — Agent-written-code extensions.** Catches the small
footguns common in AI-generated code: dependencies imported but not
declared in `pyproject.toml` / `package.json`; dependencies declared
but never used; URLs, IPs, file paths, or port numbers hardcoded
inline instead of put in config; magic numbers that should be named
constants.

**Step 12 — Comment & docstring quality.** Reads docstrings and
compares them to the function signature. Catches docs that name
parameters that no longer exist (ghost params), docs that miss real
parameters, useless one-line docstrings like "Does the thing.", and
inline comments that flatly contradict the code.

**Step 13 — Test-quality scanner.** Looks at the test files in the PR
and flags tests that won't actually catch a regression: tests with no
`assert` / `expect`, tests whose only assertion is `assert True`,
tests that mock the very thing they're supposed to be testing, plus
bug-fixes that didn't ship with a regression test.

**Step 14 — Performance, memory, energy.** Looks for code that will
be slow or wasteful: a database query inside a `for` loop (N+1),
deeply nested loops, a recursive function with no memoisation, a
giant file loaded entirely into memory instead of streamed, retain
cycles that leak memory, mobile-specific things that drain the
battery.

**Step 15 — Database / query / migration correctness.** Audits
database changes specifically: a SQL migration with no downgrade
path, an empty downgrade, a string-formatted SQL query (classic
injection target), an `ALTER TABLE` / `DROP TABLE` placed outside the
migration system, a missing foreign key or NOT NULL constraint, an
accounting / ledger invariant the new code doesn't preserve.

**Step 16 — Type-design analyzer.** When the PR introduces a new
public type (class, struct, interface, enum), this asks: does the
type actually rule out illegal states, or is everything wrapped in
`Optional<Optional<…>>`? Does its shape force users to handle the
edge cases the team cares about? Catches types that look strict but
don't really constrain anything.

**Step 17 — Architecture pattern consistency.** Reads three or four
modules near the changed file to learn how the team writes things,
then flags places where the new code does it differently for no
reason: different error-handling style, different naming scheme,
different data shape, different layering. Helps the codebase stay
coherent.

**Step 18 — Pre-mortem risk analyzer.** Pretends the PR has been live
for 6 months and asks "what blew up?". Classifies each risk as Tiger
(real and dangerous), Paper Tiger (looks scary but the code already
handles it), or Elephant (everyone knows about it, nobody acts).
Forces each Tiger finding to include evidence of what was checked and
what wasn't.

**Step 19 — Operational / deployment.** Catches PRs that change
something operational but forget the matching paperwork: a
proto/openapi/graphql schema touched without regenerating the client;
a CI workflow changed without notes; a Dockerfile changed without
docs; a release that's missing a rollback plan.

**Step 20 — Domain specialists, high-frequency (6 reviewers).** Each
wakes up only when its domain shows up in the diff:

- **GraphQL:** N+1 resolvers, missing query-depth limits, exposed introspection.
- **JWT:** weak signing algorithms, missing `exp`/`aud` claims, hardcoded secrets.
- **API design:** REST verb misuse, missing pagination, inconsistent error envelopes.
- **Docker:** running as root, `latest` tags, image bloat, secrets baked into layers.
- **Prompt-injection / LLM safety:** untrusted text concatenated into a prompt.
- **Frontend:** missing accessibility attributes, XSS, weak CSP, slow Web Vitals.

**Step 21 — Domain specialists, lower-frequency (8 reviewers).** Same
idea for the less common stacks:

- **iOS:** state on the wrong thread, weak Keychain usage, SwiftUI/Combine leaks.
- **Elixir / Phoenix:** OTP supervisor misuse, GenServer state leaks.
- **Solidity:** reentrancy, integer overflow, unchecked external calls.
- **MCP server:** tool-call auth gaps, command injection in tool wrappers.
- **i18n:** hardcoded strings that should be translated, locale-blind formatting.
- **l10n:** date / number / currency formatting that ignores the user's locale.
- **Monorepo:** cross-package imports that break the dependency graph.
- **Logging:** PII or secrets accidentally written to log lines.

**Step 22 — Function-level deep-dive.** Picks the 3–5 highest-risk
new or substantially-modified functions and walks each through a
15-question checklist: Who calls it? What state does it mutate? What
happens when its dependency fails? Is it safe to retry? Is it
idempotent? Does the docstring contract match the body? Does an
existing function in the codebase already do this?

**Step 23 — Second-opinion verification loop.** A second-pass
reviewer reads the entire merged report with fresh eyes — playing a
hostile maintainer — and either downgrades, drops, or upgrades each
finding, or adds new ones the swarm missed. A follow-up pass checks
that the author's fix commits actually addressed the original
findings instead of just touching the same lines.

### Depth presets

| Preset | Depth | Steps run | What it adds |
|--------|-------|-----------|--------------|
| `quick` | 4 | 0–4 | **Default.** Original baseline. PR sanity check. |
| `standard` | 10 | 0–10 | + linters, cross-layer, multi-tenant, silent-failure, concurrency, complexity |
| `deep` | 15 | 0–15 | + AWC extensions, comments, tests, performance, database |
| `thorough` | 19 | 0–19 | + type-design, architecture, pre-mortem, operational |
| `full` | 23 | 0–23 | Every step. Domain specialists, function deep-dive, second-opinion. |

---

## Codebase Audit Pipeline

The codebase audit pipeline runs ten phases:

```
Phase 0:  File inventory + grep triage
Phase 1:  Discovery swarm (parallel auditors, 3-4 files each)
Phase 2:  Verification swarm
Phase 3:  Gap-fill (iterative until 100% coverage)
Phase 4:  Per-domain consolidation
Phase 4b: Security scan (vulnerabilities, secrets, dependency CVEs)
Phase 5:  TODO generation
Phase 6:  Fix implementation (if --fix)
Phase 7:  Fix verification (if --fix)
Phase 8:  Final merged report
```

**Phase 0 -- File Inventory + Grep Triage.** The pipeline inventories all files in scope and runs grep-based triage to classify files by domain and identify high-priority targets.

**Phase 1 -- Discovery Swarm.** `caa-domain-auditor-agent` instances are spawned in parallel, each auditing a batch of 3-4 files against the configured reference standard. Each agent produces a per-domain audit report.

**Phase 2 -- Verification Swarm.** `caa-verification-agent` instances cross-check every audit report for accuracy, flagging false positives and identifying files that were missed.

**Phase 3 -- Gap-Fill.** Any files not covered in Phase 1 are assigned to additional auditor agents. This phase iterates until 100% file coverage is achieved.

**Phase 4 -- Per-Domain Consolidation.** `caa-consolidation-agent` instances merge findings within each domain, deduplicate issues, and harmonize severity ratings across reports.

**Phase 4b -- Security Scan (mandatory).** A single `caa-security-review-agent` performs deep security analysis of all audited files. It runs automated tools (trufflehog, bandit, osv-scanner, pip-audit, trivy, semgrep) when available, checks for OWASP Top 10 vulnerabilities, secrets exposure, dependency CVEs, and attack surface analysis. Security findings are appended to consolidated reports before TODO generation.

**Phase 5 -- TODO Generation.** `caa-todo-generator-agent` instances convert consolidated findings into actionable TODO files, one per domain.

**Phase 6 -- Fix Implementation (optional).** When `--fix` is enabled, `caa-fix-agent` instances implement the TODO items with checkpoint tracking, one agent per domain.

**Phase 7 -- Fix Verification (optional).** `caa-fix-verifier-agent` instances verify that each fix was applied correctly and detect any regressions introduced by the fixes.

**Phase 8 -- Final Merged Report.** All findings, fixes, and verification results are merged into a single final report via `caa-merge-audit-reports.py`.

---

## Report Naming Convention

Report filenames follow a pipeline-specific pattern. Codebase audit reports use `caa-{type}-P{N}-R{RUN_ID}-{UUID}.md`. PR review reports use a shorter pattern (see table below); `R{RUN_ID}` is included only in multi-pass runs via `caa-pr-review-and-fix-skill`.

Reports are written to `reports/code-auditor/` (created automatically if missing). The directory is gitignored via the `*_dev/` pattern. Override with `--report-dir` on `/audit-codebase` or `/delta-audit`.

### PR Review Reports

| Report Type | Filename Pattern |
|-------------|------------------|
| Correctness (per-domain) | `caa-correctness-P{N}-{uuid}.md` |
| Claim verification | `caa-claims-P{N}-{uuid}.md` |
| Skeptical review | `caa-review-P{N}-{uuid}.md` |
| Security review | `caa-security-P{N}-{uuid}.md` |
| Intermediate merged report | `caa-pr-review-P{N}-intermediate-{timestamp}.md` |
| Final dedup report | `caa-pr-review-P{N}-{timestamp}.md` |
| Fix summary (per-domain) | `caa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `caa-tests-outcome-P{N}.md` |
| Final clean report | `caa-pr-review-and-fix-FINAL-{timestamp}.md` |

> **Note:** When called from `caa-pr-review-and-fix-skill` (multi-pass), PR review reports include `R{RUN_ID}` in filenames (e.g., `caa-correctness-P{N}-R{RUN_ID}-{uuid}.md`). Single-pass `caa-pr-review-skill` omits `R{RUN_ID}`.

### Codebase Audit Reports

| Report Type | Filename Pattern |
|-------------|------------------|
| Audit (per-domain) | `caa-audit-P{N}-R{RUN_ID}-{UUID}.md` |
| Verification | `caa-verify-P{N}-R{RUN_ID}-{UUID}.md` |
| Consolidated (per-domain) | `caa-consolidated-{domain}.md` |
| Fix summary (per-domain) | `caa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `caa-tests-outcome-P{N}.md` |

Where:
- `{N}` is the pass number (starting from 1)
- `{RUN_ID}` is the unique run identifier for the audit session
- `{UUID}` is a short UUID for deduplication and uniqueness
- `{domain}` is the code domain name (e.g., `python`, `shell`, `typescript`)
- `{timestamp}` is an ISO 8601 timestamp

---

## CI/CD

Four GitHub Actions workflows are configured:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Push to main, Pull Request, Manual dispatch | Lint, typecheck, validate `plugin.json`, check version consistency |
| `release.yml` | Tag push (`v*`) | Tag-triggered GitHub Release with changelog generation |
| `notify-marketplace.yml` | Push to main (plugin changes) | Notifies the marketplace repository when the plugin is updated |
| `security.yml` | Push, Pull Request | Security scanning (bandit, pip-audit, trufflehog, dependabot alerts) |

---

## Development

### Publishing

Always use the unified publish pipeline (never push directly):

```bash
uv run python scripts/publish.py --patch   # e.g. 3.2.3 -> 3.2.4
uv run python scripts/publish.py --minor   # e.g. 3.2.3 -> 3.3.0
uv run python scripts/publish.py --major   # e.g. 3.2.3 -> 4.0.0
```

The pipeline runs 4 phases: pre-flight checks (connectivity, clean tree, remote version), validate (lint, strict validation, version consistency), audit (gitignore, stale files, YAML lint), then mutate+push (bump, README, CHANGELOG, commit, tag, atomic push with rollback on failure). The pre-push hook enforces that all pushes go through this pipeline.

### Validating

Run the full validation suite via CPV remote execution (no local scripts needed):

```bash
uvx --from git+https://github.com/Emasoft/claude-plugins-validation --with pyyaml cpv-remote-validate plugin . --verbose --strict
```

`cpv-remote-validate` is the wrapper that isolates validation from the target's local config files. The `plugin` subcommand runs the full plugin validation suite.

Claude Code also validates frontmatter via `claude plugin validate`.

### CI

CI runs automatically on pull requests and can be triggered manually via workflow_dispatch. It performs:

1. Linting and type checking
2. `plugin.json` schema validation
3. Version consistency checks across all config files

---

## License

MIT
