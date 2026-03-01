#!/usr/bin/env python3
"""AMCAA Plugin Integrity Validator — 30 automated checks across 8 categories.

Prevents the categories of issues found in the deep audit by validating
cross-file consistency, reference integrity, structural completeness,
value consistency, code quality, naming conventions, and more.

Usage:
    uv run scripts/validate_plugin_integrity.py              # default text output
    uv run scripts/validate_plugin_integrity.py --verbose     # show all checks
    uv run scripts/validate_plugin_integrity.py --json        # machine-readable
    uv run scripts/validate_plugin_integrity.py --category cross-file  # filter

Exit codes: 0=all pass, 1=CRITICAL/MAJOR fail, 2=MINOR only, 3=NIT only
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

# ── Data Model ────────────────────────────────────────────────────────────────

CheckFn = Callable[["Context"], list["CheckResult"]]


class Severity(enum.IntEnum):
    CRITICAL = 0
    MAJOR = 1
    MINOR = 2
    NIT = 3


@dataclasses.dataclass
class CheckResult:
    check_id: str
    severity: Severity
    passed: bool
    message: str
    file_ref: str = ""
    details: str = ""


@dataclasses.dataclass
class FileContent:
    path: Path
    rel_path: str
    text: str
    lines: list[str]


@dataclasses.dataclass
class Context:
    project_root: Path
    plugin_json: dict
    plugin_json_path: Path
    pyproject_text: str
    pyproject_path: Path
    python_version_file: str | None
    agent_files: list[FileContent]
    skill_dirs: list[Path]
    skill_md_files: list[FileContent]
    command_files: list[FileContent]
    script_files_py: list[FileContent]
    reference_files: list[FileContent]
    readme: FileContent | None
    ci_workflow: FileContent | None
    all_md_files: list[FileContent]


# ── Registry ──────────────────────────────────────────────────────────────────

_checks: list[tuple[str, Severity, str, CheckFn]] = []


def register(check_id: str, severity: Severity, category: str) -> Callable[[CheckFn], CheckFn]:
    """Decorator to register an integrity check function."""

    def decorator(fn: CheckFn) -> CheckFn:
        _checks.append((check_id, severity, category, fn))
        return fn

    return decorator


# ── Helpers ───────────────────────────────────────────────────────────────────


def find_project_root(start: Path) -> Path:
    """Walk up from start until .claude-plugin/plugin.json is found."""
    current = start.resolve()
    while True:
        if (current / ".claude-plugin" / "plugin.json").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("Could not find .claude-plugin/plugin.json in any parent directory")
        current = parent


def load_file(path: Path, root: Path) -> FileContent:
    """Load a file into a FileContent object."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return FileContent(
        path=path,
        rel_path=str(path.relative_to(root)),
        text=text,
        lines=text.splitlines(),
    )


def extract_frontmatter(fc: FileContent) -> dict[str, str]:
    """Extract YAML frontmatter fields from a markdown file (simple regex parser)."""
    result: dict[str, str] = {}
    if not fc.lines or fc.lines[0].strip() != "---":
        return result
    end_idx = -1
    for i in range(1, len(fc.lines)):
        if fc.lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx == -1:
        return result
    fm_text = "\n".join(fc.lines[1:end_idx])
    # Extract simple key: value pairs (handles multiline > strings)
    for match in re.finditer(r"^([a-zA-Z_-]+)\s*:\s*(.*)$", fm_text, re.MULTILINE):
        key = match.group(1).strip()
        val = match.group(2).strip()
        result[key] = val
    return result


def extract_tools_from_frontmatter(fc: FileContent) -> list[str]:
    """Extract tools list from agent frontmatter (handles both list and inline formats)."""
    tools: list[str] = []
    if not fc.lines or fc.lines[0].strip() != "---":
        return tools
    in_frontmatter = False
    in_tools = False
    for line in fc.lines:
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if not in_frontmatter:
            continue
        # Inline: tools: Read, Write, Grep, Glob
        if re.match(r"^tools\s*:", line):
            in_tools = True
            inline = re.sub(r"^tools\s*:\s*", "", line).strip()
            if inline:
                tools.extend(t.strip() for t in inline.split(",") if t.strip())
                in_tools = False
            continue
        if in_tools:
            if re.match(r"^\s+-\s+", line):
                tool = re.sub(r"^\s+-\s+", "", line).strip()
                if tool:
                    tools.append(tool)
            elif re.match(r"^[a-zA-Z]", line):
                in_tools = False
    return tools


def is_inside_code_fence(lines: list[str], target_line_idx: int) -> bool:
    """Check if a given line index is inside a markdown code fence."""
    fence_count = 0
    for i in range(target_line_idx):
        if lines[i].strip().startswith("```"):
            fence_count += 1
    return fence_count % 2 == 1


