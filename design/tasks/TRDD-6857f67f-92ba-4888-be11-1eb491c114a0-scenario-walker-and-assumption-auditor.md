# TRDD-6857f67f — Scenario-walker and assumption-auditor agents

**TRDD ID:** `6857f67f-92ba-4888-be11-1eb491c114a0`
**Filename:** `design/tasks/TRDD-6857f67f-92ba-4888-be11-1eb491c114a0-scenario-walker-and-assumption-auditor.md`
**Tracked in:** this repo (`design/tasks/` is git-tracked)
**Status:** Not started
**Author:** Emasoft (via Claude opus session 2026-05-10)
**Related agents:** caa-skeptical-reviewer-agent, caa-code-correctness-agent, caa-claim-verification-agent, caa-domain-auditor-agent, caa-security-review-agent

---

## 1. User's original request (verbatim)

> how can we improve the code auditor agent? too many issues and bugs are still
> missed by it. and it doesn't seem to understand when an architecture has clear
> holes, vulnerabilities, flaws in the very logic, inconsistencies in the
> behaviour, in the feedback, in the ux, in the security protocols.

Follow-up confirmation: `yes do it`.

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

### 3.1 caa-scenario-walker-agent (HIGH priority)

**Role:** Constructs concrete scenarios and walks each one through the actual
call graph, flagging every step where the path diverges from invariants,
security protocol, stated UX, or claimed behaviour.

**Scenarios it constructs** (per audit target):

1. **Happy-path user journeys.** "User submits form → validation → service →
   DB write → success response." One scenario per documented user-facing flow.
2. **Adversarial inputs.** Malformed payloads, oversize bodies, unicode edge
   cases, encoded injection, replayed requests, out-of-order events.
3. **Partial-failure paths.** "DB write fails mid-transaction", "external API
   returns 500", "network drops between step N and N+1", "process killed at
   step M". One per write/IO/network boundary.
4. **Concurrent-state paths.** "Two clients hit the same resource at the same
   instant", "user closes window mid-upload", "retry fires before original
   completes".
5. **Auth/authz state transitions.** "Token expires mid-request", "user is
   demoted mid-session", "permission revoked between check and use (TOCTOU)".
6. **Resource limits.** "Quota hit at 99%", "disk fills during write", "rate
   limit hits on partial batch".

**How it walks:** For each scenario, the agent:

1. Identifies the entry point in code (handler, command, event listener).
2. Traces the call graph using `tldr impact` / `serena find_referencing_symbols`
   / `grepika refs` recursively, depth ≥ 5.
3. At each step, asks the four sub-questions:
   - **Invariant check:** "What does this step assume to be true on entry?
     What does it promise on exit? Is either broken on this path?"
   - **Failure surface:** "What goes wrong here? Is the failure visible to
     the user, logged, retried, or silently swallowed?"
   - **Trust boundary:** "Does data cross a trust boundary here? Is it
     re-validated on the other side?"
   - **Feedback consistency:** "If this step fails, what does the user see?
     Does the UX match the actual system state?"
4. Records every divergence as a structured finding with: scenario name, code
   path (file:line list), step number, sub-question that flagged it, evidence.

**What it is NOT:** It is NOT a runtime tracer (no execution required). It is
NOT a per-file auditor (it reads multiple files per scenario). It is NOT a
compliance checklist runner.

**Inputs:**
- Codebase path or PR diff (auto-detect scope)
- Optional: `scenarios.md` user-provided scenario list (if absent, agent
  generates scenarios from API surface + UI surface + docs)
- Optional: reference architecture / design doc / threat model

**Output:** One markdown report per scenario, under
`<main-repo>/reports/caa-scenario-walker/<ts>-<scenario-slug>.md`.
Each report contains: scenario, walked path, findings, severity, suggested fix
direction. NEVER returns content to the orchestrator — only filepaths.

**Model:** opus, effort: high, maxTurns: 50 (scenarios can be deep).
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

### 4.1 New orchestration in caa-audit-codebase-cmd

The current pipeline:

```
discover → triage → audit (correctness + domain + security) → verify → gap-fill
        → consolidate → dedup → todo-gen → [fix → fix-verify]
```

Becomes:

```
discover → triage
       ├─→ audit (correctness + domain + security)        ← line-level (today)
       ├─→ scenario-walker (NEW)                          ← scenario-level
       └─→ assumption-auditor (NEW)                       ← assumption-level
                     ↓
       verify → gap-fill
                     ↓
       consolidate (extended) → dedup (extended) → todo-gen → [fix → fix-verify]
```

The three audit families run **in parallel** (independent contexts, no shared
state). Their reports converge at consolidation.

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
3. `skills/caa-scenario-audit-skill/SKILL.md` + `references/`
4. `skills/caa-assumption-audit-skill/SKILL.md` + `references/`
5. `commands/caa-scenario-audit-cmd.md`
6. `commands/caa-assumption-audit-cmd.md`
7. `tests/test_scenario_walker.py` — happy-path scenario + 1 adversarial-input
   scenario on a fixture codebase, asserting findings are emitted.
8. `tests/test_assumption_auditor.py` — fixture with 3 unguarded assumptions,
   assert each is found.
9. `tests/test_consolidation_cross_category.py` — fixture where the same
   defect surfaces from line + scenario + assumption, assert dedup merges
   into one finding with all three evidences.

### Modified

1. `agents/caa-consolidation-agent.md` — recognise new finding categories,
   add evidence-merging spec.
2. `agents/caa-dedup-agent.md` — semantic-key dedup spec across categories.
3. `agents/caa-todo-generator-agent.md` — TODO format gains optional
   scenario/assumption sections.
4. `commands/caa-audit-codebase-cmd.md` — pipeline diagram includes new
   branches.
5. `skills/caa-codebase-audit-and-fix-skill/SKILL.md` — workflow updates.
6. `skills/caa-pr-review-and-fix-skill/SKILL.md` — workflow updates.
7. `skills/caa-pr-review-skill/SKILL.md` — workflow updates.
8. `README.md` — agent count + new agents listed.
9. `.claude-plugin/plugin.json` — version bump (minor, since new agents).
10. `CHANGELOG.md` — entry generated by publish.py.

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

Phase 1 (single PR): scenario-walker-agent definition + skill + command +
fixture tests for incidents #1, #2, #5.

Phase 2 (single PR): assumption-auditor-agent + skill + command + fixture
tests for incidents #3, #4.

Phase 3 (single PR): consolidation + dedup + todo-generator updates +
cross-category dedup test (#6).

Phase 4 (single PR): pipeline command updates + skill workflow updates +
README + version bump + CHANGELOG.

Each phase publishable independently via `scripts/publish.py --minor`.

## 11. Open questions for the user (resolve before Phase 1 starts)

1. **Scenario corpus.** Should v1 ship a built-in scenario library (the
   six categories listed in §3.1), or require the user to author scenarios
   per project? Current proposal: ship a built-in library, allow per-project
   override via `scenarios.md`.
2. **Scope of scenario-walker on PR diffs.** Should it walk scenarios that
   only touch changed files, or every scenario that the changed files
   participate in? Current proposal: every scenario the changed files
   participate in (broader catches more regressions).
3. **assumption-auditor file selection.** Per-file (all files) or
   top-N-highest-risk (entry layer + high-fanin functions)? Current proposal:
   top-N for codebase audits, all-changed-files for PR audits.
4. **Severity policy.** Should a "scenario divergence" finding count as
   CRITICAL by default, or follow the same severity tiers as correctness?
   Current proposal: same tiers, severity per-finding.

## 12. Rollback plan

If the new agents produce too many false positives or slow the pipeline
unacceptably:

- The new agents are independent processes (parallel branches in the
  pipeline). Disabling them is a one-line change in `caa-audit-codebase-cmd.md`.
- The new finding categories are additive; consolidation + dedup degrade
  gracefully if no scenario / assumption reports exist.
- A feature flag in `caa-audit-codebase-cmd.md` (`--no-scenarios`,
  `--no-assumptions`) gates the new branches without removing them.

---

End of TRDD-6857f67f.
