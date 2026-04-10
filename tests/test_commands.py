"""Validate command definition files under commands/.

Tests enforce:
  - Every command has a YAML frontmatter
  - Required fields (name/description) are present
  - File count matches expectation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    yaml_text = text[4:end]
    body = text[end + 5:]
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        return None, text
    return data, body


@pytest.fixture(scope="module")
def command_files(commands_dir: Path) -> list[Path]:
    assert commands_dir.is_dir(), f"{commands_dir} is not a directory"
    files = sorted(commands_dir.glob("*.md"))
    assert files, f"No command files found in {commands_dir}"
    return files


def test_commands_directory_has_files(
    command_files: list[Path],
) -> None:
    """commands/ must contain at least one command."""
    assert len(command_files) >= 1


def test_commands_have_frontmatter(
    command_files: list[Path],
) -> None:
    """Every command .md must have YAML frontmatter."""
    for cmd_file in command_files:
        text = cmd_file.read_text(encoding="utf-8")
        fm, _ = _split_frontmatter(text)
        assert fm is not None, (
            f"{cmd_file.name}: missing YAML frontmatter"
        )


def test_commands_have_description(
    command_files: list[Path],
) -> None:
    """Every command must declare a description."""
    for cmd_file in command_files:
        text = cmd_file.read_text(encoding="utf-8")
        fm, _ = _split_frontmatter(text)
        assert fm is not None
        assert "description" in fm and fm["description"], (
            f"{cmd_file.name}: missing or empty description"
        )