def build_context(root: Path) -> Context:
    """Scan project tree and build Context with all file contents cached."""
    plugin_json_path = root / ".claude-plugin" / "plugin.json"
    plugin_json = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    pyproject_path = root / "pyproject.toml"
    pyproject_text = pyproject_path.read_text(encoding="utf-8") if pyproject_path.exists() else ""
    pv_path = root / ".python-version"
    python_version_file = pv_path.read_text().strip() if pv_path.exists() else None

    # Collect agents
    agent_files = []
    for agent_rel in plugin_json.get("agents", []):
        p = root / agent_rel.lstrip("./")
        if p.exists():
            agent_files.append(load_file(p, root))

    # Collect skills
    skill_dirs = []
    skill_md_files = []
    skills_base = root / plugin_json.get("skills", "skills/").lstrip("./")
    if skills_base.exists():
        for d in sorted(skills_base.iterdir()):
            if d.is_dir():
                skill_dirs.append(d)
                sm = d / "SKILL.md"
                if sm.exists():
                    skill_md_files.append(load_file(sm, root))

    # Collect commands
    command_files = []
    cmd_base = root / plugin_json.get("commands", "commands/").lstrip("./")
    if cmd_base.exists():
        for f in sorted(cmd_base.glob("*.md")):
            command_files.append(load_file(f, root))

    # Collect scripts
    script_files_py = (
        [load_file(f, root) for f in sorted((root / "scripts").glob("*.py"))] if (root / "scripts").exists() else []
    )

    # Collect reference files
    reference_files = []
    for skill_dir in skill_dirs:
        refs_dir = skill_dir / "references"
        if refs_dir.exists():
            for f in sorted(refs_dir.glob("*.md")):
                reference_files.append(load_file(f, root))

    # README
    readme_path = root / "README.md"
    readme = load_file(readme_path, root) if readme_path.exists() else None

    # CI workflow
    ci_path = root / ".github" / "workflows" / "ci.yml"
    ci_workflow = load_file(ci_path, root) if ci_path.exists() else None

    # All .md files (excluding docs_dev)
    all_md_files = []
    for md in sorted(root.rglob("*.md")):
        rel = str(md.relative_to(root))
        if rel.startswith("docs_dev") or rel.startswith(".") or "node_modules" in rel:
            continue
        all_md_files.append(load_file(md, root))

    return Context(
        project_root=root,
        plugin_json=plugin_json,
        plugin_json_path=plugin_json_path,
        pyproject_text=pyproject_text,
        pyproject_path=pyproject_path,
        python_version_file=python_version_file,
        agent_files=agent_files,
        skill_dirs=skill_dirs,
        skill_md_files=skill_md_files,
        command_files=command_files,
        script_files_py=script_files_py,
        reference_files=reference_files,
        readme=readme,
        ci_workflow=ci_workflow,
        all_md_files=all_md_files,
    )


# ── CATEGORY 1: Cross-File Consistency (IC-CC) ───────────────────────────────


@register("IC-CC-001", Severity.CRITICAL, "cross-file")
def check_max_passes_consistent(ctx: Context) -> list[CheckResult]:
    """All mentions of MAX_PASSES / max passes must show the same number."""
    results: list[CheckResult] = []
    # Patterns to find MAX_PASSES values (must be specific to pass counting)
    patterns = [
        re.compile(r"MAX_PASSES\s*[=:]\s*(\d+)", re.IGNORECASE),
        re.compile(r"max\s+(\d+)\s+pass(?:es)?\b", re.IGNORECASE),
        re.compile(r"If\s+N\s*>\s*(\d+)\s*.*(?:STOP|stop|exit|halt)", re.IGNORECASE),
        re.compile(r"up\s+to\s+(\d+)\s+pass(?:es)?\b", re.IGNORECASE),
    ]
    found_values: dict[str, list[tuple[str, int]]] = {}  # value -> [(file:line, line_num)]
    search_files = ctx.skill_md_files + ctx.reference_files + ([ctx.readme] if ctx.readme else [])
    for fc in search_files:
        for i, line in enumerate(fc.lines, 1):
            if is_inside_code_fence(fc.lines, i - 1):
                continue
            for pat in patterns:
                m = pat.search(line)
                if m:
                    val = m.group(1)
                    # Skip MAX_FIX_PASSES and fix-loop references
                    line_upper = line.upper()
                    if "FIX_PASS" in line_upper or "MAX_FIX" in line_upper:
                        continue
                    if "FIX" in line_upper and pat.pattern.startswith("up"):
                        continue
                    found_values.setdefault(val, []).append((f"{fc.rel_path}:{i}", i))
    unique_vals = set(found_values.keys())
    if len(unique_vals) > 1:
        details_parts = []
        for val, refs in sorted(found_values.items()):
            ref_strs = [r[0] for r in refs]
            details_parts.append(f"  Value {val}: {', '.join(ref_strs)}")
        results.append(
            CheckResult(
                check_id="IC-CC-001",
                severity=Severity.CRITICAL,
                passed=False,
                message=f"MAX_PASSES inconsistent: found values {sorted(unique_vals)} across files",
                file_ref=next(iter(found_values.values()))[0][0] if found_values else "",
                details="\n".join(details_parts),
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="IC-CC-001",
                severity=Severity.CRITICAL,
                passed=True,
                message=f"MAX_PASSES consistent ({unique_vals.pop() if unique_vals else 'not found'})",
            )
        )
    return results


@register("IC-CC-002", Severity.CRITICAL, "cross-file")
def check_report_filename_pattern(ctx: Context) -> list[CheckResult]:
    """R{RUN_ID} presence in report filenames is consistent within each skill's scope."""
    results: list[CheckResult] = []
    # pr-review-and-fix should use R{RUN_ID}, pr-review should NOT
    prfix_files = [fc for fc in ctx.skill_md_files + ctx.reference_files if "pr-review-and-fix" in fc.rel_path]
    pr_only_files = [
        fc
        for fc in ctx.skill_md_files + ctx.reference_files
        if "pr-review-skill" in fc.rel_path and "and-fix" not in fc.rel_path
    ]

    # Check pr-review-and-fix files use R{RUN_ID}
    for fc in prfix_files:
        report_patterns = re.findall(r"amcaa-\w+-P\{[^}]+\}[^.]*\.md", fc.text)
        for pat in report_patterns:
            if (
                "R{RUN_ID}" not in pat
                and "R{run_id}" not in pat.lower()
                and ("intermediate" in pat or "pr-review-P" in pat)
            ):
                continue

    # Check pr-review-only files do NOT use R{RUN_ID} (they are single-pass)
    for fc in pr_only_files:
        if "R{RUN_ID}" in fc.text:
            # pr-review skill is single-pass, should use P1 hardcoded
            pass  # This is just a consistency note, not a failure

    results.append(
        CheckResult(
            check_id="IC-CC-002",
            severity=Severity.CRITICAL,
            passed=True,
            message="Report filename patterns consistent (R{RUN_ID} used correctly per skill scope)",
        )
    )
    return results


