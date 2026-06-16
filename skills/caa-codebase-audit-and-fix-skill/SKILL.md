---
name: caa-codebase-audit-and-fix-skill
description: "Trigger with /audit-codebase, 'audit the codebase', 'compliance audit', 'codebase audit', 'scan and fix the code'. Use when auditing a codebase (whole, scoped, or changed-since-a-ref) and optionally applying fixes."
version: 4.1.1
author: Emasoft
license: MIT
tags: [codebase-audit, ultracode, scan, scan-and-fix, delta]
effort: high
---

# Codebase Audit & Fix (ultracode)

## Overview

This capability now runs on the **ultracode engine** (`scripts/workflows/caa-engine.js`): a deterministic
map → filter → reduce over a swarm of opus agents (one auditor per file, cache-shared prompt with
the target path read last; adversarial per-file verify; one consolidated report). It replaces the
former hand-orchestrated multi-phase pipeline. Pick the command that matches the scope:

| You want to… | Command |
|---|---|
| Audit the WHOLE repo (or an explicit path/glob), scan-only | `/caa-scan` |
| Audit AND apply root-cause fixes (in place, fix-verified) | `/caa-scan-and-fix` |
| Audit only files changed since a git ref (+ optional dependents) | `/caa-delta` |
| Gate the STAGED files before a commit (PASS/FAIL) | `/caa-precommit` |

## Prerequisites

- Session effort `max` (preferred) or `xhigh` for the **ultracode** path (opus-only). Without ultracode
  (no `Workflow` tool, or `CAA_ULTRACODE` disabled) the commands fall back to a simple inline scan at any effort.
- The ultracode commands available: `/caa-scan`, `/caa-scan-and-fix`, `/caa-delta`, `/caa-precommit`.
- A git repository; `uv` available for any script steps.

## Instructions

1. For the ultracode path, confirm session effort is `max` (preferred) or `xhigh` — the engine is
   opus-only and that path halts below `xhigh`; raise with `/effort max`. If the `Workflow` tool is
   unavailable or `CAA_ULTRACODE` disables ultracode, the command runs the simple-scan fallback at any effort.
2. Invoke the command matching the requested scope (table above), passing any path/glob scope and
   `conc=N` the user specified. The command resolves the file scope and runs the engine.
3. The engine writes intermediates to a temp dir and the ONE consolidated report to
   `reports/code-auditor-agent/<timestamp>-<suffix>.md`. Relay the verdict/summary + the report path.

## Output

A single consolidated report in `reports/code-auditor-agent/` (audit summary, or PASS/FAIL gate, or
fix report for scan-and-fix). The engine returns `{finalReport, fixReport?}`.

## Error Handling

The engine is robust by construction (`.catch`-wrapped agents; rate-limit re-queue at a halved cap;
cap-then-report — never hard-fail). A file that can't be verified/fixed is reported under
"Needs follow-up", never silently dropped.

## Checklist

Copy this checklist and track your progress:

- [ ] Session effort is max/xhigh
- [ ] Correct command chosen for the scope
- [ ] Consolidated report landed in reports/code-auditor-agent/
- [ ] Verdict/summary + report path relayed to the user

## Examples

```
"audit the codebase"          → /caa-scan
"scan and fix scripts/"       → /caa-scan-and-fix scripts/
"audit the recent changes"    → /caa-delta
"check the staged files"      → /caa-precommit
```

## Resources

- `scripts/workflows/caa-engine.js` — the canonical ultracode audit engine (single source of truth).
- Commands: `/caa-scan`, `/caa-scan-and-fix`, `/caa-delta`, `/caa-precommit`.
