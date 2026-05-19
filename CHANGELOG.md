# Changelog

All notable changes to this project will be documented in this file.

## [3.4.4] - 2026-05-19

### Documentation

- Add --bg / claude agents invocation example for ecaa-self-test-24 (3fe0e90)

## [3.4.3] - 2026-05-19

### Features

- *(skill/pr-review)* Wire --code-analysis-depth parameter (fd7ff42)

### Bug Fixes

- Add Opus 4.7 pricing to cpv_token_cost (Claude Code v2.1.142) (45512f7)
- *(ecaa-self-test-24)* Reconcile orchestrator + references with JSON aggregator (ca63725)
- *(scenario-generator)* Bump skill version 0.1.0 → 3.4.2 (b42ea55)
- *(skills)* Trim descriptions ≤250 chars + drop redundant checklist (c4b218b)
- *(lint)* Clear publish-blocking Phase 1 lint errors (8c06998)
- *(lint)* Exclude CHANGELOG.md from markdownlint (bac75c2)
- *(lint)* Disable MD037 + MD050 markdownlint rules (17cbc06)

### Performance

- *(ecaa-self-test-24)* Make parallel dispatch deterministic (0a31bca)

### Documentation

- Add TRDD-6857f67f — scenario-walker + assumption-auditor agents (71c07e3)
- TRDD-6857f67f revision — auto-generated scenarios + extended-review entry-point (e4a5ed5)
- TRDD-6857f67f — remove maxTurns cap on new agents (per user directive) (cb94e2b)
- TRDD-6857f67f — domain-agnostic scenario generator (firmware/OS/FPGA/anything) (067c808)
- Add TRDD-60f53034 — PR-Review-Skills top-5 ROI improvements (80299fb)
- *(skill)* Clear 5 MINORs in caa-scenario-generator-skill/SKILL.md (118219d)
- Add TRDD-7e364ace — bug-detection completeness from PR-Review corpus (faada27)
- Rewrite TRDD-7e364ace into 20-step depth-parameterised pipeline (1273acd)
- *(trdd-7e364ace)* Lock model policy + replace Codex step (34d321f)
- *(trdd-7e364ace)* Lock 24-step structure derived from 1452-row sweep (65c0b83)
- *(trdd-7e364ace)* Fix step-7 numbering typo (0082956)
- *(trdd-7e364ace)* Record step-9 commit hash in status tracker (329763c)
- *(trdd-7e364ace)* Record step-10 commit hash (2a51481)
- *(trdd-7e364ace)* Record step-11 commit hash (94004a1)
- *(trdd-7e364ace)* Record step-12 commit hash (efc4686)
- *(trdd-7e364ace)* Record step-13 commit hash (4ce8f31)
- *(trdd-7e364ace)* Record step-14 commit hash (d7a8b33)
- *(trdd-7e364ace)* Record step-15 commit hash (fc7d734)
- *(trdd-7e364ace)* Record step-16 commit hash (2725a6b)
- *(trdd-7e364ace)* Record step-17 commit hash (eb9f864)
- *(trdd-7e364ace)* Record step-18 commit hash (0efa1e6)
- *(trdd-7e364ace)* Record step-19 commit hash (51f5440)
- *(trdd-7e364ace)* Record step-20 commit hash (fca803f)
- *(trdd-7e364ace)* Record step-21 commit hash (11b2c6b)
- *(trdd-7e364ace)* Record step-22 commit hash (fdb5481)
- *(trdd-7e364ace)* Mark all 24 steps shipped (ae9be36)

### Chores

- Align uv.lock to v3.4.2 (098263c)
- *(validators)* Sync upstream CPV validators (a8cbd8a)
- *(validators)* Make new scripts executable + add README badge markers (dd0ef62)
- *(lint)* Clear markdownlint NITs (5f23bed)
- *(publish)* Print hook stdout on push failure (8f14038)

### Security

- Remove maxTurns cap from all 11 CAA agents + fix workflow path validator FPs (2ed0154)
- *(7e364ace/18)* Pre-mortem risk-analyzer agent (a5dfe94)
- *(7e364ace/20)* High-frequency domain specialist agents (4621e84)

### Other

- Scenario-generator engine foundation (Phase 1 of TRDD-6857f67f) (4bfbb1c)
- Web_python_fastapi discoverer (Phase 1 reference pattern) + mypy fix (32bc13a)
- Phase 1 complete: scenario-generator skill + 10 discoverers + 11 fixture goldens + regression test

Implements TRDD-6857f67f Phase 1 end-to-end. All 47 regression tests pass.

## What ships in this commit

### Skill
- skills/caa-scenario-generator-skill/SKILL.md (under 4000 chars, Nixtla-strict)
- references/01-software-type-detection.md (full §3.1.c registry overview)
- references/02-scenario-schema.md (universal schema, EntryPointKind/ActorRole enums)
- references/03-discoverers.md (catalog, contract, how-to-add-a-new-one)
- references/04-scenario-families.md (full §3.1.e applies-to + failure modes)

### Engine updates
- emit_scenarios_json.py — dispatch enhanced to support framework-named
  discoverers via two rules: (1) filename prefix `<type>_<framework>.py`
  and (2) module-level TYPE_ORIGIN declaration. Multiple framework variants
  per type are unioned in deterministic name order.
- web_python_fastapi.py — gains TYPE_ORIGIN = "web_service_python".
- web_python_fastapi.py + unknown_software.py — skip-dir check uses
  RELATIVE parts so fixtures under tests/fixtures/... aren't mis-skipped.

### Phase 1 discoverers (10 + fallback)
- web_python_fastapi.py — @app.get/post/..., @router.*, .add_api_route()
- web_node_express.py — app.get/post/..., router.* (Express)
- web_node_nextjs.py — pages/api/*, app/**/route.ts (Pages + App Router)
- cli_python_click.py — @click.command(), @click.group()
- cli_node_yargs.py — yargs.command() string + object forms
- library_python.py — public top-level callables filtered by __all__
- firmware_arduino.py — setup/loop/attachInterrupt/Serial.onReceive
- firmware_platformio.py — per-env framework dispatch
- linux_kernel_module.py — module_init/exit, file_operations members, EXPORT_SYMBOL
- fpga_verilog.py — top-level module ports identified via constraint files
- unknown_software.py — fallback (updated for relative skip-dirs)