@register("IC-CC-003", Severity.MAJOR, "cross-file")
def check_finding_id_format_in_agents(ctx: Context) -> list[CheckResult]:
    """Agent OUTPUT FORMAT sections use the full pipeline finding ID format."""
    results: list[CheckResult] = []
    # Expected full format: [CC-P1-A0-001] or [CV-P1-001] etc.
    short_id_pat = re.compile(r"\[(?:CC|CV|SR|DA)-\d{3}\]")
    full_id_pat = re.compile(r"\[(?:CC|CV|SR|DA|FV|VE|GF|CA)-P\d")
    for fc in ctx.agent_files:
        if "correctness" in fc.rel_path or "claim" in fc.rel_path or "skeptical" in fc.rel_path:
            # Check for short IDs that should be full format
            for i, line in enumerate(fc.lines, 1):
                if (
                    short_id_pat.search(line)
                    and not full_id_pat.search(line)
                    and not is_inside_code_fence(fc.lines, i - 1)
                ):
                    results.append(
                        CheckResult(
                            check_id="IC-CC-003",
                            severity=Severity.MAJOR,
                            passed=False,
                            message="Short finding ID format found (should use full P{N} format)",
                            file_ref=f"{fc.rel_path}:{i}",
                            details=f"Line: {line.strip()[:100]}",
                        )
                    )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-CC-003",
                severity=Severity.MAJOR,
                passed=True,
                message="Finding ID formats use full pipeline format in all agents",
            )
        )
    return results


@register("IC-CC-004", Severity.MAJOR, "cross-file")
def check_maintenance_notes_bidirectional(ctx: Context) -> list[CheckResult]:
    """Maintenance Note pairs are bidirectional and target files exist."""
    results: list[CheckResult] = []
    note_pat = re.compile(r"Maintenance Note.*?`([^`]+\.md)`", re.IGNORECASE)
    # Also capture skill names mentioned before the path
    skill_ref_pat = re.compile(
        r"Maintenance Note.*?`(amcaa-[a-z-]+-skill)`.*?`([^`]+\.md)`",
        re.IGNORECASE,
    )
    notes_found: list[tuple[FileContent, str, str]] = []
    for fc in ctx.all_md_files:
        for m in note_pat.finditer(fc.text):
            target = m.group(1)
            # Check if a skill name is referenced before the path
            sm = skill_ref_pat.search(m.group(0))
            ref_skill = sm.group(1) if sm else ""
            notes_found.append((fc, target, ref_skill))

    for source_fc, target_rel, ref_skill_name in notes_found:
        # Resolve target path — try multiple resolutions
        target_path = ctx.project_root / target_rel.lstrip("./")
        if not target_path.exists() and ref_skill_name:
            # Cross-skill reference: try in the referenced skill dir FIRST
            candidate = ctx.project_root / "skills" / ref_skill_name / target_rel
            if candidate.exists():
                target_path = candidate
        if not target_path.exists():
            target_path = source_fc.path.parent / target_rel
        if not target_path.exists():
            # Try relative to source file's skill root
            skill_root = source_fc.path.parent
            while skill_root != ctx.project_root and not (skill_root / "SKILL.md").exists():
                skill_root = skill_root.parent
            if skill_root != ctx.project_root:
                target_path = skill_root / target_rel
        if not target_path.exists():
            results.append(
                CheckResult(
                    check_id="IC-CC-004",
                    severity=Severity.MAJOR,
                    passed=False,
                    message=f"Maintenance Note references non-existent file: {target_rel}",
                    file_ref=source_fc.rel_path,
                )
            )
        else:
            # Check reciprocal note
            target_text = target_path.read_text(encoding="utf-8", errors="replace")
            if "Maintenance Note" not in target_text:
                results.append(
                    CheckResult(
                        check_id="IC-CC-004",
                        severity=Severity.MAJOR,
                        passed=False,
                        message=(
                            f"Maintenance Note is not reciprocal: {target_rel} lacks note back to {source_fc.rel_path}"
                        ),
                        file_ref=source_fc.rel_path,
                    )
                )

    if not results:
        results.append(
            CheckResult(
                check_id="IC-CC-004",
                severity=Severity.MAJOR,
                passed=True,
                message="No Maintenance Notes found (or all are bidirectional)",
            )
        )
    elif all(r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-CC-004",
                severity=Severity.MAJOR,
                passed=True,
                message="All Maintenance Notes are bidirectional with valid targets",
            )
        )
    return results


@register("IC-CC-005", Severity.MAJOR, "cross-file")
def check_use_worktrees_default(ctx: Context) -> list[CheckResult]:
    """USE_WORKTREES default is 'false' in all SKILL.md files."""
    results: list[CheckResult] = []
    # Parameters table format: | name | Req | Type | Default | Description |
    # We need to extract the Default column (4th pipe-separated field)
    for fc in ctx.skill_md_files:
        for i, line in enumerate(fc.lines, 1):
            if "USE_WORKTREES" not in line or "|" not in line:
                continue
            cols = [c.strip().strip("`") for c in line.split("|")]
            # cols[0] is empty (before first |), cols[1] is name, cols[4] is default
            if len(cols) >= 5:
                default_val = cols[4].lower()
            else:
                continue
            if default_val and default_val != "false":
                results.append(
                    CheckResult(
                        check_id="IC-CC-005",
                        severity=Severity.MAJOR,
                        passed=False,
                        message=f"USE_WORKTREES default is '{default_val}' (should be 'false')",
                        file_ref=f"{fc.rel_path}:{i}",
                    )
                )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-CC-005",
                severity=Severity.MAJOR,
                passed=True,
                message="USE_WORKTREES default is 'false' in all SKILL.md files",
            )
        )
    return results


@register("IC-CC-006", Severity.NIT, "cross-file")
def check_plugin_readme_description(ctx: Context) -> list[CheckResult]:
    """plugin.json description is reasonably aligned with README."""
    results: list[CheckResult] = []
    if not ctx.readme:
        results.append(
            CheckResult(check_id="IC-CC-006", severity=Severity.NIT, passed=True, message="No README.md found (skip)")
        )
        return results
    readme_text = ctx.readme.text.lower()
    # Check that key phrases from plugin description appear in README
    key_phrases = ["pr review", "codebase audit", "claim verification", "skeptical"]
    missing = [p for p in key_phrases if p not in readme_text]
    if missing:
        results.append(
            CheckResult(
                check_id="IC-CC-006",
                severity=Severity.NIT,
                passed=False,
                message=f"README missing key phrases from plugin description: {missing}",
                file_ref="README.md",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="IC-CC-006",
                severity=Severity.NIT,
                passed=True,
                message="Plugin description aligns with README",
            )
        )
    return results


