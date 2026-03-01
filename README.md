# ai-maestro-code-auditor-agent

**Version:** 2.0.0
**License:** MIT
**Author:** Emasoft

Three-phase PR review pipeline and full codebase audit pipeline for Claude Code. PR review: code correctness swarm, claim verification, skeptical external review with deduplication. Codebase audit: file inventory, grep triage, parallel discovery swarm, verification, gap-fill, per-domain consolidation, TODO generation, and optional fix loop with verification.

---

## Table of Contents

- [Installation](#installation)
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

Install from the `emasoft-plugins` marketplace:

```text
/install-plugin emasoft-plugins:ai-maestro-code-auditor-agent
```

For local development, launch Claude Code with the plugin path:

```bash
claude --use-plugin /path/to/ai-maestro-code-auditor-agent
```

---

## Agents

This plugin provides 10 agents, split across two pipelines.

### PR Review Pipeline Agents

| Agent | Purpose | Concurrency |
|-------|---------|-------------|
| `amcaa-code-correctness-agent` | Per-file correctness audit (type safety, logic, security, shell scripts) | Swarm (one per domain) |
| `amcaa-claim-verification-agent` | Verifies PR description claims against actual code | Single instance |
| `amcaa-skeptical-reviewer-agent` | Holistic review as an external maintainer (UX, breaking changes, consistency) | Single instance |
| `amcaa-dedup-agent` | Semantic deduplication of merged review findings | Single instance |

### Codebase Audit Pipeline Agents

| Agent | Purpose | Concurrency |
|-------|---------|-------------|
| `amcaa-domain-auditor-agent` | Per-domain file auditing against reference standard | Swarm (one per batch) |
| `amcaa-verification-agent` | Cross-checks audit reports for accuracy, finds missed files | Swarm (one per report) |
| `amcaa-consolidation-agent` | Merges per-domain findings, deduplicates, harmonizes severity | Up to 5 |
| `amcaa-todo-generator-agent` | Generates actionable TODO files from consolidated findings | Up to 5 |
| `amcaa-fix-agent` | Implements TODO fixes with checkpoint tracking | Swarm (one per domain) |
| `amcaa-fix-verifier-agent` | Verifies fixes were applied correctly, detects regressions | Swarm (one per fix report) |

---

## Skills

| Skill | Purpose |
|-------|---------|
| `pr-review` | Three-phase PR review: correctness swarm, claim verification, skeptical review, merge + dedup |
| `pr-review-and-fix` | PR review with iterative fix loop: review, fix, re-test, re-review until clean |
| `codebase-audit-and-fix` | Full 9-phase codebase audit: discovery, verify, gap-fill, consolidate, TODOs, fix, verify fixes |

### `pr-review` (review only)

Review a PR without modifying code. Runs the three-phase pipeline and presents a verdict.

```text
review PR 206
```

### `pr-review-and-fix` (review + iterative fix loop)

Review a PR AND automatically fix all findings. Loops until zero issues remain (max 10 passes).

```text
review and fix PR 206
```

Each pass runs the PR Review Pipeline (three-phase review) then a fix cycle (fix swarm + tests + commit). The loop terminates when a review pass finds zero issues or 10 passes are reached.

Fix agents are dynamically selected from whatever agents are available in the user's Claude Code instance, with `general-purpose` as the universal fallback.

### `codebase-audit-and-fix` (full codebase audit)

Run a comprehensive 9-phase codebase audit with optional automatic fix application.

```text
/audit-codebase
```

---

## Commands

| Command | Trigger | Purpose |
|---------|---------|---------|
| `amcaa-audit-codebase-cmd` | `/audit-codebase` | Launch codebase audit with configurable scope, standard, and fix mode |

---

## Scripts

### Pipeline Scripts

| Script | Purpose |
|--------|---------|
| `amcaa-merge-reports-v2.sh` | Concatenates phase reports into intermediate merged report (v2, UUID-aware) |
| `amcaa-merge-reports.sh` | Legacy v1 merger with in-script deduplication |
| `amcaa-merge-audit-reports.py` | Python merger for codebase audit reports |
| `amcaa-generate-todos.py` | Converts consolidated findings into skeleton TODO files |
| `universal_pr_linter.py` | Runs MegaLinter via Docker for PR linting |

### Publishing Scripts (in `scripts/`)

| Script | Purpose |
|--------|---------|
| `bump_version.py` | Semantic version bumping across `plugin.json` and `pyproject.toml` |
| `check_version_consistency.py` | Validates version matches across all config files |

---

## PR Review Pipeline

The PR review pipeline (Procedure 1) runs five phases:

```
Phase 1: Spawn correctness agents (one per domain, parallel swarm)
Phase 2: Spawn claim verification agent
Phase 3: Spawn skeptical reviewer agent
Phase 4: Merge reports via amcaa-merge-reports-v2.sh + dedup agent
Phase 5: Present final report
```

**Phase 1 -- Code Correctness Swarm.** One `amcaa-code-correctness-agent` is spawned per code domain (e.g., Python files, shell scripts, TypeScript files). Each agent audits files in its domain for type safety errors, logic bugs, security vulnerabilities, and shell script correctness. Agents run in parallel as a swarm.

**Phase 2 -- Claim Verification.** A single `amcaa-claim-verification-agent` reads the PR description and cross-references every claim (e.g., "adds retry logic", "fixes race condition") against the actual diff. Claims that cannot be verified in the code are flagged.

**Phase 3 -- Skeptical Review.** A single `amcaa-skeptical-reviewer-agent` performs a holistic review from the perspective of an external maintainer. It evaluates UX impact, breaking changes, API consistency, and architectural concerns that per-file audits miss.

**Phase 4 -- Merge + Dedup.** The `amcaa-merge-reports-v2.sh` script concatenates all phase reports into an intermediate merged report. Then `amcaa-dedup-agent` performs semantic deduplication, removing findings that are duplicates or subsets of other findings.

**Phase 5 -- Final Report.** The deduplicated report is presented as the final verdict.

When using `pr-review-and-fix`, a fix cycle follows each review pass:

```
Fix Cycle (Procedure 2, only if issues found):
  Fix all findings (parallel, one agent per domain)
  Run tests, fix regressions
  Commit fixes
  Loop back to Phase 1 with incremented pass counter
```

---

## Codebase Audit Pipeline

The codebase audit pipeline runs nine phases:

```
Phase 0: File inventory + grep triage
Phase 1: Discovery swarm (parallel auditors, 3-4 files each)
Phase 2: Verification swarm
Phase 3: Gap-fill (iterative until 100% coverage)
Phase 4: Per-domain consolidation
Phase 5: TODO generation
Phase 6: Fix implementation (if --fix)
Phase 7: Fix verification (if --fix)
Phase 8: Final merged report
```

**Phase 0 -- File Inventory + Grep Triage.** The pipeline inventories all files in scope and runs grep-based triage to classify files by domain and identify high-priority targets.

**Phase 1 -- Discovery Swarm.** `amcaa-domain-auditor-agent` instances are spawned in parallel, each auditing a batch of 3-4 files against the configured reference standard. Each agent produces a per-domain audit report.

**Phase 2 -- Verification Swarm.** `amcaa-verification-agent` instances cross-check every audit report for accuracy, flagging false positives and identifying files that were missed.

**Phase 3 -- Gap-Fill.** Any files not covered in Phase 1 are assigned to additional auditor agents. This phase iterates until 100% file coverage is achieved.

**Phase 4 -- Per-Domain Consolidation.** `amcaa-consolidation-agent` instances merge findings within each domain, deduplicate issues, and harmonize severity ratings across reports.

**Phase 5 -- TODO Generation.** `amcaa-todo-generator-agent` instances convert consolidated findings into actionable TODO files, one per domain.

**Phase 6 -- Fix Implementation (optional).** When `--fix` is enabled, `amcaa-fix-agent` instances implement the TODO items with checkpoint tracking, one agent per domain.

**Phase 7 -- Fix Verification (optional).** `amcaa-fix-verifier-agent` instances verify that each fix was applied correctly and detect any regressions introduced by the fixes.

**Phase 8 -- Final Merged Report.** All findings, fixes, and verification results are merged into a single final report via `amcaa-merge-audit-reports.py`.

---

## Report Naming Convention

All reports use the pattern: `amcaa-{type}-P{N}-R{RUN_ID}-{UUID}.md`

Reports are written to `docs_dev/`.

### PR Review Reports

| Report Type | Filename Pattern |
|-------------|------------------|
| Correctness (per-domain) | `amcaa-correctness-P{N}-{uuid}.md` |
| Claim verification | `amcaa-claims-P{N}-{uuid}.md` |
| Skeptical review | `amcaa-review-P{N}-{uuid}.md` |
| Intermediate merged report | `pr-review-P{N}-intermediate-{timestamp}.md` |
| Final dedup report | `pr-review-P{N}-{timestamp}.md` |
| Fix summary (per-domain) | `amcaa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `amcaa-tests-outcome-P{N}.md` |
| Final clean report | `pr-review-and-fix-FINAL-{timestamp}.md` |

### Codebase Audit Reports

| Report Type | Filename Pattern |
|-------------|------------------|
| Audit (per-domain) | `amcaa-audit-P{N}-R{RUN_ID}-{UUID}.md` |
| Verification | `amcaa-verify-P{N}-R{RUN_ID}-{UUID}.md` |
| Consolidated (per-domain) | `amcaa-consolidated-{domain}.md` |
| Fix summary (per-domain) | `amcaa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `amcaa-tests-outcome-P{N}.md` |

Where:
- `{N}` is the pass number (starting from 1)
- `{RUN_ID}` is the unique run identifier for the audit session
- `{UUID}` is a short UUID for deduplication and uniqueness
- `{domain}` is the code domain name (e.g., `python`, `shell`, `typescript`)
- `{timestamp}` is an ISO 8601 timestamp

---

## CI/CD

Three GitHub Actions workflows are configured:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | Push, Pull Request | Lint, typecheck, validate `plugin.json`, check version consistency |
| `release.yml` | Tag push (`v*`) | Tag-triggered GitHub Release with changelog generation |
| `notify-marketplace.yml` | Plugin changes | Notifies the marketplace repository when the plugin is updated |

---

## Development

### Bumping the Version

Use the bump script to increment the version across `plugin.json` and `pyproject.toml`:

```bash
python scripts/bump_version.py patch   # 2.0.0 -> 2.0.1
python scripts/bump_version.py minor   # 2.0.0 -> 2.1.0
python scripts/bump_version.py major   # 2.0.0 -> 3.0.0
```

### Checking Version Consistency

Verify that all config files agree on the version:

```bash
python scripts/check_version_consistency.py
```

### Creating a Release

Tag the commit and push to trigger the release workflow:

```bash
git tag v2.0.0
git push --tags
```

The `release.yml` workflow will create a GitHub Release with an auto-generated changelog.

### CI

CI runs automatically on every push and pull request. It performs:

1. Linting and type checking
2. `plugin.json` schema validation
3. Version consistency checks across all config files

---

## License

MIT
