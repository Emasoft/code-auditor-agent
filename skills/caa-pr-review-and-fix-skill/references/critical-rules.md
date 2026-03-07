# Critical Rules

## Table of Contents

- [Rule 1: Never Skip Phases](#rule-1-never-skip-phases)
- [Rule 2: Phase Order Matters](#rule-2-phase-order-matters)
- [Rule 3: UUID-Named Files](#rule-3-uuid-named-files)
- [Rule 4: Two-Stage Merge](#rule-4-two-stage-merge)
- [Rule 5: Dedup Agent Determines Verdict](#rule-5-dedup-agent-determines-verdict)
- [Rule 6: Fix All Severities](#rule-6-fix-all-severities)
- [Rule 7: Commit After Each Fix Pass](#rule-7-commit-after-each-fix-pass)
- [Rule 8: Maximum 25 Passes](#rule-8-maximum-25-passes)
- [Rule 9: Agent-Prefixed Finding IDs](#rule-9-agent-prefixed-finding-ids)
- [Rule 10: UUID-Based Report Filenames](#rule-10-uuid-based-report-filenames)
- [Rule 11: Same Line Different Bugs](#rule-11-same-line-different-bugs)
- [Rule 12: Merge Script Verifies Before Deleting](#rule-12-merge-script-verifies-before-deleting)
- [Rule 13: Linting Is Conditional on Docker](#rule-13-linting-is-conditional-on-docker)
- [Rule 14: Lint-Fix Loop Is Separate](#rule-14-lint-fix-loop-is-separate)

## Rule 1: Never Skip Phases

**NEVER skip Phases 2, 3, or 4.** The correctness swarm alone is insufficient. It will miss
claimed-but-not-implemented features, security vulnerabilities, cross-file inconsistencies,
and UX concerns. Phases 2, 3, and 4 are what make this pipeline catch 100% of issues.

## Rule 2: Phase Order Matters

Phase 1 (parallel) -> Phase 2 (sequential) -> Phase 3 and Phase 4 (run in parallel with each other, both sequential internally).
Later phases can reference earlier reports to avoid duplicate work, but they must NOT
skip their own checks.

## Rule 3: UUID-Named Files

Each agent writes to a UUID-named file. Agents return only 1-2 lines to the orchestrator.
Full findings go in the report files. This prevents context flooding AND file collisions.

## Rule 4: Two-Stage Merge

The Python merge script (v2) does simple concatenation.
The `caa-dedup-agent` does semantic deduplication. NEVER rely on the merge script alone
for dedup -- it deliberately does NOT deduplicate.

## Rule 5: Dedup Agent Determines Verdict

The merge script always exits 0. The dedup agent's
final report contains the accurate counts and verdict.

## Rule 6: Fix All Severities

Fix ALL severities, not just MUST-FIX. The loop terminates only when zero issues
remain -- including SHOULD-FIX and NIT. This ensures a clean codebase.

## Rule 7: Commit After Each Fix Pass

This creates rollback points and ensures clean diffs for subsequent review passes.

## Rule 8: Maximum 25 Passes

If issues persist after 25 passes, stop and escalate to the user.
Infinite loops waste resources and indicate a deeper architectural problem.

## Rule 9: Agent-Prefixed Finding IDs

Phase 1 agents MUST use unique prefixes:
`CC-P{N}-A{hex_index}-{NNN}` (e.g., `CC-P1-A0-001`, `CC-P1-A1-001`).
Phase 2/3/4 single agents use `CV-P{N}-{NNN}`, `SR-P{N}-{NNN}`, and `SC-P{N}-{NNN}`.
This eliminates ID collisions between parallel correctness agents.

## Rule 10: UUID-Based Report Filenames

All agent output files MUST include a UUID:
`caa-{phase}-P{N}-{uuid}.md`. This prevents file overwrites between concurrent agents.

## Rule 11: Same Line Different Bugs

The dedup agent must never merge findings that describe different issues at the same code location. Two bugs at line 42 are two bugs, not one.

## Rule 12: Merge Script Verifies Before Deleting

The v2 merge script deletes source files only after verifying the intermediate file exists and is non-empty. (The merged output extracts only severity-section content, so byte-size comparison is not used.) This prevents data loss from partial writes or filesystem errors.

## Rule 13: Linting Is Conditional on Docker

The MegaLinter step runs ONLY if Docker is installed and the daemon is running. If Docker is unavailable, skip linting entirely and proceed to commit. Never fail a pass because Docker is missing -- linting is an enhancement, not a gate.

## Rule 14: Lint-Fix Loop Is Separate

Within a single pass, the lint->fix cycle can iterate up to 3 times. These iterations do NOT increment the main pass number. Only the outer review->fix loop increments the pass counter.
