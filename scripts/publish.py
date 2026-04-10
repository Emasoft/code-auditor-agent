#!/usr/bin/env python3
"""Phased publish pipeline for Claude Code plugin.

Architecture:
  Phase 0: Pre-flight  (read-only checks, no mutations)
  Phase 1: Validate    (read-only, no local file mutations)
  Phase 2: Audit       (read-only diagnostics, no mutations)
  Phase 3: Auto-fix + Bump + Commit + Tag (mutations)
  Phase 4: Push        (atomic branch+tag, rollback on failure)

STRICT MODE: All checks are MANDATORY and CANNOT be skipped.
Linting, testing, plugin validation, and version consistency MUST
all pass with 0 errors. There are NO skip flags. If a prerequisite
tool (uvx, pytest, lint_files.py, tests/) is missing, the pipeline
FAILS. This is by design to guarantee no broken code reaches origin.

Usage:
  uv run python scripts/publish.py --patch             # bump patch and publish
  uv run python scripts/publish.py --minor             # bump minor and publish
  uv run python scripts/publish.py --major             # bump major and publish
  uv run python scripts/publish.py --patch --dry-run   # preview only (still runs all checks)

Exit codes:
    0 - Success
    1 - Any phase failed (fail-fast)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# -- ANSI colors ---------------------------------------------------------------

_USE_COLOR = (
    (not os.environ.get("NO_COLOR"))
    and hasattr(sys.stdout, "isatty")
    and sys.stdout.isatty()
)
RED = "\033[0;31m" if _USE_COLOR else ""
GREEN = "\033[0;32m" if _USE_COLOR else ""
YELLOW = "\033[1;33m" if _USE_COLOR else ""
BLUE = "\033[0;34m" if _USE_COLOR else ""
BOLD = "\033[1m" if _USE_COLOR else ""
NC = "\033[0m" if _USE_COLOR else ""

# -- Lazy gitignore filter -----------------------------------------------------

_gi = None


def _get_gi(plugin_root: Path):  # noqa: ANN202
    """Get or create GitignoreFilter for the plugin root."""
    global _gi  # noqa: PLW0603
    if _gi is None:
        # Ensure scripts/ is on sys.path so bare import works
        _scripts_dir = str(Path(__file__).parent)
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        try:
            from gitignore_filter import GitignoreFilter  # noqa: E402

            _gi = GitignoreFilter(plugin_root)
        except ImportError:
            # Fallback: return plugin_root directly (no filtering)
            return plugin_root
    return _gi


# -- Helpers -------------------------------------------------------------------


def get_plugin_root() -> Path:
    """Resolve plugin root from this script's location (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def run(
    cmd: list[str],
    cwd: Path,
    *,
    check: bool = True,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, print it, and fail fast on error."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        print(
            f"\n{RED}x FAILED (exit {result.returncode}): "
            f"{' '.join(cmd)}{NC}",
            file=sys.stderr,
        )
        sys.exit(result.returncode)
    return result


