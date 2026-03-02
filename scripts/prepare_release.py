#!/usr/bin/env python3
"""
prepare_release.py - Orchestrate full release preparation for code-auditor-agent.

Steps performed:
1. Bump version via bump_version.py (updates plugin.json, pyproject.toml, __version__)
2. Update README.md shields.io badges and version text
3. Prepend CHANGELOG.md entry from git log since previous tag
4. Stage changed files, commit as "release: vX.Y.Z", create annotated tag
5. Print push instructions (does NOT push)

Exit codes:
    0 - Success
    1 - Error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Color helpers -- same pattern as setup_git_hooks.py
# ---------------------------------------------------------------------------


def _colors_supported() -> bool:
    """Return True when the terminal likely supports ANSI escape codes."""
    # Respect NO_COLOR convention (https://no-color.org/)
    if os.environ.get("NO_COLOR"):
        return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON"))
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_USE_COLOR = _colors_supported()

_RED = "\033[0;31m" if _USE_COLOR else ""
_YELLOW = "\033[1;33m" if _USE_COLOR else ""
_GREEN = "\033[0;32m" if _USE_COLOR else ""
_BLUE = "\033[0;34m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_NC = "\033[0m" if _USE_COLOR else ""


def _info(msg: str) -> None:
    print(f"{_BLUE}{msg}{_NC}")


def _ok(msg: str) -> None:
    print(f"{_GREEN}{msg}{_NC}")


def _warn(msg: str) -> None:
    print(f"{_YELLOW}{msg}{_NC}")


def _err(msg: str) -> None:
    print(f"{_RED}{msg}{_NC}", file=sys.stderr)


def _step(msg: str) -> None:
    print(f"\n{_BOLD}>>> {msg}{_NC}")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cmd(cmd: list[str], *, cwd: Path | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and return the result.

    Args:
        cmd: Command and arguments as a list.
        cwd: Working directory (defaults to REPO_ROOT).
        capture: Whether to capture stdout/stderr.

    Returns:
        CompletedProcess with stdout/stderr as strings.
    """
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=capture,
        text=True,
    )


def read_version_from_plugin_json() -> str | None:
    """Read the current version string from .claude-plugin/plugin.json.

    Returns:
        Version string, or None if plugin.json is missing or unreadable.
    """
    plugin_json = REPO_ROOT / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        return None
    try:
        with open(plugin_json, encoding="utf-8") as f:
            data = json.load(f)
        version = data.get("version")
        return version if isinstance(version, str) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Step 1: Bump version
# ---------------------------------------------------------------------------


def bump_version(bump_type: str, set_version: str | None, dry_run: bool) -> str | None:
    """Call bump_version.py to update version across all files.

    Args:
        bump_type: One of 'major', 'minor', 'patch', or empty string if --set is used.
        set_version: Explicit version string when using --set, or None.
        dry_run: If True, pass --dry-run to bump_version.py.

    Returns:
        The new version string on success, or None on failure.
    """
    _step("Step 1: Bump version")

    cmd = ["uv", "run", "python", "scripts/bump_version.py"]
    if set_version:
        cmd.extend(["--set", set_version])
    else:
        cmd.append(f"--{bump_type}")
    if dry_run:
        cmd.append("--dry-run")

    result = run_cmd(cmd)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)

    if result.returncode != 0:
        _err("bump_version.py failed")
        return None

    # Read the version from plugin.json (bump_version.py has already updated it)
    if dry_run and set_version:
        # In dry-run with --set, plugin.json was NOT updated, so use the explicit version
        return set_version
    if dry_run:
        # In dry-run with bump type, compute the new version ourselves
        current = read_version_from_plugin_json()
        if current is None:
            _err("Cannot read current version from plugin.json")
            return None
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", current.strip())
        if not match:
            _err(f"Current version '{current}' is not valid semver")
            return None
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:
            return f"{major}.{minor}.{patch + 1}"

    # Not dry-run: read the actually updated version
    new_version = read_version_from_plugin_json()
    if new_version is None:
        _err("Cannot read new version from plugin.json after bump")
        return None

    _ok(f"  Version bumped to {new_version}")
    return new_version


# ---------------------------------------------------------------------------
# Step 2: Update README badges
# ---------------------------------------------------------------------------