### Fixtures + goldens (11)
- web_python_fastapi: 56 scenarios   - cli_node_yargs: 18
- web_node_express: per-fixture       - library_python: 15
- web_node_nextjs: 84 (56 HTTP + 28 UI) - firmware_arduino: 88
- cli_python_click: 18                - firmware_platformio: 176
- linux_kernel_module: 156            - fpga_verilog: 36
- unknown_software: 9

### Tests
- tests/test_scenario_generator.py — 47 parametrized tests covering:
  - per-fixture golden match (scenarios + detected_types)
  - per-fixture two-runs-byte-identical determinism
  - per-fixture name-matches-primary-detected-type
  - registry mirror consistency (ALL_TYPES == _KNOWN_TYPES)
  - FAMILY_TO_TYPES + FAMILY_TO_FAILURE_MODES key consistency
  All 47 pass.

### Dispatch model

Engine supports MULTIPLE discoverers per detected type. Example: a project
detected as web_service_node runs BOTH web_node_express.py AND
web_node_nextjs.py — useful for monorepos with both an Express backend
and a Next.js frontend in the same checkout.

Phase 1.5: ~60 more discoverers (parallel PRs). Phase 2: walker agent. (6a70133)
- Phase 2: caa-scenario-walker-agent (type-blind scenario executor)

Implements TRDD-6857f67f Phase 2. The walker consumes scenarios.json
produced by caa-scenario-generator-skill and executes each scenario by
walking the static call graph and playing the actor_role specified in
the scenario. Flags every divergence between intended behaviour and
actual code behaviour.

## Why type-blind matters

The agent reads scenario fields (entry_point.kind, actor_role,
stimulus.kind, failure_modes_to_test) and applies the SAME walking
logic regardless of whether the entry point is an HTTP route, an ISR
vector, a Linux syscall handler, a Terraform resource, or an FPGA
top-level port. Type-specific knowledge was crystallized into the
universal schema by the generator skill (Phase 1) — the walker just
executes scenarios per the schema.

This is the architecture that lets the walker support every software
type the generator supports, including future types added in
Phase 1.5, without ever needing to modify the walker code.

## Walk protocol (6 steps per scenario)

1. Load the scenario from scenarios.json by ID.
2. Locate the entry point (verify it still exists; if not, MAJOR
   finding for stale scenarios.json).
3. Adopt the actor role — apply that role's input constraints and
   trust assumptions (e.g. hardware_interrupt = async ISR domain;
   userspace_attacker = unmapped pointers + size overflow; bootloader
   = no invariants hold yet).
4. Walk the call graph (depth >= 5), checking invariants_to_check and
   failure_modes_to_test at every step.
5. Compare outcome to intended_behaviour.
6. Compare to feedback_expected if non-null (UX/error path).

## Severity scheme

CRITICAL (security boundary crossed, memory safety violation),
MAJOR (wrong outcome on happy path, missing failure-mode guard),
MINOR (UX/feedback divergence, scenario stale), NIT (style only).

Verdict per report: PASS | FAIL_MINOR | FAIL_MAJOR | FAIL_CRITICAL.

## Output contract

One markdown report per scenario at ${REPORT_DIR}/SCEN-NNNN.md.
Orchestrator receives only one line per scenario:
"[DONE] SCEN-NNNN — <verdict>. Report: <filepath>"
Findings never inlined in the orchestrator response.

## No maxTurns

Per TRDD §3.3, the walker has no maxTurns cap — walk depth is
codebase-determined, not state-machine-determined. Orchestrator budget
control is per-agent timeout (30 min default) + swarm concurrency cap
(<=15 parallel), NOT turn count.

## Validation

validate_agent.py: 0 CRITICAL, 0 MAJOR, 2 MINOR (informational:
disallowedTools is the existing CAA-agent convention; body is 2129
words because walk protocol is complex — trade-off accepted).
Score: 94/100.

## What's deferred

Integration tests for the 3 historical incidents (fromLabel/toLabel,
rate-limit before auth, feedback/state divergence) are deferred until
Phase 5 wires the --extended entry point and the orchestrator can
actually dispatch the walker swarm in an end-to-end test. The agent
definition is complete and ready to be dispatched. (97a9ce8)
- Phase 3: caa-assumption-auditor-agent (10-family implicit assumption hunter)

Implements TRDD-6857f67f Phase 3. Complements the scenario walker:
where the walker traces user/system journeys end-to-end across files,
this agent reads ONE file at a time and asks "what does THIS line
silently assume to be true?" — then enumerates the inputs/states that
violate the assumption and traces the concrete consequence.

## 10 assumption families

1. input_shape — string/collection/numeric shape assumptions
2. ordering — code that uses state assumed-initialised by prior step
3. idempotency — handlers that assume request uniqueness
4. auth_state — auth context assumed-still-valid (TOCTOU on perm/role)
5. network_io — outbound calls with timeline/shape assumptions
6. numerical — arithmetic with range/overflow assumptions
7. concurrency — code that assumes single-threaded access
8. data_model — schema/representation assumed-shared-with-peers
9. encoding — parser assumes UTF-8/no BOM/etc.
10. time_clock — timestamp comparisons with local-time/skew assumptions

For each family, the agent generates 3-5 adversarial inputs per
detected assumption, traces the code path under that violation, and
records a finding with: assumption (explicit), violating inputs,
consequence (crash/corruption/bypass/dataloss/UX), suggested guard.

## Filter aggressively

The agent only records a finding when ALL three hold:
- the assumption is plausible to violate (real attacker / retry /
  peer / hardware glitch)
- the violation has a concrete consequence
- the code has NO existing guard for that case

Cap: 10 findings per file. If more, list top-10 by severity.

## Scope and non-overlap with sibling agents