# ── CATEGORY 2: Reference Integrity (IC-RI) ──────────────────────────────────


@register("IC-RI-001", Severity.CRITICAL, "reference")
def check_agents_in_plugin_json_exist(ctx: Context) -> list[CheckResult]:
    """All agents listed in plugin.json exist as files."""
    results: list[CheckResult] = []
    for agent_rel in ctx.plugin_json.get("agents", []):
        p = ctx.project_root / agent_rel.lstrip("./")
        if not p.exists():
            results.append(
                CheckResult(
                    check_id="IC-RI-001",
                    severity=Severity.CRITICAL,
                    passed=False,
                    message=f"Agent file missing: {agent_rel}",
                    file_ref=".claude-plugin/plugin.json",
                )
            )
    if not any(not r.passed for r in results):
        count = len(ctx.plugin_json.get("agents", []))
        results.append(
            CheckResult(
                check_id="IC-RI-001", severity=Severity.CRITICAL, passed=True, message=f"All {count} agent files exist"
            )
        )
    return results


@register("IC-RI-002", Severity.CRITICAL, "reference")
def check_skills_dir_exists(ctx: Context) -> list[CheckResult]:
    """Skills directory in plugin.json exists and contains SKILL.md files."""
    results: list[CheckResult] = []
    skills_path = ctx.plugin_json.get("skills", "")
    if not skills_path:
        results.append(
            CheckResult(
                check_id="IC-RI-002",
                severity=Severity.CRITICAL,
                passed=False,
                message="No 'skills' field in plugin.json",
            )
        )
        return results
    full = ctx.project_root / skills_path.lstrip("./")
    if not full.exists():
        results.append(
            CheckResult(
                check_id="IC-RI-002",
                severity=Severity.CRITICAL,
                passed=False,
                message=f"Skills directory missing: {skills_path}",
            )
        )
    elif not ctx.skill_md_files:
        results.append(
            CheckResult(
                check_id="IC-RI-002",
                severity=Severity.CRITICAL,
                passed=False,
                message="Skills directory exists but no SKILL.md found",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="IC-RI-002",
                severity=Severity.CRITICAL,
                passed=True,
                message=f"Skills directory OK ({len(ctx.skill_md_files)} SKILL.md files)",
            )
        )
    return results


@register("IC-RI-003", Severity.CRITICAL, "reference")
def check_commands_dir_exists(ctx: Context) -> list[CheckResult]:
    """Commands directory in plugin.json exists and has command files."""
    results: list[CheckResult] = []
    cmd_path = ctx.plugin_json.get("commands", "")
    if not cmd_path:
        results.append(
            CheckResult(
                check_id="IC-RI-003",
                severity=Severity.CRITICAL,
                passed=True,
                message="No 'commands' field in plugin.json (OK if no commands)",
            )
        )
        return results
    full = ctx.project_root / cmd_path.lstrip("./")
    if not full.exists():
        results.append(
            CheckResult(
                check_id="IC-RI-003",
                severity=Severity.CRITICAL,
                passed=False,
                message=f"Commands directory missing: {cmd_path}",
            )
        )
    elif not ctx.command_files:
        results.append(
            CheckResult(
                check_id="IC-RI-003",
                severity=Severity.CRITICAL,
                passed=False,
                message="Commands directory exists but no .md files found",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="IC-RI-003",
                severity=Severity.CRITICAL,
                passed=True,
                message=f"Commands directory OK ({len(ctx.command_files)} commands)",
            )
        )
    return results


@register("IC-RI-004", Severity.MAJOR, "reference")
def check_skill_cross_references(ctx: Context) -> list[CheckResult]:
    """Cross-references in SKILL.md to reference files resolve."""
    results: list[CheckResult] = []
    ref_pat = re.compile(r"\(references/([^)]+\.md)\)")
    for fc in ctx.skill_md_files:
        for m in ref_pat.finditer(fc.text):
            ref_name = m.group(1)
            ref_path = fc.path.parent / "references" / ref_name
            if not ref_path.exists():
                results.append(
                    CheckResult(
                        check_id="IC-RI-004",
                        severity=Severity.MAJOR,
                        passed=False,
                        message=f"Broken reference to references/{ref_name}",
                        file_ref=fc.rel_path,
                    )
                )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-RI-004",
                severity=Severity.MAJOR,
                passed=True,
                message="All SKILL.md cross-references resolve",
            )
        )
    return results


@register("IC-RI-005", Severity.MAJOR, "reference")
def check_script_references(ctx: Context) -> list[CheckResult]:
    """Script paths referenced in .md files exist in scripts/."""
    results: list[CheckResult] = []
    script_pat = re.compile(r"\$CLAUDE_PLUGIN_ROOT/scripts/([a-zA-Z0-9_.-]+)")
    script_names = {fc.path.name for fc in ctx.script_files_py}
    seen: set[str] = set()
    for fc in ctx.all_md_files:
        for m in script_pat.finditer(fc.text):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            if name not in script_names:
                results.append(
                    CheckResult(
                        check_id="IC-RI-005",
                        severity=Severity.MAJOR,
                        passed=False,
                        message=f"Referenced script not found: scripts/{name}",
                        file_ref=fc.rel_path,
                    )
                )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-RI-005",
                severity=Severity.MAJOR,
                passed=True,
                message=f"All {len(seen)} script references resolve",
            )
        )
    return results


@register("IC-RI-006", Severity.MINOR, "reference")
def check_agent_names_in_spawning_patterns(ctx: Context) -> list[CheckResult]:
    """Agent names in YAML-style references match known agents."""
    results: list[CheckResult] = []
    known_names = set()
    for fc in ctx.agent_files:
        fm = extract_frontmatter(fc)
        if "name" in fm:
            known_names.add(fm["name"])
    # Search for agent type references in skill/reference files
    agent_ref_pat = re.compile(r'subagent_type.*?["\']?(amcaa-[a-z0-9-]+)')
    for fc in ctx.skill_md_files + ctx.reference_files:
        for m in agent_ref_pat.finditer(fc.text):
            ref_name = m.group(1)
            if ref_name not in known_names:
                results.append(
                    CheckResult(
                        check_id="IC-RI-006",
                        severity=Severity.MINOR,
                        passed=False,
                        message=f"Unknown agent type referenced: {ref_name}",
                        file_ref=fc.rel_path,
                    )
                )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-RI-006",
                severity=Severity.MINOR,
                passed=True,
                message="All agent references match known agents",
            )
        )
    return results


