# pre-mortem lens

## key
pre-mortem

## fire-when
always (holistic) — applies to any file that can affect runtime/production. Heightened relevance when the file touches: background jobs/cron/schedulers, DB writes or schema migrations (`*migration*`, `*.sql`, ORM model files), auth/authz, rate limiting, deployment/rollout config (`Dockerfile`, `k8s/*`, `*.tf`, CI/CD workflows), monitoring/metrics/observability hooks, money/orders/billing logic, or concurrency primitives. Skip pure-docs files (README, CONTRIBUTING, `*.md`) — no runtime impact.

## checklist
Imagine it is 3 months after this code shipped and it broke production. Find the most plausible failure modes (brainstorm >=5 before filtering), then classify EACH concrete finding. You do NOT check correctness — only "what's the worst plausible thing that could go wrong, and would we catch it?" Drop any candidate lacking BOTH a concrete trigger AND a concrete impact (speculation like "cosmic ray flips a bit" is not a finding). Layer is always `structural`.

- Trigger + impact gate: every finding names a concrete trigger (input shape, race, deployment scenario, time/clock) AND a concrete impact (data-loss, downtime, security leak, regression). No trigger or no impact -> silently dropped.
- Classify each finding as exactly one of three:
  - **Tiger** — real risk: concrete trigger + concrete impact + codebase does NOT mitigate. MUST carry `mitigation_checked`: "I searched the codebase for X, Y, Z and did NOT find them." A Tiger without this field is rejected. Severity MUST-FIX.
  - **Paper Tiger** — looks scary but codebase already mitigates (retry loop, idempotency key, schema constraint, transaction, CSP header, rate limit). MUST carry `mitigation_found`: file:line where the mitigation lives. Severity NIT (awareness only, not blocking).
  - **Elephant** — high-impact concern the code is silent on, that "everyone assumed someone else checked" (rate limiting, auth, schema migration safety, monitoring hooks, compliance). MUST carry `verify_by`: "To classify Tiger vs Paper Tiger, search for X. If found, Paper Tiger; if not, Tiger." Severity SHOULD-FIX.
- Categories (use exact names): data-loss, downtime, security, concurrency, scalability, observability, rollback.
- Hunt the classic Elephants explicitly: missing idempotency on retried/background work; missing rate limiting; unverified auth/authz on new entry points; non-zero-downtime / non-backward-compatible schema migrations; no metrics/logs emitted for new long-running or critical paths; absent rollback path; absent test plan for a risky change.
- Verify-before-flagging: before calling anything a Tiger, actually search for the mitigation (chase references) and read what you find — demote to Paper Tiger if the codebase handles it.
- Confidence calibration HIGH / MEDIUM / LOW on every finding; phrase LOW-confidence findings as questions, not assertions.
- Verdict mapping: APPROVE (no Tigers, no unresolved Elephants); APPROVE WITH NITS (Paper Tigers only); REQUEST CHANGES (>=1 Tiger); REJECT (>=1 Tiger PLUS a missing test plan or rollback path).
