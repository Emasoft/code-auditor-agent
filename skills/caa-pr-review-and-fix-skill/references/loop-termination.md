# Loop Termination

## Table of Contents

- [Termination Logic](#termination-logic)
- [Final Report Format](#final-report-format)

## Termination Logic

After PROCEDURE 2 completes and fixes are committed, increment the pass counter and run PROCEDURE 1 again:

```
PASS_NUMBER = PASS_NUMBER + 1

if PASS_NUMBER > MAX_PASSES (25):
    STOP. Write escalation report:
    "Maximum pass limit reached. {remaining_count} issues persist after {MAX_PASSES} passes.
     Review: reports_dev/code-auditor/caa-pr-review-P{last_pass}-{timestamp}.md
     Manual intervention required."
    Present to user and exit.

Run PROCEDURE 1 with new PASS_NUMBER.

if PROCEDURE 1 finds ZERO issues (all severities -- MUST-FIX, SHOULD-FIX, NIT):
    Write final report: reports_dev/code-auditor/caa-pr-review-and-fix-FINAL-{timestamp}.md
    Present final summary to user and exit.
else:
    Run PROCEDURE 2 with the new findings.
    Loop back to increment PASS_NUMBER.
```

## Final Report Format

When the loop terminates with zero issues:

```
## PR Review And Fix -- Final Report

**Total passes:** {PASS_NUMBER}
**Final verdict:** APPROVE -- zero issues remaining

### Pass History

| Pass | Issues Found | Issues Fixed | Tests | Lint |
|------|-------------|-------------|-------|------|
| 1    | {count}     | {count}     | {passed}/{total} | {clean/N errors/skipped} |
| 2    | {count}     | {count}     | {passed}/{total} | {clean/N errors/skipped} |
| ...  | ...         | ...         | ...   | ...  |
| {N}  | 0           | --          | {passed}/{total} | {clean/skipped} |

### Reports Generated
- Pass 1 review: reports_dev/code-auditor/caa-pr-review-P1-{timestamp}.md
- Pass 1 fixes: reports_dev/code-auditor/caa-fixes-done-P1-{domain}.md
- ...
- Final clean review: reports_dev/code-auditor/caa-pr-review-P{N}-{timestamp}.md

### All Fixes Applied
1. [CC-P1-001] {title} -- {file} (Pass 1)
2. [SR-P1-003] {title} -- {file} (Pass 1)
3. [CC-P2-001] {title} -- {file} (Pass 2)
...
```
