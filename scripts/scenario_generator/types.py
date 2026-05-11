"""Universal types for the scenario generator.

The schema here is the public contract between the skill and the walker
agent. Two cardinal rules:

1. The walker is TYPE-BLIND. It reads the schema fields below and applies
   the same logic regardless of whether the entry point is an HTTP route,
   an ISR vector, a syscall, or a Terraform resource. Type-specific
   knowledge crystallizes into the ENUM VALUES, not into separate schemas.

2. The schema MUST be additive-only. New enum values are fine; renaming
   or removing existing ones breaks every published scenario library and
   every walker run. Version bumps follow $schema versioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "scenarios.v1.json"


class EntryPointKind(StrEnum):
    """Universal taxonomy of code entry points.

    Every detected software type maps its native entry-point concept to
    one of these. The walker's role-aware reasoning is keyed off this.
    """

    HTTP_ROUTE = "http_route"
    CLI_COMMAND = "cli_command"
    LIBRARY_EXPORT = "library_export"
    IPC_HANDLER = "ipc_handler"
    ISR_VECTOR = "isr_vector"
    GPIO_INTERRUPT = "gpio_interrupt"
    SYSCALL_HANDLER = "syscall_handler"
    IOCTL_HANDLER = "ioctl_handler"
    MODULE_INIT = "module_init"
    MODULE_EXIT = "module_exit"
    RTOS_TASK = "rtos_task"
    RTOS_ISR = "rtos_isr"
    EVENT_LISTENER = "event_listener"
    WEBHOOK = "webhook"
    CRON_JOB = "cron_job"
    MQ_CONSUMER = "mq_consumer"
    WS_MESSAGE_HANDLER = "ws_message_handler"
    UI_ROUTE = "ui_route"
    UI_EVENT_HANDLER = "ui_event_handler"
    OS_LIFECYCLE_EVENT = "os_lifecycle_event"
    PERMISSION_REQUEST = "permission_request"
    BOOT_PATH = "boot_path"
    RESET_PATH = "reset_path"
    POWER_EVENT = "power_event"
    DMA_TRANSFER = "dma_transfer"
    HW_REGISTER_WRITE = "hw_register_write"
    HW_REGISTER_READ = "hw_register_read"
    PROTOCOL_PACKET_HANDLER = "protocol_packet_handler"
    PARSER_INPUT = "parser_input"
    DB_QUERY_HANDLER = "db_query_handler"
    MIGRATION_APPLY = "migration_apply"
    MIGRATION_ROLLBACK = "migration_rollback"
    TERRAFORM_RESOURCE = "terraform_resource"
    HELM_TEMPLATE = "helm_template"
    DAG_TASK = "dag_task"
    CONTROLLER_RECONCILE = "controller_reconcile"
    FPGA_TOPLEVEL_PORT = "fpga_toplevel_port"
    MAIN_FUNCTION = "main_function"
    UNKNOWN_ENTRY = "unknown_entry"


class ActorRole(StrEnum):
    """Roles the walker can play when tracing a scenario.

    Each scenario picks ONE actor role; the walker then traces the path
    AS that role, applying that role's permissions, input constraints,
    and trust assumptions.
    """

    ANONYMOUS_CLIENT = "anonymous_client"
    AUTHENTICATED_USER = "authenticated_user"
    ADMIN = "admin"
    ATTACKER_EXTERNAL = "attacker_external"
    ATTACKER_INTERNAL = "attacker_internal"
    ATTACKER_COMPROMISED_SESSION = "attacker_compromised_session"
    PEER_SERVICE = "peer_service"
    USERSPACE_CALLER = "userspace_caller"
    USERSPACE_ATTACKER = "userspace_attacker"
    HARDWARE_INTERRUPT = "hardware_interrupt"
    HARDWARE_DMA_ENGINE = "hardware_dma_engine"
    OS_SCHEDULER = "os_scheduler"
    OS_SIGNAL = "os_signal"
    POWER_EVENT_SOURCE = "power_event_source"
    NETWORK_PEER_MALICIOUS = "network_peer_malicious"
    NETWORK_PEER_BENIGN = "network_peer_benign"
    BOOTLOADER = "bootloader"
    WATCHDOG = "watchdog"
    BROWNOUT_DETECTOR = "brownout_detector"
    TEST_RUNNER = "test_runner"
    CI_SYSTEM = "ci_system"
    DEVELOPER_LOCAL = "developer_local"
    UNKNOWN_ACTOR = "unknown_actor"


@dataclass(frozen=True, slots=True)
class DetectedType:
    """One row of the §3.1.c registry that matched the codebase.

    A codebase may have multiple DetectedType results (monorepo, mixed
    backend + mobile, etc.). They are sorted by confidence DESC.
    """

    type: str  # one of the type names in §3.1.c
    confidence: float  # 0.0..1.0
    evidence: tuple[str, ...]  # ordered, deterministic

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "confidence": round(self.confidence, 3),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """One entry point discovered by a per-type discoverer.

    The `metadata` dict is type-specific (e.g. HTTP method+path for
    http_route, IRQ vector number for isr_vector, command name for
    cli_command). The walker reads it without interpreting it; the
    family expansion in emit_scenarios_json crystallizes any
    family-specific stimulus into the scenario.
    """

    kind: EntryPointKind
    file: str  # repo-relative
    line: int
    symbol: str  # function/class/module name, or unique identifier
    type_origin: str  # which DetectedType produced this entry point
    metadata: dict[str, Any] = field(default_factory=dict)
    docstring: str = ""  # extracted from nearby comments/docs; used for intended_behaviour
    intended_behaviour_sources: tuple[str, ...] = ()  # paths like "docs/api.md:121"

    def sort_key(self) -> tuple[str, int, str]:
        """Deterministic ordering — required for byte-identical output."""
        return (self.file, self.line, self.symbol)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "file": self.file,
            "line": self.line,
            "symbol": self.symbol,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Scenario:
    """One scenario emitted by the generator. Walker input."""

    id: str  # SCEN-NNNN, deterministic
    type_origin: str
    family: str  # one of the keys in FAMILY_TO_TYPES
    title: str
    entry_point: EntryPoint
    actor_role: ActorRole
    stimulus: dict[str, Any]  # {kind: str, value: Any}
    intended_behaviour: str
    intended_behaviour_source: tuple[str, ...]
    expected_path_summary: tuple[str, ...]
    invariants_to_check: tuple[str, ...]
    failure_modes_to_test: tuple[str, ...]
    feedback_expected: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type_origin": self.type_origin,
            "family": self.family,
            "title": self.title,
            "entry_point": self.entry_point.to_json(),
            "actor_role": self.actor_role.value,
            "stimulus": self.stimulus,
            "intended_behaviour": self.intended_behaviour,
            "intended_behaviour_source": list(self.intended_behaviour_source),
            "expected_path_summary": list(self.expected_path_summary),
            "invariants_to_check": list(self.invariants_to_check),
            "failure_modes_to_test": list(self.failure_modes_to_test),
            "feedback_expected": self.feedback_expected,
        }


@dataclass(frozen=True, slots=True)
class GeneratorOutput:
    """Top-level output structure — emitted as scenarios.json."""

    codebase_root: Path
    detected_types: tuple[DetectedType, ...]
    detected_languages: tuple[str, ...]
    scenarios: tuple[Scenario, ...]
    generated_at_local: str  # ISO 8601 with offset, e.g. 20260511_140532+0200 (matches agent-reports-location rule)

    def to_json(self) -> dict[str, Any]:
        return {
            "$schema": SCHEMA_VERSION,
            "generated_at": self.generated_at_local,
            "codebase": {
                "root": str(self.codebase_root),
                "detected_types": [t.to_json() for t in self.detected_types],
                "detected_languages": list(self.detected_languages),
            },
            "scenarios": [s.to_json() for s in self.scenarios],
        }