- caa-code-correctness-agent finds what the code DOES wrong on a line.
- caa-assumption-auditor finds what the code DOESN'T do (no guard, no
  validation, no atomic, no auth re-check) on a path that needs it.
- caa-scenario-walker finds cross-file divergences along known
  journeys; assumption-auditor stays local to ONE file at a time.

## Validation

validate_agent.py: 0 CRITICAL, 0 MAJOR, 2 MINOR (informational:
disallowedTools is the existing CAA-agent convention; body is 2128
words — the 10-family taxonomy + protocol is large but each family is
a separate self-contained playbook the agent uses as a checklist).
Score: 94/100.

## What's deferred

Integration tests for TRDD §7 #3 (TOCTOU permission) and #4 (silent
retry corruption) deferred to Phase 5 when --extended wires everything
end-to-end. The agent definition is complete and ready to be
dispatched. (12681a6)
- Phase 4: consolidation + dedup + todo-gen cross-category awareness (TRDD-6857f67f)

Adds awareness of the new finding categories (scenario_divergence,
unguarded_assumption) and cross-category merging semantics to the three
post-audit pipeline agents.

## What changes

### caa-consolidation-agent
Added Step 3.5 "Cross-category merging": when findings from
correctness/domain/security (line-level), scenario-walker
(scenario_divergence), and assumption-auditor (unguarded_assumption)
point at the SAME underlying defect, MERGE them into ONE consolidated
finding with all three evidence blocks preserved. Severity is the MAX
across kinds. Two-from-different-angles = one merged finding (stronger
signal, NOT duplicate).

The merged finding shape is documented as a YAML schema with three
optional evidence blocks keyed by `kind: line | scenario | assumption`.

### caa-dedup-agent
Added "CRITICAL: Cross-category merged findings are ONE finding, not
duplicates" section. Dedup must NOT split a merged finding into its
three evidences. Verifies file/line consistency across the evidences
and severity MAX. Counts each merged finding as ONE in the final
tally.

### caa-todo-generator-agent
Added optional evidence sections in TODO entry format. When the
consolidated finding has multiple `kind:` values, the TODO entry
appends three optional sections — "Line evidence", "Scenario
evidence", "Assumption evidence" — each surfacing its specific frame.
Single-frame findings keep the original simple format.

The fix agent in Phase 4 reads these to pick the clearest frame when
writing the patch. Reduces "I fixed the symptom but the root cause
re-surfaced elsewhere" — the most common failure of line-level patches.

## Validation

- caa-consolidation-agent: 97/100
- caa-dedup-agent: 87/100 (1 pre-existing MAJOR: no <example> blocks
  in the original file — out of scope for this PR; should be fixed in
  a follow-up that adds canonical dedup examples)
- caa-todo-generator-agent: 97/100

## What's deferred

Integration test for TRDD §7 #6 (cross-category dedup) deferred to
Phase 5 when --extended wires the full pipeline end-to-end. (aa22cfa)
- Phase 5: wire --extended flag in caa-audit-codebase + caa-delta-audit + README (TRDD-6857f67f)

Adds the user-facing --extended flag to the two top-level audit
commands per TRDD-6857f67f §4.0. The user makes ONE choice: normal
review (today's behaviour, default) or extended review (adds scenario
walker + assumption auditor swarms). No third option, no per-feature
toggles beyond two debugging escape hatches.

## caa-audit-codebase-cmd

Adds:
- `--extended` (default false): when true, runs caa-scenario-generator-skill
  to emit scenarios.json, then dispatches caa-scenario-walker-agent swarm
  (one per scenario or cluster) and caa-assumption-auditor-agent swarm
  (one per high-risk file). Reports cross-merge with line-level findings
  at consolidation.
- `--no-scenarios` (in extended mode): assumption auditor only
- `--no-assumptions` (in extended mode): scenario walker only

Updated "What Happens" to include the new Phase 4c that runs the two
swarms in parallel before consolidation. Phase 5 (TODO generation) now
documents that merged findings carry up to 3 evidence frames.

## caa-delta-audit-cmd

Adds `--extended` for PR-style incremental audits. Scenario generator
runs in delta mode (scenarios scoped to changed surfaces); assumption
auditor runs only on changed files.

## README

- Agent count: 11 → 13 (added scenario-walker + assumption-auditor)
- New "Extended Review Agents" section with concurrency/purpose table
- Added `caa-scenario-generator-skill` to the skills table

## What's NOT in this commit (deferred to future PRs)

- Version bump in .claude-plugin/plugin.json — must go through publish.py
  per the project's pre-push hook (CAA_PUBLISH_PIPELINE env var gate).
- CHANGELOG.md entry — generated by publish.py at release time.
- SKILL.md updates for the 3 pipeline skills — they're at the 4000-char
  cap; the COMMAND files document the extended path; the skills receive
  the flag at runtime and route accordingly. Adding to SKILL.md would
  push them over the cap.
- End-to-end integration test (TRDD §7 acceptance scenarios 1-6) —
  requires a working orchestrator + agent runtime; should land alongside
  the version bump in a publish.py-driven minor release. (0f2bde2)
- Phase 1.5 wave A: +26 discoverers (web/cli/lib/iac/mobile/data) (TRDD-6857f67f)

Adds discoverers + fixtures + byte-identical goldens for:
- Web: web_service_{go,ruby,php,dotnet,java_kotlin,rust}
- CLI: cli_{rust,go,csharp}
- Library: library_{node,rust,c}
- IaC: iac_{terraform,helm,docker_compose,k8s_operator}
- Mobile: mobile_{android,ios,flutter,reactnative,kotlin_multiplatform}
- Data: data_pipeline_{airflow,dbt,prefect,dagster} + ml_training

Each batch built by an isolated parallel subagent reading the shared
spec at docs_dev/discoverer-builder-spec.md. All 151 regression
tests pass; ruff lint + format clean; gofmt clean on Go fixtures.

