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

#### 3.1.a caa-scenario-generator-skill — **domain-agnostic by design**

**Role:** Auto-discover scenarios from ANY codebase. The codebase can be
a web service, a CLI tool, a firmware image for an MCU, a Linux kernel
module, an FPGA Verilog design, an iOS app, a browser extension, a
Terraform module, a database engine, a compiler, a game — anything for
any platform. The skill has no built-in assumption about software type;
type is detected first, then a per-type discoverer is dispatched.

The skill has three deterministic stages: **detect → discover → emit**.

**Stage 1 — Detect software type(s).** Reads build files and key
fingerprints to classify the codebase into one or more of ~40 software
types. A single codebase can be multiple types simultaneously (e.g. a
monorepo with a web backend + mobile app + shared library). See §3.1.c
for the full detection registry.

**Stage 2 — Discover entry points.** For each detected type, dispatch
to its dedicated discoverer. Each discoverer is a small Python module
that knows how to find that type's entry points (HTTP route registrations
for web services; argparse/click/cobra invocations for CLIs; ISR vector
tables and `attach_interrupt(...)` calls for firmware; `module_init`
macros and `file_operations` structs for Linux kernel modules; top-level
`module` declarations and constraint-file pin maps for FPGA designs;
syscall tables for kernels; `chrome.runtime.onMessage.addListener` for
browser extensions; etc.). See §3.1.e for the discoverer registry.

**Stage 3 — Emit scenarios.** For every discovered entry point, look up
which scenario families apply (per §3.1.d table) and emit one scenario
per (entry-point × applicable-family) pair. The output schema is
**universal** — same shape whether the entry point is an HTTP route,
an ISR vector, a syscall, or a hardware register. See §3.1.b for the
schema.

**How it discovers** (no LLM at any step):

1. **Type detection.** Walk the repo root + 2 levels deep looking for
   build-file fingerprints (Cargo.toml, package.json, pyproject.toml,
   CMakeLists.txt, platformio.ini, west.yml, Kbuild/Kconfig, *.xcodeproj,
   AndroidManifest.xml,*.uproject, manifest.json, Dockerfile, *.tf,
   etc.). Secondary signals (linker scripts, ISR vector files,
   module_init macros, `_start` symbols) disambiguate.
2. **Per-type discoverer dispatch.** Run the matching discoverer(s)
   from `scripts/scenario_generator/discoverers/`.
3. **Surface enrichment.** Cross-reference each discovered entry point
   with docs and specs to capture intended behaviour:
   - For web: OpenAPI specs, README API tables, doc comments.
   - For CLI: `--help` text, man pages, README usage sections.
   - For firmware: datasheets/AN docs in repo, header comments
     describing register behaviour.
   - For kernel modules: `Documentation/`, `MAINTAINERS`,
     `man-pages` references in code comments.
   - For FPGA: timing constraints, port descriptions in module headers.
   - Fallback for any type: nearby comments + README headings.
4. **Family expansion.** For each entry point, look up applicable
   scenario families (§3.1.d) and emit one normalized scenario per
   (entry × family) pair.
5. **Write outputs.** Emit `scenarios.json` (machine) and
   `scenarios.md` (human) to
   `<main-repo>/reports/caa-scenario-generator/<ts>-...`.

**Inputs:**
- Codebase path (whole-codebase mode) or PR diff (delta mode — discover
  scenarios for changed surfaces only)
- Auto-detected language(s) and type(s)

**Output:** One `scenarios.json` per run; one human-readable
`scenarios.md` for traceability; one `detected-types.json` recording
which types were detected and why (debug aid).

**This is a SKILL, not an agent** — runs in the main turn, uses Bash +
Read + Grep + (optional) Serena/Grepika MCP. No `Edit` / `Write` to source.
**Deterministic.** Two runs on the same codebase MUST produce
byte-identical `scenarios.json` and `detected-types.json`. The fixture
tests in §6 lock this.

**Fallback for unknown software.** If no specific type matches (very
obscure framework, custom build system, research code), the discoverer
falls back to "unknown-software mode": find `main()` / module-level
side effects / exported public symbols / top-level test files, and
emit generic scenarios using the universal scenario families
(happy_path + adversarial_input + partial_failure + concurrent_state +
resource_limits). Better than nothing; worse than per-type. The user
gets a clear note in `detected-types.json` saying which type wasn't
recognized and how to extend the registry.

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

