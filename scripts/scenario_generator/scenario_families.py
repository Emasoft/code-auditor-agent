"""Scenario family registry — implements TRDD-6857f67f §3.1.e.

PURE DATA. Two dicts:

- FAMILY_TO_TYPES: which software types each family applies to.
- FAMILY_TO_FAILURE_MODES: what divergence patterns the walker should
  look for, per family.

Adding a family = adding one entry to each dict. Adding an applies-to
relationship = appending to a frozenset. No code changes elsewhere.

The family-to-types map uses prefixes (`web_*`, `firmware_*`, `kernel_*`)
plus explicit type names, expanded at lookup time. Wildcards keep the
table readable while still being unambiguous.
"""

from __future__ import annotations

# Note: keep alphabetical to make merges trivial. Frozensets to prevent
# accidental mutation at runtime.

# Type-prefix groups that the wildcards expand to. Kept here (vs in
# detect_software_type) because this file is where prefix membership
# semantics matter for family eligibility.
TYPE_PREFIX_GROUPS: dict[str, frozenset[str]] = {
    "web_*": frozenset(
        {
            "web_service_python",
            "web_service_node",
            "web_service_go",
            "web_service_rust",
            "web_service_ruby",
            "web_service_php",
            "web_service_java_kotlin",
            "web_service_dotnet",
        }
    ),
    "cli_*": frozenset(
        {
            "cli_python",
            "cli_node",
            "cli_rust",
            "cli_go",
            "cli_csharp",
        }
    ),
    "library_*": frozenset(
        {
            "library_python",
            "library_node",
            "library_rust",
            "library_c",
        }
    ),
    "mobile_*": frozenset(
        {
            "mobile_android",
            "mobile_ios",
            "mobile_flutter",
            "mobile_reactnative",
            "mobile_kotlin_multiplatform",
        }
    ),
    "firmware_*": frozenset(
        {
            "firmware_arduino",
            "firmware_platformio",
            "firmware_zephyr",
            "firmware_espidf",
            "firmware_stm32",
            "firmware_nordic_sdk",
            "firmware_baremetal",
        }
    ),
    "rtos_*": frozenset(
        {
            "rtos_freertos",
            "rtos_zephyr",
            "rtos_threadx",
            "rtos_chibios",
        }
    ),
    "kernel_*": frozenset(
        {
            "linux_kernel_module",
            "linux_kernel_tree",
            "windows_kernel_driver",
            "bsd_kernel",
            "macos_kernel_ext",
        }
    ),
    "driver_*": frozenset(
        {
            "driver_linux_userspace",
            # in-kernel drivers are covered by kernel_*
        }
    ),
    "fpga_*": frozenset(
        {
            "fpga_verilog",
            "fpga_vhdl",
        }
    ),
    "iac_*": frozenset(
        {
            "iac_terraform",
            "iac_pulumi",
            "iac_helm",
            "iac_ansible",
            "iac_cloudformation",
            "iac_kustomize",
            "iac_docker_compose",
            "iac_k8s_operator",
        }
    ),
    "data_pipeline_*": frozenset(
        {
            "data_pipeline_airflow",
            "data_pipeline_dbt",
            "data_pipeline_prefect",
            "data_pipeline_dagster",
        }
    ),
    "browser_ext_*": frozenset(
        {
            "browser_ext_chrome",
            "browser_ext_firefox",
            "browser_ext_safari",
        }
    ),
    "game_*": frozenset(
        {
            "game_unity",
            "game_unreal",
            "game_godot",
        }
    ),
    "desktop_*": frozenset(
        {
            "desktop_qt",
            "desktop_gtk",
            "desktop_electron",
            "desktop_tauri",
            "desktop_flutter",
        }
    ),
    "os_*": frozenset(
        {
            "os_baremetal",
            # OS kernels are under kernel_* (linux_kernel_tree, bsd_kernel)
        }
    ),
    "ALL": frozenset(),  # filled in at runtime by expand_groups
}

