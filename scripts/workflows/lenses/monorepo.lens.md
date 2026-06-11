# monorepo lens

## key
monorepo

## fire-when
Monorepo workspace markers present at repo root: `pnpm-workspace.yaml`, `nx.json`, `turbo.json`, `lerna.json`, or a root `package.json` containing a `workspaces` key. Also fires on `.changeset/` directory presence. Per-file relevance: any `package.json` in a sub-package, or any source file (`*.ts`, `*.tsx`, `*.js`, `*.jsx`) whose imports reference a sibling workspace package (e.g. `@org/...`) or a sibling package's `internal/`/`src/` path. SKIP if no workspace layout is detected.

## checklist
Audit ONLY inter-package (cross-package) contracts; intra-package issues are out of scope. To locate a package's public entry point, read its `package.json` `main` / `module` / `exports`.

- **internal-import** (MUST-FIX): this file imports from another package's `internal/` or `src/` path directly, bypassing that package's declared entry point (`package.json` `main`/`module`/`exports`).
- **workspace-dep** (SHOULD-FIX): a cross-package import via the workspace name (e.g. `import { x } from '@org/shared'`) exists, but the imported package is NOT listed in this package's `dependencies` (devDependencies-only does not count).
- **changeset** (MUST-FIX): in a changeset-based monorepo (`@changesets/cli`), a touched package has no corresponding `.changeset/*.md` entry.
- **build-cycle** (MUST-FIX): package A depends on B which (directly or transitively) depends back on A — a build-graph cycle.
- **type-drift** (SHOULD-FIX): a type defined in another package is duplicated/reimplemented here instead of imported from its source package.
- **version-mismatch** (SHOULD-FIX): the same dependency is pinned at different versions across sibling `package.json`s, and not unified via a shared `pnpm.overrides` / `resolutions` block.
- **breaking-change** (MUST-FIX): an exported symbol is removed or renamed from a package without a major-version-style changeset entry announcing the break.
- **api-test** (SHOULD-FIX): a new public export is added without a test file covering it at the package boundary.

All findings are Layer = `structural`. Assign Severity (MUST-FIX | SHOULD-FIX | NIT), Confidence (HIGH | MEDIUM | LOW), and Category (one of: internal-import | workspace-dep | changeset | build-cycle | type-drift | version-mismatch | breaking-change | api-test). Internal-path imports, build-graph cycles, and missing-changeset breaking changes are always MUST-FIX.
