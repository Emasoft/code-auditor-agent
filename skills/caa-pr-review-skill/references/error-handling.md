# Error Handling

## Table of Contents

- [Phase-Level Recovery](#phase-level-recovery)
- [Merge Script Errors](#merge-script-errors)
- [Authentication Errors](#authentication-errors)

## Phase-Level Recovery

- If any Phase 1 agent fails, re-run it for that domain only (UUID filename avoids collision)
- If Phase 2, 3, or 4 fails, re-run that phase (they are single agents)
- If the dedup agent fails, re-run it on the intermediate report (it is idempotent)

## Merge Script Errors

- If the merge script exits with code 2: input error (missing reports, invalid dir) or
  post-merge integrity failure (merged file missing or empty). Source files are preserved — investigate manually

## Authentication Errors

- If `gh` CLI is not authenticated, stop and ask the user to run `gh auth login`
