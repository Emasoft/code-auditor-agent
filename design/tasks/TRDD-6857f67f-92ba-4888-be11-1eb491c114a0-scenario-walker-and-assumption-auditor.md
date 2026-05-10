# TRDD-6857f67f — Scenario-walker and assumption-auditor agents

**TRDD ID:** `6857f67f-92ba-4888-be11-1eb491c114a0`
**Filename:** `design/tasks/TRDD-6857f67f-92ba-4888-be11-1eb491c114a0-scenario-walker-and-assumption-auditor.md`
**Tracked in:** this repo (`design/tasks/` is git-tracked)
**Status:** Spec (post-directive revision 2026-05-10)
**Author:** Emasoft (via Claude opus session 2026-05-10)
**Related agents:** caa-skeptical-reviewer-agent, caa-code-correctness-agent, caa-claim-verification-agent, caa-domain-auditor-agent, caa-security-review-agent

---

## 1. User's original request (verbatim)

> how can we improve the code auditor agent? too many issues and bugs are still
> missed by it. and it doesn't seem to understand when an architecture has clear
> holes, vulnerabilities, flaws in the very logic, inconsistencies in the
> behaviour, in the feedback, in the ux, in the security protocols.

Follow-up confirmation: `yes do it`.

**Design directive (from 2nd user turn):**

> the plugin must be completely automated. so the scenario must be created
> by skill and executed by an agent. the user must only choose if he wants a
> normal review or an extended review that includes a scenario run (where
> the agent play the role of the user).

This resolves §11 Q1 (no per-project `scenarios.md` — scenarios are auto-generated
by a skill from the codebase surface) and fixes the entry-point UX (one binary
choice: normal review vs extended review). See §3.1 and §4.0 below.

## 2. Problem statement

The current swarm is structurally a **microscope + claim-verifier + telescope (PR
diff only) + dedup pipeline**. It is strong at:

- Per-file correctness (caa-code-correctness-agent)
- PR-claim vs code mismatch (caa-claim-verification-agent)
- Diff-level cross-file consistency (caa-skeptical-reviewer-agent — but only on the diff)
- Per-batch compliance vs a reference doc (caa-domain-auditor-agent)
- Checklist security (caa-security-review-agent: OWASP/CWE list)
- Mechanical pipeline: consolidate → dedup → todo → fix → verify

It is structurally **blind** to four classes of defect that the user named:

| Defect class | Why current swarm misses it |
|---|---|
| Architecture holes (cross-file, cross-module logic gaps) | Microscope reads files in isolation; telescope is PR-diff scoped, not whole-codebase scoped. No agent constructs the system's intended behaviour graph and walks it. |
| Logical flaws in the very rules ("the protocol is wrong even though every line compiles") | No agent models the state machine, the data flow, or the trust boundary. Code-correctness-agent checks "does the code do what it says?" — not "is what it says correct?". |
| Behaviour / feedback / UX inconsistencies | No agent constructs user journeys ("user clicks X → API → DB → response") and traces them end-to-end. UX/feedback gaps live BETWEEN files. |
| Security protocol flaws | Security-review-agent runs a CWE/OWASP checklist; it does not threat-model. It does not ask "if I were an attacker with goal G, what path through this code lets me reach G?". |

The common root cause: **the swarm has no agent that constructs a scenario and
walks it through the actual code paths**, and **no agent that extracts the
implicit assumptions the code makes and challenges each one**. Both are
SCENARIO-LEVEL operations, not line-level operations — so adding more
microscopes will never close the gap.

## 3. Proposed solution — two new agents

### 3.1 Scenario generator (skill) + scenario walker (agent)

Per the user's design directive (§1): the plugin is **fully automated**.
Scenarios are NEVER authored by the user. The split is:

- **caa-scenario-generator-skill** — discovers the codebase surface and
  emits a list of concrete scenarios as machine-readable JSON. No LLM
  reasoning over per-file code; just deterministic discovery.
- **caa-scenario-walker-agent** — consumes the generated scenarios and
  executes each one, **playing the role of the user**: it walks the same
  paths an end user / API consumer / attacker would take, and flags every
  divergence between intended behaviour and actual behaviour.