def _run_quiet(
    cmd: list[str],
    cwd: Path,
    *,
    timeout: int = 30,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command silently (no printing). Returns result."""
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
    )


# -- Semver helpers ------------------------------------------------------------


def parse_semver(version: str) -> tuple[int, int, int] | None:
    """Parse 'X.Y.Z' into (major, minor, patch), or None if invalid."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def bump_semver(current: str, bump_type: str) -> str | None:
    """Bump version by type ('major', 'minor', 'patch'). Returns new version."""
    parts = parse_semver(current)
    if parts is None:
        return None
    major, minor, patch = parts
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return None


# -- Version readers -----------------------------------------------------------


def get_current_version(plugin_root: Path) -> str | None:
    """Read current version from plugin.json."""
    pj = plugin_root / ".claude-plugin" / "plugin.json"
    if not pj.exists():
        return None
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
        v = data.get("version")
        return v if isinstance(v, str) else None
    except Exception:
        return None


# -- Version updaters ----------------------------------------------------------


def update_plugin_json(
    plugin_root: Path, new_version: str,
) -> tuple[bool, str]:
    """Update version in plugin.json."""
    pj = plugin_root / ".claude-plugin" / "plugin.json"
    if not pj.exists():
        return False, "plugin.json not found"
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
        old = data.get("version", "unknown")
        data["version"] = new_version
        pj.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True, f"plugin.json: {old} -> {new_version}"
    except Exception as e:
        return False, f"plugin.json error: {e}"


def update_pyproject_toml(
    plugin_root: Path, new_version: str,
) -> tuple[bool, str]:
    """Update version in pyproject.toml."""
    pp = plugin_root / "pyproject.toml"
    if not pp.exists():
        return True, "pyproject.toml not found (skipped)"
    try:
        content = pp.read_text(encoding="utf-8")
        pattern = r'^(version\s*=\s*["\'])(\d+\.\d+\.\d+)(["\'])$'
        old_version = None

        def _replace(match: re.Match[str]) -> str:
            nonlocal old_version
            old_version = match.group(2)
            return f"{match.group(1)}{new_version}{match.group(3)}"

        new_content, count = re.subn(
            pattern, _replace, content, flags=re.MULTILINE,
        )
        if count == 0:
            return True, "pyproject.toml has no version field (skipped)"
        pp.write_text(new_content, encoding="utf-8")
        return True, f"pyproject.toml: {old_version} -> {new_version}"
    except Exception as e:
        return False, f"pyproject.toml error: {e}"


_EXCLUDE_DIRS = {
    "__pycache__", ".venv", "venv", "env", ".env",
    "node_modules", ".git", ".mypy_cache", ".ruff_cache",
}


def update_python_versions(
    plugin_root: Path, new_version: str,
) -> list[tuple[bool, str]]:
    """Update __version__ variables in Python files."""
    results: list[tuple[bool, str]] = []
    gi = _get_gi(plugin_root)
    # Use rglob from gitignore filter if available, else fallback
    glob_source = gi if hasattr(gi, "rglob") else plugin_root
    for py_file in glob_source.rglob("*.py"):
        py_path = (
            Path(py_file) if not isinstance(py_file, Path) else py_file
        )
        parts_set = set(py_path.relative_to(plugin_root).parts)
        if parts_set & _EXCLUDE_DIRS or any(
            p.startswith(".") for p in py_path.relative_to(plugin_root).parts
        ):
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
            pattern = r'^(__version__\s*=\s*["\'])(\d+\.\d+\.\d+)(["\'])$'
            old_version = None

            def _replace(match: re.Match[str]) -> str:
                nonlocal old_version
                old_version = match.group(2)
                return (
                    f"{match.group(1)}{new_version}{match.group(3)}"
                )

            new_content, count = re.subn(
                pattern, _replace, content, flags=re.MULTILINE,
            )
            if count > 0:
                py_path.write_text(new_content, encoding="utf-8")
                rel = str(py_path.relative_to(plugin_root))
                results.append(
                    (True, f"{rel}: {old_version} -> {new_version}"),
                )
        except Exception as e:
            rel = str(py_path.relative_to(plugin_root))
            results.append((False, f"{rel} error: {e}"))
    return results


def update_skill_md_versions(
    plugin_root: Path, new_version: str,
) -> list[tuple[bool, str]]:
    """Update version in SKILL.md frontmatter (YAML 'version:' field)."""
    results: list[tuple[bool, str]] = []
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return results
    for skill_md in skills_dir.rglob("SKILL.md"):
        try:
            content = skill_md.read_text(encoding="utf-8")
            pattern = r"^(version:\s*)(\d+\.\d+\.\d+)(.*)$"
            old_version = None

            def _replace_fm(match: re.Match[str]) -> str:
                nonlocal old_version
                old_version = match.group(2)
                return (
                    f"{match.group(1)}{new_version}{match.group(3)}"
                )

            new_content, count = re.subn(
                pattern, _replace_fm, content, count=1, flags=re.MULTILINE,
            )
            if count > 0:
                skill_md.write_text(new_content, encoding="utf-8")
                rel = str(skill_md.relative_to(plugin_root))
                results.append(
                    (True, f"{rel}: {old_version} -> {new_version}"),
                )
        except Exception as e:
            rel = str(skill_md.relative_to(plugin_root))
            results.append((False, f"{rel} error: {e}"))
    return results


# -- Version consistency -------------------------------------------------------


def check_version_consistency(
    plugin_root: Path,
) -> tuple[bool, str]:
    """Check all version sources match. Returns (ok, message)."""
    versions: dict[str, str] = {}

    # plugin.json
    pj = plugin_root / ".claude-plugin" / "plugin.json"
    if pj.exists():
        try:
            v = json.loads(pj.read_text(encoding="utf-8")).get("version")
            if isinstance(v, str):
                versions["plugin.json"] = v
        except Exception:
            pass

    # pyproject.toml
    pp = plugin_root / "pyproject.toml"
    if pp.exists():
        try:
            m = re.search(
                r'^version\s*=\s*["\']([^"\']+)["\']',
                pp.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if m:
                versions["pyproject.toml"] = m.group(1)
        except Exception:
            pass

    # SKILL.md frontmatter
    skills_dir = plugin_root / "skills"
    if skills_dir.is_dir():
        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                m = re.search(
                    r"^version:\s*(\d+\.\d+\.\d+)",
                    skill_md.read_text(encoding="utf-8"),
                    re.MULTILINE,
                )
                if m:
                    rel = str(skill_md.relative_to(plugin_root))
                    versions[rel] = m.group(1)
            except Exception:
                pass

    # Python __version__ variables
    gi = _get_gi(plugin_root)
    glob_source = gi if hasattr(gi, "rglob") else plugin_root
    for py_file in glob_source.rglob("*.py"):
        py_path = (
            Path(py_file) if not isinstance(py_file, Path) else py_file
        )
        parts_set = set(py_path.relative_to(plugin_root).parts)
        if parts_set & _EXCLUDE_DIRS or any(
            p.startswith(".")
            for p in py_path.relative_to(plugin_root).parts
        ):
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
            m = re.search(
                r'^__version__\s*=\s*["\']([^"\']+)["\']',
                content,
                re.MULTILINE,
            )
            if m:
                rel = str(py_path.relative_to(plugin_root))
                versions[rel] = m.group(1)
        except Exception:
            pass

    if not versions:
        return True, "No version sources found"

    unique = set(versions.values())
    if len(unique) == 1:
        return (
            True,
            f"All {len(versions)} sources consistent: "
            f"{next(iter(unique))}",
        )

    lines = ["Version mismatch detected:"]
    for src, ver in sorted(versions.items()):
        lines.append(f"  {src}: {ver}")
    return False, "\n".join(lines)


# -- Bump all files ------------------------------------------------------------


def do_bump(
    plugin_root: Path, new_version: str, dry_run: bool = False,
) -> bool:
    """Bump version across all files. Returns True on success."""
    if dry_run:
        print(f"  [DRY-RUN] Would bump to {new_version}")
        return True

    all_results: list[tuple[bool, str]] = []
    all_results.append(update_plugin_json(plugin_root, new_version))
    all_results.append(update_pyproject_toml(plugin_root, new_version))
    all_results.extend(update_python_versions(plugin_root, new_version))
    all_results.extend(update_skill_md_versions(plugin_root, new_version))

    errors = 0
    for ok, msg in all_results:
        status = f"{GREEN}[OK]{NC}" if ok else f"{RED}[ERROR]{NC}"
        print(f"  {status} {msg}")
        if not ok:
            errors += 1

    return errors == 0


# -- README badges -------------------------------------------------------------

BADGES_BLOCK = """\
[![CI](https://github.com/Emasoft/code-auditor-agent/actions/workflows/\
ci.yml/badge.svg)]\
(https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-{version}-blue)]\
(https://github.com/Emasoft/code-auditor-agent)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)]\
(https://python.org)"""


def update_readme_badges(
    plugin_root: Path, version: str, dry_run: bool,
) -> bool:
    """Insert or update shields.io badges in README.md."""
    readme = plugin_root / "README.md"
    if not readme.exists():
        print(f"  {YELLOW}README.md not found (skipped){NC}")
        return True

    content = readme.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    badges = BADGES_BLOCK.format(version=version)

    # Find first '# ' heading
    heading_idx = None
    for i, line in enumerate(lines):
        if line.startswith("# "):
            heading_idx = i
            break

    if heading_idx is None:
        print(f"  {YELLOW}No '# ' heading in README.md (skipped){NC}")
        return True

    # Find existing badges block
    badges_start = None
    badges_end = None
    for i in range(heading_idx + 1, min(heading_idx + 15, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith("[![CI]") or stripped.startswith(
            "[![Version]",
        ):
            if badges_start is None:
                badges_start = i
            badges_end = i + 1
        elif badges_start is not None and stripped.startswith("[!["):
            badges_end = i + 1
        elif badges_start is not None:
            break

    badge_lines = [bl + "\n" for bl in badges.split("\n")]
    if badges_start is not None and badges_end is not None:
        new_lines = (
            lines[:badges_start] + badge_lines + lines[badges_end:]
        )
        action = "Replaced"
    else:
        new_lines = (
            lines[: heading_idx + 1]
            + ["\n"]
            + badge_lines
            + lines[heading_idx + 1 :]
        )
        action = "Inserted"

    if dry_run:
        print(
            f"  [DRY-RUN] Would {action.lower()} badges in README.md",
        )
    else:
        readme.write_text("".join(new_lines), encoding="utf-8")
        print(f"  {GREEN}{action} badges in README.md{NC}")
    return True


def update_readme_version_text(
    plugin_root: Path, version: str, dry_run: bool,
) -> bool:
    """Update the '**Version:** X.Y.Z' line in README.md."""
    readme = plugin_root / "README.md"
    if not readme.exists():
        return True
    content = readme.read_text(encoding="utf-8")
    pattern = r"(\*\*Version:\*\*\s*)\d+\.\d+\.\d+"
    new_content, count = re.subn(pattern, rf"\g<1>{version}", content)
    if count == 0:
        print(
            f"  {YELLOW}No '**Version:**' pattern in README.md "
            f"(skipped){NC}",
        )
        return True
    if dry_run:
        print(f"  [DRY-RUN] Would update version text to {version}")
    else:
        readme.write_text(new_content, encoding="utf-8")
        print(
            f"  {GREEN}Updated version text to {version} "
            f"in README.md{NC}",
        )
    return True


# -- CHANGELOG -----------------------------------------------------------------


def get_previous_tag(cwd: Path) -> str | None:
    """Get the most recent git tag by version sort."""
    result = subprocess.run(
        ["git", "tag", "--sort=-v:refname"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0]


def get_git_log_since_tag(prev_tag: str | None, cwd: Path) -> str:
    """Get formatted git log entries since the previous tag."""
    if prev_tag:
        cmd = [
            "git", "log", "--pretty=format:- %s (%h)",
            f"{prev_tag}..HEAD",
        ]
    else:
        cmd = ["git", "log", "--pretty=format:- %s (%h)"]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def prepend_changelog_entry(
    plugin_root: Path, version: str, dry_run: bool,
) -> bool:
    """Prepend a new changelog entry generated from git log."""
    changelog = plugin_root / "CHANGELOG.md"

    prev_tag = get_previous_tag(plugin_root)
    log_entries = get_git_log_since_tag(prev_tag, plugin_root)
    if not log_entries:
        log_entries = "- No changes recorded"

    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    new_entry = (
        f"## [{version}] - {today}\n\n### Changes\n{log_entries}\n"
    )

    if not changelog.exists():
        preamble = (
            "# Changelog\n\nAll notable changes to this project "
            "will be documented in this file.\n\n"
        )
        if dry_run:
            print(
                f"  [DRY-RUN] Would create CHANGELOG.md "
                f"with entry for {version}",
            )
        else:
            changelog.write_text(
                f"{preamble}{new_entry}\n", encoding="utf-8",
            )
            print(
                f"  {GREEN}Created CHANGELOG.md with entry "
                f"for {version}{NC}",
            )
        return True

    content = changelog.read_text(encoding="utf-8")
    lines_list = content.splitlines(keepends=True)

    # Find insertion point: before first '## [' line
    insert_idx = None
    for i, line in enumerate(lines_list):
        if line.strip().startswith("## ["):
            insert_idx = i
            break

    if insert_idx is not None:
        raw_parts = new_entry.split("\n")
        if raw_parts and raw_parts[-1] == "":
            raw_parts = raw_parts[:-1]
        entry_lines = [el + "\n" for el in raw_parts]
        new_lines = (
            lines_list[:insert_idx]
            + entry_lines
            + ["\n"]
            + lines_list[insert_idx:]
        )
    else:
        new_lines = [content.rstrip("\n"), "\n\n", new_entry, "\n"]

    if dry_run:
        print(
            f"  [DRY-RUN] Would prepend changelog entry for {version}",
        )
    else:
        changelog.write_text("".join(new_lines), encoding="utf-8")
        print(f"  {GREEN}Prepended changelog entry for {version}{NC}")

    if prev_tag:
        print(f"  Commits since {prev_tag}:")
    else:
        print("  All commits (no previous tag found):")
    # Indent log entries for display
    for entry_line in log_entries.splitlines()[:10]:
        print(f"    {entry_line}")
    if len(log_entries.splitlines()) > 10:
        remaining = len(log_entries.splitlines()) - 10
        print(f"    ... and {remaining} more")

    return True


# ==============================================================================
# Phase functions
# ==============================================================================


def phase0_preflight(root: Path) -> bool:
    """Phase 0: Pre-flight (read-only checks, no mutations).

    Validates git connectivity, GitHub API, clean tree, branch, etc.
    Returns True if all checks pass, False otherwise.
    """
    print(f"\n{BOLD}{BLUE}Phase 0: Pre-flight checks{NC}")
    print(f"{BLUE}{'=' * 50}{NC}")
    errors = 0

    # 0.1 Git connectivity
    print(f"\n  {BLUE}[0.1]{NC} Git remote connectivity...")
    r = _run_quiet(
        ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
        cwd=root, timeout=15,
    )
    if r.returncode != 0:
        print(
            f"  {RED}x Cannot reach remote. "
            f"Check network/VPN/firewall.{NC}",
            file=sys.stderr,
        )
        errors += 1
    else:
        print(f"  {GREEN}ok Remote reachable{NC}")

    # 0.2 GitHub API connectivity
    print(f"\n  {BLUE}[0.2]{NC} GitHub API connectivity...")
    r = _run_quiet(
        [
            "curl", "-sf", "--connect-timeout", "5",
            "https://api.github.com/rate_limit",
        ],
        cwd=root, timeout=10,
    )
    if r.returncode != 0:
        print(
            f"  {RED}x GitHub API unreachable "
            f"(Socket Firewall? VPN?){NC}",
            file=sys.stderr,
        )
        errors += 1
    else:
        print(f"  {GREEN}ok GitHub API reachable{NC}")

    # 0.3 Clean working tree
    print(f"\n  {BLUE}[0.3]{NC} Clean working tree...")
    r = _run_quiet(["git", "status", "--porcelain"], cwd=root)
    if r.stdout.strip():
        print(
            f"  {RED}x Uncommitted changes detected. "
            f"Commit or stash first.{NC}",
            file=sys.stderr,
        )
        # Show first 10 dirty files
        for line in r.stdout.strip().splitlines()[:10]:
            print(f"    {line}")
        errors += 1
    else:
        print(f"  {GREEN}ok Working tree clean{NC}")

    # 0.4 No stale lock files (uv.lock committed and unchanged)
    print(f"\n  {BLUE}[0.4]{NC} Lock file status...")
    uv_lock = root / "uv.lock"
    if uv_lock.exists():
        # Check if uv.lock is tracked
        r = _run_quiet(
            ["git", "ls-files", "--error-unmatch", "uv.lock"], cwd=root,
        )
        if r.returncode != 0:
            print(
                f"  {RED}x uv.lock exists but is not tracked by git. "
                f"Run: git add uv.lock && git commit{NC}",
                file=sys.stderr,
            )
            errors += 1
        else:
            # Check if uv.lock has uncommitted changes
            r2 = _run_quiet(
                ["git", "diff", "--name-only", "uv.lock"], cwd=root,
            )
            r3 = _run_quiet(
                ["git", "diff", "--cached", "--name-only", "uv.lock"],
                cwd=root,
            )
            if r2.stdout.strip() or r3.stdout.strip():
                print(
                    f"  {RED}x uv.lock has uncommitted changes. "
                    f"Commit it first.{NC}",
                    file=sys.stderr,
                )
                errors += 1
            else:
                print(f"  {GREEN}ok uv.lock committed and clean{NC}")
    else:
        print(f"  {YELLOW}~ uv.lock not found (skipped){NC}")

    # 0.5 Remote version check
    print(f"\n  {BLUE}[0.5]{NC} Remote version comparison...")
    local_version = get_current_version(root)
    if local_version:
        r = _run_quiet(
            [
                "git", "show",
                "origin/main:.claude-plugin/plugin.json",
            ],
            cwd=root, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            try:
                remote_data = json.loads(r.stdout)
                remote_ver = remote_data.get("version", "")
                remote_parts = parse_semver(remote_ver)
                local_parts = parse_semver(local_version)
                if remote_parts and local_parts:
                    if remote_parts > local_parts:
                        print(
                            f"  {RED}x Remote version "
                            f"({remote_ver}) is ahead of "
                            f"local ({local_version}). "
                            f"Pull first.{NC}",
                            file=sys.stderr,
                        )
                        errors += 1
                    elif remote_parts == local_parts:
                        print(
                            f"  {GREEN}ok Remote and local "
                            f"versions match "
                            f"({local_version}){NC}",
                        )
                    else:
                        # local > remote: this is fine, means
                        # we already bumped locally
                        print(
                            f"  {GREEN}ok Local "
                            f"({local_version}) >= remote "
                            f"({remote_ver}){NC}",
                        )
                else:
                    print(
                        f"  {YELLOW}~ Cannot parse versions "
                        f"(local={local_version}, "
                        f"remote={remote_ver}){NC}",
                    )
            except (json.JSONDecodeError, KeyError):
                print(
                    f"  {YELLOW}~ Cannot parse remote "
                    f"plugin.json{NC}",
                )
        else:
            print(
                f"  {YELLOW}~ Cannot fetch remote plugin.json "
                f"(new repo?){NC}",
            )
    else:
        print(
            f"  {RED}x Cannot read local version from "
            f"plugin.json{NC}",
            file=sys.stderr,
        )
        errors += 1

    # 0.6 Branch check
    print(f"\n  {BLUE}[0.6]{NC} Branch check...")
    r = _run_quiet(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
    )
    branch = r.stdout.strip() if r.returncode == 0 else ""
    if branch == "HEAD":
        print(
            f"  {RED}x Detached HEAD state. "
            f"Checkout a branch first.{NC}",
            file=sys.stderr,
        )
        errors += 1
    elif branch != "main":
        print(
            f"  {RED}x Must be on 'main' branch "
            f"(currently on '{branch}'){NC}",
            file=sys.stderr,
        )
        errors += 1
    else:
        print(f"  {GREEN}ok On branch main{NC}")

    # 0.7 No detached HEAD (already handled in 0.6, kept as explicit
    #     check for the spec)

    # 0.8 Disk space check
    print(f"\n  {BLUE}[0.8]{NC} Disk space...")
    try:
        stat = shutil.disk_usage("/tmp")
        free_mb = stat.free // (1024 * 1024)
        if free_mb < 100:
            print(
                f"  {RED}x Less than 100MB free in /tmp "
                f"({free_mb}MB). Free space first.{NC}",
                file=sys.stderr,
            )
            errors += 1
        else:
            print(f"  {GREEN}ok {free_mb}MB free in /tmp{NC}")
    except OSError as e:
        print(
            f"  {YELLOW}~ Cannot check disk space: {e}{NC}",
        )

    if errors > 0:
        print(
            f"\n{RED}Phase 0 FAILED: {errors} pre-flight "
            f"check(s) failed.{NC}",
            file=sys.stderr,
        )
        return False

    print(f"\n{GREEN}Phase 0 passed: all pre-flight checks OK{NC}")
    return True


def phase1_validate(root: Path) -> bool:
    """Phase 1: Validate (read-only, no local file mutations).

    STRICT MODE: Runs tests, lint, plugin validation, and version
    consistency. ALL checks are MANDATORY. Missing prerequisites
    (tests/, lint_files.py, uvx, pytest) cause the phase to FAIL.
    Returns True only if every check passes with 0 errors.
    """
    print(f"\n{BOLD}{BLUE}Phase 1: Validation (strict mode){NC}")
    print(f"{BLUE}{'=' * 50}{NC}")
    errors = 0

    # 1.0 Tests (MANDATORY — cannot be skipped)
    print(f"\n  {BLUE}[1.0]{NC} Running tests (mandatory)...")
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        print(
            f"  {RED}x tests/ directory not found. "
            f"Create tests/ with at least one test "
            f"before publishing.{NC}",
            file=sys.stderr,
        )
        errors += 1
    else:
        # Require at least one test file
        test_files = list(tests_dir.rglob("test_*.py")) + list(
            tests_dir.rglob("*_test.py"),
        )
        if not test_files:
            print(
                f"  {RED}x tests/ contains no test_*.py or "
                f"*_test.py files. Add tests before publishing.{NC}",
                file=sys.stderr,
            )
            errors += 1
        else:
            r = _run_quiet(
                [
                    "uv", "run", "pytest", "tests/",
                    "-x", "-q", "--tb=short",
                ],
                cwd=root, timeout=300,
            )
            if r.returncode != 0:
                print(
                    f"  {RED}x Tests failed:{NC}",
                    file=sys.stderr,
                )
                if r.stdout.strip():
                    for line in r.stdout.strip().splitlines()[-20:]:
                        print(f"    {line}")
                if r.stderr.strip():
                    for line in r.stderr.strip().splitlines()[-10:]:
                        print(f"    {line}", file=sys.stderr)
                errors += 1
            else:
                print(
                    f"  {GREEN}ok Tests passed "
                    f"({len(test_files)} test file(s)){NC}",
                )

    # 1.1 Lint (MANDATORY — cannot be skipped)
    print(f"\n  {BLUE}[1.1]{NC} Lint files (mandatory)...")
    lint_script = root / "scripts" / "lint_files.py"
    if not lint_script.exists():
        print(
            f"  {RED}x scripts/lint_files.py not found. "
            f"Restore it before publishing.{NC}",
            file=sys.stderr,
        )
        errors += 1
    else:
        r = _run_quiet(
            ["uv", "run", "python", str(lint_script), str(root)],
            cwd=root, timeout=120,
        )
        if r.returncode != 0:
            print(f"  {RED}x Linting failed:{NC}", file=sys.stderr)
            if r.stdout.strip():
                for line in r.stdout.strip().splitlines()[-20:]:
                    print(f"    {line}")
            if r.stderr.strip():
                for line in r.stderr.strip().splitlines()[-10:]:
                    print(f"    {line}", file=sys.stderr)
            errors += 1
        else:
            print(f"  {GREEN}ok Linting passed{NC}")

    # 1.2 Validate plugin (strict) via uvx remote execution
    print(f"\n  {BLUE}[1.2]{NC} Validate plugin (strict via CPV remote)...")
    CPV_REPO = "git+https://github.com/Emasoft/claude-plugins-validation"
    if shutil.which("uvx"):
        r = _run_quiet(
            [
                "uvx", "--from", CPV_REPO, "--with", "pyyaml",
                "cpv-validate", str(root), "--strict",
            ],
            cwd=root, timeout=180,
        )
        if r.returncode != 0:
            sev_map = {
                1: "CRITICAL", 2: "MAJOR", 3: "MINOR", 4: "NIT",
            }
            severity = sev_map.get(
                r.returncode, f"exit {r.returncode}",
            )
            print(
                f"  {RED}x Plugin validation failed "
                f"({severity} issues){NC}",
                file=sys.stderr,
            )
            if r.stdout.strip():
                for line in r.stdout.strip().splitlines()[-20:]:
                    print(f"    {line}")
            print(
                f"  {RED}  Fix ALL issues before publishing.{NC}",
                file=sys.stderr,
            )
            errors += 1
        else:
            print(f"  {GREEN}ok Plugin validation passed (strict){NC}")
    else:
        print(
            f"  {RED}x uvx not found — install uv: "
            f"curl -LsSf https://astral.sh/uv/install.sh | sh{NC}",
            file=sys.stderr,
        )
        errors += 1

    # 1.3 Version consistency
    print(f"\n  {BLUE}[1.3]{NC} Version consistency...")
    ok, msg = check_version_consistency(root)
    print(f"    {msg}")
    if not ok:
        print(
            f"  {RED}x Fix version mismatches before "
            f"publishing.{NC}",
            file=sys.stderr,
        )
        errors += 1
    else:
        print(f"  {GREEN}ok Version consistency OK{NC}")

    if errors > 0:
        print(
            f"\n{RED}Phase 1 FAILED: {errors} validation "
            f"check(s) failed.{NC}",
            file=sys.stderr,
        )
        return False

    print(f"\n{GREEN}Phase 1 passed: all validations OK{NC}")
    return True


# Required .gitignore entries for audit check
_REQUIRED_GITIGNORE_ENTRIES = [
    "__pycache__/",
    "*.py[cod]",
    ".venv/",
    ".env",
    ".DS_Store",
    "node_modules/",
    "*_dev/",
    "*.log",
    ".rechecker/",
    ".tldr/",
    ".claude/",
]


def phase2_audit(root: Path) -> bool:
    """Phase 2: Audit (read-only diagnostics, no mutations).

    Structural health checks. ERRORs block publishing; WARNINGs are
    informational only.
    Returns True if no errors found, False otherwise.
    """
    print(f"\n{BOLD}{BLUE}Phase 2: Audit{NC}")
    print(f"{BLUE}{'=' * 50}{NC}")
    errors = 0

    # 2.1 Gitignore coverage
    print(f"\n  {BLUE}[2.1]{NC} Gitignore coverage...")
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        gi_content = gitignore_path.read_text(encoding="utf-8")
        gi_lines = {
            line.strip()
            for line in gi_content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        missing = []
        for entry in _REQUIRED_GITIGNORE_ENTRIES:
            if entry not in gi_lines:
                missing.append(entry)
        if missing:
            print(
                f"  {YELLOW}~ Missing from .gitignore: "
                f"{', '.join(missing)}{NC}",
            )
        else:
            print(f"  {GREEN}ok .gitignore coverage complete{NC}")
    else:
        print(
            f"  {YELLOW}~ .gitignore not found (WARNING){NC}",
        )

    # 2.2 Stale .md files at project root
    print(f"\n  {BLUE}[2.2]{NC} Stale files at root...")
    allowed_root_md = {"README.md", "CHANGELOG.md", "LICENSE"}
    stale_md = []
    for f in root.iterdir():
        if f.is_file() and f.suffix == ".md":
            if f.name not in allowed_root_md:
                stale_md.append(f.name)
    if stale_md:
        print(
            f"  {YELLOW}~ Stale .md files at root "
            f"(move to docs_dev/): "
            f"{', '.join(stale_md)}{NC}",
        )
    else:
        print(f"  {GREEN}ok No stale root .md files{NC}")

    # 2.3 Script executable bit (informational; auto-fixed in phase 3)
    print(f"\n  {BLUE}[2.3]{NC} Script executable bits...")
    scripts_dir = root / "scripts"
    non_exec = []
    if scripts_dir.is_dir():
        for script in scripts_dir.iterdir():
            if script.is_file() and script.suffix in (".py", ".sh"):
                try:
                    first_line = script.read_text(
                        encoding="utf-8",
                    ).split("\n", maxsplit=1)[0]
                    if first_line.startswith("#!"):
                        if not os.access(script, os.X_OK):
                            rel = str(
                                script.relative_to(root),
                            )
                            non_exec.append(rel)
                except Exception:
                    pass
    if non_exec:
        print(
            f"  {YELLOW}~ Scripts missing +x "
            f"(will auto-fix in Phase 3): "
            f"{', '.join(non_exec[:5])}{NC}",
        )
        if len(non_exec) > 5:
            print(
                f"    ... and {len(non_exec) - 5} more",
            )
    else:
        print(f"  {GREEN}ok All shebanged scripts are +x{NC}")

    # 2.4 YAML lint on tracked files
    print(f"\n  {BLUE}[2.4]{NC} YAML lint...")
    # Find tracked .yml/.yaml files
    r = _run_quiet(
        ["git", "ls-files", "*.yml", "*.yaml"], cwd=root,
    )
    yaml_files = [
        f for f in r.stdout.strip().splitlines() if f.strip()
    ]
    if yaml_files:
        # Check if yamllint is available
        yamllint_check = _run_quiet(
            ["uv", "run", "python", "-m", "yamllint", "--version"],
            cwd=root,
        )
        if yamllint_check.returncode == 0:
            yaml_cmd = [
                "uv", "run", "python", "-m", "yamllint",
                "-d", "relaxed", "--format", "parsable",
            ] + yaml_files
            yr = _run_quiet(yaml_cmd, cwd=root, timeout=60)
            # Parse for [error] lines
            yaml_errors = [
                line
                for line in yr.stdout.strip().splitlines()
                if "[error]" in line
            ]
            if yaml_errors:
                print(
                    f"  {RED}x YAML errors found:{NC}",
                    file=sys.stderr,
                )
                for line in yaml_errors[:10]:
                    print(f"    {line}")
                if len(yaml_errors) > 10:
                    print(
                        f"    ... and "
                        f"{len(yaml_errors) - 10} more",
                    )
                errors += 1
            else:
                print(f"  {GREEN}ok YAML files clean{NC}")
        else:
            print(
                f"  {YELLOW}~ yamllint not available "
                f"(skipped){NC}",
            )
    else:
        print(f"  {YELLOW}~ No tracked YAML files found{NC}")

    # 2.5 Serena/rechecker pollution
    print(f"\n  {BLUE}[2.5]{NC} Tool directory pollution...")
    for dirname in (".serena", ".rechecker"):
        dpath = root / dirname
        if dpath.is_dir():
            r = _run_quiet(
                ["git", "status", "--porcelain", dirname], cwd=root,
            )
            if r.stdout.strip():
                print(
                    f"  {YELLOW}~ {dirname}/ has uncommitted "
                    f"changes (may dirty tree during "
                    f"publish){NC}",
                )
    print(f"  {GREEN}ok Tool directories checked{NC}")

    # 2.6 uv.lock freshness
    print(f"\n  {BLUE}[2.6]{NC} uv.lock freshness...")
    uv_lock = root / "uv.lock"
    if uv_lock.exists():
        r = _run_quiet(
            ["uv", "lock", "--check"], cwd=root, timeout=60,
        )
        if r.returncode != 0:
            print(
                f"  {RED}x uv.lock is stale "
                f"(does not match pyproject.toml). "
                f"Run: uv lock{NC}",
                file=sys.stderr,
            )
            errors += 1
        else:
            print(
                f"  {GREEN}ok uv.lock matches "
                f"pyproject.toml{NC}",
            )
    else:
        print(
            f"  {YELLOW}~ uv.lock not found (skipped){NC}",
        )

    if errors > 0:
        print(
            f"\n{RED}Phase 2 FAILED: {errors} audit error(s) "
            f"found.{NC}",
            file=sys.stderr,
        )
        return False

    print(f"\n{GREEN}Phase 2 passed: audit clean{NC}")
    return True


def phase3_mutate(
    root: Path,
    bump_type: str,
    *,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Phase 3: Auto-fix + Bump + Commit + Tag (mutations).

    All file mutations happen here. Returns (success, new_version).
    On failure, caller should NOT proceed to push.
    """
    print(f"\n{BOLD}{BLUE}Phase 3: Mutate{NC}")
    print(f"{BLUE}{'=' * 50}{NC}")

    # Compute new version first (read-only)
    current = get_current_version(root)
    if current is None:
        print(
            f"  {RED}x Cannot read current version from "
            f"plugin.json{NC}",
            file=sys.stderr,
        )
        return False, ""

    new_version = bump_semver(current, bump_type)
    if new_version is None:
        print(
            f"  {RED}x Current version '{current}' is not "
            f"valid semver{NC}",
            file=sys.stderr,
        )
        return False, ""

    tag = f"v{new_version}"
    print(
        f"\n  Version: {current} -> {new_version} ({bump_type})",
    )

    if dry_run:
        print(f"\n  {BLUE}[DRY-RUN] Phase 3 preview:{NC}")
        print("    Would auto-fix chmod on shebanged scripts")
        print(f"    Would bump to {new_version}")
        print("    Would update README badges")
        print("    Would update README version text")
        print("    Would prepend CHANGELOG entry")
        print(f"    Would commit: release: {tag}")
        print(f"    Would tag: {tag}")
        # Still run dry-run versions of updaters for output
        do_bump(root, new_version, dry_run=True)
        update_readme_badges(root, new_version, dry_run=True)
        update_readme_version_text(root, new_version, dry_run=True)
        prepend_changelog_entry(root, new_version, dry_run=True)
        print(
            f"\n{GREEN}Phase 3 preview complete "
            f"(no changes made){NC}",
        )
        return True, new_version

    # 3.1 Auto-fix chmod on shebanged scripts
    print(f"\n  {BLUE}[3.1]{NC} Auto-fix script permissions...")
    scripts_dir = root / "scripts"
    chmod_fixed = []
    if scripts_dir.is_dir():
        for script in scripts_dir.iterdir():
            if script.is_file() and script.suffix in (".py", ".sh"):
                try:
                    first_line = script.read_text(
                        encoding="utf-8",
                    ).split("\n", maxsplit=1)[0]
                    if first_line.startswith("#!"):
                        if not os.access(script, os.X_OK):
                            script.chmod(script.stat().st_mode | 0o755)
                            chmod_fixed.append(
                                str(script.relative_to(root)),
                            )
                except Exception:
                    pass
    if chmod_fixed:
        # Stage the permission changes
        _run_quiet(
            ["git", "add"] + chmod_fixed, cwd=root,
        )
        print(
            f"  {GREEN}ok Fixed +x on "
            f"{len(chmod_fixed)} script(s){NC}",
        )
    else:
        print(f"  {GREEN}ok No permission fixes needed{NC}")

    # 3.2 Bump version
    print(f"\n  {BLUE}[3.2]{NC} Bump version...")
    if not do_bump(root, new_version, dry_run=False):
        print(
            f"  {RED}x Version bump failed{NC}", file=sys.stderr,
        )
        return False, ""
    print(f"  {GREEN}ok Version bumped to {new_version}{NC}")

    # 3.3 Update README badges
    print(f"\n  {BLUE}[3.3]{NC} Update README badges...")
    if not update_readme_badges(root, new_version, dry_run=False):
        print(
            f"  {RED}x README badge update failed{NC}",
            file=sys.stderr,
        )
        return False, ""
    print(f"  {GREEN}ok README badges updated{NC}")

    # 3.4 Update README version text
    print(f"\n  {BLUE}[3.4]{NC} Update README version text...")
    if not update_readme_version_text(
        root, new_version, dry_run=False,
    ):
        print(
            f"  {RED}x README version text update failed{NC}",
            file=sys.stderr,
        )
        return False, ""
    print(f"  {GREEN}ok README version text updated{NC}")

    # 3.5 Prepend CHANGELOG entry
    print(f"\n  {BLUE}[3.5]{NC} Prepend CHANGELOG entry...")
    if not prepend_changelog_entry(
        root, new_version, dry_run=False,
    ):
        print(
            f"  {RED}x CHANGELOG update failed{NC}",
            file=sys.stderr,
        )
        return False, ""
    print(f"  {GREEN}ok CHANGELOG updated{NC}")

    # 3.6 Stage all tracked changes
    print(f"\n  {BLUE}[3.6]{NC} Stage changes...")
    run(["git", "add", "-u"], cwd=root)

    # 3.7 Show what is being committed
    print(f"\n  {BLUE}[3.7]{NC} Changes to commit:")
    r = _run_quiet(["git", "diff", "--cached", "--stat"], cwd=root)
    if r.stdout.strip():
        for line in r.stdout.strip().splitlines():
            print(f"    {line}")
    else:
        print(
            f"  {YELLOW}~ No changes staged (unexpected){NC}",
        )

    # 3.8 Commit
    print(f"\n  {BLUE}[3.8]{NC} Commit...")
    run(
        ["git", "commit", "-m", f"release: {tag}"],
        cwd=root,
    )
    print(f"  {GREEN}ok Committed release: {tag}{NC}")

    # 3.9 Tag
    print(f"\n  {BLUE}[3.9]{NC} Tag...")
    run(
        ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
        cwd=root,
    )
    print(f"  {GREEN}ok Tagged {tag}{NC}")

    print(f"\n{GREEN}Phase 3 passed: commit and tag created{NC}")
    return True, new_version


def phase4_push(root: Path, version: str) -> bool:
    """Phase 4: Push (atomic -- both branch and tag, or neither).

    Pushes branch AND tag in a single command. If push fails,
    rolls back the local commit and tag.
    Returns True on success, False on failure.
    """
    tag = f"v{version}"
    print(f"\n{BOLD}{BLUE}Phase 4: Push{NC}")
    print(f"{BLUE}{'=' * 50}{NC}")

    # Atomic push: branch + tag in one command
    push_env = {**os.environ, "CAA_PUBLISH_PIPELINE": "1"}
    print(f"\n  {BLUE}[4.1]{NC} Push main + {tag} to origin...")
    r = _run_quiet(
        ["git", "push", "origin", "main", tag],
        cwd=root, timeout=120, env=push_env,
    )

    if r.returncode != 0:
        # Push failed -- print error output
        print(
            f"  {RED}x Push failed (exit {r.returncode}){NC}",
            file=sys.stderr,
        )
        if r.stderr.strip():
            for line in r.stderr.strip().splitlines():
                print(f"    {line}", file=sys.stderr)

        # Rollback: delete local tag
        print(f"\n  {YELLOW}Rolling back local changes...{NC}")
        _run_quiet(["git", "tag", "-d", tag], cwd=root)
        print(f"    Deleted local tag {tag}")

        # Rollback: soft-reset the commit (keeps changes staged)
        _run_quiet(["git", "reset", "--soft", "HEAD~1"], cwd=root)
        print("    Soft-reset commit (changes still staged)")

        # Rollback: unstage
        _run_quiet(["git", "reset", "HEAD"], cwd=root)
        print("    Unstaged all changes")

        print(
            f"\n  {RED}Push failed. All local changes are "
            f"preserved but uncommitted. "
            f"Fix the issue and re-run.{NC}",
            file=sys.stderr,
        )
        return False

    # Print push stdout/stderr if any
    if r.stdout.strip():
        for line in r.stdout.strip().splitlines():
            print(f"    {line}")
    if r.stderr.strip():
        # git push often writes progress to stderr even on success
        for line in r.stderr.strip().splitlines():
            print(f"    {line}")

    print(f"\n{GREEN}Phase 4 passed: pushed to origin{NC}")
    return True


# -- Main pipeline -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phased publish pipeline: "
            "preflight -> validate -> audit -> "
            "mutate -> push"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --patch              # 1.0.0 -> 1.0.1, commit, push
  %(prog)s --minor              # 1.0.0 -> 1.1.0, commit, push
  %(prog)s --major              # 1.0.0 -> 2.0.0, commit, push
  %(prog)s --patch --dry-run    # preview (still runs ALL checks)

STRICT MODE: tests, lint, validation, and version consistency are
MANDATORY. There are NO skip flags. All checks must pass with 0
errors before anything is committed or pushed.
        """,
    )
    bump_group = parser.add_mutually_exclusive_group(required=True)
    bump_group.add_argument(
        "--major", action="store_true", help="Bump major version",
    )
    bump_group.add_argument(
        "--minor", action="store_true", help="Bump minor version",
    )
    bump_group.add_argument(
        "--patch", action="store_true", help="Bump patch version",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview without committing/pushing. "
            "ALL checks still run in strict mode."
        ),
    )
    args = parser.parse_args()

    root = get_plugin_root()
    bump_type = (
        "major" if args.major
        else "minor" if args.minor
        else "patch"
    )

    print(f"\n{BOLD}{'=' * 60}{NC}")
    label = "DRY RUN" if args.dry_run else "PUBLISH"
    print(f"{BOLD}  Publish Pipeline ({label}){NC}")
    print(f"{BOLD}{'=' * 60}{NC}")

    # -- Phase 0: Pre-flight (read-only) --
    if not phase0_preflight(root):
        return 1

    # -- Phase 1: Validate (read-only, strict) --
    if not phase1_validate(root):
        return 1

    # -- Phase 2: Audit (read-only) --
    if not phase2_audit(root):
        return 1

    # -- Phase 3: Mutate (commit + tag) --
    success, new_version = phase3_mutate(
        root, bump_type, dry_run=args.dry_run,
    )
    if not success:
        return 1

    if args.dry_run:
        print(
            f"\n{GREEN}Dry run complete -- no changes made.{NC}",
        )
        return 0

    # -- Phase 4: Push --
    if not phase4_push(root, new_version):
        return 1

    tag = f"v{new_version}"
    print(f"\n{GREEN}{'=' * 60}{NC}")
    print(f"{GREEN}  Published {tag} successfully!{NC}")
    print(f"{GREEN}{'=' * 60}{NC}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