# Family → applies-to. Use group keys ("web_*") or explicit type names.
# ALL means: every type known to the system.
FAMILY_TO_TYPES: dict[str, frozenset[str]] = {
    "happy_path": frozenset({"ALL"}),
    "adversarial_input": frozenset(
        {
            "web_*",
            "cli_*",
            "library_*",
            "firmware_*",
            "kernel_*",
            "compiler_parser",
            "network_protocol_impl",
            "database_engine",
            "browser_ext_*",
            "ml_training",
            "data_pipeline_*",
            "driver_linux_userspace",
        }
    ),
    # partial_failure is "all that do I/O" with explicit pure-compute exclusions
    "partial_failure": frozenset(
        {
            "web_*",
            "cli_*",
            "library_python",
            "library_node",
            "library_rust",
            "library_c",
            "mobile_*",
            "firmware_*",
            "rtos_*",
            "kernel_*",
            "driver_linux_userspace",
            "browser_ext_*",
            "game_*",
            "desktop_*",
            "iac_*",
            "data_pipeline_*",
            "ml_training",
            "compiler_parser",
            "network_protocol_impl",
            "database_engine",
            "distributed_system",
            "message_queue_consumer",
            "websocket_server",
            # excluded (pure compute / hardware-description / specification):
            # fpga_*, asic_design, crypto_library (pure-compute subset)
        }
    ),
    "concurrent_state": frozenset(
        {
            "web_*",
            "kernel_*",
            "driver_linux_userspace",
            "firmware_*",
            "rtos_*",
            "distributed_system",
            "database_engine",
            "ml_training",
            "message_queue_consumer",
            "websocket_server",
            "game_*",
            "desktop_*",
            "mobile_*",
        }
    ),
    "auth_state_transition": frozenset(
        {
            "web_*",
            "mobile_*",
            "browser_ext_*",
            "kernel_*",
            "desktop_*",
            "iac_k8s_operator",
        }
    ),
    "resource_limits": frozenset({"ALL"}),
    "interrupt_atomicity": frozenset(
        {
            "firmware_*",
            "rtos_*",
            "kernel_*",
            "driver_linux_userspace",
            "os_baremetal",
        }
    ),
    "userspace_pointer_validation": frozenset(
        {
            "linux_kernel_module",
            "linux_kernel_tree",
            "windows_kernel_driver",
            "bsd_kernel",
            "macos_kernel_ext",
            "driver_linux_userspace",
        }
    ),
    "dma_race": frozenset(
        {
            "firmware_*",
            "driver_linux_userspace",
            "rtos_*",
            "kernel_*",
        }
    ),
    "boot_path": frozenset(
        {
            "firmware_*",
            "os_baremetal",
            "kernel_*",
            "rtos_*",
        }
    ),
    "suspend_resume": frozenset(
        {
            "firmware_*",
            "mobile_*",
            "driver_linux_userspace",
            "kernel_*",
            "desktop_*",
        }
    ),
    "hardware_failure": frozenset(
        {
            "firmware_*",
            "driver_linux_userspace",
            "rtos_*",
            "kernel_*",
            "fpga_*",
        }
    ),
    "protocol_replay": frozenset(
        {
            "web_*",
            "network_protocol_impl",
            "firmware_*",
            "crypto_library",
            "browser_ext_*",
            "websocket_server",
            "message_queue_consumer",
        }
    ),
    "downgrade_attack": frozenset(
        {
            "crypto_library",
            "network_protocol_impl",
            "web_*",
            "browser_ext_*",
            "mobile_*",
        }
    ),
    "persistence_corruption": frozenset(
        {
            "web_*",
            "kernel_*",
            "firmware_*",
            "rtos_*",
            "database_engine",
            "distributed_system",
            "iac_*",
            "mobile_*",
            "desktop_*",
            "data_pipeline_*",
            "ml_training",
        }
    ),
    "ipc_message_malformed": frozenset(
        {
            "os_baremetal",
            "kernel_*",
            "browser_ext_*",
            "mobile_*",
            "distributed_system",
            "desktop_*",
        }
    ),
    "upgrade_migration": frozenset(
        {
            "web_*",
            "mobile_*",
            "database_engine",
            "distributed_system",
            "iac_*",
            "data_pipeline_*",
            "firmware_*",
            "kernel_*",
            "ml_training",
            "browser_ext_*",
        }
    ),
    "user_input_event": frozenset(
        {
            "mobile_*",
            "desktop_*",
            "game_*",
            "browser_ext_*",
            "webgl_three",
        }
    ),
    "scheduler_starvation": frozenset(
        {
            "rtos_*",
            "os_baremetal",
            "kernel_*",
            "distributed_system",
            "data_pipeline_*",
        }
    ),
    "backpressure": frozenset(
        {
            "data_pipeline_*",
            "web_*",
            "distributed_system",
            "network_protocol_impl",
            "websocket_server",
            "message_queue_consumer",
        }
    ),
    "clock_skew": frozenset(
        {
            "distributed_system",
            "crypto_library",
            "mobile_*",
            "web_*",
            "network_protocol_impl",
            "kernel_*",
        }
    ),
    "sandbox_escape": frozenset(
        {
            "browser_ext_*",
            "mobile_*",
            "os_baremetal",
            "kernel_*",
            "desktop_electron",
            "desktop_tauri",
        }
    ),
    "dependency_compromise": frozenset({"ALL"}),
    "signal_integrity": frozenset(
        {
            "fpga_*",
            "asic_design",
            "firmware_*",
        }
    ),
    "timing_constraint_violation": frozenset(
        {
            "fpga_*",
            "asic_design",
            "rtos_*",
            "firmware_*",
        }
    ),
    "watchdog_misuse": frozenset(
        {
            "firmware_*",
            "rtos_*",
            "kernel_*",
            "os_baremetal",
        }
    ),
    "power_glitch": frozenset(
        {
            "firmware_*",
            "os_baremetal",
            "crypto_library",
        }
    ),
    "side_channel": frozenset(
        {
            "crypto_library",
            "firmware_*",
            "kernel_*",
        }
    ),
    "concurrency_in_parser": frozenset(
        {
            "compiler_parser",
            "network_protocol_impl",
            "web_*",
        }
    ),
    "memory_safety_uaf": frozenset(
        {
            "firmware_*",
            "kernel_*",
            "driver_linux_userspace",
            "game_engine",
            "desktop_qt",
            "desktop_gtk",
            "network_protocol_impl",
            "library_c",
            "database_engine",
            "compiler_parser",
        }
    ),
    "memory_safety_bounds": frozenset(
        {
            "firmware_*",
            "kernel_*",
            "driver_linux_userspace",
            "game_engine",
            "desktop_qt",
            "desktop_gtk",
            "network_protocol_impl",
            "library_c",
            "database_engine",
            "compiler_parser",
        }
    ),
    "integer_overflow_in_size_calc": frozenset(
        {
            "kernel_*",
            "driver_linux_userspace",
            "firmware_*",
            "compiler_parser",
            "network_protocol_impl",
            "database_engine",
            "crypto_library",
            "library_c",
        }
    ),
    "privilege_escalation": frozenset(
        {
            "kernel_*",
            "driver_linux_userspace",
            "browser_ext_*",
            "desktop_*",
            "mobile_*",
        }
    ),
    "race_in_setuid_or_setgid": frozenset(
        {
            "kernel_*",
            "os_baremetal",
            "cli_*",
        }
    ),
}


