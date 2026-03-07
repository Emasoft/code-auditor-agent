# Monorepo & Workspaces

## Table of Contents
- [Workspace Detection](#workspace-detection)
- [Audit Strategy](#audit-strategy)

## Workspace Detection

For monorepos with multiple packages/workspaces:
1. **Phase 0 detection**: Check for workspace configs: `package.json` (workspaces field), `pnpm-workspace.yaml`, `lerna.json`, Cargo workspace `Cargo.toml`
2. **Domain mapping**: Treat each workspace as a separate DOMAIN. Name domains after the workspace package name.

## Audit Strategy

3. **Parallel auditing**: Run Phase 1 domain-auditor swarms per workspace in parallel. Each workspace batch respects the 3-4 files per agent limit.
4. **Cross-workspace check**: After per-workspace audits complete, run one additional domain-auditor pass checking cross-workspace imports and dependency consistency.
5. **Consolidation**: Consolidate per-workspace reports, then run single dedup pass across all workspaces.