**Model:** opus, effort: high.
**Turn budget:** uncapped — see §3.3 below. The other existing CAA agents
use 20–30 turn caps because they are bounded line-level audits; this
agent recursively walks a call graph of unknown depth across an
arbitrary number of scenarios, and an artificial cap could truncate the
walk mid-scenario and silently miss findings. The user must be sure
"no finding" means "the agent reached the end of every scenario", not
"the agent ran out of turns at scenario 42 of 200".
**Disallowed tools:** Edit, NotebookEdit, Write to source code paths.

#### 3.1.c Software-type detection registry

The skill ships a built-in registry. Each row is one software type; the
"Fingerprint" column is the primary signal (a file that exists or a
unique pattern in a build file), "Disambiguator" handles the cases where
the primary signal is ambiguous. Multiple types may apply to one repo.

| Type | Primary fingerprint | Disambiguator |
|---|---|---|
| web_service_python | `pyproject.toml`/`requirements.txt` lists `fastapi`/`flask`/`django`/`starlette`/`sanic`/`aiohttp`/`bottle` | n/a |
| web_service_node | `package.json` deps include `express`/`koa`/`fastify`/`hapi`/`@nestjs/*`/`next`/`hono`/`elysia` | n/a |
| web_service_go | `go.mod` requires `gin`/`echo`/`chi`/`fiber`/`gorilla/mux`; or `net/http` + `http.HandleFunc` patterns | n/a |
| web_service_rust | `Cargo.toml` deps include `actix-web`/`axum`/`rocket`/`warp`/`hyper`/`poem`/`salvo` | n/a |
| web_service_ruby | `Gemfile` lists `rails`/`sinatra`/`hanami`/`roda` | n/a |
| web_service_php | `composer.json` lists `symfony/*`/`laravel/*`/`slim/slim` | n/a |
| web_service_java_kotlin | `pom.xml`/`build.gradle(.kts)` lists `spring-boot-starter-web`/`spring-webflux`/`micronaut-http`/`quarkus`/`jersey`/`vertx-web` | n/a |
| web_service_dotnet | `*.csproj` references `Microsoft.AspNetCore.*` | n/a |
| cli_python | `[project.scripts]` in `pyproject.toml` OR `entry_points={"console_scripts": ...}` in `setup.py` | not also a web framework |
| cli_node | `package.json` has `bin:` field | not also a web framework |
| cli_rust | `Cargo.toml` `[[bin]]` section | not also `[lib]` only |
| cli_go | Go file with `func main()` + uses `flag`/`spf13/cobra`/`urfave/cli` | not in a web context |
| cli_csharp | `*.csproj` with `<OutputType>Exe</OutputType>` and no AspNetCore | n/a |
| library_python | `pyproject.toml` lacks `[project.scripts]` AND lacks web framework | `__init__.py` with `__all__` |
| library_node | `package.json` with `main:`/`exports:` and no `bin:` | n/a |
| library_rust | `Cargo.toml` `[lib]` only, no `[[bin]]` | n/a |
| mobile_android | `AndroidManifest.xml` present | `build.gradle` with `applicationId` (app) vs `library` plugin (Android lib) |
| mobile_ios | `*.xcodeproj` or `*.xcworkspace` + `Info.plist` | `@UIApplicationMain`/`@main` AppDelegate vs SwiftPM library |
| mobile_flutter | `pubspec.yaml` with `flutter:` key | n/a |
| mobile_reactnative | `package.json` lists `react-native` + `app.json` exists | n/a |
| mobile_kotlin_multiplatform | `build.gradle.kts` applies `kotlin-multiplatform` plugin | n/a |
| firmware_arduino | `*.ino` file OR `arduino-cli.yaml`/`platformio.ini` with arduino framework | `setup()` + `loop()` |
| firmware_platformio | `platformio.ini` | per-board section |
| firmware_zephyr | `west.yml` + `prj.conf` | `SYS_INIT` macros |
| firmware_espidf | `sdkconfig` + `idf_component.yml` | `app_main()` |
| firmware_stm32 | `STM32*.ld` linker script + `system_stm32*.c` + `*_hal_*.c` | NVIC / HAL macros |
| firmware_nordic_sdk | `Kconfig.zephyr` lacking but `nrf*` SDK headers present | n/a |
| firmware_baremetal | Linker script with hardcoded section addresses + `startup_*.s` + no kernel patterns | `_start` / `Reset_Handler` |
| rtos_freertos | `FreeRTOSConfig.h` present OR `<freertos/*>` includes | `xTaskCreate`, `vTaskStartScheduler` |
| rtos_zephyr | (covered by firmware_zephyr; many Zephyr apps ARE RTOS apps) | n/a |
| rtos_threadx | `<tx_api.h>` includes | `tx_thread_create` |
| rtos_chibios | `<ch.h>` or `chconf.h` | n/a |
| linux_kernel_module | `Kbuild`/`Makefile` with `obj-m :=` + `MODULE_LICENSE` macro + `<linux/module.h>` | `module_init`, `module_exit` |
| linux_kernel_tree | `MAINTAINERS` + `Kconfig` at root + `arch/<arch>/` + `kernel/` + `Documentation/` | n/a |
| windows_kernel_driver | `*.inf`/`*.inx` + `WdfDriverEntry`/`DriverEntry` | KMDF/WDM macros |
| bsd_kernel | `sys/kern/` + `sys/dev/` | `MOD_LOAD`, `DEVMETHOD` |
| macos_kernel_ext | `*.kext`/`Info.plist` + `IOService` includes | n/a |
| os_baremetal | Linker script + boot sector + no kernel module patterns + missing pthread/syscall | hand-rolled scheduler in source |
| fpga_verilog | `*.v`/`*.sv` + `*.xdc`/`*.lpf`/`*.sdc` constraint files | `module <top> (...)` top-level |
| fpga_vhdl | `*.vhd`/`*.vhdl` + constraint files | `entity <top> is` |
| asic_design | (similar to FPGA but with SDC + DEF/LEF + ATPG configs) | n/a |
| driver_linux_userspace | libusb/hidapi/spidev consumer + udev rules | n/a |
| browser_ext_chrome | `manifest.json` with `manifest_version: 3` + `background:`/`content_scripts:` | `chrome.runtime.*` calls |
| browser_ext_firefox | `manifest.json` with `browser_specific_settings.gecko` | `browser.runtime.*` |
| browser_ext_safari | `*.safariextz`/Safari App Ext Xcode project | n/a |
| game_unity | `Assets/` + `ProjectSettings/` + `*.unityproj`/`*.csproj` for Unity | `MonoBehaviour` subclasses |
| game_unreal | `*.uproject` + `Source/` | `AActor` / `UCLASS` macros |
| game_godot | `project.godot` + `*.tscn`/`*.gd`/`*.cs` | n/a |
| compiler_parser | grammar files (`*.lex`/`*.y`/`*.tree-sitter`/`*.pest`/`*.g4`) | `parse_*` / `tokenize_*` functions |
| iac_terraform | `*.tf` + `terraform.tfvars` | `resource "..." "..."` blocks |
| iac_pulumi | `Pulumi.yaml` + `Pulumi.<stack>.yaml` | n/a |
| iac_helm | `Chart.yaml` + `templates/` | n/a |
| iac_ansible | `playbook.yml` + `roles/`+`tasks/`+`vars/` | `- hosts:` keys |
| iac_cloudformation | `*.template` JSON/YAML with `AWSTemplateFormatVersion` | n/a |
| iac_kustomize | `kustomization.yaml` | n/a |
| iac_docker_compose | `docker-compose.yml`/`compose.yaml` | n/a |
| iac_k8s_operator | `kubebuilder.yaml` + `controllers/` | `Reconcile()` method |
| data_pipeline_airflow | `dags/` + `airflow.cfg` | `DAG(...)` constructors |
| data_pipeline_dbt | `dbt_project.yml` + `models/` | `{{ ref(...) }}` |
| data_pipeline_prefect | `prefect.yaml` + `@flow` decorators | n/a |
| data_pipeline_dagster | `dagster.yaml` + `@asset` decorators | n/a |
| ml_training | deps include `torch`/`tensorflow`/`jax`/`transformers`/`scikit-learn`/`lightning` + training loops | `nn.Module`, `train_step` |
| crypto_library | deps include `aes`/`rsa`/`ed25519`/`hkdf`/`x25519` + side-channel-aware helpers | constant-time comparison helpers |
| network_protocol_impl | source implements wire-level parser/encoder (HTTP/QUIC/TLS/DNS/MQTT/CoAP/Modbus/CAN) at packet level | magic numbers, packet header structs |
| database_engine | source implements WAL, B-tree/LSM, page cache, MVCC | `wal_append`, `page_alloc`, `commit_record` |
| distributed_system | source implements Raft/Paxos/CRDT/gossip | `appendEntries`, `requestVote`, `proposeValue` |
| game_engine | non-game-specific rendering/physics/asset-loading library | shader compile, scene graph |
| desktop_qt | `*.pro`/`CMakeLists.txt` with `find_package(Qt6)` | `QApplication`, `QMainWindow` |
| desktop_gtk | dep on `gtk4`/`gtk3` | `gtk_init`, `gtk_application_new` |
| desktop_electron | `package.json` lists `electron` | `BrowserWindow`, `app.on('ready')` |
| desktop_tauri | `tauri.conf.json` + `src-tauri/` | `#[tauri::command]` |
| desktop_flutter | `pubspec.yaml` with `flutter:` + desktop target enabled | n/a |
| webgl_three | `package.json` lists `three`/`@react-three/fiber` | `Scene`, `WebGLRenderer` |
| websocket_server | source uses `ws`/`socket.io`/`gorilla/websocket`/`tokio-tungstenite` | `onmessage` handlers |
| message_queue_consumer | `kafka`/`rabbitmq`/`redis`/`sqs`/`nats` client lib | `consume(...)`, subscription registration |
| unknown_software | none of the above match | fallback discoverer (see §3.1.a) |

