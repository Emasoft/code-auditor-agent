"""Byte-identical regression test for the scenario generator.

Walks every fixture under tests/fixtures/scenario_generator/ and asserts:
1. Running emit_scenarios_json on the fixture produces output matching
   the committed expected-*.json goldens.
2. Running it twice produces byte-identical output (determinism).
3. The detected types include the expected primary type (encoded in the
   fixture directory name).

The expected-*.json files are the GOLDENS. They are committed to the
repo alongside their fixture. If the generator changes, regenerate
each fixture's goldens explicitly and review the diff before commit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "scenario_generator"

# The deterministic timestamp used for goldens. Every agent that builds
# a fixture must use this exact value; the regression test re-runs with
# the same value and asserts byte-identical output.
GOLDEN_TS = "20260511_000000+0200"


def _list_fixtures() -> list[Path]:
    """Return one Path per fixture directory under FIXTURES_DIR."""
    if not FIXTURES_DIR.exists():
        return []
    out: list[Path] = []
    for p in sorted(FIXTURES_DIR.iterdir()):
        if not p.is_dir():
            continue
        if not (p / "expected-scenarios.json").exists():
            continue
        out.append(p)
    return out


@pytest.fixture(scope="module")
def fixtures() -> list[Path]:
    return _list_fixtures()


def _run_generator(fixture_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    """Run emit_scenarios_json against the fixture; return (scenarios, detected_types)."""
    cmd = [
        sys.executable,
        "-m",
        "scripts.scenario_generator.emit_scenarios_json",
        str(fixture_dir),
        str(output_dir),
        GOLDEN_TS,
    ]
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Generator failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    scenarios = output_dir / f"{GOLDEN_TS}-scenarios.json"
    detected = output_dir / f"{GOLDEN_TS}-detected-types.json"
    assert scenarios.exists(), f"scenarios.json not written: {scenarios}"
    assert detected.exists(), f"detected-types.json not written: {detected}"
    return scenarios, detected


def test_fixtures_exist() -> None:
    """At least one fixture must exist for the regression test to be meaningful."""
    fixtures = _list_fixtures()
    assert fixtures, (
        f"No fixtures with expected-scenarios.json found under {FIXTURES_DIR}. "
        "Phase 1 of TRDD-6857f67f requires at least 10 fixtures (10 discoverers + fallback)."
    )


@pytest.mark.parametrize("fixture", _list_fixtures(), ids=lambda p: p.name)
def test_fixture_matches_golden_scenarios(fixture: Path) -> None:
    """The generator's scenarios.json on this fixture must equal the committed golden."""
    expected = fixture / "expected-scenarios.json"
    with tempfile.TemporaryDirectory() as tmp:
        scenarios, _ = _run_generator(fixture, Path(tmp))
        actual_bytes = scenarios.read_bytes()
        expected_bytes = expected.read_bytes()
    if actual_bytes != expected_bytes:
        # Provide a useful diff hint for the developer.
        actual_data = json.loads(actual_bytes.decode("utf-8"))
        expected_data = json.loads(expected_bytes.decode("utf-8"))
        actual_ids = [s["id"] for s in actual_data.get("scenarios", [])]
        expected_ids = [s["id"] for s in expected_data.get("scenarios", [])]
        pytest.fail(
            f"scenarios.json drift for fixture {fixture.name}:\n"
            f"  expected {len(expected_ids)} scenarios, got {len(actual_ids)}\n"
            f"  first expected id: {expected_ids[0] if expected_ids else '(none)'}\n"
            f"  first actual id:   {actual_ids[0] if actual_ids else '(none)'}\n"
            f"  expected types:    "
            f"{[t['type'] for t in expected_data['codebase']['detected_types']]}\n"
            f"  actual types:      "
            f"{[t['type'] for t in actual_data['codebase']['detected_types']]}"
        )


@pytest.mark.parametrize("fixture", _list_fixtures(), ids=lambda p: p.name)
def test_fixture_matches_golden_detected_types(fixture: Path) -> None:
    """The generator's detected-types.json on this fixture must equal the committed golden."""
    expected = fixture / "expected-detected-types.json"
    assert expected.exists(), f"No golden detected-types.json for {fixture.name}"
    with tempfile.TemporaryDirectory() as tmp:
        _, detected = _run_generator(fixture, Path(tmp))
        assert detected.read_bytes() == expected.read_bytes(), f"detected-types.json drift for fixture {fixture.name}"


@pytest.mark.parametrize("fixture", _list_fixtures(), ids=lambda p: p.name)
def test_two_runs_byte_identical(fixture: Path) -> None:
    """Running the generator twice on the same fixture produces byte-identical output.

    This is the determinism contract — TRDD-6857f67f §3.1.a stage 3.
    Determinism is what makes the goldens regression-testable.
    """
    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        scenarios_a, detected_a = _run_generator(fixture, Path(tmp_a))
        scenarios_b, detected_b = _run_generator(fixture, Path(tmp_b))
        assert scenarios_a.read_bytes() == scenarios_b.read_bytes(), (
            f"Two runs produced different scenarios.json for {fixture.name}"
        )
        assert detected_a.read_bytes() == detected_b.read_bytes(), (
            f"Two runs produced different detected-types.json for {fixture.name}"
        )


