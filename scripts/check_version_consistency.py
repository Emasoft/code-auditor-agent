#!/usr/bin/env python3
"""Check that version in .claude-plugin/plugin.json matches version in pyproject.toml."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    """Walk up from start directory until .claude-plugin/plugin.json is found."""
    current = start.resolve()
    while True:
        candidate = current / ".claude-plugin" / "plugin.json"
        if candidate.exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "Could not find .claude-plugin/plugin.json in any parent directory"
            )
        current = parent


def read_plugin_version(project_root: Path) -> str:
    """Read version field from .claude-plugin/plugin.json."""
    plugin_json = project_root / ".claude-plugin" / "plugin.json"
    with plugin_json.open(encoding="utf-8") as f:
        data = json.load(f)
    version = data.get("version")
    if not version:
        raise ValueError(f"No 'version' field found in {plugin_json}")
    return str(version)


def read_pyproject_version(project_root: Path) -> str:
    """Read version from pyproject.toml using regex (no toml dependency)."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")
    text = pyproject.read_text(encoding="utf-8")
    # Match version = "x.y.z" in the [project] or [tool.poetry] section
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        raise ValueError(f"No version field found in {pyproject}")
    return match.group(1)


def main() -> int:
    script_dir = Path(__file__).parent
    try:
        project_root = find_project_root(script_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        plugin_version = read_plugin_version(project_root)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR reading plugin.json: {e}", file=sys.stderr)
        return 1

    try:
        pyproject_version = read_pyproject_version(project_root)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR reading pyproject.toml: {e}", file=sys.stderr)
        return 1

    if plugin_version == pyproject_version:
        print(f"OK: versions are consistent ({plugin_version})")
        return 0
    else:
        print(
            f"MISMATCH: plugin.json={plugin_version}, pyproject.toml={pyproject_version}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
