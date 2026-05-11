#!/usr/bin/env python3
"""scenarios.json emitter — composes type detection + per-type discovery
+ family registry into the universal output schema (TRDD-6857f67f §3.1.d).

DETERMINISTIC. Output is byte-identical across runs for the same input.

Usage from the skill:
    uv run python -m scripts.scenario_generator.emit_scenarios_json \\
        <repo_root> <output_dir>

The skill orchestrates: detect_software_type.detect_all -> for each
detected type, dispatch to discoverers/<type>.py -> emit JSON.
"""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import scenario_families as sf
from .detect_software_type import detect_all
from .types import (
    SCHEMA_VERSION,
    ActorRole,
    EntryPoint,
    EntryPointKind,
    GeneratorOutput,
    Scenario,
)

# Title templates per family — fed into f-strings with {entry} (symbol or path).
_FAMILY_TITLES: dict[str, str] = {
    "happy_path": "Happy path of {entry}",
    "adversarial_input": "{entry} rejects adversarial input",
    "partial_failure": "{entry} handles partial failure mid-operation",
    "concurrent_state": "{entry} is safe under concurrent access",
    "auth_state_transition": "{entry} re-validates auth on state transition",
    "resource_limits": "{entry} respects resource limits",
    "interrupt_atomicity": "{entry} preserves atomicity under interrupt",
    "userspace_pointer_validation": "{entry} validates userspace pointer",
    "dma_race": "{entry} handles CPU/DMA race",
    "boot_path": "{entry} on boot path",
    "suspend_resume": "{entry} across suspend/resume",
    "hardware_failure": "{entry} handles hardware failure",
    "protocol_replay": "{entry} rejects replayed protocol message",
    "downgrade_attack": "{entry} rejects protocol downgrade",
    "persistence_corruption": "{entry} survives persistence corruption",
    "ipc_message_malformed": "{entry} rejects malformed IPC message",
    "upgrade_migration": "{entry} survives upgrade/migration",
    "user_input_event": "{entry} handles user input event",
    "scheduler_starvation": "{entry} avoids scheduler starvation",
    "backpressure": "{entry} applies backpressure",
    "clock_skew": "{entry} tolerates clock skew",
    "sandbox_escape": "{entry} prevents sandbox escape",
    "dependency_compromise": "{entry} robust to dependency compromise",
    "signal_integrity": "{entry} signal integrity / metastability",
    "timing_constraint_violation": "{entry} respects timing constraints",
    "watchdog_misuse": "{entry} watchdog usage is correct",
    "power_glitch": "{entry} robust to power glitch / fault injection",
    "side_channel": "{entry} resistant to side-channel leakage",
    "concurrency_in_parser": "{entry} parser thread-safe",
    "memory_safety_uaf": "{entry} no use-after-free",
    "memory_safety_bounds": "{entry} bounds-checked",
    "integer_overflow_in_size_calc": "{entry} no integer overflow in size calc",
    "privilege_escalation": "{entry} prevents privilege escalation",
    "race_in_setuid_or_setgid": "{entry} setuid/setgid race-free",
}

