"""Validate .claude-plugin/plugin.json manifest structure and consistency.

These tests enforce that the plugin manifest:
  - exists and is valid JSON
  - has the required fields (name, version, description, author)
  - uses semantic versioning
  - matches the version declared in pyproject.toml
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?(?:\+[\w.]+)?$")


@pytest.fixture(scope="module")
def plugin_json(plugin_json_path: Path) -> dict:
    """Load and parse plugin.json once per module."""
    assert plugin_json_path.exists(), (
        f"plugin.json not found at {plugin_json_path}"
    )
    return json.loads(plugin_json_path.read_text(encoding="utf-8"))


def test_plugin_json_is_valid_json(plugin_json_path: Path) -> None:
    """plugin.json must parse as valid JSON."""
    assert plugin_json_path.is_file()
    json.loads(plugin_json_path.read_text(encoding="utf-8"))


def test_plugin_json_has_required_fields(plugin_json: dict) -> None:
    """plugin.json must declare name, version, description, author."""
    for field in ("name", "version", "description", "author"):
        assert field in plugin_json, f"Missing required field: {field}"
        assert plugin_json[field], f"Empty required field: {field}"


def test_plugin_name_matches_directory(
    plugin_json: dict, plugin_root: Path,
) -> None:
    """plugin.json name must match the repo directory name."""
    assert plugin_json["name"] == plugin_root.name


def test_plugin_version_is_semver(plugin_json: dict) -> None:
    """plugin.json version must be semver X.Y.Z."""
    version = plugin_json["version"]
    assert SEMVER_RE.match(version), (
        f"Version '{version}' is not valid semver"
    )


def test_plugin_version_matches_pyproject(
    plugin_json: dict, plugin_root: Path,
) -> None:
    """plugin.json version must match pyproject.toml version."""
    pyproject_path = plugin_root / "pyproject.toml"
    assert pyproject_path.exists()
    with pyproject_path.open("rb") as f:
        pyproject = tomllib.load(f)
    pyproject_version = pyproject["project"]["version"]
    assert plugin_json["version"] == pyproject_version, (
        f"Version mismatch: plugin.json={plugin_json['version']}, "
        f"pyproject.toml={pyproject_version}"
    )


def test_plugin_author_has_name_and_email(plugin_json: dict) -> None:
    """plugin.json author must be an object with name and email."""
    author = plugin_json["author"]
    assert isinstance(author, dict), "author must be an object"
    assert "name" in author and author["name"]
    assert "email" in author and author["email"]
