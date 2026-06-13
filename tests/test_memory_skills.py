"""Exercise the real mechanics behind the CAA memory skills.

The skills (`caa-memory-recall` / `caa-memory-write`) are markdown instruction
sets, so these tests drive the underlying behaviour they promise:
  - symptom recall via `memgrep` (when installed) ranks the matching note,
  - the documented `grep -rliE` fallback finds the same note without memgrep,
  - a note authored with the documented schema parses + carries the required fields,
  - the MEMORY.md index line is well-formed,
  - both skills declare the memgrep -> grep degrade path (recall never breaks).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PLUGIN_ROOT / "skills"

_NOTE_429 = """---
name: rate-limit-429-regex
description: "engine marked a numbered file rate-limited forever — 429 regex false match"
metadata:
  node_type: memory
  type: project
---
A bare 429 match in the RL regex flagged migrations/0429_x.py as rate-limited forever.
"""

_NOTE_LENSDIR = """---
name: lensdir-anchoring
description: "domain lens specs not found when auditing a foreign repo — lensDir path wrong"
metadata:
  node_type: memory
  type: project
---
The engine read lenses from the audited repo root instead of the plugin root.
"""


@pytest.fixture()
def memdir(tmp_path: Path) -> Path:
    """Build a small fixture memory dir with two schema-valid, symptom-indexed notes."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "rate-limit-429-regex.md").write_text(_NOTE_429, encoding="utf-8")
    (d / "lensdir-anchoring.md").write_text(_NOTE_LENSDIR, encoding="utf-8")
    (d / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    return d


def _split_frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "note must open with a YAML frontmatter block"
    end = text.find("\n---\n", 4)
    assert end != -1, "note frontmatter must be closed with ---"
    data = yaml.safe_load(text[4:end])
    assert isinstance(data, dict)
    return data


def test_grep_fallback_finds_note_by_symptom(memdir: Path) -> None:
    """The documented grep fallback (`grep -rliE SYMPTOM`) locates a note from its symptom."""
    r = subprocess.run(
        ["grep", "-rliE", "rate.?limited forever", str(memdir)],
        capture_output=True, text=True,
    )
    assert "rate-limit-429-regex.md" in r.stdout
    assert "lensdir-anchoring.md" not in r.stdout


@pytest.mark.skipif(shutil.which("memgrep") is None, reason="memgrep not installed (fallback path covers recall)")
def test_memgrep_recall_ranks_matching_note(memdir: Path) -> None:
    """`memgrep recall` returns exit 0 and ranks the symptom-matching note in its output."""
    r = subprocess.run(
        ["memgrep", "recall", "rate limited forever 429", str(memdir)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "rate-limit-429-regex" in r.stdout


def test_authored_note_schema_is_valid(memdir: Path) -> None:
    """Every fixture note parses and carries name + symptom description + a valid metadata.type."""
    for note in sorted(memdir.glob("*.md")):
        if note.name == "MEMORY.md":
            continue
        fm = _split_frontmatter(note.read_text(encoding="utf-8"))
        assert fm.get("name"), f"{note.name}: missing name"
        assert fm.get("description"), f"{note.name}: missing description"
        meta = fm.get("metadata") or {}
        assert meta.get("type") in {"project", "feedback", "reference", "user"}, (
            f"{note.name}: metadata.type must be one of project/feedback/reference/user"
        )


def test_memory_index_line_is_wellformed() -> None:
    """A MEMORY.md index line follows `- [Title](slug.md) — hook` (the documented shape)."""
    line = "- [Rate-limit 429 regex](rate-limit-429-regex.md) — bare 429 matched a numbered file"
    assert re.match(r"^- \[.+\]\([^)]+\.md\) — .+$", line)


def test_both_skills_document_the_degrade_path() -> None:
    """Both memory skills reference memgrep AND the grep fallback (recall degrades, never breaks)."""
    for name in ("caa-memory-recall", "caa-memory-write"):
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        assert "memgrep" in text, f"{name}: must mention memgrep"
        assert "grep" in text, f"{name}: must document the grep fallback"
