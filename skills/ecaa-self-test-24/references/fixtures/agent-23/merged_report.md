# Merged Review Report — pre-built for second-opinion fixture

This file simulates a consolidated PR-review report containing
deliberately mis-calibrated severities. The second-opinion agent
should downgrade Finding 1, agree with Finding 2, and upgrade
Finding 3.

## [CR-001] Variable rename for clarity
- **Severity:** CRITICAL MUST-FIX
- **File:** utils.py:42
- Variable `tmp` should be renamed to `temporary_value` for clarity.
- Cosmetic — does not affect behaviour or interfaces.

## [PE-002] Unbounded query timeout
- **Severity:** MUST-FIX
- **File:** db.py:88
- `db.query()` called without a `timeout` argument; a slow query can
  hang the request indefinitely under load.

## [SE-003] Missing rate limiting on /api/public
- **Severity:** INFORMATIONAL
- **File:** routes.py:15
- Public endpoint with no rate limit — risk of accidental DoS from a
  buggy client or trivial abuse from a malicious one.