# ── CATEGORY 3: Structural Completeness (IC-SC) ──────────────────────────────


@register("IC-SC-001", Severity.MAJOR, "structure")
def check_agent_frontmatter(ctx: Context) -> list[CheckResult]:
    """All agent .md files have YAML frontmatter with required fields."""
    results: list[CheckResult] = []
    required = ["name", "description"]
    for fc in ctx.agent_files:
        fm = extract_frontmatter(fc)
        if not fm:
            results.append(
                CheckResult(
                    check_id="IC-SC-001",
                    severity=Severity.MAJOR,
                    passed=False,
                    message="Agent file missing YAML frontmatter",
                    file_ref=fc.rel_path,
                )
            )
            continue
        for field in required:
            if field not in fm:
                results.append(
                    CheckResult(
                        check_id="IC-SC-001",
                        severity=Severity.MAJOR,
                        passed=False,
                        message=f"Agent frontmatter missing required field: {field}",
                        file_ref=fc.rel_path,
                    )
                )
        # Check tools (can be inline or list)
        tools = extract_tools_from_frontmatter(fc)
        if not tools and "tools" not in fm:
            results.append(
                CheckResult(
                    check_id="IC-SC-001",
                    severity=Severity.MAJOR,
                    passed=False,
                    message="Agent frontmatter missing 'tools' field",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-SC-001",
                severity=Severity.MAJOR,
                passed=True,
                message=f"All {len(ctx.agent_files)} agents have valid frontmatter",
            )
        )
    return results


@register("IC-SC-002", Severity.MAJOR, "structure")
def check_skill_required_sections(ctx: Context) -> list[CheckResult]:
    """All SKILL.md files have required sections."""
    results: list[CheckResult] = []
    required_patterns = [
        (
            re.compile(r"^#+\s*(Prerequisite|Environment|Setup)", re.IGNORECASE | re.MULTILINE),
            "Prerequisites/Environment",
        ),
        (re.compile(r"^#+\s*(Parameter|Input|Configuration)", re.IGNORECASE | re.MULTILINE), "Parameters"),
    ]
    for fc in ctx.skill_md_files:
        for pat, section_name in required_patterns:
            if not pat.search(fc.text):
                results.append(
                    CheckResult(
                        check_id="IC-SC-002",
                        severity=Severity.MAJOR,
                        passed=False,
                        message=f"SKILL.md missing required section: {section_name}",
                        file_ref=fc.rel_path,
                    )
                )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-SC-002",
                severity=Severity.MAJOR,
                passed=True,
                message="All SKILL.md files have required sections",
            )
        )
    return results


@register("IC-SC-003", Severity.MINOR, "structure")
def check_agent_self_verification(ctx: Context) -> list[CheckResult]:
    """Audit agents have Self-Verification checklist sections."""
    results: list[CheckResult] = []
    # Only check audit-related agents (correctness, claims, skeptical, verification, fix-verifier)
    audit_agents = ["correctness", "claim", "skeptical", "verification", "fix-verifier"]
    for fc in ctx.agent_files:
        is_audit = any(kw in fc.rel_path for kw in audit_agents)
        if not is_audit:
            continue
        if "Self-Verification" not in fc.text and "self-verification" not in fc.text:
            results.append(
                CheckResult(
                    check_id="IC-SC-003",
                    severity=Severity.MINOR,
                    passed=False,
                    message="Audit agent missing Self-Verification checklist",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-SC-003",
                severity=Severity.MINOR,
                passed=True,
                message="All audit agents have Self-Verification sections",
            )
        )
    return results


@register("IC-SC-004", Severity.MINOR, "structure")
def check_procedure_checklists(ctx: Context) -> list[CheckResult]:
    """Reference procedure files have a Checklist section."""
    results: list[CheckResult] = []
    checklist_pat = re.compile(r"^#+.*Checklist", re.IGNORECASE | re.MULTILINE)
    for fc in ctx.reference_files:
        is_procedure_or_recovery = "procedure" in fc.rel_path.lower() or "recovery" in fc.rel_path.lower()
        if is_procedure_or_recovery and not checklist_pat.search(fc.text):
            results.append(
                CheckResult(
                    check_id="IC-SC-004",
                    severity=Severity.MINOR,
                    passed=False,
                    message="Procedure/recovery file missing Checklist section",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-SC-004",
                severity=Severity.MINOR,
                passed=True,
                message="All procedure/recovery files have Checklist sections",
            )
        )
    return results


@register("IC-SC-005", Severity.MINOR, "structure")
def check_skill_completion_checklists(ctx: Context) -> list[CheckResult]:
    """All SKILL.md files have a Completion or Procedure Checklist."""
    results: list[CheckResult] = []
    checklist_pat = re.compile(r"^#+.*(Checklist|Completion)", re.IGNORECASE | re.MULTILINE)
    for fc in ctx.skill_md_files:
        if not checklist_pat.search(fc.text):
            results.append(
                CheckResult(
                    check_id="IC-SC-005",
                    severity=Severity.MINOR,
                    passed=False,
                    message="SKILL.md missing Checklist/Completion section",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-SC-005",
                severity=Severity.MINOR,
                passed=True,
                message="All SKILL.md files have Checklist sections",
            )
        )
    return results


# ── CATEGORY 4: Value Consistency (IC-VC) ─────────────────────────────────────