# Family → list of failure-mode strings the walker uses as a checklist.
# These are opaque to the schema (just strings); the walker interprets
# them. Kept tight and orthogonal — each mode is one concrete divergence
# pattern.
FAMILY_TO_FAILURE_MODES: dict[str, tuple[str, ...]] = {
    "happy_path": (
        "step_skipped",
        "step_returned_wrong_status",
        "expected_side_effect_missing",
    ),
    "adversarial_input": (
        "size_check_bypass",
        "encoding_injection",
        "unicode_normalization_inconsistency",
        "out_of_range_numeric",
        "type_confusion",
        "parser_recursion_depth_unbounded",
    ),
    "partial_failure": (
        "no_compensation_on_step_failure",
        "rollback_path_buggy",
        "silent_swallowed_exception",
        "double_commit_on_retry",
        "partial_state_visible",
    ),
    "concurrent_state": (
        "race_window_unprotected",
        "lock_held_during_io",
        "deadlock_two_resources",
        "lost_update",
        "double_free_or_release",
    ),
    "auth_state_transition": (
        "token_expiry_mid_operation",
        "role_change_not_reread",
        "permission_revoke_not_propagated",
        "session_fixation",
        "auth_check_after_action",
    ),
    "resource_limits": (
        "no_quota_check",
        "no_oom_handling",
        "unbounded_allocation",
        "no_disk_full_handling",
        "no_stack_depth_limit",
    ),
    "interrupt_atomicity": (
        "isr_modifies_shared_without_lock",
        "critical_section_not_irq_disabled",
        "isr_yields_or_blocks",
        "non_reentrant_function_called_from_isr",
    ),
    "userspace_pointer_validation": (
        "missing_access_ok",
        "toctou_between_check_and_copy",
        "copy_size_attacker_controlled",
        "leak_kernel_memory_on_failure",
    ),
    "dma_race": (
        "cpu_reads_during_dma_write",
        "no_cache_invalidate_before_read",
        "no_cache_flush_before_dma",
        "dma_buffer_freed_before_completion",
    ),
    "boot_path": (
        "uninitialised_peripheral_used",
        "stack_pointer_set_after_use",
        "watchdog_not_serviced_during_long_init",
        "no_brownout_safe_state",
    ),
    "suspend_resume": (
        "state_not_persisted_before_suspend",
        "interrupt_pending_lost_on_resume",
        "peripheral_state_not_restored",
        "race_on_wake_with_pending_work",
    ),
    "hardware_failure": (
        "no_timeout_on_peripheral_wait",
        "no_retry_or_degraded_mode",
        "no_failure_indication_to_caller",
        "infinite_loop_on_bus_error",
    ),
    "protocol_replay": (
        "no_nonce_check",
        "nonce_window_too_wide",
        "replay_within_session_accepted",
        "no_message_ordering_check",
    ),
    "downgrade_attack": (
        "weak_cipher_acceptable",
        "no_version_pinning",
        "no_renegotiation_check",
        "fallback_path_unauthenticated",
    ),
    "persistence_corruption": (
        "no_fsync_on_commit",
        "torn_write_visible",
        "no_checksum_on_record",
        "rename_not_atomic",
        "wal_truncated_silently",
    ),
    "ipc_message_malformed": (
        "no_length_validation",
        "no_type_validation",
        "trust_unsigned_peer",
        "deserialization_of_untrusted_class",
    ),
    "upgrade_migration": (
        "no_downgrade_path",
        "partial_migration_state_unrecoverable",
        "schema_assumption_drift_between_services",
        "rollback_loses_data",
    ),
    "user_input_event": (
        "double_tap_triggers_twice",
        "background_event_resumes_in_wrong_state",
        "permission_dialog_dismissed_treated_as_grant",
        "back_button_loses_unsaved_state",
    ),
    "scheduler_starvation": (
        "low_priority_task_never_runs",
        "priority_inversion",
        "leader_election_stuck",
        "consumer_starved_by_producer",
    ),
    "backpressure": (
        "unbounded_queue_growth",
        "no_drop_or_throttle_policy",
        "producer_blocks_forever",
        "load_shedding_drops_critical_messages",
    ),
    "clock_skew": (
        "expiry_check_uses_local_time",
        "skew_window_too_narrow",
        "monotonic_vs_wall_clock_confused",
        "leader_lease_breaks_on_minor_skew",
    ),
    "sandbox_escape": (
        "permission_check_bypass",
        "ipc_to_more_privileged_peer_unchecked",
        "file_uri_leak_through_redirect",
        "intent_hijack_or_url_scheme_takeover",
    ),
    "dependency_compromise": (
        "unpinned_dependency_version",
        "supply_chain_unverified_signature",
        "transitive_dep_with_known_cve",
        "build_script_executes_untrusted_code",
    ),
    "signal_integrity": (
        "metastability_on_async_crossing",
        "no_cdc_synchroniser",
        "setup_or_hold_time_violation",
        "long_combinational_path",
    ),
    "timing_constraint_violation": (
        "deadline_missed_under_load",
        "isr_jitter_too_high",
        "clock_constraint_unsatisfied",
        "back_pressure_violates_deadline",
    ),
    "watchdog_misuse": (
        "watchdog_disabled_during_critical_section",
        "watchdog_petted_inside_a_hang",
        "watchdog_reset_loses_state",
        "watchdog_window_too_wide",
    ),
    "power_glitch": (
        "no_brownout_aware_critical_section",
        "fault_injection_skips_security_check",
        "voltage_drop_during_flash_write",
    ),
    "side_channel": (
        "non_constant_time_compare",
        "key_dependent_branch_or_memory_access",
        "cache_timing_leak",
        "power_or_em_emanation",
    ),
    "concurrency_in_parser": (
        "shared_lexer_state",
        "buffer_reuse_across_concurrent_parses",
        "thread_unsafe_globals",
    ),
    "memory_safety_uaf": (
        "use_after_free",
        "double_free",
        "dangling_pointer_in_signal_handler",
        "concurrent_free_and_use",
    ),
    "memory_safety_bounds": (
        "off_by_one_in_loop",
        "size_attacker_controlled",
        "no_buffer_check_in_copy",
        "negative_index_passed_through",
    ),
    "integer_overflow_in_size_calc": (
        "multiplication_overflow_for_alloc_size",
        "addition_overflow_for_buffer_size",
        "signed_unsigned_confusion",
        "truncation_loses_high_bits",
    ),
    "privilege_escalation": (
        "setuid_binary_unsafe_env_var",
        "ioctl_capable_for_unprivileged_user",
        "extension_requests_overbroad_permission",
        "deeplink_grants_unintended_action",
    ),
    "race_in_setuid_or_setgid": (
        "drop_privileges_after_action",
        "file_op_between_check_and_use",
        "saved_uid_not_dropped",
    ),
}