# Default actor role per family.
_FAMILY_ROLES: dict[str, ActorRole] = {
    "happy_path": ActorRole.AUTHENTICATED_USER,
    "adversarial_input": ActorRole.ATTACKER_EXTERNAL,
    "partial_failure": ActorRole.AUTHENTICATED_USER,
    "concurrent_state": ActorRole.AUTHENTICATED_USER,
    "auth_state_transition": ActorRole.AUTHENTICATED_USER,
    "resource_limits": ActorRole.ATTACKER_EXTERNAL,
    "interrupt_atomicity": ActorRole.HARDWARE_INTERRUPT,
    "userspace_pointer_validation": ActorRole.USERSPACE_ATTACKER,
    "dma_race": ActorRole.HARDWARE_DMA_ENGINE,
    "boot_path": ActorRole.BOOTLOADER,
    "suspend_resume": ActorRole.POWER_EVENT_SOURCE,
    "hardware_failure": ActorRole.HARDWARE_INTERRUPT,
    "protocol_replay": ActorRole.NETWORK_PEER_MALICIOUS,
    "downgrade_attack": ActorRole.NETWORK_PEER_MALICIOUS,
    "persistence_corruption": ActorRole.POWER_EVENT_SOURCE,
    "ipc_message_malformed": ActorRole.PEER_SERVICE,
    "upgrade_migration": ActorRole.CI_SYSTEM,
    "user_input_event": ActorRole.AUTHENTICATED_USER,
    "scheduler_starvation": ActorRole.OS_SCHEDULER,
    "backpressure": ActorRole.NETWORK_PEER_BENIGN,
    "clock_skew": ActorRole.PEER_SERVICE,
    "sandbox_escape": ActorRole.ATTACKER_INTERNAL,
    "dependency_compromise": ActorRole.ATTACKER_EXTERNAL,
    "signal_integrity": ActorRole.HARDWARE_INTERRUPT,
    "timing_constraint_violation": ActorRole.HARDWARE_INTERRUPT,
    "watchdog_misuse": ActorRole.WATCHDOG,
    "power_glitch": ActorRole.BROWNOUT_DETECTOR,
    "side_channel": ActorRole.ATTACKER_EXTERNAL,
    "concurrency_in_parser": ActorRole.NETWORK_PEER_BENIGN,
    "memory_safety_uaf": ActorRole.ATTACKER_EXTERNAL,
    "memory_safety_bounds": ActorRole.ATTACKER_EXTERNAL,
    "integer_overflow_in_size_calc": ActorRole.ATTACKER_EXTERNAL,
    "privilege_escalation": ActorRole.ATTACKER_INTERNAL,
    "race_in_setuid_or_setgid": ActorRole.ATTACKER_INTERNAL,
}


def _entry_label(ep: EntryPoint) -> str:
    """Short human-readable label for an entry point, used in scenario titles."""
    meta = ep.metadata
    if ep.kind == EntryPointKind.HTTP_ROUTE and "method" in meta and "path" in meta:
        return f"{meta['method']} {meta['path']}"
    if ep.kind == EntryPointKind.CLI_COMMAND and "command" in meta:
        return str(meta["command"])
    if ep.kind == EntryPointKind.ISR_VECTOR and "vector" in meta:
        return f"ISR {meta['vector']} ({ep.symbol})"
    if ep.kind == EntryPointKind.SYSCALL_HANDLER and "cmd" in meta:
        return f"syscall {meta['cmd']} ({ep.symbol})"
    return ep.symbol


def _make_scenario(
    *,
    scen_id: str,
    type_origin: str,
    family: str,
    entry_point: EntryPoint,
) -> Scenario:
    """Compose one scenario from an entry point + family.

    Stimulus and intended_behaviour are derived from the family +
    entry-point metadata; both are deterministic given the same inputs.
    """
    label = _entry_label(entry_point)
    title = _FAMILY_TITLES[family].format(entry=label)
    actor = _FAMILY_ROLES[family]
    failure_modes = sf.FAMILY_TO_FAILURE_MODES[family]

    # Stimulus: a structured tuple (kind, value). Kind names mirror the
    # family but make the schema discoverable. Value is family-defaulted.
    stimulus_kind = f"{family}_default"
    stimulus_value: dict[str, Any] = {
        "entry_point": entry_point.symbol,
        "metadata": dict(entry_point.metadata),
    }
    stimulus = {"kind": stimulus_kind, "value": stimulus_value}

    # Intended behaviour: prefer the entry point's docstring when present;
    # otherwise emit a family-default phrase. Either way, walker treats
    # this as the canonical expectation.
    intended = entry_point.docstring.strip() or (
        f"Default for {family}: see family playbook in "
        f"scripts/scenario_generator/scenario_families.py (FAMILY_TO_FAILURE_MODES)."
    )

    return Scenario(
        id=scen_id,
        type_origin=type_origin,
        family=family,
        title=title,
        entry_point=entry_point,
        actor_role=actor,
        stimulus=stimulus,
        intended_behaviour=intended,
        intended_behaviour_source=entry_point.intended_behaviour_sources,
        expected_path_summary=(),  # discoverer may populate; default empty
        invariants_to_check=(),  # walker fills based on family + entry
        failure_modes_to_test=failure_modes,
        feedback_expected=None,
    )


