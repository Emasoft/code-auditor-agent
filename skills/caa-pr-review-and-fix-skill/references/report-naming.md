# Report Naming Convention

## Table of Contents

- [Overview](#overview)
- [Filename Table](#filename-table)
- [UUID Filename Generation](#uuid-filename-generation)
- [Agent-Prefixed Finding IDs](#agent-prefixed-finding-ids)
- [Pre-Pass Cleanup](#pre-pass-cleanup)

## Overview

All reports use **UUID-based filenames** to prevent file overwrites between concurrent agents,
and **agent-prefixed finding IDs** to prevent ID collisions between parallel agents.

## Filename Table

| Report | Filename |
|--------|----------|
| Correctness (per-domain) | `docs_dev/caa-correctness-P{N}-R{RUN_ID}-{uuid}.md` |
| Claim verification | `docs_dev/caa-claims-P{N}-R{RUN_ID}-{uuid}.md` |
| Security review | `docs_dev/caa-security-P{N}-R{RUN_ID}-{uuid}.md` |
| Skeptical review | `docs_dev/caa-review-P{N}-R{RUN_ID}-{uuid}.md` |
| Agent manifest | `docs_dev/caa-agents-P{N}-R{RUN_ID}.json` |
| Merged intermediate | `docs_dev/caa-pr-review-P{N}-intermediate-{timestamp}.md` |
| Final dedup report | `docs_dev/caa-pr-review-P{N}-{timestamp}.md` |
| Fix checkpoint (per-domain) | `docs_dev/caa-checkpoint-P{N}-R{RUN_ID}-{domain}.json` |
| Fix summary (per-domain) | `docs_dev/caa-fixes-done-P{N}-{domain}.md` |
| Test outcome | `docs_dev/caa-tests-outcome-P{N}.md` |
| Lint outcome | `docs_dev/caa-lint-outcome-P{N}.md` |
| Lint summary (JSON) | `docs_dev/megalinter-P{N}/lint-summary.json` |
| Lint fixes | `docs_dev/caa-lint-fixes-P{N}.md` |
| Recovery log | `docs_dev/caa-recovery-log-P{N}.md` |
| Final clean report | `docs_dev/caa-pr-review-and-fix-FINAL-{timestamp}.md` |
| Escalation (if max reached) | `docs_dev/caa-pr-review-and-fix-escalation-{timestamp}.md` |

## UUID Filename Generation

Each agent generates a UUID at startup and uses it in its output filename:

```bash
UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
REPORT_PATH="docs_dev/caa-correctness-P${PASS}-R${RUN_ID}-${UUID}.md"
```

The combination of RUN_ID + UUID provides two levels of isolation:
- **RUN_ID** scopes files to a single pipeline invocation (prevents stale file pollution)
- **UUID** prevents collisions between concurrent agents within the same run

## Agent-Prefixed Finding IDs

**Finding IDs** include the pass number AND a unique agent prefix to avoid collisions:

```
Phase 1 (swarm): Each correctness agent gets a unique prefix A0, A1, A2, ...
  Agent 0: CC-P1-A0-001, CC-P1-A0-002, ...
  Agent 1: CC-P1-A1-001, CC-P1-A1-002, ...
  Agent 2: CC-P1-A2-001, CC-P1-A2-002, ...

Phase 2 (single): CV-P1-001, CV-P1-002, ... (no agent prefix needed)
Phase 3 (single): SR-P1-001, SR-P1-002, ... (no agent prefix needed)
Phase 4 (single): SC-P1-001, SC-P1-002, ... (no agent prefix needed)
```

The orchestrator assigns prefixes at spawn time using this algorithm:

```
domains = sorted(list of domains with changed files)
for i, domain in enumerate(domains):
    agent_prefix = f"A{i:X}"  # A0, A1, A2, ..., AF, A10, ...
    finding_id_prefix = f"CC-P{PASS_NUMBER}-{agent_prefix}"
```

This guarantees zero ID collisions because:
1. Each agent has a unique prefix (A0, A1, ...) within the pass
2. Each pass has a unique number (P1, P2, ...)
3. UUIDs in filenames prevent file-level collisions

## Pre-Pass Cleanup

**Before each pass**, run the pre-pass cleanup protocol (see Procedure 1 reference). Do NOT delete merged reports or fix summaries from previous passes -- they form the audit trail.

The merge script v2 uses pass-specific and run-specific glob patterns, so prior-pass and prior-run files are automatically excluded.
