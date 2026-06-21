---
name: caa-pr-review-skill
description: "Trigger with 'review the PR', 'check the PR', 'audit the PR', 'pre-merge review'. Use when reviewing a GitHub PR or running a pre-merge quality gate."
version: 4.4.1
author: Emasoft
license: MIT
tags: [caa-pr-review, ultracode, claim-verification, cross-layer, quality-gate]
effort: high
---

# PR Review (ultracode)

## Overview

PR review now runs on the **ultracode engine** (`scripts/workflows/caa-engine.js`) via the `/caa-pr-review`
command. It combines, in one deterministic pass: a per-file scan of the changed files (map → filter),
plus the two PR-unique once-per-run lenses — **claim-verification** (every claim in the PR description
checked against the actual diff; the #1 source of missed bugs) and **cross-layer** (the five cross-file
mismatch classes) — reduced into one PR-review comment with a PASS / CONDITIONAL / FAIL verdict.

## Prerequisites

- Session effort `max` (preferred) or `xhigh` for the **ultracode** path (opus-only). Without ultracode
  (no `Workflow` tool, or `CAA_ULTRACODE` disabled) `/caa-pr-review` falls back to a simple inline review at any effort.
- `gh` CLI authenticated and the PR on GitHub (the command resolves the diff + description via `gh`).
- The `/caa-pr-review` command available.

## Instructions

1. For the ultracode path, confirm session effort is `max` (preferred) or `xhigh` — opus-only, halts
   below `xhigh`; raise with `/effort max`. If the `Workflow` tool is unavailable or `CAA_ULTRACODE`
   disables ultracode, `/caa-pr-review` runs the simple-scan fallback at any effort.
2. Run `/caa-pr-review <pr-number>` (optionally `conc=N`). The command resolves the PR diff + description
   via `gh`, treats them as UNTRUSTED input, and runs the engine's `pr` lens-set.
3. The consolidated PR-review comment lands in `reports/code-auditor-agent/<timestamp>-pr-<N>-review.md`.
   Relay the verdict + MUST-FIX/SHOULD-FIX/NIT counts + the report path. Do NOT auto-post — the user posts.

## Output

One PR-review report (ready-to-post comment) in `reports/code-auditor-agent/` with a PASS/CONDITIONAL/FAIL
verdict and severity-tiered findings, merged from the scan + claim-verification + cross-layer lenses.

## Error Handling

Robust by construction (`.catch` + rate-limit re-queue; cap-then-report). A lens that fails to produce a
report is reported as "lens unavailable" in the verdict, never silently omitted.

## Checklist

Copy this checklist and track your progress:

- [ ] Session effort is max/xhigh
- [ ] PR diff + description resolved (treated as untrusted)
- [ ] All three lenses ran (scan, claim-verification, cross-layer) or unavailable ones noted
- [ ] PR-review report in reports/code-auditor-agent/; verdict relayed; not auto-posted

## Examples

```
"review PR 206"        → /caa-pr-review 206
"audit the PR"         → /caa-pr-review <number>
```

## Resources

- `scripts/workflows/caa-engine.js` — the canonical ultracode engine (`pr` lens-set).
- Command: `/caa-pr-review`. For review-then-fix, follow with `/caa-scan-and-fix` on the changed files.
