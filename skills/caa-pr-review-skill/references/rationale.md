# Why This Pipeline Exists

## Table of Contents

- [The Incident](#the-incident)
- [Four Complementary Perspectives](#four-complementary-perspectives)

## The Incident

In a real incident, 20+ specialized audit agents checked a 40-file PR and found zero issues.
A single external reviewer then immediately found 3 real bugs — including a function that
claimed to populate 4 fields but actually populated zero of them. The audit swarm checked
code correctness per-file; the reviewer checked claims against reality.

## Four Complementary Perspectives

This pipeline automates the four complementary review perspectives needed to catch 100% of
issues:

| Phase | Agent | What it catches | Analogy |
|-------|-------|-----------------|---------|
| 1 | Code Correctness (swarm) | Per-file bugs, type errors, logic errors | Microscope |
| 2 | Claim Verification (single) | PR description lies, missing implementations | Fact-checker |
| 3 | Skeptical Review (single) | UX concerns, cross-file issues, design judgment | Telescope |
| 4 | Security Review (single, parallel with Phase 3) | OWASP Top 10, injections, secrets, auth bypasses, dependency vulns | Threat model |

> Plus Phase 5 (Merge + Deduplicate) and Phase 6 (Present Results) which handle report infrastructure.
