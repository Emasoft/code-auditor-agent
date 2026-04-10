"""Validate every agent definition file conforms to the plugin spec.

The Claude Code plugin spec defines these valid agent frontmatter fields:
  name, description, model, disallowedTools, effort, isolation,
  maxTurns, background, memory, permissionMode, initialPrompt

Any unknown field in an agent's YAML frontmatter is a violation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Valid frontmatter fields per Claude Code plugin spec
VALID_AGENT_FIELDS = {
    "name",
    "description",
    "model",
    "disallowedTools",
    "effort",
    "isolation",
    "maxTurns",
    "background",
    "memory",
    "permissionMode",
    "initialPrompt",
}

# Valid values for specific fields
VALID_MODELS = {"opus", "sonnet", "haiku"}
VALID_EFFORT = {"low", "medium", "high"}
VALID_ISOLATION = {"worktree"}
VALID_PERMISSION_MODES = {
    "default", "acceptEdits", "plan", "bypassPermissions",
}


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Return (frontmatter_dict, body) or (None, text) if no frontmatter."""
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


def _collect_agent_files(agents_dir: Path) -> list[Path]:
    if not agents_dir.is_dir():
        return []
    return sorted(agents_dir.glob("*.md"))


@pytest.fixture(scope="module")
def agent_files(agents_dir: Path) -> list[Path]:
    files = _collect_agent_files(agents_dir)
    assert files, f"No agent files found in {agents_dir}"
    return files


def test_agents_directory_exists(agents_dir: Path) -> None:
    assert agents_dir.is_dir(), f"{agents_dir} is not a directory"


def test_every_agent_has_frontmatter(agent_files: list[Path]) -> None:
    """Every agent .md file must have a YAML frontmatter block."""
    for agent_file in agent_files:
        text = agent_file.read_text(encoding="utf-8")
        fm, _ = _split_frontmatter(text)
        assert fm is not None, (
            f"{agent_file.name} has no YAML frontmatter"
        )


def test_agent_frontmatter_fields_are_valid(
    agent_files: list[Path],
) -> None:
    """No agent frontmatter may contain fields outside the plugin spec."""
    violations: list[str] = []
    for agent_file in agent_files:
        text = agent_file.read_text(encoding="utf-8")
        fm, _ = _split_frontmatter(text)
        assert fm is not None
        unknown = set(fm.keys()) - VALID_AGENT_FIELDS
        if unknown:
            violations.append(
                f"{agent_file.name}: unknown fields {sorted(unknown)}",
            )
    assert not violations, (
        "Agent frontmatter violations:\n  " + "\n  ".join(violations)
    )


def test_agent_required_fields_present(
    agent_files: list[Path],
) -> None:
    """Every agent must declare name and description."""
    for agent_file in agent_files:
        fm, _ = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        assert fm is not None
        assert "name" in fm and fm["name"], (
            f"{agent_file.name}: missing name"
        )
        assert "description" in fm and fm["description"], (
            f"{agent_file.name}: missing description"
        )


def test_agent_name_matches_filename(
    agent_files: list[Path],
) -> None:
    """Agent name field must match the filename stem."""
    for agent_file in agent_files:
        fm, _ = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        assert fm is not None
        assert fm["name"] == agent_file.stem, (
            f"{agent_file.name}: name '{fm['name']}' != "
            f"filename '{agent_file.stem}'"
        )


def test_agent_model_values_are_valid(
    agent_files: list[Path],
) -> None:
    """Model must be opus, sonnet, or haiku if present."""
    for agent_file in agent_files:
        fm, _ = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        assert fm is not None
        if "model" in fm:
            assert fm["model"] in VALID_MODELS, (
                f"{agent_file.name}: invalid model '{fm['model']}'"
            )


def test_agent_effort_values_are_valid(
    agent_files: list[Path],
) -> None:
    """Effort must be low, medium, or high if present."""
    for agent_file in agent_files:
        fm, _ = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        assert fm is not None
        if "effort" in fm:
            assert fm["effort"] in VALID_EFFORT, (
                f"{agent_file.name}: invalid effort '{fm['effort']}'"
            )


def test_agent_maxturns_is_positive_int(
    agent_files: list[Path],
) -> None:
    """maxTurns must be a positive integer if present."""
    for agent_file in agent_files:
        fm, _ = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        assert fm is not None
        if "maxTurns" in fm:
            value = fm["maxTurns"]
            assert isinstance(value, int) and value > 0, (
                f"{agent_file.name}: maxTurns must be positive int, "
                f"got {value!r}"
            )


def test_read_only_agents_disallow_edit(
    agent_files: list[Path],
) -> None:
    """Read-only agents must disallow Edit and NotebookEdit.

    The fix-agent is the only agent that should have write access.
    """
    for agent_file in agent_files:
        if agent_file.stem == "caa-fix-agent":
            continue  # fix-agent is allowed to edit
        fm, _ = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        assert fm is not None
        disallowed = fm.get("disallowedTools", []) or []
        assert "Edit" in disallowed, (
            f"{agent_file.name}: must disallow Edit"
        )
        assert "NotebookEdit" in disallowed, (
            f"{agent_file.name}: must disallow NotebookEdit"
        )
