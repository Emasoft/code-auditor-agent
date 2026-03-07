# Examples

## Table of Contents

- [Full Review-and-Fix Pipeline](#full-review-and-fix-pipeline)

## Full Review-and-Fix Pipeline

```
# Full review-and-fix pipeline on PR 206
User: "review and fix PR 206"
-> Pass 1: Review finds 8 issues (3 MUST-FIX, 4 SHOULD-FIX, 1 NIT)
-> Pass 1: Fix agents resolve all 8 issues, tests pass, commit
-> Pass 2: Review finds 2 new issues (regressions from fixes)
-> Pass 2: Fix agents resolve 2 issues, tests pass, commit
-> Pass 3: Review finds 0 issues
-> Final report presented: "APPROVE -- zero issues after 3 passes"
```
