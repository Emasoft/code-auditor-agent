# Universal scenario schema

## Table of Contents

- [Top-level shape](#top-level-shape)
- [EntryPointKind enum](#entrypointkind-enum)
- [ActorRole enum](#actorrole-enum)
- [Examples per kind](#examples-per-kind)
- [Walker contract](#walker-contract)

## Top-level shape

The skill emits `scenarios.json` with this structure. **Universal —
identical regardless of detected software type.** Type-specific
knowledge crystallizes into the ENUM VALUES (`entry_point.kind`,
`actor_role`), not into per-type schemas. See TRDD-6857f67f §3.1.d.

```json
{
  "$schema": "scenarios.v1.json",
  "generated_at": "20260511_140532+0200",
  "codebase": {
    "root": "/abs/path/to/repo",
    "detected_types": [
      {"type": "linux_kernel_module", "confidence": 0.93,
       "evidence": ["Kbuild has obj-m += myhw.o", "MODULE_LICENSE in src/myhw_main.c:12"]}
    ],
    "detected_languages": ["c"]
  },
  "scenarios": [ { ...one scenario... }, ... ]
}
```

Each scenario:

```json
{
  "id": "SCEN-0001",
  "type_origin": "<one of detected_types[].type>",
  "family": "<one of FAMILY_TO_TYPES keys — see ref 04>",
  "title": "Short human-readable title",
  "entry_point": {
    "kind": "<one of EntryPointKind values, see below>",
    "file": "<repo-relative path>",
    "line": <int>,
    "symbol": "<function/class/identifier>",
    "metadata": { ...kind-specific, free-form... }
  },
  "actor_role": "<one of ActorRole values>",
  "stimulus": {
    "kind": "<usually family_default; discoverers may override>",
    "value": { ...free-form... }
  },
  "intended_behaviour": "What the system SHOULD do",
  "intended_behaviour_source": [
    "<source paths — docs/spec/OpenAPI/datasheet/man-page references>"
  ],
  "expected_path_summary": ["step1", "step2", "..."],
  "invariants_to_check": ["..."],
  "failure_modes_to_test": [ "from FAMILY_TO_FAILURE_MODES (ref 04)" ],
  "feedback_expected": "What the user/caller sees on success, or null"
}
```

### Determinism contract

- `detected_types`: sorted by `confidence` DESC, then `type` ASC.
- `scenarios`: sorted by `(type_origin, entry_point.file, entry_point.line, entry_point.symbol, family)`. IDs assigned in that order as `SCEN-NNNN` (zero-padded to 4 digits, starting at 1).
- Evidence strings are sorted in the order produced by the deterministic
  glob walk (sorted file paths, deterministic regex iteration).

Two runs on the same input MUST produce byte-identical JSON.

## EntryPointKind enum

38 values, all in `scripts/scenario_generator/types.py`. Grouped by
typical software domain:

| Kind | Used by | Description |
|---|---|---|
| `http_route` | web_* | HTTP API endpoint |
| `cli_command` | cli_* | command-line tool subcommand |
| `library_export` | library_* | public top-level callable |
| `ipc_handler` | os_*, kernel_*, distributed_system | inter-process message handler |
| `isr_vector` | firmware_*, rtos_*, kernel_* | hardware interrupt vector |
| `gpio_interrupt` | firmware_* | pin-change ISR |
| `syscall_handler` | kernel_* | syscall table entry handler |
| `ioctl_handler` | kernel_* | device ioctl dispatch |
| `module_init` / `module_exit` | linux_kernel_module | module load/unload |
| `rtos_task` / `rtos_isr` | rtos_* | task entry / RTOS-aware ISR |
| `event_listener` | mobile_*, browser_ext_*, ws_*, mq_*, firmware_* | callback registration |
| `webhook` | web_* | inbound webhook endpoint |
| `cron_job` | web_*, data_pipeline_* | scheduled job |
| `mq_consumer` | message_queue_consumer | subscribed handler |
| `ws_message_handler` | websocket_server | websocket onmessage |
| `ui_route` / `ui_event_handler` | web_*, mobile_*, desktop_*, game_* | screen or UI event |
| `os_lifecycle_event` | mobile_*, desktop_* | suspend/resume/etc. |
| `permission_request` | mobile_*, browser_ext_* | runtime permission flow |
| `boot_path` / `reset_path` | firmware_*, os_baremetal, kernel_* | startup paths |
| `power_event` | firmware_*, mobile_*, kernel_* | brownout/sleep/wake |
| `dma_transfer` | driver_*, firmware_* | DMA setup/completion |
| `hw_register_write` / `hw_register_read` | firmware_*, driver_*, kernel_* | MMIO operations |
| `protocol_packet_handler` | network_protocol_impl | wire-level packet handler |
| `parser_input` | compiler_parser | parser entry point |
| `db_query_handler` | database_engine | query plan entry |
| `migration_apply` / `migration_rollback` | iac_*, database_engine, data_pipeline_* | schema migration step |
| `terraform_resource` / `helm_template` | iac_* | declarative resource |
| `dag_task` | data_pipeline_* | airflow/dagster task |
| `controller_reconcile` | iac_k8s_operator | reconcile loop step |
| `fpga_toplevel_port` | fpga_* | top-level module I/O port |
| `main_function` | unknown_software, cli_*, firmware_arduino (loop) | program entry |
| `unknown_entry` | fallback | when nothing else fits |

## ActorRole enum

22 values. The walker plays the role on a scenario — applies that role's
permissions, input constraints, and trust assumptions.

| Role | Typical scenarios |
|---|---|
| `anonymous_client` / `authenticated_user` / `admin` | web/mobile/desktop happy paths |
| `attacker_external` / `attacker_internal` / `attacker_compromised_session` | adversarial input, sandbox escape, replay |
| `peer_service` | IPC, distributed messages |
| `userspace_caller` / `userspace_attacker` | kernel syscall/ioctl handlers |
| `hardware_interrupt` / `hardware_dma_engine` | firmware/kernel ISRs, DMA races |
| `os_scheduler` / `os_signal` | RTOS/kernel scheduling, signal handlers |
| `power_event_source` | suspend/resume, brownout |
| `network_peer_malicious` / `network_peer_benign` | protocol replay, downgrade |
| `bootloader` / `watchdog` / `brownout_detector` | boot paths, watchdog misuse |
| `test_runner` / `ci_system` / `developer_local` | upgrade migrations, dev-only flows |
| `unknown_actor` | fallback |

## Examples per kind

### HTTP route (FastAPI)

```json
{"id": "SCEN-0001", "type_origin": "web_service_python", "family": "adversarial_input",
 "title": "POST /orders rejects adversarial input",
 "entry_point": {"kind": "http_route", "file": "src/api/orders.py", "line": 17,
   "symbol": "create_order", "metadata": {"method": "POST", "path": "/orders",
   "framework": "fastapi", "binding": "app"}},
 "actor_role": "attacker_external", ...}
```

### ISR vector (firmware)

```json
{"id": "SCEN-0042", "type_origin": "firmware_arduino", "family": "interrupt_atomicity",
 "title": "ISR fires during atomic write",
 "entry_point": {"kind": "gpio_interrupt", "file": "sketch.ino", "line": 47,
   "symbol": "buttonHandler", "metadata": {"pin": "2", "mode": "FALLING"}},
 "actor_role": "hardware_interrupt", ...}
```

### Kernel ioctl

```json
{"id": "SCEN-0099", "type_origin": "linux_kernel_module",
 "family": "userspace_pointer_validation",
 "title": "ioctl receives bad userspace pointer",
 "entry_point": {"kind": "ioctl_handler", "file": "myhw_main.c", "line": 42,
   "symbol": "myhw_ioctl", "metadata": {"op": "ioctl", "fops_var": "myhw_fops"}},
 "actor_role": "userspace_attacker", ...}
```

### FPGA top-level port

```json
{"id": "SCEN-0177", "type_origin": "fpga_verilog",
 "family": "signal_integrity",
 "title": "Top port `uart_rx` signal integrity",
 "entry_point": {"kind": "fpga_toplevel_port", "file": "top.v", "line": 8,
   "symbol": "uart_rx", "metadata": {"port_direction": "input",
   "port_width_bits": 1, "module": "top", "constraint_file": "constraints/top.xdc"}},
 "actor_role": "hardware_interrupt", ...}
```

## Walker contract

The walker reads `scenarios.json`, picks scenarios (one or many per agent),
and for each:

1. Locates the entry point via `tldr context` / Serena `find_symbol`.
2. Adopts `actor_role` — applies role-specific input constraints and trust assumptions.
3. Walks the call graph statically (`tldr impact` / Serena `find_referencing_symbols`).
4. Compares walked path to `expected_path_summary` and outcome to `intended_behaviour`.
5. Checks every item in `failure_modes_to_test` against the walked code.
6. Records divergences as structured findings.

The walker is type-blind — it reads the schema fields above and applies
the same logic regardless of whether the entry is an HTTP route or an
ISR vector. Type-specific reasoning was crystallized into the enum
values by the discoverer at generation time.