def _load_discoverer(type_name: str):
    """Import the discoverer module for a type. Returns None on miss."""
    try:
        return importlib.import_module(f"scripts.scenario_generator.discoverers.{type_name}")
    except ModuleNotFoundError:
        return None


def _load_framework_discoverers(type_name: str) -> list[Any]:
    """Find all framework-variant discoverers for a type.

    Two resolution rules apply, both deterministic; results are unioned
    and de-duplicated by module name:

    1. **Filename prefix.** `discoverers/<type>_<framework>.py` — e.g.
       `cli_node_yargs.py` for type `cli_node`. Works when the file
       stem starts with `<type>_`.

    2. **Module-declared TYPE_ORIGIN.** Any module under `discoverers/`
       that exposes a top-level `TYPE_ORIGIN = "<type>"` constant whose
       value equals `type_name` is also a match — even if its filename
       does NOT start with `<type>_`. This supports the framework
       naming convention from TRDD-6857f67f §3.1.d where simplified
       prefixes are used (e.g. `web_node_express.py` for
       `web_service_node`, `kernel_linux_module.py` for
       `linux_kernel_module`).

    Returns modules sorted by name for deterministic ordering. The
    bare type-named module (if it exists) is excluded — that one is
    loaded separately by _load_discoverer.
    """
    discoverers_dir = Path(__file__).parent / "discoverers"
    if not discoverers_dir.is_dir():
        return []

    candidates: set[str] = set()

    # Rule 1 — filename prefix.
    prefix = f"{type_name}_"
    for f in discoverers_dir.glob(f"{prefix}*.py"):
        stem = f.stem
        if stem.startswith("_"):
            continue
        if stem == type_name:
            continue
        candidates.add(stem)

    # Rule 2 — TYPE_ORIGIN attribute. Scan every .py under discoverers/
    # (cheap — directory is small) and probe-load. Cost: O(discoverers).
    # Each module's import is memoised by importlib, so the second
    # invocation is free.
    for f in discoverers_dir.glob("*.py"):
        stem = f.stem
        if stem.startswith("_"):
            continue
        if stem == type_name:
            continue
        if stem in candidates:
            continue
        mod = _load_discoverer(stem)
        if mod is None:
            continue
        declared = getattr(mod, "TYPE_ORIGIN", None)
        if declared == type_name:
            candidates.add(stem)

    mods: list[Any] = []
    for stem in sorted(candidates):
        mod = _load_discoverer(stem)
        if mod is not None:
            mods.append(mod)
    return mods


def _discover_entry_points(type_name: str, repo_root: Path, languages: tuple[str, ...]) -> list[EntryPoint]:
    """Dispatch to the per-type discoverer; fall back to unknown_software.

    Resolution order (deterministic):
    1. `discoverers/<type_name>.py` — bare type-named module if present.
    2. `discoverers/<type_name>_<framework>.py` — every framework-variant
       module, scanned alphabetically. Results are concatenated.
    3. `discoverers/unknown_software.py` — only if neither (1) nor (2)
       contributed any modules.
    """
    found: list[EntryPoint] = []
    matched_any = False

    mod = _load_discoverer(type_name)
    if mod is not None:
        matched_any = True
        found.extend(mod.discover(repo_root, list(languages)))

    for variant_mod in _load_framework_discoverers(type_name):
        matched_any = True
        found.extend(variant_mod.discover(repo_root, list(languages)))

    if not matched_any:
        fallback = _load_discoverer("unknown_software")
        if fallback is not None:
            found.extend(fallback.discover(repo_root, list(languages)))

    return found


def _detect_languages(repo_root: Path) -> tuple[str, ...]:
    """Cheap language detection by extension frequency. Deterministic.

    Returns sorted-by-name tuple — order matters for byte-identical output.
    """
    ext_to_lang = {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".java": "java",
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".cs": "csharp",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
        ".swift": "swift",
        ".m": "objc",
        ".dart": "dart",
        ".v": "verilog",
        ".sv": "verilog",
        ".vhd": "vhdl",
        ".vhdl": "vhdl",
        ".ino": "arduino",
        ".tf": "terraform",
        ".gd": "gdscript",
    }
    seen: set[str] = set()
    for f in repo_root.rglob("*"):
        if not f.is_file():
            continue
        if any(part.startswith(".") for part in f.parts):
            continue
        if any(part in {"node_modules", "vendor", "target", "dist", "build", "out"} for part in f.parts):
            continue
        lang = ext_to_lang.get(f.suffix.lower())
        if lang:
            seen.add(lang)
    return tuple(sorted(seen))