#### 3.1.a caa-scenario-generator-skill

**Role:** Auto-discover scenarios from the codebase surface. No human
authorship required — the user just picks "extended review" and this
skill produces the scenario list.

**Surfaces it scans** (deterministic, no LLM judgment):

| Surface | Source | Scenario shape |
|---|---|---|
| HTTP API endpoints | route registrations (FastAPI/Express/Flask/Koa/etc.), OpenAPI spec, grep for `@app.route`, `app.get/post/...`, `Router`, `Mux.HandleFunc` | 1 happy-path + 1 adversarial-input + 1 partial-failure scenario per endpoint |
| CLI commands | argparse/click/cobra/yargs entry points | 1 happy-path + 1 invalid-args + 1 missing-deps scenario per command |
| UI routes / screens | React Router / Next.js pages / Vue Router / etc. | 1 happy-path + 1 auth-required + 1 error-state scenario per route |
| Event listeners | message queue subscribers, websocket handlers, file watchers | 1 happy-path + 1 malformed-event + 1 duplicate-event scenario per listener |
| Webhooks / callbacks | route prefixes like `/webhook`, `/callback`, third-party SDK init calls | 1 happy-path + 1 replay-attack + 1 signature-invalid scenario |
| Background jobs / crons | celery/cron/bull/sidekiq | 1 happy-path + 1 mid-job-crash + 1 concurrent-fire scenario |
| Auth flows | login/logout/refresh routes, OAuth callbacks, session middleware | 1 happy-path + 1 token-expired-mid-request + 1 permission-revoked-mid-session scenario |
| State-mutating writes | `INSERT`/`UPDATE`/`DELETE`, file writes, external API POSTs | 1 happy-path + 1 mid-write-failure + 1 idempotency-retry scenario per write site |
| Trust boundaries | input deserialization, file uploads, header parsing | 1 oversize-input + 1 encoded-injection + 1 unicode-edge-case scenario per boundary |

**How it discovers** (no LLM, pure mechanical):

1. Run `tldr arch <path>` to detect entry layer (handlers/controllers/CLIs).
2. Run `tldr structure <path> --lang <auto>` to enumerate functions.
3. Grep + AST queries via Serena for routing registrations,
   handler decorators, CLI entry points, etc. (one rule set per language/framework).
4. Parse OpenAPI/AsyncAPI specs if present, parse `package.json` scripts, parse `pyproject.toml` `[project.scripts]`, parse `Cargo.toml` `[[bin]]`.
5. Cross-reference with docs (`README.md`, `docs/`, `CHANGELOG.md`) to enrich each
   surface with the **intended behaviour** (used by the walker for divergence detection). Doc parsing is grep + heading extraction, not LLM.
6. Emit a normalised scenarios.json file under
   `<main-repo>/reports/caa-scenario-generator/<ts>-scenarios.json`.

**Output schema** (each scenario):

```json
{
  "id": "SCEN-0042",
  "title": "POST /orders rejects oversize body",
  "family": "adversarial-input",
  "entry_point": {"file": "src/api/orders.py", "line": 17, "symbol": "create_order"},
  "intended_behaviour": "Return 413 with error body; do not invoke the handler logic.",
  "intended_behaviour_source": "docs/api.md:121 + OpenAPI 4xx response",
  "user_role": "anonymous client",
  "input": {"method": "POST", "path": "/orders", "body_size_bytes": 10485761},
  "expected_path": ["middleware/size_limit", "middleware/auth", "<reject>"],
  "feedback_expected": "user sees 413 + Retry-After hint"
}
```

**Inputs:**
- Codebase path (whole-codebase mode) or PR diff (delta mode — discover
  scenarios for changed surfaces only)
- Auto-detected language(s)

**Output:** One `scenarios.json` per run; ALSO a human-readable
`scenarios.md` listing every generated scenario for traceability.

**This is a SKILL, not an agent** — runs in the main turn, uses Bash +
Read + Grep + (optional) Serena/Grepika MCP. No `Edit` / `Write` to source.
Deterministic enough that two runs on the same codebase produce
byte-identical `scenarios.json`.

#### 3.1.b caa-scenario-walker-agent