BADGES_BLOCK = """\
[![CI](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-{version}-blue)](https://github.com/Emasoft/code-auditor-agent)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)"""


def update_readme_badges(version: str, dry_run: bool) -> bool:
    """Insert or update shields.io badges in README.md.

    Badges are placed right after the first '# ' heading line.
    If badges already exist (detected by '[![CI]' or '[![Version]'), they are replaced.

    Args:
        version: The new version string to embed in the badges.
        dry_run: If True, only print what would change.

    Returns:
        True on success, False on failure.
    """
    _step("Step 2: Update README badges")

    readme_path = REPO_ROOT / "README.md"
    if not readme_path.exists():
        _err("README.md not found")
        return False

    content = readme_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    badges = BADGES_BLOCK.format(version=version)

    # Find the first '# ' heading line
    heading_idx = None
    for i, line in enumerate(lines):
        if line.startswith("# "):
            heading_idx = i
            break

    if heading_idx is None:
        _err("No '# ' heading found in README.md")
        return False

    # Check if badges already exist after the heading
    # Look for lines starting with '[![' near the heading
    badges_start = None
    badges_end = None
    for i in range(heading_idx + 1, min(heading_idx + 15, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith("[![CI]") or stripped.startswith("[![Version]"):
            if badges_start is None:
                badges_start = i
            badges_end = i + 1
        elif badges_start is not None and stripped.startswith("[!["):
            # Continuation badge line
            badges_end = i + 1
        elif badges_start is not None and stripped == "":
            # Empty line after badges, stop
            break
        elif badges_start is not None:
            # Non-badge, non-empty line: stop
            break

    if badges_start is not None and badges_end is not None:
        # Replace existing badges
        badge_lines = [bl + "\n" for bl in badges.split("\n")]
        new_lines = lines[:badges_start] + badge_lines + lines[badges_end:]
        action = "Replaced"
    else:
        # Insert badges after heading line (single blank line separator)
        badge_lines = ["\n"] + [bl + "\n" for bl in badges.split("\n")]
        new_lines = lines[: heading_idx + 1] + badge_lines + lines[heading_idx + 1 :]
        action = "Inserted"

    new_content = "".join(new_lines)

    if dry_run:
        _info(f"  [DRY-RUN] Would {action.lower()} badges in README.md")
    else:
        readme_path.write_text(new_content, encoding="utf-8")
        _ok(f"  {action} badges in README.md")

    return True


# ---------------------------------------------------------------------------
# Step 3: Update README version text
# ---------------------------------------------------------------------------


def update_readme_version_text(version: str, dry_run: bool) -> bool:
    """Update the '**Version:** X.Y.Z' line in README.md.

    Args:
        version: The new version string.
        dry_run: If True, only print what would change.

    Returns:
        True on success, False on failure.
    """
    _step("Step 3: Update README version text")

    readme_path = REPO_ROOT / "README.md"
    if not readme_path.exists():
        _err("README.md not found")
        return False

    content = readme_path.read_text(encoding="utf-8")
    pattern = r"(\*\*Version:\*\*\s*)\d+\.\d+\.\d+"
    new_content, count = re.subn(pattern, rf"\g<1>{version}", content)

    if count == 0:
        _warn("  No '**Version:** X.Y.Z' pattern found in README.md (skipped)")
        return True

    if dry_run:
        _info(f"  [DRY-RUN] Would update version text to {version} in README.md")
    else:
        readme_path.write_text(new_content, encoding="utf-8")
        _ok(f"  Updated version text to {version} in README.md")

    return True


# ---------------------------------------------------------------------------
# Step 4: Prepend CHANGELOG entry
# ---------------------------------------------------------------------------


def get_previous_tag() -> str | None:
    """Get the most recent git tag by version sort.

    Returns:
        The most recent tag string, or None if no tags exist.
    """
    result = run_cmd(["git", "tag", "--sort=-v:refname"])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0]


def get_git_log_since_tag(prev_tag: str | None) -> str:
    """Get formatted git log entries since the previous tag.

    Args:
        prev_tag: Previous tag to start from, or None to get all commits.

    Returns:
        Formatted git log string with '- message (hash)' lines.
    """
    if prev_tag:
        cmd = ["git", "log", "--pretty=format:- %s (%h)", f"{prev_tag}..HEAD"]
    else:
        cmd = ["git", "log", "--pretty=format:- %s (%h)"]
    result = run_cmd(cmd)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def prepend_changelog_entry(version: str, dry_run: bool) -> bool:
    """Prepend a new changelog entry generated from git log.

    The entry is inserted after the '# Changelog' header and any preamble text,
    but before the first '## [' section.

    Args:
        version: The new version string.
        dry_run: If True, only print what would change.

    Returns:
        True on success, False on failure.
    """
    _step("Step 4: Prepend CHANGELOG entry")

    changelog_path = REPO_ROOT / "CHANGELOG.md"

    # Get git log since previous tag
    prev_tag = get_previous_tag()
    log_entries = get_git_log_since_tag(prev_tag)

    if not log_entries:
        _warn("  No commits found since previous tag (empty changelog entry)")
        log_entries = "- No changes recorded"

    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    new_entry = f"## [{version}] - {today}\n\n### Changes\n{log_entries}\n"

    if not changelog_path.exists():
        # Create CHANGELOG.md from scratch
        preamble = "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n"
        full_content = f"{preamble}{new_entry}\n"
        if dry_run:
            _info(f"  [DRY-RUN] Would create CHANGELOG.md with entry for {version}")
            print(f"\n{new_entry}")
        else:
            changelog_path.write_text(full_content, encoding="utf-8")
            _ok(f"  Created CHANGELOG.md with entry for {version}")
        return True

    content = changelog_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    # Find the insertion point: before the first '## [' line
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("## ["):
            insert_idx = i
            break

    if insert_idx is not None:
        # Insert the new entry before the first existing version section
        # new_entry ends with \n, so split produces a trailing empty string — drop it
        raw_parts = new_entry.split("\n")
        if raw_parts and raw_parts[-1] == "":
            raw_parts = raw_parts[:-1]
        entry_lines = [el + "\n" for el in raw_parts]
        new_lines = lines[:insert_idx] + entry_lines + ["\n"] + lines[insert_idx:]
    else:
        # No existing version sections -- append after all existing content
        if not content.endswith("\n"):
            content += "\n"
        new_lines = [content, "\n", new_entry, "\n"]

    new_content = "".join(new_lines)

    if dry_run:
        _info(f"  [DRY-RUN] Would prepend changelog entry for {version}")
        print(f"\n{new_entry}")
    else:
        changelog_path.write_text(new_content, encoding="utf-8")
        _ok(f"  Prepended changelog entry for {version}")

    if prev_tag:
        _info(f"  Commits since {prev_tag}:")
    else:
        _info("  All commits (no previous tag found):")
    print(f"  {log_entries.replace(chr(10), chr(10) + '  ')}")

    return True


# ---------------------------------------------------------------------------
# Step 5: Git operations
# ---------------------------------------------------------------------------


def git_commit_and_tag(version: str, dry_run: bool) -> bool:
    """Stage changed files, commit, and create annotated tag.

    Stages: README.md, CHANGELOG.md, plugin.json, pyproject.toml, and any .py files
    modified by bump_version.py.

    Args:
        version: The version string for the commit message and tag.
        dry_run: If True, only print what would happen.

    Returns:
        True on success, False on failure.
    """
    _step("Step 5: Git commit and tag")

    tag = f"v{version}"

    # Files to stage explicitly
    files_to_stage = [
        "README.md",
        "CHANGELOG.md",
        ".claude-plugin/plugin.json",
        "pyproject.toml",
    ]

    # Also find any .py files that were modified (from bump_version)
    result = run_cmd(["git", "diff", "--name-only"])
    if result.returncode == 0 and result.stdout.strip():
        for changed_file in result.stdout.strip().splitlines():
            if changed_file.endswith(".py") and changed_file not in files_to_stage:
                files_to_stage.append(changed_file)

    if dry_run:
        _info(f"  [DRY-RUN] Would stage: {', '.join(files_to_stage)}")
        _info(f"  [DRY-RUN] Would commit: release: {tag}")
        _info(f"  [DRY-RUN] Would create tag: {tag}")
        return True

    # Stage files
    existing_files = [f for f in files_to_stage if (REPO_ROOT / f).exists()]
    if existing_files:
        result = run_cmd(["git", "add"] + existing_files)
        if result.returncode != 0:
            _err(f"  git add failed: {result.stderr}")
            return False
        _ok(f"  Staged: {', '.join(existing_files)}")

    # Commit
    commit_msg = f"release: {tag}"
    result = run_cmd(["git", "commit", "-m", commit_msg])
    if result.returncode != 0:
        _err(f"  git commit failed: {result.stderr}")
        return False
    _ok(f"  Committed: {commit_msg}")

    # Create annotated tag
    result = run_cmd(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    if result.returncode != 0:
        _err(f"  git tag failed: {result.stderr}")
        return False
    _ok(f"  Tagged: {tag}")

    return True


# ---------------------------------------------------------------------------
# Step 6: Print push instructions
# ---------------------------------------------------------------------------


def print_push_instructions(version: str) -> None:
    """Print the manual push commands the user should run.

    Args:
        version: The version string for the tag name.
    """
    tag = f"v{version}"
    # Detect current branch instead of hardcoding 'main'
    branch_result = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"
    _step("Step 6: Push instructions")
    print()
    _info("  Release prepared. To publish, run:")
    print()
    print(f"    git push origin {branch} && git push origin {tag}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Main entry point for the release preparation CLI."""
    parser = argparse.ArgumentParser(
        description="Prepare a release: bump version, update README/CHANGELOG, commit and tag.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --patch            # 1.0.0 -> 1.0.1
  %(prog)s --minor            # 1.0.0 -> 1.1.0
  %(prog)s --major            # 1.0.0 -> 2.0.0
  %(prog)s --set 2.5.0        # Set explicit version
  %(prog)s --patch --dry-run  # Preview changes without writing
        """,
    )

    bump_group = parser.add_mutually_exclusive_group(required=True)
    bump_group.add_argument("--major", action="store_true", help="Bump major version (X.0.0)")
    bump_group.add_argument("--minor", action="store_true", help="Bump minor version (x.Y.0)")
    bump_group.add_argument("--patch", action="store_true", help="Bump patch version (x.y.Z)")
    bump_group.add_argument("--set", metavar="VERSION", help="Set explicit version (format: X.Y.Z)")

    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing files or committing",
    )

    args = parser.parse_args()

    # Determine bump type
    if args.set:
        # Validate semver format
        if not re.match(r"^\d+\.\d+\.\d+$", args.set.strip()):
            _err(f"Invalid version format '{args.set}'. Expected X.Y.Z")
            return 1
        bump_type = ""
        set_version: str | None = args.set.strip()
    elif args.major:
        bump_type = "major"
        set_version = None
    elif args.minor:
        bump_type = "minor"
        set_version = None
    else:
        bump_type = "patch"
        set_version = None

    dry_run = args.dry_run

    print(f"{_BOLD}{'=' * 60}{_NC}")
    print(f"{_BOLD}  Release Preparation{' (DRY RUN)' if dry_run else ''}{_NC}")
    print(f"{_BOLD}{'=' * 60}{_NC}")

    # Step 1: Bump version
    new_version = bump_version(bump_type, set_version, dry_run)
    if new_version is None:
        _err("Aborting: version bump failed")
        return 1

    # Step 2: Update README badges
    if not update_readme_badges(new_version, dry_run):
        _err("Aborting: README badge update failed")
        return 1

    # Step 3: Update README version text
    if not update_readme_version_text(new_version, dry_run):
        _err("Aborting: README version text update failed")
        return 1

    # Step 4: Prepend CHANGELOG entry
    if not prepend_changelog_entry(new_version, dry_run):
        _err("Aborting: CHANGELOG update failed")
        return 1

    # Step 5: Git commit and tag (skip in dry-run, but still show what would happen)
    if not git_commit_and_tag(new_version, dry_run):
        _err("Aborting: git operations failed")
        return 1

    # Step 6: Print push instructions
    if not dry_run:
        print_push_instructions(new_version)
    else:
        _step("Step 6: Push instructions")
        _info(f"  [DRY-RUN] Would print: git push origin main && git push origin v{new_version}")

    print()
    print(f"{_BOLD}{'=' * 60}{_NC}")
    if dry_run:
        _ok("  Dry run complete. No files were changed.")
    else:
        _ok(f"  Release v{new_version} prepared successfully!")
    print(f"{_BOLD}{'=' * 60}{_NC}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
