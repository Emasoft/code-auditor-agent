# graphql lens

## key
graphql

## fire-when
GraphQL detected: schema files (*.graphql, *.gql, schema.ts/js with `gql`/`buildSchema`/`makeExecutableSchema`), Apollo/graphql-yoga/mercurius/Nexus/TypeGraphQL/Pothos imports, `type Query`/`type Mutation`/`type Subscription`/`Connection`/`Edge` SDL markers, resolver maps (`Query: {`, `Mutation: {`, `resolvers:`), `@auth`/`@requires`/`@key` directives, DataLoader usage. Skip when no GraphQL surface present.

## checklist
Apply to every changed resolver / schema fragment in this file (Layer = `structural`; Category ∈ depth-limit | complexity-limit | introspection | n+1 | pagination | idempotency | error-masking | authz):

- **Query-depth limit** — server config MUST set a max query depth (graphql-depth-limit, Apollo plugin, graphql-shield rule). Missing → MUST-FIX (category: depth-limit).
- **Query-complexity limit** — a cost analyser MUST cap query cost (graphql-cost-analysis, graphql-query-complexity, or a persisted-query allowlist). Missing → SHOULD-FIX (category: complexity-limit).
- **Introspection disabled in prod** — config gates introspection (`introspection: process.env.NODE_ENV !== 'production'` or equivalent). Enabled in prod / missing gate → SHOULD-FIX (category: introspection).
- **N+1 resolver** — resolver invokes a DB/network call per-item without a DataLoader / batch loader. Confirm the resolver-specific shape (per-field fan-out) → flag (category: n+1).
- **Pagination on list fields** — list/collection fields return Connection / Edge types and accept `first`/`after`/`last`/`before`. Unbounded list result with no pagination → MUST-FIX (category: pagination).
- **Mutation idempotency** — create/non-trivial mutations accept `clientMutationId` / `idempotency_key` / `Idempotency-Key` header. Missing → SHOULD-FIX (category: idempotency).
- **Error masking in prod** — config strips stack traces / internal errors (Apollo `formatError`, `maskErrors`). Leaking internal errors / no masking → MUST-FIX (category: error-masking).
- **Field-level authz** — sensitive fields gated by `@auth` / `@requires` directive or an explicit resolver-level check; authorization inferred-by-context only → SHOULD-FIX (category: authz).
- **Confidence calibration** — tag each finding HIGH / MEDIUM / LOW; phrase LOW as a question. Every finding cites `file:line` evidence with the offending snippet.
- **Scope** — GraphQL-specific concerns only; do NOT re-audit generic correctness (type errors, broken imports) — those belong to other lenses.
