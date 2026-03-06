# Changelog

All notable changes to this project will be documented in this file.

## [3.1.12] - 2026-03-06

### Changes
- feat: add TOOL GUIDANCE section to all 11 agent definitions (Serena MCP, Grepika MCP, haiku avoidance)
- feat: add Model Selection Rules to all 3 SKILL.md files (Opus/Sonnet only for analysis, Haiku prohibited)
- feat: create caa-collect-context.py — information retrieval script with 3 modes (pr-info, file-context, codebase-overview)
- docs: token consumption audit report (docs_dev/token-consumption-audit-20260306.md)

## [3.1.11] - 2026-03-06

### Changes
- feat: add --quiet flag to caa-generate-todos.py, caa-merge-reports.py, caa-merge-audit-reports.py
- feat: add REPORTING RULES section to all 10 CAA agent definitions (dedup already had it)
- feat: pass --quiet to script invocations in skill SKILL.md files
- refactor: gate verbose print() calls behind `if not quiet:` in all 3 CAA scripts
- refactor: always print 1-line summary with output path regardless of --quiet flag

## [3.1.10] - 2026-03-06

### Changes
- fix: atomic write in caa-generate-todos.py — use tempfile.mkstemp() instead of deterministic .tmp suffix
- fix: smart_exec.py choose_best() — respect prefer_latest flag (try ecosystem executors first)
- fix: smart_exec.py deno_npm_argv — stop passing cmd as argument after `--`
- fix: smart_exec.py executor_versions() — report both uvx and uv (elif→if)
- fix: bump_version.py — extract duplicate exclude_dirs to module-level _EXCLUDE_DIRS constant
- fix: prepare_release.py — detect current branch dynamically instead of hardcoding "main"
- fix: sync_cpv_scripts.py — add error count message before SystemExit(1)
- fix: gitignore_filter.py — add sys.path setup before bare cpv_validation_common import
- fix: update_marketplace_metadata.py — add sys.path setup before bare cpv_validation_common import
- fix: caa-merge-reports.py — route all error/failure messages to stderr
- fix: caa-merge-audit-reports.py — route all error/failure messages to stderr
- fix: add top-level exception handling (__main__ guard) to all 3 CAA scripts
- fix: caa-merge-reports.py pass_number argparse type str→int
- fix: caa-merge-audit-reports.py pass_number argparse type str→int

## [3.1.9] - 2026-03-06

### Changes
- docs: update README — add Phase 4b (security scan) to codebase audit pipeline description
- docs: update README — add 7 missing scripts to Scripts tables
- docs: update README — add caa-security-review-agent to codebase audit agents table
- docs: correct "9-phase" → "10-phase" across README, plugin.json, pyproject.toml, CHANGELOG
- docs: add "security scan" to plugin.json and pyproject.toml descriptions
- fix: FINDING_ID_RE regex in caa-merge-reports.py — allow 2-4 letter prefixes (was 2 only)
- fix: add -intermediate- skip check to caa-merge-reports.py is_skipped() to prevent re-merging
- fix: case-insensitive file extension matching in caa-generate-todos.py RE_INLINE_FILE regex

## [3.1.8] - 2026-03-05

### Changes
- fix: make PASS and RUN_ID optional in security-review-agent INPUT FORMAT for single-pass mode
- fix: align DIFF_PATH → DIFF in skeptical-reviewer and claim-verification agents to match SKILL.md
- fix: duplicate item number "5" → correct numbering (5,6,7) in skeptical-reviewer INPUT FORMAT
- fix: add RUN_ID-omission note to security agent output filename and self-verification checklist

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
- Added caa-codebase-audit-and-fix-skill with 10-phase audit pipeline
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
