# Why This Exists

## Table of Contents

- [The Incident](#the-incident)
- [Four Complementary Review Perspectives](#four-complementary-review-perspectives)

## The Incident

In a real incident, 20+ specialized audit agents checked a 40-file PR and found zero issues.
A single external reviewer then immediately found 3 real bugs -- including a function that
claimed to populate 4 fields but actually populated zero of them. The audit swarm checked
code correctness per-file; the reviewer checked claims against reality.

## Four Complementary Review Perspectives

This pipeline automates the four complementary review perspectives AND the fix cycle:

| Phase | Agent | What it catches | Analogy |
|-------|-------|-----------------|---------|
| 1 | Code Correctness (swarm) | Per-file bugs, type errors, logic errors | Microscope |
| 2 | Claim Verification (single) | PR description lies, missing implementations | Fact-checker |
| 3 | Skeptical Review (single) | UX concerns, cross-file issues, design judgment | Telescope |
| 4 | Security Review (`caa-security-review-agent`) | Vulnerabilities, secrets, injection flaws, auth issues | Scanner |

After review, a swarm of fixing agents resolves all findings. Then the review runs again to verify the fixes and catch any regressions. This continues until zero issues remain.