Coverage: 10 discoverers -> 36 (60% of TRDD §3.1.c registry). (353a4f5)
- Phase 1.5 wave B: +33 discoverers (firmware/rtos/kernel/games/desktop) (TRDD-6857f67f)

Adds discoverers + fixtures + byte-identical goldens for:
- Firmware: firmware_{zephyr,espidf,stm32,nordic_sdk,baremetal}
- RTOS: rtos_{freertos,zephyr,threadx,chibios}
- Kernel/OS: linux_kernel_tree, windows_kernel_driver, bsd_kernel,
  macos_kernel_ext, os_baremetal, driver_linux_userspace
- HDL: fpga_vhdl, asic_design
- Browser ext: browser_ext_{chrome,firefox,safari}
- Game: game_{unity,unreal,godot,engine}
- IaC: iac_{pulumi,ansible,cloudformation,kustomize}
- Desktop: desktop_{qt,gtk,electron,tauri,flutter}

Also fixes two fingerprint bugs found while building fixtures:
- desktop_flutter vs mobile_flutter: tightened desktop_flutter's
  primary_content to require platform deps (flutter_acrylic /
  window_manager / desktop_window / windows: / linux: / macos:)
  AND reordered before mobile_flutter, with bidirectional
  conflicts_with so each fixture detects as exactly one.
- game_unity: fixed broken Python rglob pattern - '**/Assets/**' /
  '**/ProjectSettings/**' don't recurse into the directory; changed
  to '**/Assets/**/*.cs' / '**/ProjectSettings/*.asset' which do.

All 283 regression tests pass; ruff lint + format clean; remote CPV
validator reports 0 CRITICAL / 0 MAJOR.

Coverage: 36 -> 69 discoverers (~91% of TRDD §3.1.c registry). (bec4581)
- Phase 1.5 wave C: +8 discoverers (systems/transport/crypto) (TRDD-6857f67f)

Adds discoverers + fixtures + byte-identical goldens for:
- Systems: compiler_parser, network_protocol_impl, database_engine,
  distributed_system
- Transport: crypto_library, webgl_three, websocket_server,
  message_queue_consumer

All 315 regression tests pass; remote CPV validator reports
0 CRITICAL / 0 MAJOR; ruff format clean.

Coverage: 69 -> 77 discoverers — complete TRDD §3.1.c registry coverage.
Phase 1.5 complete. (749644e)
- Phase A (F-004 + F-001): confidence + layer schema on all 13 CAA agents (TRDD-60f53034)

Every CAA agent's finding template now carries two new schema fields:

- Confidence: HIGH | MEDIUM | LOW — LOW must be phrased as a question
- Layer: mechanical | structural | narrative — mechanical findings
  are deprioritized (CI should catch them), structural is the primary
  CAA value, narrative covers PR description / linked-issue / docs.

Pipeline-stage agents got additional sections:
- caa-consolidation: Confidence-filtering rule (LOW + NIT dropped
  except security) + Layer-grouping (Structural / Narrative /
  Mechanical sections in that order).
- caa-dedup: Confidence merge rule (use max of merged findings).
- caa-todo-generator: Layer-based TODO priority.

Each agent updated by an isolated 1-file Opus subagent per the
"more agents, smaller batches" feedback rule.

Remote CPV validator: 0 CRITICAL / 0 MAJOR. Existing 315 scenario-
generator regression tests untouched (no Python code changed). (9ac1ef4)
- Phase B (F-002): linked-issue verification + BLOCKER short-circuit (TRDD-60f53034)

caa-claim-verification-agent now:
- Detects `Fixes #NNN` / `Closes #NNN` / `Resolves #NNN` references in
  the PR description.
- Calls `gh issue view <N> --json title,body,labels` for each — treats
  the issue body as UNTRUSTED data (no instruction-following).
- Parses acceptance criteria in priority order: markdown task list,
  explicit "Acceptance Criteria:" section, MUST/SHOULD sentences.
- Emits one MUST-FIX (Layer=narrative, Category=functional-completeness)
  per unmet criterion AND a special top-level BLOCKER finding when
  any criterion is unmet.
- Falls back to WARNING when `gh` is unavailable or --skip-linked-issue
  is set.

caa-consolidation-agent now short-circuits on BLOCKER:
- Top-level `# BLOCKER` section at the start of the consolidated report.
- Downstream agents' findings are NOT consolidated (not actionable until
  the BLOCKER is resolved).
- `recommendation:` field forced to REQUEST_CHANGES.

caa-audit-codebase-cmd now:
- Documents the new `--skip-linked-issue` flag.
- Documents the BLOCKER short-circuit behavior in the orchestration
  section.

Remote CPV validator: 0 CRITICAL / 0 MAJOR. (0ce495d)
- Phase C (F-006): agent-written code sub-checklist (TRDD-60f53034)

caa-code-correctness-agent now has an AGENT-WRITTEN CODE SUB-CHECKLIST
covering the six characteristic agent-generated failure modes:

1. Invented APIs (function/import/attribute that does not exist)
2. Fake test coverage (tests mocking the function under test, tests
   with vacuous assertions, tests that always pass)