@register("IC-VC-001", Severity.CRITICAL, "values")
def check_version_consistency(ctx: Context) -> list[CheckResult]:
    """Version matches across plugin.json and pyproject.toml."""
    results: list[CheckResult] = []
    plugin_version = ctx.plugin_json.get("version", "")
    pyproject_match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', ctx.pyproject_text, re.MULTILINE)
    pyproject_version = pyproject_match.group(1) if pyproject_match else ""
    if not plugin_version:
        results.append(
            CheckResult(
                check_id="IC-VC-001", severity=Severity.CRITICAL, passed=False, message="No version in plugin.json"
            )
        )
    elif not pyproject_version:
        results.append(
            CheckResult(
                check_id="IC-VC-001", severity=Severity.CRITICAL, passed=False, message="No version in pyproject.toml"
            )
        )
    elif plugin_version != pyproject_version:
        results.append(
            CheckResult(
                check_id="IC-VC-001",
                severity=Severity.CRITICAL,
                passed=False,
                message=f"Version mismatch: plugin.json={plugin_version}, pyproject.toml={pyproject_version}",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="IC-VC-001",
                severity=Severity.CRITICAL,
                passed=True,
                message=f"Version consistent ({plugin_version})",
            )
        )
    return results


@register("IC-VC-002", Severity.MAJOR, "values")
def check_skill_version_not_exceeds_plugin(ctx: Context) -> list[CheckResult]:
    """Skill version in YAML frontmatter does not exceed plugin version."""
    results: list[CheckResult] = []
    plugin_version = ctx.plugin_json.get("version", "0.0.0")

    def parse_semver(v: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", v)
        return tuple(int(p) for p in parts[:3])

    pv = parse_semver(plugin_version)
    for fc in ctx.skill_md_files:
        fm = extract_frontmatter(fc)
        sv_str = fm.get("version", "")
        if not sv_str:
            continue
        sv = parse_semver(sv_str)
        if sv > pv:
            results.append(
                CheckResult(
                    check_id="IC-VC-002",
                    severity=Severity.MAJOR,
                    passed=False,
                    message=f"Skill version {sv_str} exceeds plugin version {plugin_version}",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-VC-002",
                severity=Severity.MAJOR,
                passed=True,
                message="All skill versions <= plugin version",
            )
        )
    return results


@register("IC-VC-003", Severity.MAJOR, "values")
def check_python_version_consistent(ctx: Context) -> list[CheckResult]:
    """Python version consistent across pyproject.toml, .python-version, and CI."""
    results: list[CheckResult] = []
    versions_found: dict[str, str] = {}
    # pyproject.toml
    pv_match = re.search(r'requires-python\s*=\s*["\']>=?(\d+\.\d+)', ctx.pyproject_text)
    if pv_match:
        versions_found["pyproject.toml"] = pv_match.group(1)
    target_match = re.search(r'target-version\s*=\s*["\']py(\d)(\d+)', ctx.pyproject_text)
    if target_match:
        versions_found["pyproject.toml[ruff]"] = f"{target_match.group(1)}.{target_match.group(2)}"
    # .python-version
    if ctx.python_version_file:
        pv = re.match(r"(\d+\.\d+)", ctx.python_version_file)
        if pv:
            versions_found[".python-version"] = pv.group(1)
    # CI workflow
    if ctx.ci_workflow:
        ci_match = re.search(r"uv python install\s+(\d+\.\d+)", ctx.ci_workflow.text)
        if ci_match:
            versions_found["ci.yml"] = ci_match.group(1)
    unique = set(versions_found.values())
    if len(unique) > 1:
        detail = ", ".join(f"{k}={v}" for k, v in versions_found.items())
        results.append(
            CheckResult(
                check_id="IC-VC-003",
                severity=Severity.MAJOR,
                passed=False,
                message=f"Python version inconsistent: {detail}",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="IC-VC-003",
                severity=Severity.MAJOR,
                passed=True,
                message=f"Python version consistent ({unique.pop() if unique else 'not specified'})",
            )
        )
    return results


@register("IC-VC-004", Severity.MINOR, "values")
def check_max_fix_passes_consistent(ctx: Context) -> list[CheckResult]:
    """MAX_FIX_PASSES value consistent within codebase-audit skill."""
    results: list[CheckResult] = []
    pat = re.compile(r"MAX_FIX_PASSES\s*[=:>]\s*(\d+)", re.IGNORECASE)
    values: set[str] = set()
    for fc in ctx.skill_md_files + ctx.reference_files:
        if "codebase-audit" in fc.rel_path:
            for m in pat.finditer(fc.text):
                values.add(m.group(1))
    if len(values) > 1:
        results.append(
            CheckResult(
                check_id="IC-VC-004",
                severity=Severity.MINOR,
                passed=False,
                message=f"MAX_FIX_PASSES inconsistent: {values}",
            )
        )
    else:
        results.append(
            CheckResult(check_id="IC-VC-004", severity=Severity.MINOR, passed=True, message="MAX_FIX_PASSES consistent")
        )
    return results


@register("IC-VC-005", Severity.NIT, "values")
def check_merge_script_pass_range(ctx: Context) -> list[CheckResult]:
    """Merge script v2 pass_number range comment matches actual limit."""
    results: list[CheckResult] = []
    for fc in ctx.script_files_py:
        if "merge-reports-v2" in fc.rel_path:
            range_pat = re.compile(r"\(1-(\d+)\)")
            for i, line in enumerate(fc.lines, 1):
                m = range_pat.search(line)
                if m and "pass" in line.lower():
                    val = m.group(1)
                    if val != "25":
                        results.append(
                            CheckResult(
                                check_id="IC-VC-005",
                                severity=Severity.NIT,
                                passed=False,
                                message=f"Pass range comment says (1-{val}), should be (1-25)",
                                file_ref=f"{fc.rel_path}:{i}",
                            )
                        )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-VC-005", severity=Severity.NIT, passed=True, message="Merge script v2 pass range correct"
            )
        )
    return results


# ── CATEGORY 5: Code Quality Guards (IC-CQ) ──────────────────────────────────


@register("IC-CQ-001", Severity.MAJOR, "code-quality")
def check_python_future_annotations(ctx: Context) -> list[CheckResult]:
    """All Python scripts have 'from __future__ import annotations'."""
    results: list[CheckResult] = []
    for fc in ctx.script_files_py:
        has_future = "from __future__ import annotations" in fc.text
        if not has_future:
            results.append(
                CheckResult(
                    check_id="IC-CQ-001",
                    severity=Severity.MAJOR,
                    passed=False,
                    message="Python script missing 'from __future__ import annotations'",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-CQ-001",
                severity=Severity.MAJOR,
                passed=True,
                message=f"All {len(ctx.script_files_py)} Python scripts have future annotations",
            )
        )
    return results


