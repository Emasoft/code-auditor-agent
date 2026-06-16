---
name: caa-pr-review-and-fix-skill
description: "Trigger with 'review and fix the PR', 'review the PR and apply fixes', 'pre-merge review and fix'. Use when reviewing a GitHub PR AND then applying root-cause fixes to its changed files."
version: 4.1.1
author: Emasoft
license: MIT
tags: [caa-pr-review, ultracode, fix, claim-verification, cross-layer]
effort: high
---

# PR Review & Fix (ultracode)

## Overview

Two-step ultracode flow on `scripts/workflows/caa-engine.js`: first review the PR (`pr` lens-set), then apply
root-cause fixes to the changed files (scan-and-fix mode, in-place per-file, fix-verified). Both steps
write their consolidated report to `reports/code-auditor-agent/`.

## Prerequisites

- Session effort `max` (preferred) or `xhigh` for the **ultracode** path (opus-only). Without ultracode
  (no `Workflow` tool, or `CAA_ULTRACODE` disabled) the commands fall back to a simple inline review/fix at any effort.
- `gh` CLI authenticated and the PR on GitHub (for the review step).
- A clean working tree or a feature branch before the fix step (fixes edit files in place).
- The `/caa-pr-review` and `/caa-scan-and-fix` commands available.

## Instructions

1. For the ultracode path, confirm session effort is `max` (preferred) or `xhigh` — opus-only, halts
   below `xhigh`; raise with `/effort max`. Without ultracode (no `Workflow` tool, or `CAA_ULTRACODE`
   disabled) the commands run the simple-scan fallback at any effort.
2. **Review:** run `/caa-pr-review <pr-number>` → PR-review comment with a PASS/CONDITIONAL/FAIL verdict.
3. **Fix (only after the user reviews the verdict):** ensure the working tree is clean / on a feature
   branch, then run `/caa-scan-and-fix` on the PR's changed files. Each fixer owns one file (in-place, no
   conflict); fix-verify confirms each fix; the user reviews `git diff` before committing. NEVER auto-commit/push.

## Output

A PR-review report and (after the fix step) a fix report, both in `reports/code-auditor-agent/`.

## Error Handling

Robust by construction. The fix step edits files in place — the working-tree-clean guard + the
review-the-diff step prevent unreviewed changes; failures are reported under "Needs follow-up".

## Checklist

Copy this checklist and track your progress:

- [ ] Session effort is max/xhigh
- [ ] Review run first; verdict relayed
- [ ] Working tree clean / feature branch before fixing
- [ ] Fixes applied in place + fix-verified; user reviews diff; not auto-committed

## Examples

```
"review and fix PR 206"   → /caa-pr-review 206, then /caa-scan-and-fix <changed files>
```

## Resources

- `scripts/workflows/caa-engine.js` — canonical engine (`pr` lens-set + scan-and-fix mode).
- Commands: `/caa-pr-review`, `/caa-scan-and-fix`.
