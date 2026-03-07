# Error Handling

## Table of Contents

- [Error Recovery by Phase](#error-recovery-by-phase)

## Error Recovery by Phase

- If any Phase 1 agent fails, re-run it for that domain only (with a new UUID)
- If Phase 2, 3, or 4 fails, re-run that phase (single agents, new UUID)
- If merge script exits code 2 (missing reports, invalid dir, or empty merged file), investigate (source files are preserved)
- If dedup agent reports MUST-FIX > 0, proceed to PROCEDURE 2; if dedup fails, re-run on same intermediate
- If `gh` CLI not authenticated, stop and ask user to run `gh auth login`
- If fix agent fails, re-run for that domain; if tests fail, spawn domain agents to investigate
- If max passes reached, write escalation report and stop
- Docker/lint failures: skip MegaLinter and proceed to commit (linting is enhancement, not gate). If lint-fix loop exhausts 3 attempts, escalate to user
