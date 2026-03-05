# Changelog

All notable changes to this project will be documented in this file.

## [3.1.7] - 2026-03-05

### Changes
- fix: correct "Four-phase" to "Six-phase" across all docs, skills, config (pipeline has 6 phases)
- fix: add Phase 5+6 note to review perspective table in SKILL.md
- fix: update SKILL.md versions from 2.0.0 to 3.1.7, add missing version field to codebase-audit skill
- fix: worktree range "Phase 1-3" → "Phase 1-4" to include security review
- fix: dedup agent phase code "SA" → "SC" for security, add codebase audit codes to checklist
- fix: add 6 missing agents to agent-recovery.md timeout table and agentType enum
- fix: REPORT_PATH → REPORT_DIR in correctness, claim-verification, skeptical-reviewer agents
- fix: add AGENT_PREFIX, FINDING_ID_PREFIX to agent INPUT FORMAT sections
- fix: .stat() guards, missing_ok=True, sys.exit(1) in merge scripts
- fix: add errors="replace" for UTF-8 resilience in caa-generate-todos.py
- fix: add missing CHANGELOG entries for v3.1.1 and v3.1.2

## [3.1.6] - 2026-03-05

### Changes
- compat: adopt `${CLAUDE_PLUGIN_ROOT}` brace notation in all SKILL.md and reference files (Claude Code 2.1.69)
- compat: update skill descriptions to use "Trigger with" + "Use when" format for validator compliance
- compat: add post-compaction behavior note to agent-recovery.md (Claude Code 2.1.69 no longer produces preamble recap)
- chore: standardize variable references in procedure-1-review.md and procedure-2-fix.md

## [3.1.5] - 2026-03-03

### Changes
- chore: sync 21 CPV validation scripts from upstream v1.5.2

## [3.1.4] - 2026-03-03

### Changes
- fix: SHA-pin all GitHub Actions (checkout, setup-uv, action-gh-release) for supply-chain safety
- fix: add timeout-minutes and concurrency groups to all CI/CD workflows
- fix: add job-level permissions to release.yml
- fix: pin bandit/pip-audit versions in security.yml
- fix: file existence guard in caa-merge-reports.py before .stat() call
- fix: safer colon parsing in caa-generate-todos.py (split vs index)
- fix: pip-audit two-step command in security agent (uv pip compile + pip-audit)
- fix: "Four-phase" → "Six-phase" in procedure-1-review.md
- fix: add security agent to agent-recovery.md scope/timeout/enum
- fix: add Phase 4b security scan to caa-audit-codebase-cmd.md
- fix: add codebase audit phase codes to dedup agent
- docs: update README CI/CD section count, add publishing scripts table

## [3.1.3] - 2026-03-03

### Changes
- chore: sync CPV validation scripts from upstream (multiple rounds)
- fix: resolve validation warnings — document git-hooks, fix TOC link
- feat: add security scanning CI workflow and enhance security review agent
- fix: resolve critical skill audit findings (off-by-one, missing PR_NUMBER)
- fix: CI version check uses --plugin-dir flag instead of positional arg
- chore: bump version through 3.1.1, 3.1.2, 3.1.3

## [3.1.2] - 2026-03-03

### Changes
- chore: sync 2 CPV skill validators from upstream, bump to 3.1.2

## [3.1.1] - 2026-03-03

### Changes
- chore: sync 11 CPV validation scripts from upstream, bump to 3.1.1

## [3.1.0] - 2026-03-01

### Changes
- fix: mypy return type annotation in sync_cpv_scripts.py (921de1c)
- feat: release automation, CPV sync, git hooks (75cc464)
- fix: audit findings — swapped phases, stale refs, version, changelog (a5ea13b)

## [3.0.0] - 2026-03-01

### Features
- Added security review agent (caa-security-review-agent, SC prefix)
- Integrated security review as Phase 4 in PR review pipeline (parallel with Phase 3)
- Replaced validation scripts with claude-plugins-validation suite
- Added markdownlint configuration
- Version bump to 3.0.0

### Breaking Changes
- Renamed plugin from ai-maestro-code-auditor-agent to code-auditor-agent
- Renamed all amcaa- prefixes to caa-

## [2.0.0] - 2026-03-01

### Features
- Renamed plugin from emasoft-pr-checking-plugin to code-auditor-agent
- Unified prefix from epcp-/epca- to caa- across all agents, scripts, and commands
- Added caa-codebase-audit-and-fix-skill with 9-phase audit pipeline
- Added 6 new agents for codebase auditing: domain-auditor, verification, consolidation, todo-generator, fix, fix-verifier
- Added caa-audit-codebase-cmd command for launching codebase audits
- Added CI/CD workflows for validation, release, and marketplace notification
- Added publishing scripts: bump_version.py, check_version_consistency.py

### Breaking Changes
- All agent, script, and command filenames changed from epcp-/epca- prefix to caa-
- All report filename patterns changed from epcp-/epca- to caa-

## [1.0.0] - 2026-02-01

### Features
- Initial release as emasoft-pr-checking-plugin
- Three-phase PR review pipeline: code correctness, claim verification, skeptical review
- Deduplication agent for merged findings
- Iterative review-and-fix loop skill
- Merge report scripts (v1 and v2)
- Universal PR linter with MegaLinter/Docker support
