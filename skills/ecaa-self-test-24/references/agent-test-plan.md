# Agent test plan

Human-readable companion to [`plan.json`](plan.json) — fixture seeds and verification rules for every agent-half of the 24-step bug-detection pipeline. Loaded by `ecaa-orchestrator` when the `ecaa-self-test-24` skill is invoked. Script halves are covered by `tests/integration/test_pipeline_efficacy.py` and not repeated here.

## Table of contents

- [Conventions](#conventions)
- [Early-stage agent halves (steps 1-4)](#early-stage-agent-halves-steps-1-4)
- [Mid-stage and deep-dive agent halves (steps 17, 18, 22, 23)](#mid-stage-and-deep-dive-agent-halves-steps-17-18-22-23)
- [Domain specialists (steps 20 and 21)](#domain-specialists-steps-20-and-21)
- [Parallelism plan](#parallelism-plan)

## Conventions

Each row corresponds to one entry in [`plan.json`](plan.json) and lists the same `agent`, `fixture`, `cat`, and `expected_where` values. If they ever drift, `plan.json` wins.

The orchestrator reads each fixture in place under `references/fixtures/` and dispatches the named sub-agent via the `Agent` tool. **No `model=` override on dispatch** — every CAA sub-agent has the correct model pinned in its own frontmatter (MODEL POLICY: Sonnet/Opus only, never Haiku for these reviewers).

**TERSE-JSON PROTOCOL — applies to every dispatch.** The dispatch prompt is the verbatim block in the [ecaa-orchestrator agent](../../../agents/ecaa-orchestrator.md). The sub-agent's only output is a JSON file at `$WS/dispatch-<step>.json` of shape:

```json
{"step":"<NN[-sub]>","fixture":"<basename>","found":[
  {"cat":<int>,"where":"<free-form locator>"}
]}
```

`cat` is the integer category from the plan (e.g. 4=security, 9=concurrency, 17=architecture, 18=pre-mortem, 20=domain-hf, 21=domain-lf, 22=function-deep-dive, 23=second-opinion). `where` is a free-form locator: `"line 3"`, `"function login"`, `"class Vault"`, `"module loader.py"`, `"library jwt"`, or `"missing X in module foo.py"`. Line numbers are NOT required for absence bugs.

The aggregator matches `cat` exactly and runs case-insensitive substring search of every `expected_where` from the plan over the concatenated `where` strings.

Verdict semantics (from `scripts/ecaa_aggregate.py`):

- **PASS** — every `expected_where` substring matched in some finding's `where`.
- **PARTIAL** — ≥1 matched but at least one missing. The result JSON lists `matched_where` and `missed_where` explicitly.
- **FAIL** — `EVIDENCE_MISSING` (no dispatch file), `EVIDENCE_MALFORMED` (not valid JSON), `WRONG_CATEGORY` (cat mismatch), `EMPTY_FINDINGS`, `NO_WHERE_MATCH` (cat right but 0 expected_where matched), or `PLAN_HAS_NO_EXPECTED_WHERE`.

## Early-stage agent halves (steps 1-4)

### Step 1 — caa-code-correctness-agent

**Fixture:** `agent-01/buggy.py`
**Seed:**

```python
def divide(a: int, b: int) -> int:
    return a / b  # type mismatch: returns float, signature says int
```

**Expected `where`:** must mention `divide` (the buggy function).

### Step 2 — caa-claim-verification-agent

**Fixture:** `agent-02/pr_description.md` + `agent-02/actual_diff.patch`
**Seed:** PR description claims "Adds retry-with-backoff to the HTTP client" but the diff only adds a single try/except with no retry / no backoff / no exponential delay.
**Expected `where`:** mentions of `retry` and `backoff`.

### Step 3 — caa-skeptical-reviewer-agent

**Fixture:** `agent-03/diff.patch` + `agent-03/callers.py` — a diff that renames a public function used by N callers without updating callers.
**Expected `where`:** mentions of `get_user` and `callers`.

### Step 4 — caa-security-review-agent

**Fixture:** `agent-04/auth.py` with `password = "admin123"` and `query = f"SELECT * FROM users WHERE id = {user_id}"`.
**Expected `where`:** mentions of `login` and `password`.

## Mid-stage and deep-dive agent halves (steps 17, 18, 22, 23)

### Step 17 — caa-architecture-consistency-agent

**Fixture:** `agent-17/{orders,users,products,payments}.py` — three sibling modules using `Result<T, E>` returns; the new file under audit uses raw exceptions.
**Expected `where`:** mentions of `payments` and `Result`.

### Step 18 — caa-pre-mortem-agent

**Fixture:** `agent-18/cache.py` — a new in-memory cache without TTL or size cap.
**Expected `where`:** mentions of `_CACHE` and `store`.

### Step 22 — caa-function-deep-dive-agent

**Fixture:** `agent-22/order_processor.py` — a 50-line function called from ≥3 sites that mutates a global, makes an unawaited DB call, and has no retry safety.
**Expected `where`:** mentions of `process_order` and `_stats`.

### Step 23 — caa-second-opinion-agent

**Fixture:** `agent-23/merged_report.md` — a pre-built merged report with one obviously-overinflated MUST-FIX and one obviously-missing concern. Dispatch LAST (after steps 1-22 return).
**Expected `where`:** mentions of `CR-001` and `rename`.

## Domain specialists (steps 20 and 21)

### Step 20 — high-frequency

Six specialists dispatched in parallel (gated):

| Sub | Agent | Fixture | Bug | Expected `where` |
|---|---|---|---|---|
| graphql | caa-graphql-reviewer-agent | `agent-20-graphql/schema.graphql` | deep nested Query, no depth limit | `Query`, `friends` |
| jwt | caa-jwt-reviewer-agent | `agent-20-jwt/signer.py` | `algorithm="none"` | `sign`, `algorithm` |
| api | caa-api-design-reviewer-agent | `agent-20-api/routes.py` | DELETE without auth | `user_handler`, `DELETE` |
| docker | caa-docker-reviewer-agent | `agent-20-docker/container_spec.txt` | `USER root`, `:latest` | `FROM`, `USER` |
| prompt | caa-prompt-injection-reviewer-agent | `agent-20-prompt/prompts.py` | user input concatenated into template | `user_input`, `build_summary_prompt` |
| frontend | caa-frontend-reviewer-agent | `agent-20-frontend/App.tsx` | `<img>` no alt, `dangerouslySetInnerHTML` | `ProfilePage`, `img` |

### Step 21 — lower-frequency

Eight specialists dispatched in parallel (gated). All 8 MUST produce an evidence file — missing any of l10n / monorepo (a common bug in prior runs that dispatched only 6) → FAIL:

| Sub | Agent | Fixture | Bug | Expected `where` |
|---|---|---|---|---|
| ios | caa-ios-reviewer-agent | `agent-21-ios/NetworkManager.swift` | singleton + ATS bypass | `NetworkManager`, `completionHandlers` |
| elixir | caa-elixir-reviewer-agent | `agent-21-elixir/user_service.ex` | blocking GenServer call | `UserService`, `handle_call` |
| solidity | caa-solidity-reviewer-agent | `agent-21-solidity/Vault.sol` | reentrancy (call before state update) | `withdraw`, `Vault` |
| mcp | caa-mcp-server-reviewer-agent | `agent-21-mcp/mcp_server.py` | tool-call shell=True with user input | `run_tool`, `shell` |
| i18n | caa-i18n-reviewer-agent | `agent-21-i18n/messages.py` | hardcoded English strings | `greet`, `pluralize` |
| l10n | caa-l10n-reviewer-agent | `agent-21-l10n/format.py` | locale-blind date/currency formatting | `format_date`, `format_money` |
| monorepo | caa-monorepo-reviewer-agent | `agent-21-monorepo/internal_dep.ts` | cross-package import bypassing public API | `internal`, `leak` |
| logging | caa-logging-reviewer-agent | `agent-21-logging/payment_service.py` | card number + CVV logged at INFO/DEBUG | `process_payment`, `card_number` |

## Parallelism plan

Steps 1, 2, 3, 4, 17, 18, 22 (= 7) + all 6 step-20 specialists + all 8 step-21 specialists = **21 dispatches** are independent and MUST go out in a single assistant message with 21 `Agent` tool blocks. Splitting them across multiple messages adds 8-30s of serial gap per split.

Step 23 (`caa-second-opinion-agent`) MUST be in a SEPARATE, LATER message — it consumes the upstream evidence files from `$WS/dispatch-*.json`, so it cannot start until the 21-batch returns. Two messages total: one batch of 21, then step 23 alone.
