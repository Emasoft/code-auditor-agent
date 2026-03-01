# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2026-03-01

### Features
- Renamed plugin from emasoft-pr-checking-plugin to ai-maestro-code-auditor-agent
- Unified prefix from epcp-/epca- to amcaa- across all agents, scripts, and commands
- Added codebase-audit-and-fix skill with 9-phase audit pipeline
- Added 6 new agents for codebase auditing: domain-auditor, verification, consolidation, todo-generator, fix, fix-verifier
- Added amcaa-audit-codebase-cmd command for launching codebase audits
- Added CI/CD workflows for validation, release, and marketplace notification
- Added publishing scripts: bump_version.py, check_version_consistency.py

### Breaking Changes
- All agent, script, and command filenames changed from epcp-/epca- prefix to amcaa-
- All report filename patterns changed from epcp-/epca- to amcaa-

## [1.0.0] - 2026-02-01

### Features
- Initial release as emasoft-pr-checking-plugin
- Three-phase PR review pipeline: code correctness, claim verification, skeptical review
- Deduplication agent for merged findings
- Iterative review-and-fix loop skill
- Merge report scripts (v1 and v2)
- Universal PR linter with MegaLinter/Docker support
