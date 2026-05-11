# Scenario family registry

## Table of Contents

- [Overview](#overview)
- [Family applies-to map](#family-applies-to-map)
- [Per-family failure modes](#per-family-failure-modes)
- [Adding a family](#adding-a-family)
- [Why these families](#why-these-families-and-not-others)

## Overview

Implements TRDD-6857f67f §3.1.e. The registry lives at
`scripts/scenario_generator/scenario_families.py` as two **pure-data
dicts**:

- `FAMILY_TO_TYPES: dict[str, frozenset[str]]` — which software types
  each family applies to. Wildcards (`web_*`, `firmware_*`, `kernel_*`,
  etc.) are defined in `TYPE_PREFIX_GROUPS` and expanded at lookup
  time. `ALL` means "every known type".
- `FAMILY_TO_FAILURE_MODES: dict[str, tuple[str, ...]]` — per-family
  list of opaque divergence patterns the walker uses as a checklist.

Adding a family = adding one entry to each dict. Adding an applies-to
mapping = appending to a frozenset. No code changes elsewhere.

Self-check at import: every family in `FAMILY_TO_TYPES` MUST have a
matching entry in `FAMILY_TO_FAILURE_MODES`, and vice versa.

## Family applies-to map

| Family | Applies to |
|---|---|
| `happy_path` | ALL |
| `adversarial_input` | web_*, cli_*, library_*, firmware_*, kernel_*, compiler_parser, network_protocol_impl, database_engine, browser_ext_*, ml_training, data_pipeline_*, driver_linux_userspace |
| `partial_failure` | web_*, cli_*, library_python/node/rust/c, mobile_*, firmware_*, rtos_*, kernel_*, driver_linux_userspace, browser_ext_*, game_*, desktop_*, iac_*, data_pipeline_*, ml_training, compiler_parser, network_protocol_impl, database_engine, distributed_system, message_queue_consumer, websocket_server (explicitly EXCLUDED: fpga_*, asic_design, crypto_library pure-compute) |
| `concurrent_state` | web_*, kernel_*, driver_linux_userspace, firmware_* (multi-task), rtos_*, distributed_system, database_engine, ml_training, message_queue_consumer, websocket_server, game_*, desktop_*, mobile_* |
| `auth_state_transition` | web_*, mobile_*, browser_ext_*, kernel_*, desktop_*, iac_k8s_operator |
| `resource_limits` | ALL |
| `interrupt_atomicity` | firmware_*, rtos_*, kernel_*, driver_linux_userspace, os_baremetal |
| `userspace_pointer_validation` | linux_kernel_module, linux_kernel_tree, windows_kernel_driver, bsd_kernel, macos_kernel_ext, driver_linux_userspace |
| `dma_race` | firmware_*, driver_linux_userspace, rtos_*, kernel_* |
| `boot_path` | firmware_*, os_baremetal, kernel_*, rtos_* |
| `suspend_resume` | firmware_*, mobile_*, driver_linux_userspace, kernel_*, desktop_* |
| `hardware_failure` | firmware_*, driver_linux_userspace, rtos_*, kernel_*, fpga_* |
| `protocol_replay` | web_*, network_protocol_impl, firmware_*, crypto_library, browser_ext_*, websocket_server, message_queue_consumer |
| `downgrade_attack` | crypto_library, network_protocol_impl, web_*, browser_ext_*, mobile_* |
| `persistence_corruption` | web_*, kernel_*, firmware_*, rtos_*, database_engine, distributed_system, iac_*, mobile_*, desktop_*, data_pipeline_*, ml_training |
| `ipc_message_malformed` | os_baremetal, kernel_*, browser_ext_*, mobile_*, distributed_system, desktop_* |
| `upgrade_migration` | web_*, mobile_*, database_engine, distributed_system, iac_*, data_pipeline_*, firmware_*, kernel_*, ml_training, browser_ext_* |
| `user_input_event` | mobile_*, desktop_*, game_*, browser_ext_*, webgl_three |
| `scheduler_starvation` | rtos_*, os_baremetal, kernel_*, distributed_system, data_pipeline_* |
| `backpressure` | data_pipeline_*, web_*, distributed_system, network_protocol_impl, websocket_server, message_queue_consumer |
| `clock_skew` | distributed_system, crypto_library, mobile_*, web_*, network_protocol_impl, kernel_* |
| `sandbox_escape` | browser_ext_*, mobile_*, os_baremetal, kernel_*, desktop_electron, desktop_tauri |
| `dependency_compromise` | ALL |
| `signal_integrity` | fpga_*, asic_design, firmware_* |
| `timing_constraint_violation` | fpga_*, asic_design, rtos_*, firmware_* |
| `watchdog_misuse` | firmware_*, rtos_*, kernel_*, os_baremetal |
| `power_glitch` | firmware_*, os_baremetal, crypto_library |
| `side_channel` | crypto_library, firmware_*, kernel_* |
| `concurrency_in_parser` | compiler_parser, network_protocol_impl, web_* |
| `memory_safety_uaf` | firmware_*, kernel_*, driver_linux_userspace, game_engine, desktop_qt, desktop_gtk, network_protocol_impl, library_c, database_engine, compiler_parser |
| `memory_safety_bounds` | (same set as memory_safety_uaf) |
| `integer_overflow_in_size_calc` | kernel_*, driver_linux_userspace, firmware_*, compiler_parser, network_protocol_impl, database_engine, crypto_library, library_c |
| `privilege_escalation` | kernel_*, driver_linux_userspace, browser_ext_*, desktop_*, mobile_* |
| `race_in_setuid_or_setgid` | kernel_*, os_baremetal, cli_* |

## Per-family failure modes

Each family ships a list of failure modes — opaque strings the walker
treats as a checklist. The walker reads them and asks "does this code
manifest this failure mode?". The strings are intentionally
free-form — adding a new failure mode is just appending a string.

Examples:

| Family | Sample failure modes |
|---|---|
| `adversarial_input` | size_check_bypass, encoding_injection, unicode_normalization_inconsistency, out_of_range_numeric, type_confusion, parser_recursion_depth_unbounded |
| `partial_failure` | no_compensation_on_step_failure, rollback_path_buggy, silent_swallowed_exception, double_commit_on_retry, partial_state_visible |
| `interrupt_atomicity` | isr_modifies_shared_without_lock, critical_section_not_irq_disabled, isr_yields_or_blocks, non_reentrant_function_called_from_isr |
| `userspace_pointer_validation` | missing_access_ok, toctou_between_check_and_copy, copy_size_attacker_controlled, leak_kernel_memory_on_failure |
| `dma_race` | cpu_reads_during_dma_write, no_cache_invalidate_before_read, no_cache_flush_before_dma, dma_buffer_freed_before_completion |
| `boot_path` | uninitialised_peripheral_used, stack_pointer_set_after_use, watchdog_not_serviced_during_long_init, no_brownout_safe_state |
| `signal_integrity` | metastability_on_async_crossing, no_cdc_synchroniser, setup_or_hold_time_violation, long_combinational_path |
| `side_channel` | non_constant_time_compare, key_dependent_branch_or_memory_access, cache_timing_leak, power_or_em_emanation |
| `memory_safety_uaf` | use_after_free, double_free, dangling_pointer_in_signal_handler, concurrent_free_and_use |
| `integer_overflow_in_size_calc` | multiplication_overflow_for_alloc_size, addition_overflow_for_buffer_size, signed_unsigned_confusion, truncation_loses_high_bits |

The full list per family is in
`scripts/scenario_generator/scenario_families.py:FAMILY_TO_FAILURE_MODES`.

## Adding a family

1. Decide the family name (snake_case, descriptive).
2. Add an entry to `FAMILY_TO_TYPES`: list the types it applies to,
   using prefix groups (`web_*`, `firmware_*`) where applicable.
3. Add an entry to `FAMILY_TO_FAILURE_MODES`: 3-6 concrete divergence
   patterns the walker should check.
4. Add a title template to `emit_scenarios_json._FAMILY_TITLES`
   (string with `{entry}` placeholder).
5. Add a default actor role to `emit_scenarios_json._FAMILY_ROLES`.
6. Add a row to the table above (this document).
7. Add unit tests that:
   - Assert the family appears in `families_for_type(<each applicable type>)`.
   - Assert it does NOT appear in `families_for_type(<each non-applicable type>)`.

The import-time consistency check in `scenario_families.py` will
fail loudly if you miss step 3 (FAMILY_TO_TYPES and
FAMILY_TO_FAILURE_MODES must stay in sync).

## Why these families and not others

The 34 families were chosen to cover the four defect classes named in
the user's original request (architecture holes, logical-rule flaws,
UX/feedback inconsistencies, security protocol flaws) PLUS specialised
families for software types where line-level audits structurally
cannot reach:

- `signal_integrity` / `timing_constraint_violation` for FPGA/ASIC
- `interrupt_atomicity` / `dma_race` / `watchdog_misuse` for firmware
- `userspace_pointer_validation` for kernel modules
- `side_channel` / `power_glitch` for crypto
- `concurrency_in_parser` for parsers
- `memory_safety_uaf` / `memory_safety_bounds` /
  `integer_overflow_in_size_calc` for C/C++/unsafe-Rust code

The set is not exhaustive — future families will be added as user
need emerges. The registry is designed to be additive.
