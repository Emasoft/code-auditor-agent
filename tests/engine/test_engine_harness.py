"""Bridge the node-based engine tests into the pytest gate.

The ultracode engine (scripts/workflows/caa-engine.js) is a Workflow-DSL script; its
deterministic tests live in run_engine_tests.mjs and execute the REAL engine body with a
scripted agent() boundary. This bridge makes `uv run pytest` (and therefore the publish
gate) fail whenever an engine regression slips in. node is a hard requirement — fail fast
rather than silently skipping the engine's only deterministic coverage.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "tests" / "engine" / "run_engine_tests.mjs"


def test_engine_mock_dsl_suite() -> None:
    """The full node mock-DSL engine suite (run_engine_tests.mjs) passes: exit code 0."""
    node = shutil.which("node")
    assert node is not None, (
        "node is required to test scripts/workflows/caa-engine.js — install Node.js; "
        "skipping would leave the engine's orchestration logic untested"
    )
    proc = subprocess.run(
        [node, str(RUNNER)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, (
        f"engine test suite failed (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "All green." in proc.stdout
