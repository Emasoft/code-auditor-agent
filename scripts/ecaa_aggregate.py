#!/usr/bin/env python3
"""Aggregate ecaa-self-test-24 dispatch evidence into one tiny result JSON.

Usage:
    python3 scripts/ecaa_aggregate.py <workspace_dir> <plan_json> <pytest_xml_or_log> [out_json]

Reads:
- `<workspace_dir>/dispatch-<step>.json` — terse evidence files written by each sub-agent.
- `<plan_json>` — canonical plan with `expected_keywords` per agent step.
- `<pytest_xml_or_log>` — pytest output (text log accepted, junitxml preferred).

Writes (to `out_json` or stdout):
- A flat JSON object with `ts`, `wall_seconds`, `verdict`, and a 24-entry
  `step_results` array. One JSON line per step (no prose, no markdown).

Exit codes:
- 0 = PASS (all steps verified)
- 1 = PARTIAL (some steps matched ≥1 keyword but not all)
- 2 = FAIL (any step missing evidence / no keyword match / pytest failed)
- 3 = harness error (bad args, missing plan, etc.)

The whole verification is deterministic Python; the orchestrator LLM
never has to read the dispatch files itself. That removes the
markdown-synthesis bottleneck (was ~3m45s on Sonnet).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _load_plan(plan_path: Path) -> dict:
    with plan_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_dispatch(workspace: Path, step_key: str) -> tuple[dict | None, str]:
    """Return (json_payload, status). status is 'ok', 'missing', or 'malformed'.

    Tolerates both zero-padded (`dispatch-04-foo.json`) and non-padded
    (`dispatch-4-foo.json`) numeric prefixes — the orchestrator and
    aggregator must agree on one form but historic dispatches mix both.
    """
    # Split "NN[-sub]" into numeric prefix + suffix
    if "-" in step_key:
        num_str, _, suffix = step_key.partition("-")
        suffix = "-" + suffix
    else:
        num_str, suffix = step_key, ""
    try:
        num = int(num_str)
    except ValueError:
        return None, "missing"
    candidates = [
        workspace / f"dispatch-{num:02d}{suffix}.json",
        workspace / f"dispatch-{num}{suffix}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    return json.load(f), "ok"
            except (json.JSONDecodeError, OSError):
                return None, "malformed"
    return None, "missing"


def _verify_agent(
    payload: dict | None,
    status: str,
    expected_cat: int,
    expected_where: list[str],
) -> dict:
    """Match the sub-agent's findings against the plan's `cat` + `expected_where`.

    Schema for `payload`:
        {"step": "<key>", "fixture": "<name>", "found": [
            {"cat": <int>, "where": "<locator>"}, ...
        ]}

    Verdict logic:
    - File missing → FAIL EVIDENCE_MISSING
    - File malformed → FAIL EVIDENCE_MALFORMED
    - No finding has the expected `cat` → FAIL WRONG_CATEGORY
    - All `expected_where` substrings found in some finding's `where` → PASS
    - Some matched, some missed → PARTIAL
    - None matched → FAIL NO_WHERE_MATCH
    """
    if status == "missing":
        return {"verdict": "FAIL", "reason": "EVIDENCE_MISSING",
                "found": [], "missed_where": expected_where}
    if status == "malformed":
        return {"verdict": "FAIL", "reason": "EVIDENCE_MALFORMED",
                "found": [], "missed_where": expected_where}
    findings = (payload or {}).get("found", [])
    cats_seen = sorted({int(f.get("cat", -1)) for f in findings if "cat" in f})
    where_strings = [str(f.get("where", "")) for f in findings]
    cat_match = expected_cat in cats_seen
    if not cat_match and findings:
        return {"verdict": "FAIL", "reason": "WRONG_CATEGORY",
                "expected_cat": expected_cat, "found_cats": cats_seen,
                "where_strings": where_strings}
    if not findings:
        return {"verdict": "FAIL", "reason": "EMPTY_FINDINGS",
                "expected_cat": expected_cat, "missed_where": expected_where}
    blob = " ".join(where_strings).lower()
    matched_where = [w for w in expected_where if w.lower() in blob]
    missed_where = [w for w in expected_where if w.lower() not in blob]
    if not expected_where:
        return {"verdict": "FAIL", "reason": "PLAN_HAS_NO_EXPECTED_WHERE",
                "where_strings": where_strings}
    if not matched_where:
        return {"verdict": "FAIL", "reason": "NO_WHERE_MATCH",
                "expected_cat": expected_cat, "where_strings": where_strings,
                "missed_where": missed_where}
    if missed_where:
        return {"verdict": "PARTIAL", "reason": "MISSED_SOME_WHERE",
                "expected_cat": expected_cat,
                "matched_where": matched_where, "missed_where": missed_where,
                "where_strings": where_strings}
    return {"verdict": "PASS", "expected_cat": expected_cat,
            "matched_where": matched_where,
            "where_strings": where_strings}


_PYTEST_RESULT_RE = re.compile(r"\[(?P<id>step-\d+-[\w-]+)\]\s+(?P<state>PASSED|FAILED|ERROR|SKIPPED)")


def _parse_pytest_log(log_path: Path) -> dict[str, str]:
    """Return {pytest_id: 'PASS'|'FAIL'} keyed by the parametrize ID."""
    if not log_path.exists():
        return {}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for m in _PYTEST_RESULT_RE.finditer(text):
        out["[" + m.group("id") + "]"] = "PASS" if m.group("state") == "PASSED" else "FAIL"
    return out


def main() -> int:
    if len(sys.argv) < 4:
        print(json.dumps({"error": "usage: ecaa_aggregate.py <workspace> <plan.json> <pytest_log> [out.json]"}),
              file=sys.stderr)
        return 3

    workspace = Path(sys.argv[1])
    plan_path = Path(sys.argv[2])
    pytest_log = Path(sys.argv[3])
    out_path = Path(sys.argv[4]) if len(sys.argv) >= 5 else None

    if not workspace.is_dir():
        print(json.dumps({"error": f"workspace not a directory: {workspace}"}), file=sys.stderr)
        return 3
    if not plan_path.is_file():
        print(json.dumps({"error": f"plan not found: {plan_path}"}), file=sys.stderr)
        return 3

    plan = _load_plan(plan_path)
    pytest_results = _parse_pytest_log(pytest_log)

    step_results: list[dict] = []
    overall_pass = True
    any_partial = False

    for step_key, spec in plan.get("steps", {}).items():
        entry: dict = {"step": step_key, "half": spec.get("half"), "name": spec.get("name")}
        half = spec.get("half")
        if half in ("script", "gate"):
            pid = spec.get("pytest_id", "")
            # Match by suffix — pytest_id ends with "[step-NN-name]"
            verdict = "FAIL"
            for log_id, state in pytest_results.items():
                if pid.endswith(log_id):
                    verdict = state
                    break
            entry["verdict"] = verdict
            if verdict == "FAIL":
                overall_pass = False
                entry["reason"] = "PYTEST_FAILED_OR_MISSING"
        elif half == "agent":
            payload, status = _load_dispatch(workspace, step_key)
            v = _verify_agent(
                payload,
                status,
                int(spec.get("cat", -1)),
                spec.get("expected_where", []),
            )
            entry.update(v)
            if v["verdict"] == "FAIL":
                overall_pass = False
            elif v["verdict"] == "PARTIAL":
                any_partial = True
        else:
            entry["verdict"] = "FAIL"
            entry["reason"] = "UNKNOWN_HALF"
            overall_pass = False
        step_results.append(entry)

    if not overall_pass:
        verdict = "FAIL"
        exit_code = 2
    elif any_partial:
        verdict = "PARTIAL"
        exit_code = 1
    else:
        verdict = "PASS"
        exit_code = 0

    result = {
        "ts": workspace.name.replace("ecaa-", ""),
        "workspace": str(workspace),
        "plan": str(plan_path),
        "verdict": verdict,
        "step_count": len(step_results),
        "step_results": step_results,
    }
    blob = json.dumps(result, indent=2, ensure_ascii=False)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(blob + "\n", encoding="utf-8")
        pass_count = sum(1 for s in step_results if s.get("verdict") == "PASS")
        print(f"[{verdict}] ecaa-self-test-24 — {pass_count}/{len(step_results)} PASS. Result: {out_path}")
    else:
        print(blob)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