@pytest.mark.parametrize("fixture", _list_fixtures(), ids=lambda p: p.name)
def test_fixture_name_matches_primary_detected_type(fixture: Path) -> None:
    """The fixture directory name encodes the primary type that should be detected.

    Example: fixtures/scenario_generator/web_node_express/ → detected types
    must include `web_service_node`.
    """
    # Mapping from fixture-dir name → expected detected type. Multiple
    # fixtures may target the same type (e.g. web_node_express and
    # web_node_nextjs both expect web_service_node).
    fixture_to_type = {
        "web_python_fastapi": "web_service_python",
        "web_node_express": "web_service_node",
        "web_node_nextjs": "web_service_node",
        "web_service_dotnet": "web_service_dotnet",
        "web_service_go": "web_service_go",
        "web_service_java_kotlin": "web_service_java_kotlin",
        "web_service_php": "web_service_php",
        "web_service_ruby": "web_service_ruby",
        "web_service_rust": "web_service_rust",
        "cli_python_click": "cli_python",
        "cli_node_yargs": "cli_node",
        "cli_csharp": "cli_csharp",
        "cli_go": "cli_go",
        "cli_rust": "cli_rust",
        "data_pipeline_airflow": "data_pipeline_airflow",
        "data_pipeline_dagster": "data_pipeline_dagster",
        "data_pipeline_dbt": "data_pipeline_dbt",
        "data_pipeline_prefect": "data_pipeline_prefect",
        "desktop_electron": "desktop_electron",
        "desktop_flutter": "desktop_flutter",
        "desktop_gtk": "desktop_gtk",
        "desktop_qt": "desktop_qt",
        "desktop_tauri": "desktop_tauri",
        "library_c": "library_c",
        "library_node": "library_node",
        "library_python": "library_python",
        "library_rust": "library_rust",
        "firmware_arduino": "firmware_arduino",
        "firmware_baremetal": "firmware_baremetal",
        "firmware_espidf": "firmware_espidf",
        "firmware_nordic_sdk": "firmware_nordic_sdk",
        "firmware_platformio": "firmware_platformio",
        "firmware_stm32": "firmware_stm32",
        "firmware_zephyr": "firmware_zephyr",
        "browser_ext_chrome": "browser_ext_chrome",
        "browser_ext_firefox": "browser_ext_firefox",
        "browser_ext_safari": "browser_ext_safari",
        "bsd_kernel": "bsd_kernel",
        "linux_kernel_module": "linux_kernel_module",
        "linux_kernel_tree": "linux_kernel_tree",
        "macos_kernel_ext": "macos_kernel_ext",
        "os_baremetal": "os_baremetal",
        "windows_kernel_driver": "windows_kernel_driver",
        "driver_linux_userspace": "driver_linux_userspace",
        "fpga_verilog": "fpga_verilog",
        "fpga_vhdl": "fpga_vhdl",
        "asic_design": "asic_design",
        "game_engine": "game_engine",
        "game_godot": "game_godot",
        "game_unity": "game_unity",
        "game_unreal": "game_unreal",
        "ml_training": "ml_training",
        "mobile_android": "mobile_android",
        "mobile_flutter": "mobile_flutter",
        "mobile_ios": "mobile_ios",
        "mobile_kotlin_multiplatform": "mobile_kotlin_multiplatform",
        "mobile_reactnative": "mobile_reactnative",
        "rtos_chibios": "rtos_chibios",
        "rtos_freertos": "rtos_freertos",
        "rtos_threadx": "rtos_threadx",
        "rtos_zephyr": "rtos_zephyr",
        "iac_ansible": "iac_ansible",
        "iac_cloudformation": "iac_cloudformation",
        "iac_docker_compose": "iac_docker_compose",
        "iac_helm": "iac_helm",
        "iac_k8s_operator": "iac_k8s_operator",
        "iac_kustomize": "iac_kustomize",
        "iac_pulumi": "iac_pulumi",
        "iac_terraform": "iac_terraform",
        "unknown_software": "unknown_software",
    }
    expected_type = fixture_to_type.get(fixture.name)
    if expected_type is None:
        pytest.skip(f"No expected primary type registered for fixture {fixture.name}")
    expected = json.loads((fixture / "expected-detected-types.json").read_text())
    types = [t["type"] for t in expected["detected_types"]]
    assert expected_type in types, f"Fixture {fixture.name} expected {expected_type} but detected: {types}"


def test_known_types_mirror_consistent() -> None:
    """The mirror in scenario_families._KNOWN_TYPES must equal detect_software_type.ALL_TYPES.

    Import-time check in detect_software_type asserts this too, but the
    unit test makes the contract explicit and catches drift in PRs.
    """
    from scripts.scenario_generator import scenario_families as sf
    from scripts.scenario_generator.detect_software_type import ALL_TYPES

    assert ALL_TYPES == sf._KNOWN_TYPES, (
        f"Drift between registries: only_in_detect={ALL_TYPES - sf._KNOWN_TYPES}, "
        f"only_in_families={sf._KNOWN_TYPES - ALL_TYPES}"
    )


def test_family_to_failure_modes_complete() -> None:
    """Every family in FAMILY_TO_TYPES must have an entry in FAMILY_TO_FAILURE_MODES."""
    from scripts.scenario_generator import scenario_families as sf

    types_keys = set(sf.FAMILY_TO_TYPES)
    modes_keys = set(sf.FAMILY_TO_FAILURE_MODES)
    assert types_keys == modes_keys, (
        f"Drift: only_in_types={sorted(types_keys - modes_keys)}, only_in_modes={sorted(modes_keys - types_keys)}"
    )


# Sanity guard — ensure shutil import is referenced so the linter doesn't
# remove it; we use it in conditional cleanup paths in future evolutions.
_ = shutil
