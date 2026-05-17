# Report format

JSON schema emitted by `scripts/ecaa_aggregate.py` when the `ecaa-self-test-24` skill runs. The file lands at `<main-repo-root>/reports/code-auditor/efficacy-audit/<%Y%m%d_%H%M%S%z>-self-test.json`. NO markdown report is produced — the JSON is the deliverable.

## Table of contents

- [Filename rule](#filename-rule)
- [JSON top-level shape](#json-top-level-shape)
- [Per-step entry schema](#per-step-entry-schema)
- [Sub-agent evidence file format](#sub-agent-evidence-file-format)
- [Verdict line (stdout contract)](#verdict-line)

## Filename rule

`<%Y%m%d_%H%M%S%z>-self-test.json` — local time + GMT offset (compact `±HHMM`, never `±HH:MM`, never UTC). Matches the agent-reports-location rule.

## JSON top-level shape

```json
{
  "ts": "<workspace timestamp, e.g. 20260517_182950+0200>",
  "workspace": "/tmp/ecaa-<ts>",
  "plan": "<absolute path to plan.json>",
  "verdict": "PASS | PARTIAL | FAIL",
  "step_count": 36,
  "step_results": [ ... 36 entries ... ]
}
```

`step_count` equals the number of keys in `plan.json`'s `steps` map (currently 36: 14 script-halves + 22 agent-halves).

## Per-step entry schema

Every step has at minimum `step`, `half`, `name`, `verdict`. Diagnostic fields are added by the aggregator depending on the verdict.

### Script / gate steps (`half: "script"` or `half: "gate"`)

```json
{
  "step": "00",
  "half": "script",
  "name": "domain-detection",
  "verdict": "PASS | FAIL",
  "reason": "PYTEST_FAILED_OR_MISSING"
}
```

`reason` is present only on FAIL. The aggregator parses `pytest.log` for lines matching `[step-NN-name]\s+(PASSED|FAILED|ERROR|SKIPPED)` and matches each pytest ID against the row's `pytest_id`.

### Agent steps (`half: "agent"`)

`_verify_agent` writes one of these shapes per row:

**PASS** — all `expected_where` substrings matched:

```json
{
  "step": "4",
  "half": "agent",
  "name": "security",
  "verdict": "PASS",
  "expected_cat": 4,
  "matched_where": ["login", "password"],
  "where_strings": ["variable password", "function login — SQL injection", "..."]
}
```

**PARTIAL** — at least one expected `where` matched, others missing:

```json
{
  "step": "...",
  "verdict": "PARTIAL",
  "reason": "MISSED_SOME_WHERE",
  "expected_cat": 4,
  "matched_where": ["..."],
  "missed_where": ["..."],
  "where_strings": ["..."]
}
```

**FAIL** — one of `EVIDENCE_MISSING`, `EVIDENCE_MALFORMED`, `WRONG_CATEGORY`, `EMPTY_FINDINGS`, `NO_WHERE_MATCH`, `PLAN_HAS_NO_EXPECTED_WHERE`. Each carries `reason` plus the diagnostic fields relevant to that failure mode (`found_cats`, `where_strings`, `missed_where`, etc.).

## Sub-agent evidence file format

Each agent dispatch writes a tiny JSON to `/tmp/ecaa-<ts>/dispatch-<step>.json`. Schema:

```json
{
  "step": "<NN>[-<sub>]",
  "fixture": "<basename>",
  "found": [
    {"cat": <int>, "where": "<free-form locator>"}
  ]
}
```

- `cat` is the integer category for this step (from plan.json — security=4, concurrency=9, monorepo=21, etc.). The aggregator matches by exact equality.
- `where` is a free-form locator: `"line 3"`, `"function login"`, `"class Vault"`, `"module loader.py"`, `"library jwt"`, or `"missing X in module foo.py"`. Line numbers are NOT required for absence bugs. The aggregator runs case-insensitive substring search of every `expected_where` from the plan over the concatenated `where` strings.

NO prose, NO recommendations, NO verbatim snippets, NO markdown in the evidence file.

## Verdict line

The aggregator's final stdout line (the orchestrator's contract with CI / the calling user) is EXACTLY one of:

```
[PASS] ecaa-self-test-24 — 36/36 PASS. Result: <abs-path>
[PARTIAL] ecaa-self-test-24 — <N>/36 PASS. Result: <abs-path>
[FAIL] ecaa-self-test-24 — <N>/36 PASS. Result: <abs-path>
```

`<N>` is `len([s for s in step_results if s.verdict == "PASS"])`. The orchestrator echoes this line verbatim; CI parses the bracket prefix. The aggregator's exit code mirrors the verdict: 0=PASS, 1=PARTIAL, 2=FAIL, 3=harness error.