# All known software type names. The detect_software_type module also
# enumerates these; the source of truth is the registry in that file,
# but we mirror the EXPANSION here so this module can resolve "ALL"
# without importing detect_software_type (avoids a circular import).
# The mirror is asserted equal to detect_software_type.ALL_TYPES at
# import time below.
_KNOWN_TYPES: frozenset[str] = frozenset(
    {
        "web_service_python",
        "web_service_node",
        "web_service_go",
        "web_service_rust",
        "web_service_ruby",
        "web_service_php",
        "web_service_java_kotlin",
        "web_service_dotnet",
        "cli_python",
        "cli_node",
        "cli_rust",
        "cli_go",
        "cli_csharp",
        "library_python",
        "library_node",
        "library_rust",
        "library_c",
        "mobile_android",
        "mobile_ios",
        "mobile_flutter",
        "mobile_reactnative",
        "mobile_kotlin_multiplatform",
        "firmware_arduino",
        "firmware_platformio",
        "firmware_zephyr",
        "firmware_espidf",
        "firmware_stm32",
        "firmware_nordic_sdk",
        "firmware_baremetal",
        "rtos_freertos",
        "rtos_zephyr",
        "rtos_threadx",
        "rtos_chibios",
        "linux_kernel_module",
        "linux_kernel_tree",
        "windows_kernel_driver",
        "bsd_kernel",
        "macos_kernel_ext",
        "os_baremetal",
        "fpga_verilog",
        "fpga_vhdl",
        "asic_design",
        "driver_linux_userspace",
        "browser_ext_chrome",
        "browser_ext_firefox",
        "browser_ext_safari",
        "game_unity",
        "game_unreal",
        "game_godot",
        "game_engine",
        "compiler_parser",
        "network_protocol_impl",
        "database_engine",
        "distributed_system",
        "crypto_library",
        "iac_terraform",
        "iac_pulumi",
        "iac_helm",
        "iac_ansible",
        "iac_cloudformation",
        "iac_kustomize",
        "iac_docker_compose",
        "iac_k8s_operator",
        "data_pipeline_airflow",
        "data_pipeline_dbt",
        "data_pipeline_prefect",
        "data_pipeline_dagster",
        "ml_training",
        "desktop_qt",
        "desktop_gtk",
        "desktop_electron",
        "desktop_tauri",
        "desktop_flutter",
        "webgl_three",
        "websocket_server",
        "message_queue_consumer",
        "unknown_software",
    }
)

