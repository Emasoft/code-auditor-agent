"""Validate every SKILL.md file conforms to the plugin spec.

Tests enforce:
  - SKILL.md exists for every skill directory
  - Frontmatter has required fields (name, description, version)
  - Version matches plugin.json
  - description <= 250 chars (Claude Code v2.1.86 cap)
  - SKILL.md body <= 4000 chars (progressive disclosure bar)
  - Every referenced reference file actually exists
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

MAX_DESCRIPTION_CHARS = 250
MAX_SKILL_BODY_CHARS = 4000
REFERENCE_LINK_RE = re.compile(r"\[[^\]]+\]\((references/[^)]+\.md)\)")


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
def skill_files(skills_dir: Path) -> list[Path]:
    assert skills_dir.is_dir(), f"{skills_dir} is not a directory"
    files = sorted(skills_dir.glob("*/SKILL.md"))
    assert files, f"No SKILL.md files found under {skills_dir}"
    return files


@pytest.fixture(scope="module")
def plugin_version(plugin_json_path: Path) -> str:
    data = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    return data["version"]


def test_every_skill_has_skill_md(skills_dir: Path) -> None:
    """Every subdirectory under skills/ must contain a SKILL.md."""
    subdirs = [p for p in skills_dir.iterdir() if p.is_dir()]
    assert subdirs, f"No skill subdirectories under {skills_dir}"
    for subdir in subdirs:
        skill_md = subdir / "SKILL.md"
        assert skill_md.is_file(), (
            f"Missing {skill_md.relative_to(skills_dir)}"
        )


def test_skill_required_frontmatter_fields(
    skill_files: list[Path],
) -> None:
    """Each SKILL.md must declare name, description, version."""
    for skill_file in skill_files:
        fm, _ = _split_frontmatter(skill_file.read_text(encoding="utf-8"))
        assert fm is not None, f"{skill_file}: no frontmatter"
        for field in ("name", "description", "version"):
            assert field in fm and fm[field], (
                f"{skill_file.parent.name}: missing field '{field}'"
            )


def test_skill_version_matches_plugin(
    skill_files: list[Path], plugin_version: str,
) -> None:
    """Each SKILL.md version must match plugin.json version."""
    for skill_file in skill_files:
        fm, _ = _split_frontmatter(skill_file.read_text(encoding="utf-8"))
        assert fm is not None
        # SKILL.md version may be a YAML float or a string like "3.2.17"
        skill_version = str(fm["version"])
        assert skill_version == plugin_version, (
            f"{skill_file.parent.name}: version {skill_version} "
            f"!= plugin.json {plugin_version}"
        )


def test_skill_description_within_cap(
    skill_files: list[Path],
) -> None:
    """Description must be <= 250 chars (Claude Code v2.1.86 cap)."""
    for skill_file in skill_files:
        fm, _ = _split_frontmatter(skill_file.read_text(encoding="utf-8"))
        assert fm is not None
        desc = str(fm["description"]).strip()
        assert len(desc) <= MAX_DESCRIPTION_CHARS, (
            f"{skill_file.parent.name}: description is "
            f"{len(desc)} chars (max {MAX_DESCRIPTION_CHARS})"
        )


def test_skill_body_within_progressive_disclosure_cap(
    skill_files: list[Path],
) -> None:
    """SKILL.md body (post-frontmatter) must be <= 4000 chars."""
    for skill_file in skill_files:
        _, body = _split_frontmatter(skill_file.read_text(encoding="utf-8"))
        size = len(body)
        assert size <= MAX_SKILL_BODY_CHARS, (
            f"{skill_file.parent.name}: SKILL.md body is {size} chars "
            f"(max {MAX_SKILL_BODY_CHARS})"
        )


def test_skill_reference_links_resolve(
    skill_files: list[Path],
) -> None:
    """Every references/*.md link in SKILL.md must point to an existing file."""
    broken: list[str] = []
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        skill_dir = skill_file.parent
        for match in REFERENCE_LINK_RE.finditer(text):
            rel_path = match.group(1)
            target = skill_dir / rel_path
            if not target.is_file():
                broken.append(
                    f"{skill_file.parent.name}: {rel_path}",
                )
    assert not broken, (
        "Broken reference links:\n  " + "\n  ".join(broken)
    )
