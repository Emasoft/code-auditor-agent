# Lessons Learned (Baked Into This Pipeline)

These lessons emerged from a real incident where 20+ specialized audit agents checked a 40-file PR and found zero issues, while a single external reviewer immediately found 3 real bugs.

1. **Swarms are microscopes.** Great at per-file correctness. Blind to the big picture.
2. **PR descriptions lie.** Not maliciously — authors believe they implemented what they described.
   The gap between intent and implementation is the #1 source of missed bugs.
3. **Absence is the hardest bug to find.** A missing field assignment produces no error, no warning,
   no test failure. The code compiles and runs fine. Only a claim verifier or skeptical reviewer
   will notice that `fromLabel` is declared in the type but never set in the return statement.
4. **Cross-file consistency requires holistic view.** Version "0.22.5" in JSON-LD but "0.22.4"
   in prose HTML — each file is internally valid, but together they're inconsistent.
5. **UX judgment is not a code concern.** Auto-copying clipboard on text selection is technically
   correct code. Whether it's a good idea requires a different kind of thinking.
6. **The stranger's perspective is irreplaceable.** Twenty agents who know the codebase missed
   what one agent pretending to be a stranger caught immediately. Fresh eyes see what familiarity
   blinds you to.

## Checklist

- [ ] Phase 1 (correctness swarm) catches per-file bugs but not big-picture issues
- [ ] Phase 2 (claim verification) catches PR description lies and missing implementations
- [ ] Phase 3 (skeptical review) catches cross-file inconsistencies and UX concerns
- [ ] All three phases are necessary — no single phase catches everything
- [ ] Re-run the full pipeline after fixes to verify no regressions