TYPE_PREFIX_GROUPS["ALL"] = _KNOWN_TYPES


def expand_types(spec: frozenset[str]) -> frozenset[str]:
    """Expand a family's type-set into concrete type names.

    Group names like 'web_*' expand to all their members; concrete names
    pass through unchanged. 'ALL' is the universe.
    """
    out: set[str] = set()
    for item in spec:
        if item in TYPE_PREFIX_GROUPS:
            out.update(TYPE_PREFIX_GROUPS[item])
        else:
            out.add(item)
    return frozenset(out)


def families_for_type(detected_type: str) -> tuple[str, ...]:
    """Return the family names that apply to a given software type.

    Returned in alphabetical order so emit_scenarios_json gets deterministic
    expansion regardless of dict iteration order.
    """
    applicable: list[str] = []
    for family, spec in FAMILY_TO_TYPES.items():
        if detected_type in expand_types(spec):
            applicable.append(family)
    return tuple(sorted(applicable))


# Sanity: every family in FAMILY_TO_TYPES has matching failure-modes
# (asserted at import so misconfiguration fails loud).
_missing = set(FAMILY_TO_TYPES) - set(FAMILY_TO_FAILURE_MODES)
if _missing:
    raise RuntimeError(f"scenario_families: families without failure_modes: {sorted(_missing)}")
_extra = set(FAMILY_TO_FAILURE_MODES) - set(FAMILY_TO_TYPES)
if _extra:
    raise RuntimeError(f"scenario_families: failure_modes for unknown families: {sorted(_extra)}")
