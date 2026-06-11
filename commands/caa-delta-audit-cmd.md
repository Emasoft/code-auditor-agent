---
name: caa-delta-audit-cmd
description: >
  Legacy alias for the incremental (changed-since-a-ref) ultracode audit. Superseded by /caa-delta.
  Kept so existing "audit the changes" / "incremental audit" muscle memory still resolves; it simply
  redirects to the new ultracode command.
argument-hint: "[ref] [deps] [fix]"
---

# Delta Audit (legacy alias → ultracode)

This command has been migrated to the **ultracode engine** (`scripts/workflows/caa-engine.js`). Use the new
command directly:

- **Audit files changed since a ref** (default `origin/main`, fallback `HEAD~1`), optionally including
  their direct dependents → run **`/caa-delta [ref] [deps]`**.
- To also **fix** the delta → run `/caa-delta`, then `/caa-scan-and-fix` on the changed files (review the
  diff before committing).

## Orchestrator contract

1. Redirect to **`/caa-delta`**, passing through the `ref` and `deps` from `$ARGUMENTS`.
2. Follow `/caa-delta`'s contract verbatim — its Step A picks the path (ultracode engine when the
   `Workflow` tool is available and `CAA_ULTRACODE` is not disabled, else the simple-scan fallback),
   then delta scope resolution → run the audit → present + temp purge.
3. The single consolidated report lands in `reports/code-auditor-agent/`.

There is no separate logic here — the audit lives ONLY in `scripts/workflows/caa-engine.js`. A delta is NOT a
substitute for a full audit (unchanged files that interact with the change are not covered; `deps`
mitigates). **Never** use llm-externalizer. opus-only at `xhigh`/`max` effort.
