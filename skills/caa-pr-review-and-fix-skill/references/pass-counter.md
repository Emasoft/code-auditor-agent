# Pass Counter Management

## Table of Contents

- [Initialization](#initialization)
- [Run ID Generation](#run-id-generation)
- [Pass Increment and Limit](#pass-increment-and-limit)

## Initialization

Before the first pass, initialize:

```
PASS_NUMBER = 1
MAX_PASSES = 25
```

## Run ID Generation

At the start of EACH pass (including the first), generate a unique run ID:

```
RUN_ID = first 8 hex characters from python3 -c "import uuid; print(uuid.uuid4().hex[:8])"
# Example: RUN_ID = "a1b2c3d4"
```

The run ID scopes ALL report filenames for this pass invocation, preventing
stale files from prior interrupted runs from contaminating the merge.

## Pass Increment and Limit

After each PROCEDURE 2 completes:

```
PASS_NUMBER = PASS_NUMBER + 1
if PASS_NUMBER > MAX_PASSES:
    STOP -- write escalation report and present to user:
    "Maximum pass limit (25) reached. {N} issues remain unresolved.
     Manual intervention required. See: reports/code-auditor/caa-pr-review-and-fix-escalation-{timestamp}.md"
```