@dataclass(frozen=True)
class GenerationContext:
    repo_root: Path
    timestamp: str  # "YYYYMMDD_HHMMSS±HHMM" — local time + offset


def generate(ctx: GenerationContext) -> GeneratorOutput:
    """Top-level: detect → discover → expand families → emit GeneratorOutput.

    Determinism contract:
    - detected_types: sorted by confidence DESC, then name ASC.
    - scenarios: sorted by (type_origin, entry_point.file, entry_point.line,
      entry_point.symbol, family). IDs assigned in that order as SCEN-NNNN
      starting from 1, zero-padded to 4 digits.
    """
    repo_root = ctx.repo_root.resolve()
    detected = detect_all(repo_root)
    languages = _detect_languages(repo_root)

    # Collect (type_origin, entry_point, family) triples, dedup by triple.
    triples: list[tuple[str, EntryPoint, str]] = []
    seen_triples: set[tuple[str, str, int, str, str]] = set()

    for dt in detected:
        # Each detected type contributes scenarios proportional to its
        # discoverer's entry-point output.
        eps = _discover_entry_points(dt.type, repo_root, languages)
        applicable_families = sf.families_for_type(dt.type)
        for ep in eps:
            for family in applicable_families:
                key = (dt.type, ep.file, ep.line, ep.symbol, family)
                if key in seen_triples:
                    continue
                seen_triples.add(key)
                triples.append((dt.type, ep, family))

    # Deterministic sort for ID assignment.
    triples.sort(key=lambda t: (t[0], t[1].file, t[1].line, t[1].symbol, t[2]))

    scenarios: list[Scenario] = []
    for idx, (type_origin, ep, family) in enumerate(triples, start=1):
        scen_id = f"SCEN-{idx:04d}"
        scenarios.append(
            _make_scenario(
                scen_id=scen_id,
                type_origin=type_origin,
                family=family,
                entry_point=ep,
            )
        )

    return GeneratorOutput(
        codebase_root=repo_root,
        detected_types=detected,
        detected_languages=languages,
        scenarios=tuple(scenarios),
        generated_at_local=ctx.timestamp,
    )


def write_outputs(out: GeneratorOutput, output_dir: Path) -> tuple[Path, Path]:
    """Write scenarios.json + detected-types.json to output_dir.

    Returns (scenarios_path, detected_types_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios_path = output_dir / f"{out.generated_at_local}-scenarios.json"
    detected_path = output_dir / f"{out.generated_at_local}-detected-types.json"

    scenarios_path.write_text(
        json.dumps(out.to_json(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    detected_path.write_text(
        json.dumps(
            {
                "$schema": SCHEMA_VERSION,
                "generated_at": out.generated_at_local,
                "root": str(out.codebase_root),
                "detected_types": [t.to_json() for t in out.detected_types],
                "detected_languages": list(out.detected_languages),
            },
            indent=2,
            sort_keys=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return scenarios_path, detected_path


def _local_timestamp() -> str:
    """Local time + GMT offset, e.g. 20260511_140532+0200.

    Matches the agent-reports-location rule (TRDD requirement: never UTC,
    never `±HH:MM`).
    """
    from datetime import datetime

    now = datetime.now().astimezone()
    return now.strftime("%Y%m%d_%H%M%S%z")


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write("Usage: emit_scenarios_json.py <repo_root> <output_dir> [<timestamp_override>]\n")
        return 2
    repo_root = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    timestamp = sys.argv[3] if len(sys.argv) >= 4 else _local_timestamp()
    ctx = GenerationContext(repo_root=repo_root, timestamp=timestamp)
    out = generate(ctx)
    scenarios_path, detected_path = write_outputs(out, output_dir)
    sys.stdout.write(f"scenarios: {scenarios_path}\n")
    sys.stdout.write(f"detected:  {detected_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