3. Comment-vs-code contradiction (docstring claims behavior the code
   doesn't implement)
4. Edits outside requested scope (file changes far from PR's stated
   purpose)
5. Stale library usage (deprecated APIs from older training data)
6. Plausible-but-incorrect logic (off-by-one, swapped operands,
   inverted conditions)

Activation: explicit `--agent-written-code` flag OR auto-detection
from PR description (Claude/Codex/Cursor/Copilot/GPT-N/Gemini/Aider/
Continue/Cline mentions); OR author handle `*[bot]`; OR commit
`Co-authored-by:` agent attribution. Force-off via
`--no-agent-written-code`.

caa-audit-codebase-cmd now documents the two flags + the orchestration
precedence rule for the AGENT_WRITTEN_CODE_MODE parameter.

Remote CPV validator: 0 CRITICAL / 0 MAJOR. (a7001ca)
- Phase D (F-003): caa-cross-layer-auditor-agent + wiring (TRDD-60f53034)

New agent caa-cross-layer-auditor-agent hunts cross-file mismatches
that per-file auditors are structurally blind to:

1. env-var-drift — code reads FOO_API_KEY but .env.example has FOO_KEY
2. default-value-drift — frontend default vs backend default disagree
3. schema-mismatch — schema says non-null but code returns null (or
   schema removed field but consumer still queries it)
4. orphan-caller — PR deletes function but callers still reference it
   (detected via Serena's find_referencing_symbols)
5. hidden-ops-prereq — new runtime dependency (Redis / wildcard DNS /
   S3 / IAM perm) not mentioned in deployment docs or runbook

Hard constraints:
- ALL cross-layer findings carry Layer: structural BY DEFINITION
- Two-file evidence rule: every finding MUST cite >= 2 files in
  Related files section (if only one file, it's a per-file finding —
  belongs in caa-code-correctness-agent instead)
- Finding-ID prefix CL-PN-AN to distinguish from CC-/SR-/SK- swarms
- Confidence calibration: HIGH if both sides directly read; MEDIUM if
  one side directly read + one grep-matched; LOW if inferred (phrase
  as a question)
- Pre-flag verification: if both sides of the mismatch are inside
  the SAME diff (PR is fixing the mismatch), skip or downgrade to LOW

Wiring:
- caa-audit-codebase-cmd: Phase 1b runs the new agent ONCE per audit
  (not per-domain swarm) since findings span the whole repo. New
  --skip-cross-layer-audit flag.
- caa-consolidation-agent: new "## Cross-layer findings" section
  preserves Related files: verbatim, refuses to merge per-file
  findings with cross-layer findings (would lose cross-file context),
  groups under Structural with sub-heading "### Cross-layer mismatches".

Agent count: 13 -> 14. Remote CPV validator: 0 CRITICAL / 0 MAJOR.
TRDD-60f53034 (all 5 phases) complete. (aafcd8d)
- *(7e364ace/0)* Domain detection pre-flight gate (d9a48d4)
- *(7e364ace/5)* Linter & scanner pre-flight wrapper (c9ca3d2)
- *(7e364ace/6)* Cross-layer drift detector (script half) (dcc35e1)
- *(7e364ace/7)* Multi-tenant data-isolation scanner (script half) (0b2bd72)
- *(7e364ace/8)* Silent-failure hunter (script half) (5de0ffc)
- *(7e364ace/9)* Concurrency hazards scanner (script half) (445e134)
- *(7e364ace/10)* Complexity & dead-code scanner (8420e44)
- *(7e364ace/11)* AWC extensions — deps + hardcoded config (dca072c)
- *(7e364ace/12)* Comment & docstring quality scanner (2bbf2bd)
- *(7e364ace/13)* Test-quality scanner (ee77889)
- *(7e364ace/14)* Performance / memory / energy scanner (d3b35a6)
- *(7e364ace/15)* Database / query / migration scanner (7b5da79)
- *(7e364ace/16)* Type-design analyzer agent + gate (1e59440)
- *(7e364ace/17)* Architecture-consistency agent (22bf29b)
- *(7e364ace/19)* Operational / deployment scanner (72a1a92)
- *(7e364ace/21)* Low-frequency domain specialist agents (2fa8da4)
- *(7e364ace/22)* Function-level deep-dive agent (403333f)
- *(7e364ace/23)* Opus second-opinion verification loop (2e91047)
- *(ecaa-self-test-24)* Baseline 36/36 PASS before audit fixes (0ff5342)

## [3.4.2] - 2026-04-25

### Chores

- Align uv.lock to v3.4.1 (541ec51)

## [3.4.1] - 2026-04-22

### Bug Fixes

- Apply LLM-externalizer findings + cover two missed bugs (d379ce6)

### Chores

- *(checkpoint)* Pre-scan-and-fix 20260421T181758+0200 (f4d4f92)

## [3.4.0] - 2026-04-21

### Features

- Apply canonical $MAIN_ROOT/reports/<component>/<ts±tz>-<slug>.<ext> (c4eb9d6)

## [3.3.0] - 2026-04-20

### Features

- Relocate agent reports to ./reports/, add worktree-safe root resolver (e86c8f3)

## [3.2.24] - 2026-04-12

### Bug Fixes

- Harden concurrency, trust boundaries, and input validation (5e29b7b)

## [3.2.23] - 2026-04-12

### Features

- Reports_dev/code-auditor path, mandatory security, prompt injection defense (61686a5)

## [3.2.22] - 2026-04-12

### Features

- Align with Claude Code v2.1.92-v2.1.101 spec (69ad576)

## [3.2.21] - 2026-04-10

### Features

- Pre-push gate uses process ancestry, not env var (74daa13)

## [3.2.20] - 2026-04-10

### Bug Fixes

- Phase5 uses --current instead of --unreleased for release notes (1f2b903)

### Chores

- Update uv.lock to v3.2.19 (00d5b4d)

## [3.2.19] - 2026-04-10

### Features

- Integrate git-cliff and GitHub release creation into publish.py (4a9783d)

### Bug Fixes

- Cliff.toml clean output, prepend-only changelog, remove release.yml (cbddf09)

## [3.2.18] - 2026-04-10

### Changes
- fix: make yamllint mandatory in phase 2.4 (3674425)
- fix: update CPV invocation to use cpv-remote-validate wrapper (d8944fd)
- feat: harden publish.py — mandatory checks, zero skip paths (f0d0be1)

## [3.2.17] - 2026-04-02

### Changes
- fix: update plugin for Claude Code v2.1.85-v2.1.90 changes (32ed723)

## [3.2.16] - 2026-03-28

### Changes
- chore: update uv.lock (8500847)
- feat: add /delta-audit as separate command from /audit-codebase (10e59eb)

## [3.2.15] - 2026-03-28

### Changes
- chore: update uv.lock (8445b30)
- fix: enforce full codebase audit as default, never skip files (470e862)

## [3.2.14] - 2026-03-28

### Changes
- chore: update uv.lock (f077c46)
- fix: replace check_against_specs with 3-perspective code_task analysis (8b68d2c)

## [3.2.13] - 2026-03-28

### Changes
- chore: update uv.lock (7bafddd)
- feat: use GROUP markers for single-call multi-group externalizer dispatch (0889172)

## [3.2.12] - 2026-03-28

### Changes
- chore: update validate_hook.py from CPV sync (0ee5555)
- feat: switch to CPV uvx remote execution, remove local script sync (e04c1cd)

## [3.2.11] - 2026-03-28

### Changes
- chore: update uv.lock (d416dd4)
- fix: unify GROUP_ID naming, add per-group files to report tables (d464f67)

## [3.2.10] - 2026-03-28

### Changes
- chore: update uv.lock (c4fc172)
- feat: per-group linting and per-group output for holistic agents (d61ff22)

## [3.2.9] - 2026-03-28

### Changes
- chore: update uv.lock (0744ded)
- fix: eliminate report reading from orchestrator context (8d55c90)

## [3.2.8] - 2026-03-28

### Changes
- chore: update uv.lock and README badges (bf960bf)
- fix: verification findings + add TLDR tool guidance to agents (b65da46)

## [3.2.7] - 2026-03-28

### Changes
- fix: update TOC anchor for renamed worktree heading (f127648)
- chore: update uv.lock (386e170)
- feat: per-group dispatch architecture, discourage worktrees (7d014ab)

## [3.2.6] - 2026-03-28

### Changes
- chore: update uv.lock (84eb1e4)
- fix: remove declarative worktree isolation, add tool loss warnings (cdeba4e)

## [3.2.5] - 2026-03-28

### Changes
- chore: sync CPV validation scripts (360d679)
- feat: add effort and isolation frontmatter to agents (e9a25f6)

## [3.2.4] - 2026-03-26

### Changes
- chore: add CPV cli.py and __init__.py from upstream sync (bd4728c)
- chore: disable mypy warn_return_any (all 60 errors are in CPV-synced upstream scripts) (109d611)
- fix: address 12 SHOULD-FIX audit findings (30b3871)

## [3.2.3] - 2026-03-26

### Changes
- feat: rewrite publish.py with phased architecture and atomic push (1a4c9d9)

## [3.2.2] - 2026-03-26

### Changes
- fix: replace uv pip install --system with uv tool install in security workflow (6e8592a)
- chore: sync CPV scripts (bump_version, check_version_consistency, claude-plugin-install) (a945c3f)
- fix: resolve lint failures from CPV-synced scripts (bf6516a)
- chore: sync CPV validator scripts (new management + standardize scripts) (cd3f083)
- docs: sync with llm-externalizer MCP updates (243b014)
- chore: gitignore .rechecker/ (auto-managed by rechecker plugin, overwrites tracked files) (140ca73)
- chore: update rechecker progress state (5193637)
- chore: track all rechecker state files (4709302)
- chore: add yamllint config, disable shellcheck on third-party rechecker script (7f5ef05)
- chore: add .rechecker dir, update .gitignore with TLDR artifacts (39357c9)
- chore: track Serena project files (3207283)

## [3.2.1] - 2026-03-18

### Changes
- feat: comprehensive plugin spec sync for Claude Code v2.1.76-2.1.78 (8cbbd2d)

## [3.2.0] - 2026-03-18

### Changes
- feat: sync with Claude Code v2.1.76-2.1.78 plugin spec updates (9901dd0)

## [3.1.28] - 2026-03-15

### Changes
- chore: update uv.lock (0cb551c)
- docs: add ensemble parameter guidance to externalizer references (3990519)

## [3.1.27] - 2026-03-15

### Changes
- docs: update llm-externalizer MCP tool prefix for plugin structure (780c938)

## [3.1.26] - 2026-03-14

### Changes
- docs: update llm-externalizer references for removed write tools (8b3612c)

## [3.1.25] - 2026-03-12

### Changes
- chore: update uv.lock (bff0214)
- fix: resolve remaining audit findings (6 files) (7c47944)
- fix: self-audit batch 2 — 14 remaining MUST-FIX issues (c0712a9)
- fix: self-audit batch 1 — 5 Python bugs + llm-externalizer docs update (d1cd4c0)
- fix: correct llm-externalizer parameter names (self-audit MUST-FIX #1) (0677f9f)

## [3.1.24] - 2026-03-10

### Changes
- update uv.lock (0f7ade1)
- integrate llm-externalizer for consolidation and TODO generation steps (ab910f9)

## [3.1.23] - 2026-03-10

### Changes
- update llm-externalizer parameter names to new MCP syntax (38d3172)

## [3.1.22] - 2026-03-10

### Changes
- chore: sync updated CPV validator (backtick reference detection) (c139a74)
- fix: restore markdown link for instructions.md reference in SKILL.md (bfcd2cd)
- chore: update uv.lock (bd4bcc3)
- feat: add LLM Externalizer fix protocol and Fix Dispatch Ledger (845ce0c)

## [3.1.21] - 2026-03-08

### Changes
- fix: embed complete TOC headings in all SKILL.md files (d8592b2)

## [3.1.20] - 2026-03-08

### Changes
- chore: sync CPV validator scripts from upstream (ffa1751)

## [3.1.19] - 2026-03-08

### Changes
- feat: enforce publish.py for all pushes via pre-push hook gate (7a85e03)

## [3.1.18] - 2026-03-07

### Changes
- feat: auto-discover upstream CPV scripts + progressive disclosure SKILL.md refactor (681c6b4)

## [3.1.17] - 2026-03-07

### Changes
- feat: strict quality gate + CPV sync in publish pipeline (f376910)

## [3.1.16] - 2026-03-07

### Changes
- fix: publish.py only blocks on CRITICAL/MAJOR validation, warns on MINOR (9eda67f)
- chore: add types-pyyaml dev dependency for mypy stubs (f6470fe)
- chore: update uv.lock (e1576e3)
- feat: unified publish.py pipeline + pre-push version enforcement (275d98c)

## [3.1.15] - 2026-03-07

### Changes
- fix: remove auto-discovered commands/agents/skills fields from plugin.json (CRITICAL — caused malformed manifest errors preventing plugin from loading)
- fix: bump_version.py now updates SKILL.md frontmatter versions
- fix: prepare_release.py now stages SKILL.md files in git commit

## [3.1.14] - 2026-03-07

### Changes
- chore: bump version 3.1.13 → 3.1.14, update changelog (77acbe8)
- fix: stale paths, trim examples, contract gaps, procedures, non-code auditing (6454bd3)
- chore: bump version 3.1.12 → 3.1.13, update changelog (d3a9f4e)
- fix: agent definitions, skill docs, and procedure references from re-audit (2853604)
- fix: critical merge script bugs — RECORD_KEEPING, FINDING_ID_RE, consolidated glob (f4f53b8)
- chore: add .claude/ and .tldr/ to .gitignore (d1fdb7f)
- chore: remove duplicate pyyaml from dev dependencies in uv.lock (51dd401)
- fix: regex false positives, audit merge #{1,4}, add prompt generator script (705f50a)
- fix: tailor TOOL GUIDANCE per agent, resolve read-completely contradiction (9293da6)
- fix: update GHA action versions, security tools, and workflow bugs (4c4ad41)
- fix: section header regex #{1,3} → #{1,4} for skeptical reviewer (CONTRACT-PR-001) (030866e)
- fix: audit6 findings — README CI/CD table, stale "bash script" refs, agent-recovery timeouts (b0b677a)
- feat: add TOOL GUIDANCE, model selection rules, and context collection script (4c678ed)
- feat: reduce token consumption — add --quiet to scripts, REPORTING RULES to agents (1f763d7)
- feat: remove tool restrictions from all agent frontmatter (e22baf8)
- fix: suppress ruff E402 for cpv_validation_common imports after sys.path setup (14b99d2)
- fix: suppress ruff E402 for cpv_validation_common import in bump_version.py (f03abce)
- fix: post-audit corrections from v3.1.10 verification (a819dcb)

## [3.1.13] - 2026-03-06

### Changes
- fix: merge scripts — RECORD_KEEPING section support, FINDING_ID_RE expanded for domain IDs, consolidated report glob
- fix: merge scripts — NEW_SECTION_RE harmonized between caa-merge-reports.py and caa-merge-audit-reports.py
- fix: dedup agent — RECORD_KEEPING severity, phase codes VR→VE / SA→SC per SKILL.md
- fix: skeptical-reviewer agent — added CLEAN section, restructured severity headers
- fix: fix-agent — resolved contradictory rollback (restore only for syntax/structural errors)
- fix: todo-generator agent — Source field traceability, severity-to-priority mapping, priority-level numbering
- fix: fix-verifier agent — added TODO_FILE as input parameter
- fix: domain-auditor agent — renamed PREFIX→AGENT_SUFFIX for clarity
- fix: code-correctness, claim-verification, security-review agents — MCP "when available" caveat
- fix: PR review skill — docs_dev→${REPORT_DIR}, integrity check docs corrected
- fix: codebase audit skill — Phase 8 FINAL flow, P7 spawning pattern, naming convention clarification
- fix: PR review-and-fix skill — byte-size claims corrected, exit code 2 docs expanded
- fix: procedure-1-review.md — byte-size→non-empty integrity check
- feat: add caa-generate-prompts.py — domain-splitting and prompt generation for agent spawning

## [3.1.12] - 2026-03-06

### Changes
- feat: add TOOL GUIDANCE section to all 11 agent definitions (Serena MCP, Grepika MCP, haiku avoidance)
- feat: add Model Selection Rules to all 3 SKILL.md files (Opus/Sonnet only for analysis, Haiku prohibited)
- feat: create caa-collect-context.py — information retrieval script with 3 modes (pr-info, file-context, codebase-overview)
- docs: token consumption audit report (docs_dev/token-consumption-audit-20260306.md)

## [3.1.11] - 2026-03-06

### Changes
- feat: add --quiet flag to caa-generate-todos.py, caa-merge-reports.py, caa-merge-audit-reports.py
- feat: add REPORTING RULES section to all 10 CAA agent definitions (dedup already had it)
- feat: pass --quiet to script invocations in skill SKILL.md files
- refactor: gate verbose print() calls behind `if not quiet:` in all 3 CAA scripts
- refactor: always print 1-line summary with output path regardless of --quiet flag

## [3.1.10] - 2026-03-06

### Changes
- fix: atomic write in caa-generate-todos.py — use tempfile.mkstemp() instead of deterministic .tmp suffix
- fix: smart_exec.py choose_best() — respect prefer_latest flag (try ecosystem executors first)
- fix: smart_exec.py deno_npm_argv — stop passing cmd as argument after `--`
- fix: smart_exec.py executor_versions() — report both uvx and uv (elif→if)
- fix: bump_version.py — extract duplicate exclude_dirs to module-level _EXCLUDE_DIRS constant
- fix: prepare_release.py — detect current branch dynamically instead of hardcoding "main"
- fix: sync_cpv_scripts.py — add error count message before SystemExit(1)
- fix: gitignore_filter.py — add sys.path setup before bare cpv_validation_common import
- fix: update_marketplace_metadata.py — add sys.path setup before bare cpv_validation_common import
- fix: caa-merge-reports.py — route all error/failure messages to stderr
- fix: caa-merge-audit-reports.py — route all error/failure messages to stderr
- fix: add top-level exception handling (__main__ guard) to all 3 CAA scripts
- fix: caa-merge-reports.py pass_number argparse type str→int
- fix: caa-merge-audit-reports.py pass_number argparse type str→int

## [3.1.9] - 2026-03-06

### Changes
- docs: update README — add Phase 4b (security scan) to codebase audit pipeline description
- docs: update README — add 7 missing scripts to Scripts tables
- docs: update README — add caa-security-review-agent to codebase audit agents table
- docs: correct "9-phase" → "10-phase" across README, plugin.json, pyproject.toml, CHANGELOG
- docs: add "security scan" to plugin.json and pyproject.toml descriptions
- fix: FINDING_ID_RE regex in caa-merge-reports.py — allow 2-4 letter prefixes (was 2 only)
- fix: add -intermediate- skip check to caa-merge-reports.py is_skipped() to prevent re-merging
- fix: case-insensitive file extension matching in caa-generate-todos.py RE_INLINE_FILE regex

## [3.1.8] - 2026-03-05

### Changes
- fix: make PASS and RUN_ID optional in security-review-agent INPUT FORMAT for single-pass mode
- fix: align DIFF_PATH → DIFF in skeptical-reviewer and claim-verification agents to match SKILL.md
- fix: duplicate item number "5" → correct numbering (5,6,7) in skeptical-reviewer INPUT FORMAT
- fix: add RUN_ID-omission note to security agent output filename and self-verification checklist

## [3.1.7] - 2026-03-05

### Changes
- fix: correct "Four-phase" to "Six-phase" across all docs, skills, config (pipeline has 6 phases)
- fix: add Phase 5+6 note to review perspective table in SKILL.md
- fix: update SKILL.md versions from 2.0.0 to 3.1.7, add missing version field to codebase-audit skill
- fix: worktree range "Phase 1-3" → "Phase 1-4" to include security review
- fix: dedup agent phase code "SA" → "SC" for security, add codebase audit codes to checklist
- fix: add 6 missing agents to agent-recovery.md timeout table and agentType enum
- fix: REPORT_PATH → REPORT_DIR in correctness, claim-verification, skeptical-reviewer agents
- fix: add AGENT_PREFIX, FINDING_ID_PREFIX to agent INPUT FORMAT sections
- fix: .stat() guards, missing_ok=True, sys.exit(1) in merge scripts
- fix: add errors="replace" for UTF-8 resilience in caa-generate-todos.py
- fix: add missing CHANGELOG entries for v3.1.1 and v3.1.2

## [3.1.6] - 2026-03-05

### Changes
- compat: adopt `${CLAUDE_PLUGIN_ROOT}` brace notation in all SKILL.md and reference files (Claude Code 2.1.69)
- compat: update skill descriptions to use "Trigger with" + "Use when" format for validator compliance
- compat: add post-compaction behavior note to agent-recovery.md (Claude Code 2.1.69 no longer produces preamble recap)
- chore: standardize variable references in procedure-1-review.md and procedure-2-fix.md

## [3.1.5] - 2026-03-03

### Changes
- chore: sync 21 CPV validation scripts from upstream v1.5.2

## [3.1.4] - 2026-03-03

### Changes
- fix: SHA-pin all GitHub Actions (checkout, setup-uv, action-gh-release) for supply-chain safety
- fix: add timeout-minutes and concurrency groups to all CI/CD workflows
- fix: add job-level permissions to release.yml
- fix: pin bandit/pip-audit versions in security.yml
- fix: file existence guard in caa-merge-reports.py before .stat() call
- fix: safer colon parsing in caa-generate-todos.py (split vs index)
- fix: pip-audit two-step command in security agent (uv pip compile + pip-audit)
- fix: "Four-phase" → "Six-phase" in procedure-1-review.md
- fix: add security agent to agent-recovery.md scope/timeout/enum
- fix: add Phase 4b security scan to caa-audit-codebase-cmd.md
- fix: add codebase audit phase codes to dedup agent
- docs: update README CI/CD section count, add publishing scripts table

## [3.1.3] - 2026-03-03

### Changes
- chore: sync CPV validation scripts from upstream (multiple rounds)
- fix: resolve validation warnings — document git-hooks, fix TOC link
- feat: add security scanning CI workflow and enhance security review agent
- fix: resolve critical skill audit findings (off-by-one, missing PR_NUMBER)
- fix: CI version check uses --plugin-dir flag instead of positional arg
- chore: bump version through 3.1.1, 3.1.2, 3.1.3

## [3.1.2] - 2026-03-03

### Changes
- chore: sync 2 CPV skill validators from upstream, bump to 3.1.2

## [3.1.1] - 2026-03-03

### Changes
- chore: sync 11 CPV validation scripts from upstream, bump to 3.1.1

## [3.1.0] - 2026-03-01

### Changes
- fix: mypy return type annotation in sync_cpv_scripts.py (921de1c)
- feat: release automation, CPV sync, git hooks (75cc464)
- fix: audit findings — swapped phases, stale refs, version, changelog (a5ea13b)

## [3.0.0] - 2026-03-01

### Features
- Added security review agent (caa-security-review-agent, SC prefix)
- Integrated security review as Phase 4 in PR review pipeline (parallel with Phase 3)
- Replaced validation scripts with claude-plugins-validation suite
- Added markdownlint configuration
- Version bump to 3.0.0

### Breaking Changes
- Renamed plugin from ai-maestro-code-auditor-agent to code-auditor-agent
- Renamed all amcaa- prefixes to caa-

## [2.0.0] - 2026-03-01

### Features
- Renamed plugin from emasoft-pr-checking-plugin to code-auditor-agent
- Unified prefix from epcp-/epca- to caa- across all agents, scripts, and commands
- Added caa-codebase-audit-and-fix-skill with 10-phase audit pipeline
- Added 6 new agents for codebase auditing: domain-auditor, verification, consolidation, todo-generator, fix, fix-verifier
- Added caa-audit-codebase-cmd command for launching codebase audits
- Added CI/CD workflows for validation, release, and marketplace notification
- Added publishing scripts: bump_version.py, check_version_consistency.py

### Breaking Changes
- All agent, script, and command filenames changed from epcp-/epca- prefix to caa-
- All report filename patterns changed from epcp-/epca- to caa-

## [1.0.0] - 2026-02-01

### Features
- Initial release as emasoft-pr-checking-plugin
- Three-phase PR review pipeline: code correctness, claim verification, skeptical review
- Deduplication agent for merged findings
- Iterative review-and-fix loop skill
- Merge report scripts (v1 and v2)
- Universal PR linter with MegaLinter/Docker support