**Role:** Consumes `scenarios.json` and executes each scenario, **playing
the user's role**. For each scenario, the agent:

1. Reads the scenario JSON (intent, entry point, input, expected path,
   expected feedback).
2. Locates the entry point in code via `tldr context` + Serena.
3. Walks the actual code path the input would take, step by step, using
   `tldr impact` / `serena find_referencing_symbols` / `grepika refs`
   recursively (depth ≥ 5).
4. At each step, asks the four divergence questions:
   - **Invariant check:** What does this step assume on entry? What does it
     promise on exit? Is either broken on this path?
   - **Failure surface:** What goes wrong here? Is the failure visible to
     the user, logged, retried, or silently swallowed?
   - **Trust boundary:** Does data cross a trust boundary here? Is it
     re-validated on the other side?
   - **Feedback consistency:** If this step fails, what does the user
     see? Does the UX match the actual system state? Does it match
     `feedback_expected` in the scenario?
5. Compares the walked path to `expected_path`. Any deviation = finding.
6. Compares the actual outcome to `intended_behaviour`. Any divergence = finding.
7. Records every divergence as a structured finding with: scenario id,
   walked code path (file:line list), step number, sub-question that
   flagged it, evidence (code excerpts).

**The agent literally plays the user** in the sense that it adopts the
`user_role` from the scenario ("anonymous client", "authenticated user",
"admin", "attacker with leaked session token") and traces the path AS
that role — applying that role's permissions, that role's input
constraints, that role's UX expectations. It does NOT execute code; it
performs static walk + role-aware reasoning.

**What it is NOT:** Not a runtime tracer. Not a fuzzer. Not a per-file
auditor. Not a scenario AUTHOR — scenarios always come from the skill
(or from a delta-audit PR scope) and never from human authorship.

**Inputs:**
- Path to `scenarios.json` (mandatory — produced by the skill)
- Codebase path (must match the codebase the scenarios were generated for)
- Optional: reference docs (the skill embeds doc references in each
  scenario, but the agent may re-read them for the divergence checks)

**Output:** One markdown report per scenario, under
`<main-repo>/reports/caa-scenario-walker/<ts>-<scenario-id>.md`.
Each report contains: scenario, walked path, divergences, severity,
suggested fix direction. NEVER returns content to the orchestrator —
only filepaths.

**Spawning:** Spawned as a SWARM by the main pipeline — one agent per
scenario (or one agent per scenario-cluster when `scenarios.json` is
large). Parallel execution bounded by the orchestrator (≤ 15 concurrent).

**Model:** opus, effort: high, maxTurns: 50.
**Disallowed tools:** Edit, NotebookEdit, Write to source code paths.

### 3.2 caa-assumption-auditor-agent (HIGH priority)

**Role:** Extracts every implicit assumption the code makes and challenges
each one against real-world adversarial inputs and edge cases.

**Assumptions it extracts** (per file or per function):

1. **Input shape assumptions.** "This function assumes `user.email` is a
   non-empty string." (What if `null`? `""`? `["a@b", "c@d"]`? `123`?)
2. **Ordering assumptions.** "This step assumes `init()` ran first." (What
   if called from a path that skipped init?)
3. **Idempotency assumptions.** "This handler assumes the request is unique."
   (What if retried? Duplicated? Replayed by an attacker?)
4. **Auth-state assumptions.** "This route assumes `req.user` is set." (What
   if middleware was reordered? Bypassed? Expired between check and use?)
5. **Network/IO assumptions.** "This client assumes the API answers in < 5s."
   (What if it answers in 30s? Never? Returns 200 with an error body?)
6. **Numerical assumptions.** "This counter assumes int32 is enough." (What
   at 2^31? Negative? Float coercion?)
7. **Concurrency assumptions.** "This code assumes single-threaded access."
   (What under N concurrent callers?)
8. **Data-model assumptions.** "This query assumes `users.deleted_at IS NULL`
   means active." (What if soft-delete semantics differ across services?)
9. **Encoding assumptions.** "This parser assumes UTF-8." (What about BOM?
   Surrogate pairs? Mixed encoding?)
10. **Time-zone / clock-skew assumptions.** "This expiry check uses local
    time." (What at DST? Across regions? With clock-skew?)

