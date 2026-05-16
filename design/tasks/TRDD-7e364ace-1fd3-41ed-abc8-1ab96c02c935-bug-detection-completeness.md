# TRDD-7e364ace — Bug-detection completeness from PR-Review corpus

**TRDD ID:** `7e364ace-1fd3-41ed-abc8-1ab96c02c935`
**Filename:** `design/tasks/TRDD-7e364ace-1fd3-41ed-abc8-1ab96c02c935-bug-detection-completeness.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)
**Status:** Not started
**Source inventory:** `docs_dev/codex-comparison/FULL-PR-REVIEW-INVENTORY.md`

## Mission (verbatim from user)

> "this is a plugin with only one mission: catch all bugs. it must use all
> possible techniques, but the result must be that not a single error,
> shortcoming, vulnerability, inconsistencies, bottleneck or anything else
> found in those 300+ skills files should escape it!"
>
> "it must do it using the minimum amount of tokens and delegating to
> scripts and linters as much work as possible, but not so much that the
> detection ability is lost!"

## Two governing constraints

1. **DETECTION COMPLETENESS** — every detection technique extracted from
   the corpus (216 ideas → ~95 bug-detection-relevant after filtering out
   R/V/W/X/Z + mermaid + dev-time-only items) must be encoded somewhere
   in the pipeline.
2. **TOKEN ECONOMY** — every check that can be expressed as a deterministic
   rule (regex, AST visitor, linter, type-checker, schema diff) MUST be a
   script, not an agent checklist item. Agents spend LLM tokens only on
   the residue that genuinely needs judgment.

## Routing rule (script vs agent)

For each detection technique:

| Trait | Script | Agent (LLM) |
|---|---|---|
| Deterministic pattern match (regex/AST/symbol) | ✅ | ❌ |
| Established linter or scanner exists (ruff, eslint, semgrep, bandit, trivy, trufflehog, codespell, gitleaks, hadolint, mypy, pyright, etc.) | ✅ wrap and ingest | ❌ |
| Cross-file mechanical diff (env-var ↔ docs, schema ↔ model) | ✅ | ❌ |
| Requires semantic understanding of intent, design, business rules | ❌ | ✅ |
| Requires creative "imagine failure modes" reasoning | ❌ | ✅ |
| Requires reading an issue thread for design decisions | ❌ | ✅ |
| Requires comparing PR diff against the linked acceptance criteria | ❌ | ✅ |
| Independent-model second opinion (Codex CLI) | (LLM, external) | ✅ |

Hard rule: **an agent never re-greps for anything a script already produced.**
The script pass runs once per PR, emits a structured JSON report at a known
path, and agents Read that path instead of re-doing the search.

## Pipeline (revised, low-token)

```
                       ┌──────────────────────────────────────────────┐
                       │  STAGE 1 — pre-flight script pass (no LLM)   │
                       │  caa-prereview-scripts (NEW)                 │
                       │  emits: reports/caa-prereview/<ts>.json      │
                       └──────────────────────────────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────────┐
                       │  STAGE 2 — LLM swarm (judgment only)         │
                       │  agents read STAGE-1 JSON + diff, focus on   │
                       │  residue not already caught by scripts       │
                       └──────────────────────────────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────────┐
                       │  STAGE 3 — codex second opinion (LLM, ext)   │
                       └──────────────────────────────────────────────┘
                                          │
                                          ▼
                       ┌──────────────────────────────────────────────┐
                       │  STAGE 4 — consolidate/dedup/todo-gen        │
                       └──────────────────────────────────────────────┘
