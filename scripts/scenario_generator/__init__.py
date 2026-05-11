"""Scenario generator engine for caa-scenario-generator-skill.

Public surface:
    detect_software_type.detect_all(repo_root) -> list[DetectedType]
    discoverers.<type>.discover(repo_root, languages) -> list[EntryPoint]
    scenario_families.FAMILY_TO_TYPES / FAMILY_TO_FAILURE_MODES
    emit_scenarios_json.emit(detected, entry_points) -> dict (scenarios.json)
    emit_scenarios_md.emit(scenarios_json) -> str

Deterministic at every step. Two runs on the same codebase MUST produce
byte-identical scenarios.json and detected-types.json. See TRDD-6857f67f.
"""