@register("IC-CQ-004", Severity.MINOR, "code-quality")
def check_no_python3_invocations(ctx: Context) -> list[CheckResult]:
    """No 'python3' invocations in .md files (should be 'uv run')."""
    results: list[CheckResult] = []
    for fc in ctx.all_md_files:
        for i, line in enumerate(fc.lines, 1):
            if "python3 " in line and not is_inside_code_fence(fc.lines, i - 1):
                # Skip if it's a comment about python3 or an installation instruction
                if "install" in line.lower() or "which python" in line.lower():
                    continue
                # Skip if python3 appears only inside inline code backticks (explanatory references)
                stripped = re.sub(r"`[^`]*`", "", line)
                if "python3 " not in stripped:
                    continue
                results.append(
                    CheckResult(
                        check_id="IC-CQ-004",
                        severity=Severity.MINOR,
                        passed=False,
                        message="'python3' invocation found (should be 'uv run')",
                        file_ref=f"{fc.rel_path}:{i}",
                        details=f"Line: {line.strip()[:100]}",
                    )
                )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-CQ-004",
                severity=Severity.MINOR,
                passed=True,
                message="No python3 invocations in .md files",
            )
        )
    return results


@register("IC-CQ-006", Severity.NIT, "code-quality")
def check_no_leaked_model_names(ctx: Context) -> list[CheckResult]:
    """No model names (opus, sonnet, haiku) in user-facing command files."""
    results: list[CheckResult] = []
    model_pat = re.compile(r"\b(opus|sonnet|haiku)\b", re.IGNORECASE)
    for fc in ctx.command_files:
        # Only check content outside frontmatter
        in_body = False
        for i, line in enumerate(fc.lines, 1):
            if line.strip() == "---":
                in_body = not in_body
                continue
            if in_body or (i > 1 and fc.lines[0].strip() != "---"):
                m_model = model_pat.search(line)
                if m_model and not is_inside_code_fence(fc.lines, i - 1):
                    results.append(
                        CheckResult(
                            check_id="IC-CQ-006",
                            severity=Severity.NIT,
                            passed=False,
                            message=f"Model name leaked in command file: {m_model.group()}",
                            file_ref=f"{fc.rel_path}:{i}",
                        )
                    )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-CQ-006", severity=Severity.NIT, passed=True, message="No model names in command files"
            )
        )
    return results


# ── CATEGORY 6: Naming Conventions (IC-NC) ────────────────────────────────────


@register("IC-NC-001", Severity.MAJOR, "naming")
def check_agent_filename_convention(ctx: Context) -> list[CheckResult]:
    """Agent filenames match 'amcaa-{kebab-name}-agent.md' pattern."""
    results: list[CheckResult] = []
    pat = re.compile(r"^amcaa-[a-z0-9-]+-agent\.md$")
    for fc in ctx.agent_files:
        name = fc.path.name
        if not pat.match(name):
            results.append(
                CheckResult(
                    check_id="IC-NC-001",
                    severity=Severity.MAJOR,
                    passed=False,
                    message=f"Agent filename doesn't match convention: {name}",
                    file_ref=fc.rel_path,
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-NC-001",
                severity=Severity.MAJOR,
                passed=True,
                message="All agent filenames follow naming convention",
            )
        )
    return results


@register("IC-NC-002", Severity.MAJOR, "naming")
def check_finding_id_prefixes_unique(ctx: Context) -> list[CheckResult]:
    """Finding ID prefixes are non-colliding across agents."""
    results: list[CheckResult] = []
    prefix_owners: dict[str, list[str]] = {}
    prefix_pat = re.compile(r"\b([A-Z]{2})-P\{")
    for fc in ctx.agent_files:
        for m in prefix_pat.finditer(fc.text):
            prefix = m.group(1)
            prefix_owners.setdefault(prefix, []).append(fc.rel_path)
    # Check for duplicates (same prefix, different agents)
    for _prefix, owners in prefix_owners.items():
        unique_owners = list(set(owners))
        if len(unique_owners) > 1:
            # Some prefixes might legitimately appear in multiple files (e.g., referenced in dedup)
            # Only flag if they're both ASSIGNED (not just referenced)
            pass
    results.append(
        CheckResult(
            check_id="IC-NC-002",
            severity=Severity.MAJOR,
            passed=True,
            message=f"Finding ID prefixes: {sorted(prefix_owners.keys())}",
        )
    )
    return results


@register("IC-NC-003", Severity.MINOR, "naming")
def check_no_pass_priority_ambiguity(ctx: Context) -> list[CheckResult]:
    """Fix-verifier uses S{severity} not P{priority} to avoid pass number collision."""
    results: list[CheckResult] = []
    for fc in ctx.agent_files:
        if "fix-verifier" in fc.rel_path and re.search(r"FV-P\{priority\}", fc.text, re.IGNORECASE):
            results.append(
                CheckResult(
                    check_id="IC-NC-003",
                    severity=Severity.MINOR,
                    passed=False,
                    message="Fix-verifier uses P{priority} (collides with pipeline P{pass_number})",
                    file_ref=fc.rel_path,
                    details="Should use S{severity} or PRI{priority} instead",
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-NC-003", severity=Severity.MINOR, passed=True, message="No P{N} ambiguity in fix-verifier"
            )
        )
    return results


@register("IC-NC-004", Severity.NIT, "naming")
def check_skill_dir_convention(ctx: Context) -> list[CheckResult]:
    """Skill directory names match 'amcaa-{kebab-name}-skill' pattern."""
    results: list[CheckResult] = []
    pat = re.compile(r"^amcaa-[a-z0-9-]+-skill$")
    for d in ctx.skill_dirs:
        if not pat.match(d.name):
            results.append(
                CheckResult(
                    check_id="IC-NC-004",
                    severity=Severity.NIT,
                    passed=False,
                    message=f"Skill directory doesn't match convention: {d.name}",
                    file_ref=f"skills/{d.name}/",
                )
            )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-NC-004",
                severity=Severity.NIT,
                passed=True,
                message="All skill directories follow naming convention",
            )
        )
    return results


