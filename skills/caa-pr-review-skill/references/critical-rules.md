# Critical Rules

## Table of Contents

- [Rule 1: Never Skip Phases](#rule-1-never-skip-phases)
- [Rule 2: Phase Order](#rule-2-phase-order)
- [Rule 3: UUID Filenames](#rule-3-uuid-filenames)
- [Rule 4: Two-Stage Merge](#rule-4-two-stage-merge)
- [Rule 5: Agent Prefix Assignment](#rule-5-agent-prefix-assignment)
- [Rule 6: UUID Collision Prevention](#rule-6-uuid-collision-prevention)
- [Rule 7: Same Line Not Same Bug](#rule-7-same-line-not-same-bug)
- [Rule 8: Re-Run After Fixes](#rule-8-re-run-after-fixes)
- [Rule 9: Merge Script Safety](#rule-9-merge-script-safety)

## Rule 1: Never Skip Phases

**NEVER skip Phases 2, 3, or 4.** The correctness swarm alone is insufficient. It will miss
claimed-but-not-implemented features, cross-file inconsistencies, UX concerns, and security
vulnerabilities. Phases 2, 3, and 4 are what make this pipeline catch 100% of issues.

## Rule 2: Phase Order

Phase 1 (parallel swarm) -> Phase 2 (sequential) -> Phase 3 + Phase 4
(parallel with each other, sequential after Phase 2) -> Phase 5 (merge) -> Phase 6 (present).
Later phases can reference earlier reports to avoid duplicate work, but they must NOT
skip their own checks.

## Rule 3: UUID Filenames

Each agent writes to a UUID-named file. Agents return only 1-2 lines to the orchestrator.
Full findings go in the report files. This prevents context flooding and file collisions.

## Rule 4: Two-Stage Merge

Stage 1 (Python script) concatenates without dedup.
Stage 2 (caa-dedup-agent) performs semantic deduplication. The Python script handles
simple concatenation; the AI agent handles complex same-line-different-bug decisions.

## Rule 5: Agent Prefix Assignment

Each Phase 1 agent gets a unique hex prefix (A0, A1, ...)
assigned by the orchestrator at spawn time. Finding IDs use this prefix (CC-P1-A0-001,
CC-P1-A1-001) to guarantee global uniqueness within a pass.

## Rule 6: UUID Collision Prevention

Each agent generates a UUID for its output file
(`python3 -c "import uuid; print(uuid.uuid4())"`). This eliminates file overwrites between
concurrent agents.

## Rule 7: Same Line Not Same Bug

Two findings at the same file:line are only duplicates if they
describe the same root cause. The dedup agent uses semantic analysis, not just line
number matching.

## Rule 8: Re-Run After Fixes

After fixing issues, re-run the full pipeline to verify the fixes
are correct and didn't introduce new issues.

## Rule 9: Merge Script Safety

The v2 merge script deletes source files only after verifying the intermediate file
exists and is non-empty. (The merged output extracts only severity-section content,
so it is typically smaller than source files — byte-size comparison is not used.)
If verification fails, source files are preserved for manual inspection.
