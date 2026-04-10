"""Shared fixtures for plugin structure tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def plugin_root() -> Path:
    """Return absolute path to the plugin repository root."""
    # tests/conftest.py → tests/ → plugin_root
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def plugin_json_path(plugin_root: Path) -> Path:
    return plugin_root / ".claude-plugin" / "plugin.json"


@pytest.fixture(scope="session")
def agents_dir(plugin_root: Path) -> Path:
    return plugin_root / "agents"


@pytest.fixture(scope="session")
def skills_dir(plugin_root: Path) -> Path:
    return plugin_root / "skills"


@pytest.fixture(scope="session")
def commands_dir(plugin_root: Path) -> Path:
    return plugin_root / "commands"