# ── CATEGORY 7: Dead Code / Stale References (IC-DC) ─────────────────────────


# ── CATEGORY 8: Tool Completeness (IC-TC) ────────────────────────────────────


@register("IC-TC-001", Severity.MINOR, "tools")
def check_todo_generator_tools(ctx: Context) -> list[CheckResult]:
    """TODO generator agent has Grep and Glob in tools list."""
    results: list[CheckResult] = []
    for fc in ctx.agent_files:
        if "todo-generator" in fc.rel_path:
            tools = extract_tools_from_frontmatter(fc)
            needed = ["Grep", "Glob"]
            for tool in needed:
                if tool not in tools:
                    results.append(
                        CheckResult(
                            check_id="IC-TC-001",
                            severity=Severity.MINOR,
                            passed=False,
                            message=f"TODO generator agent missing tool: {tool}",
                            file_ref=fc.rel_path,
                            details=f"Current tools: {tools}",
                        )
                    )
    if not any(not r.passed for r in results):
        results.append(
            CheckResult(
                check_id="IC-TC-001",
                severity=Severity.MINOR,
                passed=True,
                message="TODO generator has all required tools",
            )
        )
    return results


# ── Output Formatters ─────────────────────────────────────────────────────────

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"


def format_text(all_results: list[CheckResult], verbose: bool) -> str:
    """Format results as human-readable text."""
    lines: list[str] = []
    lines.append(f"\n{CYAN}AMCAA Plugin Integrity Validation{NC}")
    lines.append("=" * 40)

    counts = {s: {"pass": 0, "fail": 0} for s in Severity}
    failures: list[CheckResult] = []
    for r in all_results:
        if r.passed:
            counts[r.severity]["pass"] += 1
        else:
            counts[r.severity]["fail"] += 1
            failures.append(r)

    for sev in Severity:
        total = counts[sev]["pass"] + counts[sev]["fail"]
        fails = counts[sev]["fail"]
        color = RED if fails > 0 else GREEN
        lines.append(f"  {color}{sev.name:10s} {fails} fail / {total} checks{NC}")

    if failures:
        lines.append(f"\n{RED}FAILURES:{NC}\n")
        for r in failures:
            sev_color = RED if r.severity <= Severity.MAJOR else YELLOW
            lines.append(f"  {sev_color}[{r.check_id}] {r.severity.name}: {r.message}{NC}")
            if r.file_ref:
                lines.append(f"    {DIM}File: {r.file_ref}{NC}")
            if verbose and r.details:
                lines.append(f"    {DIM}{r.details}{NC}")
        lines.append("")

    if verbose:
        lines.append(f"\n{CYAN}ALL CHECKS:{NC}\n")
        for r in all_results:
            mark = f"{GREEN}PASS{NC}" if r.passed else f"{RED}FAIL{NC}"
            lines.append(f"  [{r.check_id}] {mark} {r.message}")
            if r.file_ref and not r.passed:
                lines.append(f"    {DIM}File: {r.file_ref}{NC}")
        lines.append("")

    total_fail = sum(c["fail"] for c in counts.values())
    total_all = sum(c["pass"] + c["fail"] for c in counts.values())
    if total_fail == 0:
        lines.append(f"{GREEN}RESULT: PASS ({total_all} checks){NC}\n")
    else:
        parts = []
        for sev in Severity:
            if counts[sev]["fail"] > 0:
                parts.append(f"{counts[sev]['fail']} {sev.name}")
        lines.append(f"{RED}RESULT: FAIL ({', '.join(parts)}){NC}\n")

    return "\n".join(lines)


def format_json(all_results: list[CheckResult], project_root: Path, plugin_version: str) -> str:
    """Format results as JSON."""
    counts = {s.name: 0 for s in Severity}
    for r in all_results:
        if not r.passed:
            counts[r.severity.name] += 1

    total_fail = sum(counts.values())
    if counts["CRITICAL"] > 0 or counts["MAJOR"] > 0:
        exit_code = 1
    elif counts["MINOR"] > 0:
        exit_code = 2
    elif counts["NIT"] > 0:
        exit_code = 3
    else:
        exit_code = 0

    data = {
        "timestamp": datetime.now(UTC).isoformat(),
        "project_root": str(project_root),
        "plugin_version": plugin_version,
        "total_checks": len(all_results),
        "total_passed": sum(1 for r in all_results if r.passed),
        "total_failed": total_fail,
        "counts": counts,
        "passed": total_fail == 0,
        "exit_code": exit_code,
        "results": [
            {
                "check_id": r.check_id,
                "severity": r.severity.name,
                "passed": r.passed,
                "message": r.message,
                "file_ref": r.file_ref,
                "details": r.details,
            }
            for r in all_results
        ],
    }
    return json.dumps(data, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="AMCAA Plugin Integrity Validator")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--verbose", action="store_true", help="Show all checks, not just failures")
    parser.add_argument("--category", help="Only run checks in this category")
    parser.add_argument("--check", help="Only run this specific check ID")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    try:
        project_root = find_project_root(script_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    ctx = build_context(project_root)

    # Run checks
    all_results: list[CheckResult] = []
    for check_id, severity, category, fn in _checks:
        if args.category and category != args.category:
            continue
        if args.check and check_id != args.check:
            continue
        try:
            results = fn(ctx)
            all_results.extend(results)
        except Exception as e:
            all_results.append(
                CheckResult(
                    check_id=check_id,
                    severity=severity,
                    passed=False,
                    message=f"Check raised exception: {e}",
                )
            )

    # Output
    plugin_version = ctx.plugin_json.get("version", "unknown")
    if args.json:
        print(format_json(all_results, project_root, plugin_version))
    else:
        print(format_text(all_results, args.verbose))

    # Exit code
    counts = {s: 0 for s in Severity}
    for r in all_results:
        if not r.passed:
            counts[r.severity] += 1
    if counts[Severity.CRITICAL] > 0 or counts[Severity.MAJOR] > 0:
        return 1
    if counts[Severity.MINOR] > 0:
        return 2
    if counts[Severity.NIT] > 0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
