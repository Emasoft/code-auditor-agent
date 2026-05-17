# Report format

Markdown template the `ecaa-orchestrator` agent must produce when running the `ecaa-self-test-24` skill. The report lands at `<main-repo-root>/reports/code-auditor/efficacy-audit/<%Y%m%d_%H%M%S%z>-self-test.md`.

## Table of contents

- [Filename rule](#filename-rule)
- [Section structure](#section-structure)
- [Summary table columns](#summary-table-columns-single-table-the-whole-report)
- [Sub-agent evidence file format](#sub-agent-evidence-file-format)
- [Cost & timing line](#cost--timing-line-one-line-mandatory)
- [Verdict line (stdout contract)](#verdict-line)

## Filename rule

`<%Y%m%d_%H%M%S%z>-self-test.md` — local time + GMT offset (compact `±HHMM`, never `±HH:MM`, never UTC). Matches the agent-reports-location rule.

## Section structure

```markdown
# Bug-Detection Pipeline — Self-Test Report

**Date:** <TS>
**Skill:** ecaa-self-test-24
**Plugin:** code-auditor-agent v<VERSION>
**Verdict:** PASS | PARTIAL | FAIL

## Summary

| # | Step | Half | Verdict | Notes |
|---|------|------|---------|-------|
| ... | ... | script/agent | PASS/PARTIAL/FAIL | ... |

## Script-half gate (pytest)

- **Command:** `uv run pytest tests/integration/test_pipeline_efficacy.py -v --tb=short`
- **Exit code:** <N>
- **Tests collected:** <N>
- **Tests passed:** <N>
- **Tail (last 20 lines):**

\`\`\`
<pytest tail>
\`\`\`

## Agent-half per-step results

### Step 1 — caa-code-correctness-agent (✅ PASS | ⚠️  PARTIAL | ❌ FAIL)
- **Fixture seed:** `$WS/agent-01/buggy.py`
- **Dispatch:** `Agent(subagent_type="caa-code-correctness-agent", prompt="...")`
- **Return line:** `<verbatim>`
- **Expected categories:** type, mismatch, return type, incorrect type
- **Matched:** <list> | none → PARTIAL/FAIL

(repeat for each agent step)

## Verdict justification

One paragraph: which steps passed, which failed, what blocks the gate.

## Cost & timing

- Wall time: <s>
- LLM-token usage (sum of all agent dispatches): <input> input / <output> output
- Approximate dollar cost: $<x.xx>
```

## Summary table columns (single table, the whole report)

The report is essentially this one table plus a pytest tail and a cost line. NO prose findings. NO per-step detail blocks. The diff IS the report.

| Column | Values |
|--------|--------|
| `#` | step number 0..23 |
| `Sub` | specialist suffix (e.g. `graphql`, `l10n`); empty for non-multi steps |
| `Half` | `script` / `agent` / `gate` |
| `EvidencePath` | `/tmp/ecaa-<ts>/dispatch-<NN>[-<sub>].json` for agent halves, `n/a` for script halves |
| `mtime-OK` | `yes` / `no` (no → FAIL) |
| `Cat` | integer category (matches plan; 4=security, 9=concurrency, 21=monorepo, etc.) |
| `Where-strings` | csv of `where` locators from the sub-agent's JSON (e.g. `function login,module auth.py`) |
| `Expected-where` | csv from plan (e.g. `login,auth.py`) — substring match over `where-strings` |
| `Missed` | expected-where substrings with no match (empty when PASS) |
| `Verdict` | `PASS` / `PARTIAL` / `FAIL` / `SKIPPED_BUDGET` |

## Sub-agent evidence file format

Each agent dispatch writes a tiny JSON to `/tmp/ecaa-<ts>/dispatch-<NN>[-<sub>].json`. Schema:

```json
{
  "step": "<NN>[-<sub>]",
  "fixture": "<basename>",
  "found": [
    {"cat": <int>, "where": "<free-form locator>"}
  ]
}
```

`cat` is the integer category for this step (from plan.json — security=4, concurrency=9, monorepo=21, etc.). `where` is a free-form locator: `"line 3"`, `"function login"`, `"class Vault"`, `"module loader.py"`, `"library jwt"`, or `"missing in module cli.py"`. Use whichever locator is natural — line numbers are NOT required when the bug is "missing X" or applies to a whole file or library. NO prose, NO recommendations, NO verbatim snippets, NO markdown. The aggregator matches `cat` exactly and runs case-insensitive substring search over the concatenated `where` strings.

## Cost & timing line (one line, MANDATORY)

`Cost: wall=<s>s, dispatches=<N>, tokens=<input>i/<output>o, est=$<x.xx>` — `est=$0.00` while claiming dispatches happened is a contract violation per orchestrator rule #3.

## Verdict line

The final stdout line (the orchestrator's contract with CI / the calling user) must be EXACTLY one of:

```
[PASS] ecaa-self-test-24 — 24/24 steps clean. Report: <abs-path>
[PARTIAL] ecaa-self-test-24 — <N>/24 PARTIAL, 0 FAIL. Report: <abs-path>
[FAIL] ecaa-self-test-24 — <N>/24 FAIL. Report: <abs-path>
```

No trailing text. CI parses the bracket prefix. `<abs-path>` is the absolute path to the markdown report.