```

## Phase A — Pre-flight script pass (HIGH ROI, do first)

**Goal:** every deterministic detection in the corpus is wrapped as a script.
The agent swarm in Stage 2 reads the JSON report and never re-runs these.

Output schema (`reports/caa-prereview/<ts>.json`):

```jsonc
{
  "pr_number": 123,
  "files_changed": ["app.py", ".env.example", ...],
  "languages_detected": ["python", "yaml"],
  "domains_detected": ["graphql", "jwt"],
  "linter_results": {
    "ruff":   [ { "file": "...", "line": 17, "rule": "F401", "msg": "..." }, ... ],
    "mypy":   [ ... ],
    "semgrep":[ ... ],
    "bandit": [ ... ],
    "eslint": [ ... ],
    "trivy":  [ ... ],
    "trufflehog":[ ... ],
    "gitleaks":[ ... ],
    "hadolint":[ ... ],
    "codespell":[ ... ]
  },
  "ast_findings": {
    "silent_failure": [ { "file": "...", "line": 21, "pattern": "empty-catch", ... } ],
    "complexity":     [ { "file": "...", "fn": "x", "metric": "branches", "value": 7, "threshold": 5 } ],
    "dead_code":      [ ... ],
    "param_count":    [ ... ],
    "fn_length":      [ ... ],
    "docstring_param_mismatch": [ ... ]
  },
  "cross_layer_findings": {
    "env_var_drift":      [ ... ],
    "default_value_drift":[ ... ],
    "schema_drift":       [ ... ],
    "generated_file_drift":[ ... ],
    "orphan_callers":     [ ... ]
  },
  "security_pattern_findings": {
    "jwt_alg_none":        [ ... ],
    "jwt_no_kid":          [ ... ],
    "ssrf_url_no_allowlist":[ ... ],
    "hardcoded_secret":    [ ... ],
    "weak_crypto":         [ ... ],
    "sql_string_concat":   [ ... ]
  },
  "test_quality": {
    "mock_replaces_sut":   [ ... ],
    "naming_too_short":    [ ... ],
    "no_assertion":        [ ... ],
    "deterministic_violations":[ ... ]
  }
}
```

### Script-level deliverables

Each script lives under `scripts/prereview/` and is invoked by the umbrella
`scripts/prereview/run_all.py`. Scripts call existing external scanners
(ruff, eslint, semgrep, etc.) when available; otherwise implement minimal
AST detectors with `ast`, `libcst`, `tree-sitter`, or language-native parsers.

| Script | Detects | Source IDs (from inventory) |
|---|---|---|
| `scripts/prereview/detect_languages_and_domains.py` | Python/JS/Go/Rust/Java/PHP/Ruby/Swift/Kotlin/SQL/YAML/HCL/Dockerfile + GraphQL/JWT/i18n/l10n/monorepo/API/DB-migration/CI domain markers | T-routing precondition |
| `scripts/prereview/run_linters.py` | Wrap & parse output of ruff, mypy, eslint, biome, gofmt, govet, clippy, hadolint, markdownlint, sqlfluff, codespell, gitleaks, trufflehog, semgrep, bandit, trivy, pip-audit, npm-audit, govulncheck — only those installed; gracefully skip absent ones | A2, B5, G11, G12, G13, I9, J1-J5, Q6, multiple H |
| `scripts/prereview/ast_silent_failure.py` | empty-catch, broad-catch, catch-and-only-log, `?.` over fallible calls, fallback-to-mock in prod path | J2-J7 |
| `scripts/prereview/ast_complexity.py` | function-too-long, too-many-branches, too-many-parameters, cyclomatic complexity > 10, nested-loop depth | M3-M5, N2, P4 |
| `scripts/prereview/ast_dead_code.py` | unused imports, unused functions, unreachable code, unused abstractions (export with zero callers) | G13 |
| `scripts/prereview/docstring_signature_diff.py` | docstring claims param X but signature lacks it, or vice versa | L6 |
| `scripts/prereview/env_var_drift.py` | env-var read in code without entry in `.env.example` / README "Configuration" / chart values | E2, Q1 |
| `scripts/prereview/schema_drift.py` | DB migration columns vs ORM model fields; OpenAPI/GraphQL schema vs handler signatures; generated-file checksum vs source | E10, Q5 |
| `scripts/prereview/generated_file_check.py` | flag if `*.gen.*`, `*.pb.go`, `*_pb2.py`, OpenAPI clients, codegen outputs are stale | Q5 |
| `scripts/prereview/orphan_caller_scan.py` | PR removes a symbol still referenced outside the diff | E5 |
| `scripts/prereview/cross_platform_check.py` | Windows-incompatible path constructions (`/` joins, hard-coded `\`), CRLF in shell scripts, exec-bit on text files | Q8 |
| `scripts/prereview/jwt_pattern_scan.py` | `algorithm=` `none`, missing `verify_signature`, hardcoded `HS256` secrets, no `kid` rotation hook | H9, H10, T2 |
| `scripts/prereview/ssrf_pattern_scan.py` | `requests.get(...)` / `urllib.urlopen(...)` / `fetch(...)` with arg sourced from request body, no allowlist, no protocol filter | H14 |
| `scripts/prereview/secret_scan.py` | Wrap trufflehog + gitleaks output | H6, J10 |
| `scripts/prereview/test_quality_scan.py` | Mock replaces SUT, no-assertion tests, `assert True`, retry-decorator missing on known-flaky patterns, test name < 8 chars, manual-tests file missing on big features | G3, I3-I5, I7, I9 |
| `scripts/prereview/n_plus_one_heuristic.py` | DB query call inside `for` / `while` / `map` (best-effort heuristic, marked LOW confidence in output) | P1 |
| `scripts/prereview/release_annotation_check.py` | CHANGELOG.md / RELEASE_NOTES entry exists for non-trivial diff | Q7 |
| `scripts/prereview/feature_flag_test_check.py` | When a new feature flag is introduced, BOTH on-state and off-state must have tests | E9 |
| `scripts/prereview/api_consistency_scan.py` | New REST endpoint vs existing endpoints — error format, parameter ordering, return type drift | N7, Y6 |
| `scripts/prereview/run_all.py` | Orchestrator: invoke all of the above in parallel via `concurrent.futures`, merge JSON output, emit `reports/caa-prereview/<ts>.json` | (orchestration) |

**Token cost of Phase A: ZERO** (pure deterministic scripts, no LLM calls).

## Phase B — Extend existing agents to consume the script report

Each Stage-2 agent prompt is updated to:
1. Open `reports/caa-prereview/<ts>.json` **first** (1 file read).
2. Treat script findings as ALREADY-FOUND — do not re-discover them.
3. Spend LLM attention only on the residue that needs judgment.

### B.1 — `caa-code-correctness-agent.md`

Extensions (judgment-only items that scripts can't cover):
- D3: 15-question function-level checklist (callers, mutated state, dep-failure paths, similar function exists).
- D4: explicit "map the change surface" emit at top of report.
- G9: "Verify behavior, not plausibility" slogan added to AWC mode header.
- G10: AWC "silent security regressions" sub-bullet.
- G14: hardcoded values that *should be config* — judgment (script flags any literal, agent decides).
- I1: behavioural test coverage ("would tests fail if behaviour breaks?").
- I2: critical-gap taxonomy (untested error / missing-edge / business-branch / negative-cases / concurrency).
- I8: regression-test-for-every-fixed-bug.
- I11: cost/benefit framing (don't suggest tests for trivial getters).
- M1, M2, M6: simplification suggestions (judgment).
- P2-P3, P5: performance tradeoffs / repeated work / memory patterns.
- Q3: migration impact (forward + reverse) description.

### B.2 — `caa-security-review-agent.md`

Extensions:
- H2-H8: attack-surface battery (8 q), input-trust battery (6 q), auth/authz battery (7 q), dependency safety (6 q), sensitive-data battery (7 q), **failure-state security battery (6 q)**.
- H8: OWASP Top 10 explicit walkthrough.
- H11: server-side enforcement of auth (UI-only is insufficient).
- H15: defence-in-depth / least-privilege / deny-by-default principles as named checks.
- H16: account-lockout / rate-limit / credential-stuffing protection check.
- B5 policy: every security finding defaults to BLOCKER unless explicitly demoted with evidence.

### B.3 — `caa-claim-verification-agent.md`

Extensions:
- F3: emit "Functional Completeness" as named dimension.
- F5: read linked-issue COMMENTS (not just description) for design decisions; verify implementation matches agreed approach.
- V8: separately assess commit-message quality.

### B.4 — `caa-cross-layer-auditor-agent.md`

Extensions (judgment items beyond the env-var / schema script findings):
- E3: removed-state-without-replacement.
- E7: UI-only security as explicit cross-layer check.
- E8: invalid failure state (partial-write-then-throw).
- E10 residue: DB migration ↔ application expectations (script catches column-level; agent catches nullability + business-rule alignment).

### B.5 — `caa-pr-review-skill/SKILL.md`

- Step 0 (new): run `scripts/prereview/run_all.py`, surface JSON path.
- Step 1-6: existing pipeline, but each agent gets the JSON path as input.

## Phase C — New specialised judgment agents

| Agent file | Purpose | Source IDs |
|---|---|---|
| `agents/caa-silent-failure-hunter-agent.md` | Judgment-residue of J1-J11 — script catches the mechanical patterns, agent flags subtler smells (retry-without-user-feedback, fallback-to-mock-in-prod, error-without-context) and judges severity | J1, J4, J6, J7, J8, J9, J11 |
| `agents/caa-type-design-analyzer-agent.md` | K1-K8 — 4-dimensional invariant rating + anti-pattern catalogue. Fires only when PR introduces new public types | K1-K8 |
| `agents/caa-comment-quality-agent.md` | L1-L5 — comment completeness, long-term value, misleading-element hunt. Fires only on docstring/comment changes | L1-L5 |
| `agents/caa-pre-mortem-agent.md` | O1-O8 — Tiger / Paper-Tiger / Elephant taxonomy with mandatory `mitigation_checked` evidence. Fires once per PR as a parallel "imagine it failed" pass | O1-O8 |
| `agents/caa-performance-review-agent.md` | P1-P5 — fires when diff touches DB query, loop hotspot, large-input handling, or `O(n²)`-suspect pattern flagged by script | P1-P5 |
| `agents/caa-architecture-consistency-agent.md` | N3-N8 — pattern consistency vs other modules, polyglot boundaries, data-structure / API-design consistency | N3-N8 |

Each agent is small (~150-200 lines). Each one **must** start by reading the
prereview JSON and skipping anything already found there.

## Phase D — Codex second-opinion (the deferred F-016)

| File | Purpose | Source IDs |
|---|---|---|
| `agents/caa-codex-second-opinion-agent.md` | Spawn Codex CLI (`codex --full-auto --ephemeral`) with the consolidated CAA report + diff; ask for material-issues-only + uncertain-concerns | S1, S4, S5, S9 |
| `skills/caa-codex-review-skill/SKILL.md` | Wrapper invoking Codex with `.codex-review.json` config + `-o` capture; multi-round PASS-1 / PASS-2 verification | S2, S3, S6, S7, S8, S10 |

## Phase E — Domain routing + specialist agents

Detection step (script, `scripts/prereview/detect_languages_and_domains.py`)
emits `domains_detected: ["graphql", "jwt", "i18n", ...]`.

The pipeline orchestrator (caa-pr-review-skill) reads that list and fires
only the matching specialist agents — others stay dormant (zero token cost).

| File | Purpose | Source IDs |
|---|---|---|
| `agents/caa-graphql-reviewer-agent.md` | T1 — query complexity, N+1 via DataLoader, persisted queries, schema versioning | T1 |
| `agents/caa-jwt-reviewer-agent.md` | H9-H10 / T2 — alg whitelist, kid, none-rejection, claims, rotation, JWKS | H9, H10, T2 |
| `agents/caa-i18n-reviewer-agent.md` | T3 — hardcoded strings, RTL, text-expansion, namespace organisation | T3 |
| `agents/caa-l10n-reviewer-agent.md` | T4 — regional variants, fallback chains, Intl.* API usage | T4 |
| `agents/caa-monorepo-reviewer-agent.md` | T5 — workspace boundaries, shared-package import discipline, build-cache validity | T5 |
| `agents/caa-api-design-reviewer-agent.md` | Y6 — REST URL structure, status codes, pagination, versioning, OpenAPI alignment | Y6 |
| `agents/caa-database-reviewer-agent.md` | Y7 — naming, indexes, transactions, migration up+down, connection pooling, N+1, integrity | Y7 |
| `agents/caa-docker-reviewer-agent.md` | Y8 — pinned versions, non-root, multi-stage, health checks, no-`latest` | Y8 |
| `agents/caa-logging-reviewer-agent.md` | Y9 — env-aware verbosity, structured logs, no-sensitive-data-in-logs, error-IDs | Y9 |

Each specialist is small (~100-150 lines), focused on a 5-15-item checklist
specific to its domain. Fires only when its domain is detected. Reads
prereview JSON first.

## Execution order (phases, with token budget in mind)

1. **Phase A — scripts.** Build all the deterministic checkers first. Zero
   LLM token cost; immediate detection gain. Touches ~20 new files under
   `scripts/prereview/`.
2. **Phase B — extend existing agents** to consume the script report.
   Adds maybe 30-50 lines per existing agent. Marginal token cost.
3. **Phase C — new judgment agents.** Each fires conditionally and reads the
   script report first. ~6 new agent files.
4. **Phase D — Codex second-opinion.** F-016. Adds 1 agent + 1 skill.
5. **Phase E — domain routing + specialists.** ~9 new files but each agent
   fires only when its domain is in `domains_detected`.

After every phase: re-run the n=5 multi-run experiment (see
`docs_dev/codex-comparison/MULTIRUN-VERDICT.md`) and re-score recall against
ground-truth. Phase A is expected to move recall by the largest margin
(deterministic checks never miss). Phases B-E close residual judgment gaps.

## Verification (per phase)

- **Phase A:** unit tests for each script under `tests/prereview/`. Each
  script test feeds a fixture file and asserts the JSON output.
- **Phase B-E:** golden-fixture tests confirming the new agent prompts
  produce expected MUST-FIX / SHOULD-FIX findings on the canonical Flask
  PR #57 benchmark.
- **End-to-end:** the existing 10-run experiment (5 OLD + 5 NEW
  code-correctness baselines in `docs_dev/codex-comparison/multirun/`)
  must show recall ≥ baseline on the 12 seeded bugs, AND should detect
  additional issues introduced by new agents (track separately under
  `multirun/post-trdd-runs/`).

## Out of scope (deliberately excluded per user)

- Theme R (GitHub thread automation: post comments / resolve / link issues).
- Theme V (PR-description generation).
- Theme W (session rituals, TTS, metrics dashboards).
- Theme X (custom rule-set config UI).
- Theme Z (workflow/devops dev-time guidance).
- D7 mermaid sequence-diagram rendering (the underlying flow-tracing IS in
  scope; just no visual artifact).

## Token-economy invariants (do not violate)

1. Agents NEVER re-grep / re-walk what scripts already produced.
2. Agents NEVER read the full PR diff if a structured summary is available.
3. Each new agent prompt is ≤ 200 lines unless a checklist genuinely needs
   more.
4. Specialist agents fire ONLY when their domain is detected.
5. Pre-flight scripts run in parallel (no sequential overhead).
6. Linter output is filtered to PR-touched files only before being added
   to the script JSON — never the whole repo's lint backlog.
