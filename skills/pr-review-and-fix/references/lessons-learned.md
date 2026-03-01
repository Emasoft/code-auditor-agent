# Lessons Learned (Baked Into This Pipeline)

Hard-won insights from real incidents that shaped the design of the PR Review And Fix pipeline.

## Review Architecture Lessons

1. **Swarms are microscopes.** Great at per-file correctness. Blind to the big picture.

2. **PR descriptions lie.** Not maliciously -- authors believe they implemented what they described.
   The gap between intent and implementation is the #1 source of missed bugs.

3. **Absence is the hardest bug to find.** A missing field assignment produces no error, no warning,
   no test failure. The code compiles and runs fine. Only a claim verifier or skeptical reviewer
   will notice that `fromLabel` is declared in the type but never set in the return statement.

4. **Cross-file consistency requires holistic view.** Version "0.22.5" in JSON-LD but "0.22.4"
   in prose HTML -- each file is internally valid, but together they're inconsistent.

5. **UX judgment is not a code concern.** Auto-copying clipboard on text selection is technically
   correct code. Whether it's a good idea requires a different kind of thinking.

6. **The stranger's perspective is irreplaceable.** Twenty agents who know the codebase missed
   what one agent pretending to be a stranger caught immediately. Fresh eyes see what familiarity
   blinds you to.

## Fix Cycle Lessons

7. **Fixes introduce regressions.** A single fix pass is never enough. The review-fix loop
   catches regressions that manual fix-and-ship workflows miss.

8. **Commit between passes.** Without commits, the diff for subsequent review passes includes
   both the original changes AND the fixes, confusing the reviewers. Clean commits let each
   review pass focus on what changed since the last fix.

9. **Linting catches what reviewers and tests miss.** AI reviewers focus on logic and design;
   tests verify behavior. Neither catches style violations, unused imports, type annotation gaps,
   or language-specific anti-patterns that static analysis tools flag. MegaLinter covers 50+
   linters across all languages in a single Docker run -- a cheap safety net that's worth the
   Docker dependency when available.

## Pipeline Robustness Lessons

10. **Stale files poison the pipeline.** When a pass is interrupted and restarted, leftover
    report files from the prior run get merged into the new run's intermediate report. This
    inflates finding counts, adds duplicate/contradictory findings, and wastes dedup agent
    tokens. Run ID isolation and pre-pass cleanup are defense-in-depth against this.

11. **Agent rate limits are inevitable.** Fix agents can die mid-execution when API rate limits
    hit. Without checkpoints, the orchestrator must manually verify which fixes were applied
    and which weren't. Checkpoint files make recovery automatic.

12. **Line numbers drift across passes.** After multiple fix passes, line numbers in the codebase
    shift. Review agents must verify their cited line numbers against the actual current file
    content, not rely on stale mental models from prior reads.

13. **Task IDs are ephemeral.** When the orchestrator's context is compacted, background agent
    task IDs are lost. An on-disk agent manifest file survives compaction and enables recovery
    without the fragile glob+read-first-5-lines pattern.

---

## Lessons Learned Review Checklist

Copy this checklist and track your progress:

- [ ] Reviewed all 13 lessons before starting the pipeline
- [ ] Verified Phase 2 (claim verification) and Phase 3 (skeptical review) are not skipped
- [ ] Confirmed commit-between-passes strategy is active
- [ ] Confirmed pre-pass cleanup runs before each pass
- [ ] Confirmed checkpoint files are being written by fix agents
- [ ] Confirmed line number verification is included in correctness agent prompts
- [ ] Confirmed agent manifest is written to disk for compaction recovery