Each row is also enumerated in `references/01-software-type-detection.md`
inside the skill, with a concrete example fingerprint for each.

The skill MUST be designed so new types can be added without modifying
existing discoverers — each discoverer lives in its own
`scripts/scenario_generator/discoverers/<type>.py` file, registered by
filename. Adding a new type = adding a file. This keeps the type
registry open-ended for future contributions (FPGA partial reconfig,
quantum hardware controllers, RISC-V vector extensions, anything we
haven't thought of yet).

#### 3.1.d Universal scenario schema

The output of the skill is one `scenarios.json` file with this schema,
**identical regardless of detected software type**:

```json
{
  "$schema": "scenarios.v1.json",
  "generated_at": "2026-05-10T22:30:00+0200",
  "codebase": {
    "root": "/path/to/repo",
    "detected_types": [
      {"type": "linux_kernel_module", "confidence": 0.95,
       "evidence": ["Kbuild has obj-m += myhw.o",
                    "MODULE_LICENSE in src/myhw_main.c:12"]}
    ],
    "detected_languages": ["c"]
  },
  "scenarios": [
    {
      "id": "SCEN-0042",
      "type_origin": "linux_kernel_module",
      "family": "userspace_pointer_validation",
      "title": "ioctl receives bad userspace pointer",
      "entry_point": {
        "kind": "syscall_handler",
        "file": "drivers/myhw/myhw_ioctl.c",
        "line": 42,
        "symbol": "myhw_ioctl",
        "metadata": {"cmd": "MYHW_GET_STATUS"}
      },
      "actor_role": "userspace_attacker",
      "stimulus": {
        "kind": "syscall_with_bad_pointer",
        "value": {"arg_pointer": "0xDEADBEEF", "size": 1024}
      },
      "intended_behaviour": "copy_to_user MUST check the pointer; if bad, return -EFAULT without leaking kernel state.",
      "intended_behaviour_source": [
        "Documentation/security/self-protection.rst",
        "man-page: ioctl(2)"
      ],
      "expected_path_summary": ["access_ok()", "copy_to_user()", "<EFAULT return>"],
      "invariants_to_check": [
        "access_ok_called_before_copy",
        "no_kernel_data_leaked_on_failure"
      ],
      "failure_modes_to_test": [
        "missing_access_ok",
        "TOCTOU_between_access_ok_and_copy"
      ],
      "feedback_expected": null
    }
  ]
}
```

Key universal fields:

- **`entry_point.kind`** — one of: `http_route`, `cli_command`,
  `library_export`, `ipc_handler`, `isr_vector`, `gpio_interrupt`,
  `syscall_handler`, `ioctl_handler`, `module_init`, `module_exit`,
  `rtos_task`, `rtos_isr`, `event_listener`, `webhook`, `cron_job`,
  `mq_consumer`, `ws_message_handler`, `ui_route`, `ui_event_handler`,
  `os_lifecycle_event`, `permission_request`, `boot_path`, `reset_path`,
  `power_event`, `dma_transfer`, `hw_register_write`, `hw_register_read`,
  `protocol_packet_handler`, `parser_input`, `db_query_handler`,
  `migration_apply`, `migration_rollback`, `terraform_resource`,
  `helm_template`, `dag_task`, `controller_reconcile`, `main_function`,
  `unknown_entry`.
- **`actor_role`** — one of: `anonymous_client`, `authenticated_user`,
  `admin`, `attacker_external`, `attacker_internal`,
  `attacker_compromised_session`, `peer_service`, `userspace_caller`,
  `userspace_attacker`, `hardware_interrupt`, `hardware_dma_engine`,
  `os_scheduler`, `os_signal`, `power_event_source`,
  `network_peer_malicious`, `network_peer_benign`, `bootloader`,
  `watchdog`, `brownout_detector`, `test_runner`, `ci_system`,
  `developer_local`, `unknown_actor`.
- **`stimulus.kind`** — type-specific but the SHAPE is universal:
  `{kind, value}` where `value` is JSON. The walker reads `kind` to
  understand what role-aware reasoning to apply.
- **`failure_modes_to_test`** — opaque to the schema; the walker
  interprets them against the scenario family's playbook.

The walker is type-blind. Type knowledge lived in the skill at scenario
generation time, then was crystallized into the universal schema. The
walker just executes scenarios per the schema.

#### 3.1.e Scenario family registry (applies-to map)

The skill ships a built-in registry of scenario families. Each family
declares the set of software types it applies to. The expansion step in
§3.1.a stage 3 reads this registry to know which families to instantiate
per entry point. Families and their applicability:

| Family | Applies to types |
|---|---|
| happy_path | ALL types |
| adversarial_input | web_*, cli_*, library_*, firmware_*, driver_*, kernel_*, compiler_parser, network_protocol_impl, database_engine, browser_ext_*, ml_training, data_pipeline_* |
| partial_failure | ALL types that perform I/O (i.e. most) — explicit exclusion list: fpga_*, asic_design, crypto_library (pure-compute subset) |
| concurrent_state | web_*, kernel_*, driver_*, firmware_* (multi-task), rtos_*, distributed_system, database_engine, ml_training, message_queue_consumer, websocket_server, game_*, desktop_*, mobile_* (background work) |
| auth_state_transition | web_*, mobile_*, browser_ext_*, kernel_* (capability/cred subsystems), desktop_* (login flows), iac_k8s_operator (RBAC) |
| resource_limits | ALL types |
| interrupt_atomicity | firmware_*, rtos_*, kernel_*, driver_*, os_baremetal |
| userspace_pointer_validation | kernel_*, driver_linux_*, windows_kernel_driver, bsd_kernel, macos_kernel_ext |
| dma_race | firmware_*, driver_*, rtos_*, kernel_* (with DMA-capable peripherals) |
| boot_path | firmware_*, os_baremetal, kernel_*, rtos_* |
| suspend_resume | firmware_*, mobile_*, driver_*, kernel_*, desktop_* |
| hardware_failure | firmware_*, driver_*, rtos_*, kernel_*, fpga_* |
| protocol_replay | web_*, network_protocol_impl, firmware_* (with comms), crypto_library, browser_ext_*, ws_*, mq_consumer |
| downgrade_attack | crypto_library, network_protocol_impl, web_* (TLS termination), browser_ext_*, mobile_* (cert pinning) |
| persistence_corruption | ALL that write state — explicit list per-type in references |
| ipc_message_malformed | os_*, browser_ext_*, mobile_*, distributed_system, desktop_* (IPC), kernel_* (netlink/dbus) |
| upgrade_migration | ALL types with versioned state |
| user_input_event | mobile_*, desktop_*, game_*, browser_ext_*, webgl_three |
| scheduler_starvation | rtos_*, os_*, kernel_*, distributed_system, data_pipeline_* |
| backpressure | data_pipeline_*, web_*, distributed_system, network_protocol_impl, ws_server, mq_consumer |
| clock_skew | distributed_system, crypto_library, mobile_*, web_* (token expiry), network_protocol_impl |
| sandbox_escape | browser_ext_*, mobile_* (permissions), os_*, desktop_electron, desktop_tauri |
| dependency_compromise | ALL types — supply-chain risk is universal |
| signal_integrity | fpga_*, asic_design, firmware_* (high-speed interfaces) |
| timing_constraint_violation | fpga_*, asic_design, rtos_* (deadlines), firmware_* (real-time) |
| watchdog_misuse | firmware_*, rtos_*, kernel_* (kernel watchdog), os_baremetal |
| power_glitch | firmware_*, os_baremetal, crypto_library (fault injection resistance) |
| side_channel | crypto_library, firmware_*(running crypto), kernel_* (crypto subsystem) |
| concurrency_in_parser | compiler_parser, network_protocol_impl, web_* (request parsing) |
| memory_safety_uaf | ALL C/C++/unsafe-Rust types — firmware, kernel, driver, game_engine, desktop_qt/gtk, network_protocol_impl |
| memory_safety_bounds | same set as memory_safety_uaf |
| integer_overflow_in_size_calc | ALL types that do size arithmetic — kernel, driver, firmware, parser, network_protocol_impl, database_engine, crypto_library |
| privilege_escalation | kernel_*, driver_*, browser_ext_*(extension permissions), desktop_* (suid/elevated tasks), mobile_* (intent hijack) |
| race_in_setuid_or_setgid | kernel_*, os_baremetal, cli_* with setuid binaries |

The registry lives in `scripts/scenario_generator/scenario_families.py`
as a single dict: `FAMILY_TO_TYPES: dict[str, set[str]]`. Adding a new
family or a new applies-to relationship is a one-line change. The skill's
behaviour is fully driven by this registry — there is no per-family
hardcoded logic in the discoverers.

The set of `failure_modes_to_test` per family is a separate registry
(`FAMILY_TO_FAILURE_MODES`) — also a dict — that the walker reads to
know what divergence patterns to look for. This keeps the walker
type-blind while letting families inject family-specific test
expectations.

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

**Model:** opus, effort: high.
**Turn budget:** uncapped — see §3.3 below. Same reasoning as the
walker: enumerating + adversarially-challenging every implicit
assumption in a non-trivial file is unbounded; an artificial cap could
truncate the audit mid-file. The agent must finish or fail loud — never
silently stop.
**Disallowed tools:** Edit, NotebookEdit, Write to source code paths.

### 3.3 Turn-budget policy (per user directive)

Per the user directive received during TRDD review, expanded in a
follow-up: **no CAA agent — old or new — carries a `maxTurns` cap.**
The policy is uniform across the entire plugin.

Original directive: the two NEW agents must not carry a cap, because
their workload (walking a call graph across N scenarios; auditing
every implicit assumption per file) is fundamentally unbounded.

Follow-up directive: **remove the cap from ALL agents.** The reasoning
generalises — every CAA agent walks a workload whose size is
determined by the codebase or report under review, not by the agent's
own state machine. The previous 20–30 caps were heuristics tuned for
"typical" cases, but the failure mode they produce on atypical cases
is silent truncation, which is the worst possible failure mode for an
audit pipeline (the user is told "no findings" when the agent simply
ran out of turns mid-audit).

**Implementation choice for ALL agent frontmatters:**

We OMIT the `maxTurns:` key entirely from every agent definition file
(11 existing + 2 new). The behavior of an omitted `maxTurns` in Claude
Code agent frontmatter is "use the platform default", understood to
be effectively very large and the designed escape hatch for
long-running agents. If empirical testing during Phase 2 shows that
omission triggers a low default, every agent file will switch to
explicit `maxTurns: 999` (effectively unlimited for any plausible walk
depth) in a single sweep. Either way: NO small cap. See §11 Q8 — the
fallback policy is "explicit very-high integer everywhere" if omission
turns out to default to a small number.

The pre-revision asymmetry (20–30 for existing agents, uncapped for
new agents) has been eliminated. All CAA agents now share the same
policy: they audit a workload whose size is determined by the codebase
or report, not by the agent's own state machine, and must run to
completion or fail loud on a per-agent orchestrator timeout.

**Operational consequences:**

- The walker swarm and assumption-auditor swarm may run for many minutes
  per agent on a large codebase. The orchestrator-side budget control is
  the `≤ 15 concurrent` swarm cap and per-agent timeout (configurable
  via plugin `userConfig`, default 30 min), NOT turn count.
- If a single agent genuinely hangs (e.g. tool-call loop), the
  orchestrator detects it via the per-agent timeout — not via maxTurns.
- Phase 2/3 acceptance tests MUST include a fixture large enough that
  the agents would have exceeded a 30- or 50-turn cap, to prove the
  uncapped policy holds end-to-end.

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
   deterministic scenario discovery skill (§3.1.a). References:
   `01-software-type-detection.md` (full §3.1.c registry with concrete
   fingerprint examples per row), `02-scenario-schema.md` (full §3.1.d
   schema with examples per `entry_point.kind`), `03-discoverers.md`
   (catalog of all discoverers under `scripts/scenario_generator/discoverers/`
   with one-line descriptions), `04-scenario-families.md` (full §3.1.e
   applies-to map + per-family failure-mode list).
4. `scripts/scenario_generator/` — Python engine for the skill. Layout:
   - `detect_software_type.py` — implements §3.1.c registry. Walks the
     repo, matches fingerprints, returns `[{type, confidence, evidence}]`.
   - `scenario_families.py` — implements §3.1.e registry as two dicts:
     `FAMILY_TO_TYPES` (which types each family applies to) and
     `FAMILY_TO_FAILURE_MODES` (what divergence patterns to test per
     family). Both are pure data.
   - `emit_scenarios_json.py` — composes type + entry points + families
     into the universal `scenarios.json` (§3.1.d).
   - `emit_scenarios_md.py` — companion human-readable index.
   - `discoverers/` — one Python module per software type:
     `web_python_fastapi.py`, `web_python_flask.py`, `web_python_django.py`,
     `web_node_express.py`, `web_node_nextjs.py`, `web_node_koa.py`,
     `web_go_stdlib.py`, `web_go_gin.py`, `web_rust_axum.py`,
     `web_rust_actix.py`, `web_ruby_rails.py`, `web_php_laravel.py`,
     `web_java_spring.py`, `web_dotnet_aspnet.py`,
     `cli_python_argparse.py`, `cli_python_click.py`, `cli_node_yargs.py`,
     `cli_node_commander.py`, `cli_rust_clap.py`, `cli_go_cobra.py`,
     `library_python.py`, `library_node.py`, `library_rust.py`,
     `library_c.py`,
     `mobile_android.py`, `mobile_ios.py`, `mobile_flutter.py`,
     `mobile_reactnative.py`, `mobile_kmp.py`,
     `firmware_arduino.py`, `firmware_platformio.py`,
     `firmware_zephyr.py`, `firmware_espidf.py`, `firmware_stm32.py`,
     `firmware_nordic.py`, `firmware_baremetal.py`,
     `rtos_freertos.py`, `rtos_threadx.py`, `rtos_chibios.py`,
     `kernel_linux_module.py`, `kernel_linux_tree.py`,
     `kernel_windows_driver.py`, `kernel_bsd.py`, `kernel_macos_ext.py`,
     `os_baremetal.py`,
     `fpga_verilog.py`, `fpga_vhdl.py`, `asic_design.py`,
     `compiler_parser.py`, `network_protocol_impl.py`,
     `database_engine.py`, `distributed_system.py`,
     `crypto_library.py`, `game_engine.py`,
     `iac_terraform.py`, `iac_pulumi.py`, `iac_helm.py`,
     `iac_ansible.py`, `iac_cloudformation.py`, `iac_kustomize.py`,
     `iac_docker_compose.py`, `iac_k8s_operator.py`,
     `data_pipeline_airflow.py`, `data_pipeline_dbt.py`,
     `data_pipeline_prefect.py`, `data_pipeline_dagster.py`,
     `ml_training.py`,
     `browser_ext_chrome.py`, `browser_ext_firefox.py`,
     `browser_ext_safari.py`,
     `game_unity.py`, `game_unreal.py`, `game_godot.py`,
     `desktop_qt.py`, `desktop_gtk.py`, `desktop_electron.py`,
     `desktop_tauri.py`, `desktop_flutter.py`,
     `webgl_three.py`, `websocket_server.py`,
     `message_queue_consumer.py`,
     `unknown_software.py` (fallback — main(), exported symbols).

   Each discoverer file exports a single function:
   `discover(repo_root: Path, detected_languages: list[str]) -> list[EntryPoint]`.
   The shape of `EntryPoint` is defined in `scripts/scenario_generator/types.py`.
   The skill loads discoverers by introspecting the directory — adding a
   new discoverer is just adding a new file.

   For v1 NOT all ~70 discoverers ship in Phase 1 — see §10 for the
   minimal viable set. The unimplemented ones fall back to
   `unknown_software.py` until added.
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
12. `agents/caa-claim-verification-agent.md` — `maxTurns:` line removed.
13. `agents/caa-code-correctness-agent.md` — `maxTurns:` line removed.
14. `agents/caa-consolidation-agent.md` — `maxTurns:` line removed.
15. `agents/caa-dedup-agent.md` — `maxTurns:` line removed.
16. `agents/caa-domain-auditor-agent.md` — `maxTurns:` line removed.
17. `agents/caa-fix-agent.md` — `maxTurns:` line removed.
18. `agents/caa-fix-verifier-agent.md` — `maxTurns:` line removed.
19. `agents/caa-security-review-agent.md` — `maxTurns:` line removed.
20. `agents/caa-skeptical-reviewer-agent.md` — `maxTurns:` line removed.
21. `agents/caa-todo-generator-agent.md` — `maxTurns:` line removed.
22. `agents/caa-verification-agent.md` — `maxTurns:` line removed.

Items 12–22 are the uniform-policy sweep covered in §3.3. They land in
their own commit (separate from the spec phases) because they are a
no-design-change cleanup applicable today, independent of when the
new agents ship.

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

Phase 1 — the skill foundation (single PR):
- `caa-scenario-generator-skill` directory with SKILL.md + 4 references
- `scripts/scenario_generator/detect_software_type.py` — full registry
  of ~70 type fingerprints (§3.1.c). MUST be implemented in full because
  later phases extend it incrementally; the registry is the table that
  unblocks everything else.
- `scripts/scenario_generator/scenario_families.py` — full registry of
  scenario families with applies-to map (§3.1.e). Also implemented in
  full — pure data, low cost.
- `scripts/scenario_generator/emit_scenarios_json.py` + the universal
  schema (§3.1.d).
- `scripts/scenario_generator/types.py` — `EntryPoint` dataclass +
  enums.
- `scripts/scenario_generator/discoverers/unknown_software.py` —
  fallback discoverer (always shipped first, used when no specific
  discoverer matches).
- **Minimal viable discoverer set for Phase 1** (the 10 most common
  software types, ordered by likely real-world frequency):
  `web_python_fastapi.py`, `web_node_express.py`, `web_node_nextjs.py`,
  `cli_python_click.py`, `cli_node_yargs.py`, `library_python.py`,
  `firmware_arduino.py`, `firmware_platformio.py`,
  `kernel_linux_module.py`, `fpga_verilog.py`. Plus the fallback.
- Golden-file fixture tests: one fixture per Phase-1 discoverer + one
  fixture for the fallback. Each fixture has `expected-scenarios.json`
  - `expected-detected-types.json` golden files. The skill must produce
  byte-identical output. **NO agent yet** — Phase 1 is just deterministic
  discovery, easy to test, easy to land.

Phase 1.5 — discoverer expansion (separate PRs, can land in parallel):
each remaining discoverer ships in its own PR with its own fixture +
golden files. Adding a discoverer is a self-contained change (file ×
fixture × golden), so 5 contributors can ship 5 discoverers in parallel
without merge conflicts. Target: cover the top 30 types in v1.0; the
remaining ~40 types land via community PRs (or as needed) and use the
fallback in the interim.

Phase 2 (single PR): `caa-scenario-walker-agent` definition + walker
tests (consumes Phase 1's golden `scenarios.json`, asserts findings on
incidents #1, #2, #5). The agent is type-blind, so Phase 2 is
independent of which discoverers are in or out — the agent processes
any scenarios.json that conforms to the §3.1.d schema.

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
8. **`maxTurns: omitted` vs `maxTurns: 999`.** §3.3 commits to omitting
   `maxTurns:` entirely on the two new agents and relying on the platform
   default being "effectively unlimited". Phase 2 testing MUST verify
   this empirically: run the walker on a fixture that requires >50 tool
   calls and confirm it completes. If the omitted default turns out to
   be a small number (e.g. 25, 50), Phase 2 will switch to explicit
   `maxTurns: 999`. The TRDD will be updated with whichever path proved
   correct. No cap-with-small-value is acceptable either way.

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
