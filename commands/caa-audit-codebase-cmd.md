---
name: caa-audit-codebase-cmd
description: >
  Legacy alias for the ultracode codebase audit. Superseded by /caa-scan (scan-only) and
  /caa-scan-and-fix (audit + root-cause fixes). Kept so existing "audit the codebase" muscle
  memory still resolves; it simply redirects to the new ultracode commands.
argument-hint: "[path/glob ...] [fix]"
---

# Codebase Audit (legacy alias → ultracode)

This command has been migrated to the **ultracode engine** (`scripts/workflows/caa-engine.js`). The former
hand-orchestrated multi-phase pipeline is retired. Use the command that matches the request:

- **Scan only** (whole repo or an explicit path/glob) → run **`/caa-scan`** with the same scope.
- **Scan AND fix** (apply root-cause fixes, fix-verified, in place) → run **`/caa-scan-and-fix`**.
- **Only changed files since a ref** → run **`/caa-delta`**.
- **Gate the staged files before a commit** → run **`/caa-precommit`**.

## Orchestrator contract

1. Map the request to the right new command (table above): `fix` in `$ARGUMENTS` → `/caa-scan-and-fix`,
   otherwise `/caa-scan`. Pass through any path/glob scope and `conc=N`.
2. Follow that command's contract verbatim (effort guard → scope resolution → `Workflow({scriptPath:
   "${CLAUDE_PLUGIN_ROOT}/scripts/workflows/caa-engine.js", args})` → present + temp purge).
3. The single consolidated report lands in `reports/code-auditor-agent/`.

There is no separate logic here — the audit lives ONLY in `scripts/workflows/caa-engine.js`. **Never** use
llm-externalizer. opus-only at `xhigh`/`max` effort (the target command enforces this).