**How it challenges:** For each extracted assumption, the agent:

1. Writes the assumption explicitly: "Code at file:line ASSUMES X."
2. Generates 3–5 adversarial inputs/states that violate the assumption.
3. Traces what happens in code if the assumption is violated (crash, silent
   corruption, security bypass, UX confusion, dataloss).
4. Records the violation severity and the recommended guard (validate,
   short-circuit, log+alert, fail-closed, etc.).

**Inputs:**
- Codebase path or file list (auto-discover top-N highest-risk files via
  `tldr arch` entry layer + `tldr impact` high-fanin functions)
- Optional: domain knowledge file (threat model, spec, RFC)

**Output:** One markdown report per file or function-cluster, under
`<main-repo>/reports/caa-assumption-auditor/<ts>-<file-slug>.md`.

**Model:** opus, effort: high, maxTurns: 40.
**Disallowed tools:** Edit, NotebookEdit, Write to source code paths.

## 4. Integration with the existing swarm

### 4.0 Entry-point UX — normal vs extended review (per §1 design directive)

The user makes ONE choice. There are exactly two entry-points exposed:

| Entry point | Slash command | What runs |
|---|---|---|
| **Normal review** | `/caa-audit-codebase` (today's behaviour, default) | Today's pipeline — correctness + domain + security + claim-verification + skeptical-review. NO scenario generation, NO assumption audit. Same speed and cost as today. |
| **Extended review** | `/caa-audit-codebase --extended` (or `/caa-extended-audit`) | Today's pipeline PLUS scenario-generator skill PLUS scenario-walker swarm PLUS assumption-auditor swarm. Slower, more thorough, finds architectural / UX / protocol defects line-level review cannot. |

The same split applies to PR review:

| Entry point | Slash command | What runs |
|---|---|---|
| Normal PR review | `/caa-pr-review` | Today's PR pipeline. |
| Extended PR review | `/caa-pr-review --extended` | Today's pipeline + scenario discovery scoped to the changed surfaces + scenario-walker + assumption-auditor on changed files. |

There is NO third option, no per-feature toggles, no scenario-corpus
configuration. The user picks normal or extended; the plugin does
everything else.

### 4.1 New orchestration in caa-audit-codebase-cmd

The current pipeline (still the **normal** path):

```
discover → triage → audit (correctness + domain + security) → verify → gap-fill
        → consolidate → dedup → todo-gen → [fix → fix-verify]
```

The **extended** path:

```
discover → triage
       ├─→ audit (correctness + domain + security)        ← line-level (today)
       ├─→ caa-scenario-generator-skill  (1 turn, deterministic)
       │           ↓
       │     scenarios.json
       │           ↓
       │     caa-scenario-walker-agent swarm              ← scenario-level
       └─→ caa-assumption-auditor-agent swarm             ← assumption-level
                     ↓
       verify → gap-fill
                     ↓
       consolidate (extended) → dedup (extended) → todo-gen → [fix → fix-verify]
```

The three audit families run **in parallel** (independent contexts, no
shared state). The scenario generator runs first because the walker
agents need its output; once `scenarios.json` exists the walker swarm
fans out (one agent per scenario or per cluster). Their reports
converge at consolidation.

### 4.2 What consolidation + dedup needs to change

1. **New finding categories.** `consolidation-agent` and `dedup-agent` must
   recognise these new finding types:
   - `scenario_divergence` — "scenario S step N diverges from invariant I"
   - `unguarded_assumption` — "code at file:line assumes X; X is violated by Y"
   These join the existing line-level categories (type_safety, logic_bug, etc.).

2. **Cross-category dedup.** A single bug can surface from three angles:
   - correctness-agent says "missing null check at line 42"
   - scenario-walker says "scenario 'partial-failure-DB-write' step 3 crashes
     because user object is null when error path runs"
   - assumption-auditor says "code at file:42 assumes user is non-null"
   The dedup-agent must merge these three reports into ONE finding with three
   pieces of evidence (line + scenario + assumption). Current dedup keys on
   file+line+violation_type; the type now matters less than the underlying
   defect, so dedup gets a NEW semantic key: a normalised description of the
   defect plus the affected code region.

3. **Severity reconciliation.** Three reports may assign different severities.
   Take the MAX, but record all three so the user sees that this defect was
   reached from multiple angles (signal of importance).

4. **Evidence merging.** The merged finding includes:
   - line evidence (from correctness)
   - scenario evidence (from scenario-walker — the user-visible path)
   - assumption evidence (from assumption-auditor — the root-cause framing)
   This gives the fix-agent three frames to choose from when writing the TODO.

### 4.3 todo-generator-agent changes

The todo file format gains two new sections per finding (optional, present
only when scenario-walker or assumption-auditor contributed):

```markdown
### Finding F-042: User object is null on partial-failure path

Severity: MAJOR (max of {correctness: MAJOR, scenario: MAJOR, assumption: MINOR})

**Line evidence** (correctness-agent):
- src/api/orders.py:42 — `user.id` accessed without null check

**Scenario evidence** (scenario-walker):
- Scenario: partial-failure-DB-write
- Path: POST /orders → validate → save_order (FAILS) → on_failure handler
- Divergence: on_failure handler runs with `user=None` because the request
  was rate-limited before auth middleware completed.

**Assumption evidence** (assumption-auditor):
- src/api/orders.py:42 assumes `request.user` is non-null
- Violated when: rate-limiter fast-rejects before auth middleware runs

**Required fix:** Guard `request.user` at orders.py:42. If null, return 401
(matches the security protocol stated in docs/auth.md §4.2).
```

This shape gives the human (or the fix-agent) all three frames, which
dramatically reduces "I fixed the symptom but the root cause re-surfaces
elsewhere" — the most common failure mode of line-level fixes.

### 4.4 New skills wrapping the agents

- `caa-scenario-audit-skill` — invokes scenario-walker standalone (without
  the full pipeline). For users who want "walk these 5 scenarios against the
  current codebase" as a one-shot.
- `caa-assumption-audit-skill` — same for assumption-auditor.

These let the user run either agent independently when the full
audit-codebase pipeline is overkill.

## 5. Why this fixes the 4 named defect classes

| User-named defect | Caught by |
|---|---|
| Architecture holes (cross-file, cross-module logic gaps) | scenario-walker traces the full call graph per scenario; cross-file is the default unit, not the exception. |
| Logical flaws in the rules | assumption-auditor surfaces "the code assumes X; X is the wrong rule" by forcing the assumption to be written down. scenario-walker complements: if rule-as-implemented diverges from rule-as-stated-in-docs, it's flagged at the invariant-check step. |
| Behaviour / feedback / UX inconsistencies | scenario-walker's "feedback consistency" sub-question is the explicit hook. Per-scenario walk surfaces "system state ≠ what the user is told". |
| Security protocol flaws | scenario-walker runs adversarial-input + auth-state-transition scenarios per audit; assumption-auditor extracts auth/trust-boundary assumptions and adversarial-tests each. Together they are a threat-model lite — not a full STRIDE workshop, but vastly more than a CWE checklist. |

## 6. Files that need to be created / modified

### Created

1. `agents/caa-scenario-walker-agent.md` — agent definition
2. `agents/caa-assumption-auditor-agent.md` — agent definition
3. `skills/caa-scenario-generator-skill/SKILL.md` + `references/` — the
   deterministic scenario discovery skill (§3.1.a)
4. `scripts/scenario_generator/` — Python helpers the skill calls
   (`discover_http_routes.py`, `discover_cli_commands.py`,
   `discover_ui_routes.py`, `discover_event_listeners.py`,
   `discover_write_sites.py`, `emit_scenarios_json.py`,
   `emit_scenarios_md.py`) — one file per surface type, each
   language-aware. The skill orchestrates them; the agent never invokes
   them directly.
5. `commands/caa-extended-audit-cmd.md` — extended-audit entry point
   (`/caa-audit-codebase --extended` and `/caa-extended-audit` alias)
6. `tests/fixtures/scenario_walker/` — small fixture codebases (one per
   acceptance scenario in §7), with `expected-scenarios.json` and
   `expected-findings.md` golden files.
7. `tests/test_scenario_generator.py` — runs the skill on each fixture,
   asserts byte-identical `scenarios.json` against the golden.
8. `tests/test_scenario_walker.py` — feeds golden `scenarios.json` to the
   agent, asserts findings match expected per scenario.
9. `tests/test_assumption_auditor.py` — fixture with 3 unguarded
   assumptions, assert each is found.
10. `tests/test_consolidation_cross_category.py` — fixture where the same
    defect surfaces from line + scenario + assumption, assert dedup merges
    into one finding with all three evidences.
11. `tests/test_extended_audit_e2e.py` — end-to-end: invoke `/caa-extended-audit`
    on a fixture, assert all three audit families ran, reports merged, TODO
    file emitted with multi-evidence findings.

### Modified

1. `agents/caa-consolidation-agent.md` — recognise new finding categories,
   add evidence-merging spec.
2. `agents/caa-dedup-agent.md` — semantic-key dedup spec across categories.
3. `agents/caa-todo-generator-agent.md` — TODO format gains optional
   scenario/assumption sections.
4. `commands/caa-audit-codebase-cmd.md` — add `--extended` flag, pipeline
   diagram updated with the extended path.
5. `commands/caa-delta-audit-cmd.md` — same `--extended` flag for PR delta
   audits (scenarios scoped to changed surfaces).
6. `skills/caa-codebase-audit-and-fix-skill/SKILL.md` — workflow updates
   (extended path described, normal path unchanged).
7. `skills/caa-pr-review-and-fix-skill/SKILL.md` — same.
8. `skills/caa-pr-review-skill/SKILL.md` — same.
9. `README.md` — agent count + new agents listed + extended-review entry
   point documented + "what does extended add?" table.
10. `.claude-plugin/plugin.json` — version bump (minor, since new agents +
    new skill + new command).
11. `CHANGELOG.md` — entry generated by publish.py.

## 7. Test scenarios (acceptance criteria)

A successful implementation MUST pass these scenarios:

1. **The "fromLabel/toLabel" historical incident.** Feed a PR where the
   description claims "registry-lookup populates 4 fields" but the function
   populates zero. Today's swarm catches this via claim-verification. NEW:
   scenario-walker must ALSO catch this independently from the user-journey
   angle ("user sees label-rendered UI but labels are blank"). Two
   independent agents flagging the same bug = stronger signal.

2. **The "rate-limit before auth" scenario.** Construct a fixture where a
   rate-limiter middleware runs BEFORE auth middleware, then an on-failure
   handler reads `request.user`. Today's correctness agent does NOT catch
   this (the line itself is fine; `request.user` is the right field name).
   NEW: scenario-walker must catch this via the partial-failure-path
   scenario. assumption-auditor must also catch it via the `request.user`
   assumption.

3. **The "TOCTOU permission" scenario.** Permission is checked at line A,
   used at line B, with N lines between. assumption-auditor must flag the
   "permission unchanged between A and B" assumption. scenario-walker must
   flag the "user demoted mid-request" scenario.

4. **The "silent retry corruption" scenario.** An idempotent-looking endpoint
   actually mutates state on each call. scenario-walker's
   adversarial-input scenario must catch it.

5. **The "feedback / state divergence" scenario.** UI shows "saved" but the
   DB write was rolled back. scenario-walker's feedback-consistency
   sub-question must flag this.

6. **Cross-category dedup.** All five scenarios above must produce ONE
   finding each in the final consolidated report (not three duplicates from
   three different agents). Each finding must list line + scenario +
   assumption evidence.

## 8. Security considerations

- The new agents read code; they do not execute it.
- Reports may contain code excerpts with embedded credentials or PII from
  test fixtures. Reports MUST go to gitignored
  `<main-repo>/reports/<component>/` per the agent-reports-location rule.
- The agents must NOT auto-send reports anywhere; the orchestrator handles
  delivery.
- assumption-auditor's adversarial-input section is for DOCUMENTING attack
  ideas in the report only. The agent must NEVER attempt to execute them or
  generate runnable exploit code (only descriptions of inputs).

## 9. Out of scope (deferred)

- **Full STRIDE threat-modelling agent.** A future TRDD could add a
  threat-model-agent that consumes the assumption-auditor output and
  organises threats by STRIDE category. For now, scenario-walker +
  assumption-auditor cover the high-leverage 80%.
- **Runtime fuzzing.** A future TRDD could add a fuzzer that ACTUALLY
  executes the adversarial inputs. For now, static-only.
- **Live UX-walk in browser.** A future TRDD could add a browser-walker
  that uses chrome-devtools MCP to walk scenarios in a real UI. For now,
  scenario-walker is static / call-graph-based.
- **Cross-service / multi-repo scenarios.** v1 is single-repo. Multi-repo
  scenario walks (microservices) are a v2 problem.

## 10. Implementation order

Phase 1 (single PR): `caa-scenario-generator-skill` + the
`scripts/scenario_generator/` discovery helpers + golden-file fixture
tests. Skill must produce byte-identical `scenarios.json` on the
fixtures. NO agent yet — phase 1 is just deterministic discovery, easy
to test, easy to land.

Phase 2 (single PR): `caa-scenario-walker-agent` definition + walker
tests (consumes Phase 1's golden `scenarios.json`, asserts findings on
incidents #1, #2, #5).

Phase 3 (single PR): `caa-assumption-auditor-agent` + tests for
incidents #3, #4.

Phase 4 (single PR): consolidation + dedup + todo-generator updates +
cross-category dedup test (#6).

Phase 5 (single PR): pipeline command updates (the `--extended` flag,
the new entry-point), skill workflow updates, README + version bump +
CHANGELOG. End-to-end test #7 (`test_extended_audit_e2e.py`) lands here.

Each phase publishable independently via `scripts/publish.py --minor`.

## 11. Open questions for the user

### Resolved

1. **Scenario corpus.** ✅ RESOLVED 2026-05-10 (user directive in §1):
   scenarios are auto-generated by `caa-scenario-generator-skill` from the
   codebase surface. NO per-project `scenarios.md`. NO human authorship.
2. **Entry-point UX.** ✅ RESOLVED 2026-05-10 (user directive in §1):
   the user picks normal review or extended review. Nothing else to
   configure. See §4.0.

### Still open (pre-Phase-1 resolution preferred)

3. **PR scope of the scenario-walker.** Should the walker process every
   scenario the changed files PARTICIPATE in (broader; catches caller-side
   regressions) or only scenarios whose ENTRY POINT is in the changed
   files (narrower; faster)? Current proposal: broader for full-codebase
   extended review, narrower for `/caa-pr-review --extended`.
4. **assumption-auditor file selection.** Per-file (all files) or
   top-N-highest-risk (entry layer + high-fanin functions)? Current
   proposal: top-N for codebase audits, all-changed-files for PR audits.
5. **Severity policy.** Should a "scenario divergence" finding count as
   CRITICAL by default, or follow the same severity tiers as correctness?
   Current proposal: same tiers, severity per-finding.
6. **Concurrency cap on the walker swarm.** Hardcoded at 15 (matches
   parallel-fixer cap), or configurable via `userConfig`? Current proposal:
   hardcoded at 15 for v1; revisit if users hit the cap.
7. **Scenario-generator language coverage for v1.** Which surface-scanners
   ship in v1? Current proposal: Python (FastAPI/Flask/argparse/click) +
   TypeScript/JavaScript (Express/Next.js/React Router/yargs/commander).
   Go/Rust/Java framework support deferred to v2 unless a user asks.

## 12. Rollback plan

If the new agents produce too many false positives or slow the pipeline
unacceptably:

- The extended path is gated by a single flag (`--extended`). Disabling
  it returns the user to today's exact behaviour, instantly. No code
  changes needed.
- The new finding categories are additive; consolidation + dedup degrade
  gracefully if no scenario / assumption reports exist (normal review
  produces neither, and the pipeline is unaffected).
- Within the extended path, two sub-flags (`--no-scenarios`,
  `--no-assumptions`) disable either branch individually for partial
  rollback or debugging.
- If `caa-scenario-generator-skill` produces a malformed `scenarios.json`,
  the walker swarm fails closed with a clear error; the normal-review
  pipeline still completes and the user gets today's report. The
  extended branches never block the line-level audit.

---

End of TRDD-6857f67f.
