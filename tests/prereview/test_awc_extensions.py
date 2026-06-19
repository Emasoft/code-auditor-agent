"""Unit tests for Step 11 — AWC extensions (deps + hardcoded config)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import awc_extensions as awc


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- Python deps -----------------------------------------------------------


def test_optional_dependencies_table_parsed() -> None:
    """PEP-621 [project.optional-dependencies] / PEP-735 [dependency-groups]
    TABLE form (the dominant uv/PEP-621 shape) must be parsed — its entries are
    keyed by the extra/group name, not 'dependencies', so the trigger gate alone
    missed them (MAJ-05). Covers single-line and multi-line table entries.
    """
    text = (
        "[project]\n"
        'dependencies = ["requests"]\n'
        "\n"
        "[project.optional-dependencies]\n"
        'dev = ["pytest", "ruff"]\n'
        "test = [\n"
        '    "coverage",\n'
        "]\n"
    )
    deps = awc._parse_pyproject_dependencies(text)
    assert "requests" in deps  # main deps still parsed
    assert "pytest" in deps
    assert "ruff" in deps
    assert "coverage" in deps  # multi-line table entry


def test_undeclared_python_dep_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["requests"]\n',
    )
    _write(
        tmp_path / "app.py",
        "import requests\nimport pandas\nprint(requests, pandas)\n",
    )
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    assert any("pandas" in f["message"] for f in undeclared)
    # `requests` IS declared — should not be flagged.
    assert not any("`import requests`" in f["message"] for f in undeclared)


def test_unused_python_dep_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["requests", "left-pad"]\n',
    )
    _write(tmp_path / "app.py", "import requests\nprint(requests)\n")
    result = awc.detect(tmp_path)
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_DEP"]
    names = {f["message"].split("`")[1] for f in unused}
    assert "left-pad" in names
    assert "requests" not in names


def test_python_import_to_dist_mapping(tmp_path: Path) -> None:
    """`import yaml` should match a `pyyaml` declaration."""
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["pyyaml"]\n',
    )
    _write(tmp_path / "app.py", "import yaml\nprint(yaml)\n")
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_DEP"]
    assert not undeclared
    assert not unused


def test_python_stdlib_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["requests"]\n',
    )
    _write(
        tmp_path / "app.py",
        "import os\nimport sys\nimport json\nimport requests\nprint(requests)\n",
    )
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    assert not undeclared


def test_python_relative_imports_skipped(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "x"\ndependencies = []\n',
    )
    _write(tmp_path / "app.py", "from . import helpers\n")
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    assert not undeclared


# ---- Node deps -------------------------------------------------------------


def test_undeclared_node_dep_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "package.json",
        '{"name":"x","dependencies":{"lodash":"^4"}}\n',
    )
    _write(
        tmp_path / "app.ts",
        "import lodash from 'lodash';\nimport axios from 'axios';\n",
    )
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    assert any("axios" in f["message"] for f in undeclared)
    assert not any("lodash" in f["message"] for f in undeclared)


def test_unused_node_dep_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "package.json",
        '{"name":"x","dependencies":{"lodash":"^4","unused-lib":"^1"}}\n',
    )
    _write(tmp_path / "app.ts", "import lodash from 'lodash';\n")
    result = awc.detect(tmp_path)
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_DEP"]
    assert any("unused-lib" in f["message"] for f in unused)


def test_node_builtin_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "package.json",
        '{"name":"x","dependencies":{}}\n',
    )
    _write(
        tmp_path / "app.ts",
        "import fs from 'fs';\nimport path from 'node:path';\n",
    )
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    assert not undeclared


def test_node_scoped_pkg_root(tmp_path: Path) -> None:
    """`@anthropic-ai/sdk` should match the package.json key `@anthropic-ai/sdk`."""
    _write(
        tmp_path / "package.json",
        '{"name":"x","dependencies":{"@anthropic-ai/sdk":"^0"}}\n',
    )
    _write(
        tmp_path / "app.ts",
        "import Anthropic from '@anthropic-ai/sdk';\n",
    )
    result = awc.detect(tmp_path)
    undeclared = [f for f in result["findings"] if f["code"] == "UNDECLARED_DEP"]
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_DEP"]
    assert not undeclared
    assert not unused


# ---- hardcoded config ------------------------------------------------------


def test_hardcoded_url_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "URL = 'https://api.production.com/v1'\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_URL" in codes


def test_hardcoded_url_in_example_com_not_flagged(tmp_path: Path) -> None:
    """`example.com` is a doc/test convention — agents shouldn't be scolded for it."""
    _write(tmp_path / "app.py", "URL = 'https://example.com'\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_URL" not in codes


def test_hardcoded_ip_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "IP = '192.168.1.10'\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_IP" in codes


def test_hardcoded_path_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "LOG = '/var/log/myapp/app.log'\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_PATH" in codes


def test_hardcoded_path_in_tmp_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "TMP = '/tmp/somefile'\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_PATH" not in codes


def test_hardcoded_port_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "config = { 'port': 5432 }\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_PORT" in codes


def test_magic_number_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "TIMEOUT = 30000\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MAGIC_NUMBER" in codes


def test_common_http_codes_not_flagged_as_magic(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "STATUS = 200\nNOT_FOUND = 404\n")
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MAGIC_NUMBER" not in codes


def test_comment_lines_skipped_for_hardcoded(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "# example URL: https://prod.com/x\nx = 1\n",
    )
    result = awc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HARDCODED_URL" not in codes


# ---- determinism + CLI -----------------------------------------------------


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\ndependencies = []\n')
    _write(tmp_path / "a.py", "URL = 'https://api.prod.com/x'\n")
    _write(tmp_path / "b.py", "URL = 'https://api.staging.com/y'\n")
    r1 = awc.detect(tmp_path)
    r2 = awc.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "pyproject.toml", '[project]\nname = "x"\ndependencies = ["requests"]\n')
    _write(repo / "app.py", "import requests\nprint(requests)\n")
    rc = awc.main(["awc_extensions", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert "manifest_dep_counts" in body
