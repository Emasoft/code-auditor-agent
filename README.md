# code-auditor-agent

[![CI](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-3.4.1-blue)](https://github.com/Emasoft/code-auditor-agent)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)

**Version:** 3.4.1
**License:** MIT
**Author:** Emasoft

Six-phase PR review pipeline and 10-phase codebase audit pipeline for Claude Code. PR review: code correctness swarm, claim verification, skeptical external review, security analysis with deduplication. Includes iterative fix loop for automated resolution. Codebase audit: file inventory, grep triage, parallel discovery swarm, verification, gap-fill, per-domain consolidation, TODO generation, and optional fix loop with verification.

---

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [Agents](#agents)
- [Skills](#skills)
- [Commands](#commands)
- [Scripts](#scripts)
- [PR Review Pipeline](#pr-review-pipeline)
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

This plugin provides 11 agents, split across two pipelines.

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

---

## Skills

| Skill | Purpose |
|-------|---------|
| `caa-pr-review-skill` | Six-phase PR review pipeline: correctness swarm, claim verification, skeptical review, security analysis, merge + dedup |
| `caa-pr-review-and-fix-skill` | PR review with iterative fix loop: review, fix, re-test, re-review until clean |
| `caa-codebase-audit-and-fix-skill` | Full 10-phase codebase audit: discovery, verify, gap-fill, consolidate, security scan, TODOs, fix, verify fixes |

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
