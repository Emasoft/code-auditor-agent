# Agent test plan

Detailed fixture seeds and verification rules for every agent-half of the 24-step bug-detection pipeline. Loaded by `ecaa-orchestrator` when the `ecaa-self-test-24` skill is invoked. The script halves are covered separately by `tests/integration/test_pipeline_efficacy.py` and are not repeated here.

## Table of contents

- [Conventions](#conventions)
- [Step 1 — caa-code-correctness-agent](#step-1)
- [Step 2 — caa-claim-verification-agent](#step-2)
- [Step 3 — caa-skeptical-reviewer-agent](#step-3)
- [Step 4 — caa-security-review-agent](#step-4)
- [Step 17 — caa-architecture-consistency-agent](#step-17)
- [Step 18 — caa-pre-mortem-agent](#step-18)
- [Step 20 — domain specialists, high-frequency](#step-20)
- [Step 21 — domain specialists, lower-frequency](#step-21)
- [Step 22 — caa-function-deep-dive-agent](#step-22)
- [Step 23 — caa-second-opinion-agent](#step-23)
- [Parallelism plan](#parallelism)

## Conventions

Each row has: `subagent_type | fixture file | expected_keywords (csv)`. The orchestrator seeds the fixture under `$WS/agent-<NN>[-<sub>]/`, dispatches via the `Agent` tool (with `model="haiku"` unless the agent's frontmatter pins another), and forces the sub-agent to output ONLY a tiny JSON.

**TERSE-JSON PROTOCOL — applies to every dispatch.** The dispatch prompt MUST follow the verbatim template in the orchestrator agent. The sub-agent's only output is a JSON file at `$WS/dispatch-<NN>[-<sub>].json` of shape `{"step":"<NN>[-<sub>]","fixture":"<basename>","found":[{"code":"<UPPER_SNAKE>","line":<int>},…]}` — no prose, no markdown, no fenced code blocks. After dispatch, the orchestrator `Read`s the file, parses the JSON, and runs a case-insensitive substring diff between the `expected_keywords` for this step and the lowercased `found.code` values.

Verdict semantics:

- **PASS** — every expected keyword matched (substring within ≥1 `found.code`).
- **PARTIAL** — ≥1 keyword matched but at least one is missing. The report lists missing keywords explicitly.
- **FAIL** — `EVIDENCE_MISSING` (no file), `EVIDENCE_MALFORMED` (not valid JSON), `EVIDENCE_STALE` (mtime < TS), or `NO_CATEGORY_MATCH` (0 keywords matched). Sub-agent crashed / refused dispatch is also FAIL.

## Step 1

**Agent:** `caa-code-correctness-agent`
**Fixture:** `src/buggy.py`
**Seed:**

```python
def divide(a: int, b: int) -> int:
    return a / b  # type mismatch: returns float, signature says int
```

**Verification:** return line / report mentions one of `type`, `mismatch`, `return type`, `incorrect type`.

## Step 2

**Agent:** `caa-claim-verification-agent`
**Fixture:** `pr_description.md` + `actual_diff.patch`
**Seed:** PR description claims "Adds retry-with-backoff to the HTTP client" but the diff only adds a single try/except with no retry / no backoff / no exponential delay.
**Verification:** return mentions one of `claim`, `unverified`, `not implemented`, `missing retry`, `mismatch`.

## Step 3

**Agent:** `caa-skeptical-reviewer-agent`
**Fixture:** A diff that renames a public function used by N callers without updating callers.
**Verification:** mentions one of `breaking change`, `public api`, `callers`, `consumer`.

## Step 4

**Agent:** `caa-security-review-agent`
**Fixture:** `auth.py` with `password = "admin123"` and `query = f"SELECT * FROM users WHERE id = {user_id}"`.
**Verification:** mentions one of `hardcoded`, `secret`, `sql injection`, `OWASP`.

## Step 17

**Agent:** `caa-architecture-consistency-agent`
**Fixture:** Three sibling modules using `Result<T, E>` returns; the new file under audit uses raw exceptions.
**Verification:** mentions one of `convention`, `consistency`, `error handling`, `differs`.

## Step 18

**Agent:** `caa-pre-mortem-agent`
**Fixture:** A diff adding a new in-memory cache without TTL or size cap.
**Verification:** mentions one of `tiger`, `paper tiger`, `elephant`, `memory leak`, `unbounded`.

## Step 20

**Agents (gated, parallel):** graphql / jwt / api-design / docker / prompt-injection / frontend reviewers.

| Fixture file | Bug | Expected mention |
|---|---|---|
| `schema.graphql` (deep Query nesting) | missing depth-limit | `depth limit` / `introspection` / `n+1` |
| `jwt_signer.py` (`algorithm="none"`) | weak algo | `algorithm` / `weak` / `none` |
| `routes.py` (DELETE without auth) | verb misuse | `verb` / `rest` / `auth` |
| `Dockerfile` (`USER root`, `:latest`) | hardening | `root` / `latest` / `non-root` |
| `prompts.py` (user input concatenated into template) | injection | `prompt injection` / `untrusted` |
| `App.tsx` (`<img>` no alt, `dangerouslySetInnerHTML`) | xss/a11y | `xss` / `alt` / `csp` |

## Step 21

**Agents (gated, parallel — 8 specialists, ALL must dispatch):**

| Sub | Agent | Fixture file | Bug | Expected mention |
|---|---|---|---|---|
| ios | caa-ios-reviewer-agent | `NetworkManager.swift` | singleton + ATS bypass | `memory leak` / `certificate pinning` / `ATS` |
| elixir | caa-elixir-reviewer-agent | `user_service.ex` | blocking GenServer call | `blocking` / `GenServer` / `Stream` |
| solidity | caa-solidity-reviewer-agent | `Vault.sol` | reentrancy (call before state update) | `reentrancy` |
| mcp | caa-mcp-server-reviewer-agent | `mcp_server.py` | tool-call shell=True with user input | `command injection` / `RCE` / `shell` |
| i18n | caa-i18n-reviewer-agent | `messages.py` | hardcoded English strings | `i18n` / `hardcoded strings` |
| l10n | caa-l10n-reviewer-agent | `format.py` | locale-blind date/currency formatting | `l10n` / `locale` / `formatting` |
| monorepo | caa-monorepo-reviewer-agent | `apps/web/src/internal_dep.ts` | cross-package import bypassing public API | `cross-package` / `internal` / `dependency` |
| logging | caa-logging-reviewer-agent | `payment_service.py` | card number + CVV logged at INFO/DEBUG | `PII` / `secrets` / `PCI` |

All 8 specialists must produce an evidence file. Missing any of l10n / monorepo (a common bug in prior runs that dispatched only 6) → FAIL.

## Step 22

**Agent:** `caa-function-deep-dive-agent`
**Fixture:** A 50-line function called from ≥3 sites that mutates a global, makes an unawaited DB call, and has no retry safety.
**Verification:** mentions one of `callers`, `mutated state`, `retry`, `idempotent`, `contract`.

## Step 23

**Agent:** `caa-second-opinion-agent`
**Fixture:** A pre-built `merged_report.md` with one obviously-overinflated MUST-FIX and one obviously-missing concern. Dispatch with `PASS=1` (per the agent's contract).
**Verification:** mentions one of `downgrade`, `drop`, `upgrade`, `agree`, `disagree`.

## Parallelism

Steps 1, 2, 3, 4, 17, 18, 22 are independent — dispatch them all in one `Agent` tool message. Step 20 / 21 contain multiple specialists that are independent of each other; batch them as well. Step 23 MUST run last because it consumes the merged output from the earlier passes.
