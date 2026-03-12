#!/usr/bin/env python3
"""Unified publish pipeline: clean → test → sync → lint → validate → bump → README → CHANGELOG → commit → push.

Absorbs all release logic into a single fail-fast script.

Usage:
  uv run python scripts/publish.py --patch            # bump patch and publish
  uv run python scripts/publish.py --minor            # bump minor and publish
  uv run python scripts/publish.py --major            # bump major and publish
  uv run python scripts/publish.py --patch --dry-run   # preview only
  uv run python scripts/publish.py --patch --skip-tests # skip pytest

Exit codes:
    0 - Success
    1 - Any step failed (fail-fast)
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

# ── ANSI colors ──────────────────────────────────────────────────────────────

_USE_COLOR = (not os.environ.get("NO_COLOR")) and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
RED = "\033[0;31m" if _USE_COLOR else ""
GREEN = "\033[0;32m" if _USE_COLOR else ""
YELLOW = "\033[1;33m" if _USE_COLOR else ""
BLUE = "\033[0;34m" if _USE_COLOR else ""
BOLD = "\033[1m" if _USE_COLOR else ""
NC = "\033[0m" if _USE_COLOR else ""

# ── Lazy gitignore filter ────────────────────────────────────────────────────

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


# ── Helpers ──────────────────────────────────────────────────────────────────


def get_plugin_root() -> Path:
    """Resolve plugin root from this script's location (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path, *, check: bool = True, timeout: int = 600, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command, print it, and fail fast on error."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        print(f"\n{RED}✗ FAILED (exit {result.returncode}): {' '.join(cmd)}{NC}", file=sys.stderr)
        sys.exit(result.returncode)
    return result


# ── Semver helpers ───────────────────────────────────────────────────────────


def parse_semver(version: str) -> tuple[int, int, int] | None:
    """Parse 'X.Y.Z' into (major, minor, patch), or None if invalid."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def bump_semver(current: str, bump_type: str) -> str | None:
    """Bump version by type ('major', 'minor', 'patch'). Returns new version or None."""
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


# ── Version readers ──────────────────────────────────────────────────────────


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


# ── Version updaters ─────────────────────────────────────────────────────────


def update_plugin_json(plugin_root: Path, new_version: str) -> tuple[bool, str]:
    """Update version in plugin.json."""
    pj = plugin_root / ".claude-plugin" / "plugin.json"
    if not pj.exists():
        return False, "plugin.json not found"
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
        old = data.get("version", "unknown")
        data["version"] = new_version
        pj.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True, f"plugin.json: {old} → {new_version}"
    except Exception as e:
        return False, f"plugin.json error: {e}"


def update_pyproject_toml(plugin_root: Path, new_version: str) -> tuple[bool, str]:
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

        new_content, count = re.subn(pattern, _replace, content, flags=re.MULTILINE)
        if count == 0:
            return True, "pyproject.toml has no version field (skipped)"
        pp.write_text(new_content, encoding="utf-8")
        return True, f"pyproject.toml: {old_version} → {new_version}"
    except Exception as e:
        return False, f"pyproject.toml error: {e}"


_EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", "env", ".env", "node_modules", ".git", ".mypy_cache", ".ruff_cache"}


def update_python_versions(plugin_root: Path, new_version: str) -> list[tuple[bool, str]]:
    """Update __version__ variables in Python files."""
    results: list[tuple[bool, str]] = []
    gi = _get_gi(plugin_root)
    # Use rglob from gitignore filter if available, else fallback
    glob_source = gi if hasattr(gi, "rglob") else plugin_root
    for py_file in glob_source.rglob("*.py"):
        py_path = Path(py_file) if not isinstance(py_file, Path) else py_file
        parts_set = set(py_path.relative_to(plugin_root).parts)
        if parts_set & _EXCLUDE_DIRS or any(p.startswith(".") for p in py_path.relative_to(plugin_root).parts):
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
            pattern = r'^(__version__\s*=\s*["\'])(\d+\.\d+\.\d+)(["\'])$'
            old_version = None

            def _replace(match: re.Match[str]) -> str:
                nonlocal old_version
                old_version = match.group(2)
                return f"{match.group(1)}{new_version}{match.group(3)}"

            new_content, count = re.subn(pattern, _replace, content, flags=re.MULTILINE)
            if count > 0:
                py_path.write_text(new_content, encoding="utf-8")
                rel = str(py_path.relative_to(plugin_root))
                results.append((True, f"{rel}: {old_version} → {new_version}"))
        except Exception as e:
            rel = str(py_path.relative_to(plugin_root))
            results.append((False, f"{rel} error: {e}"))
    return results


def update_skill_md_versions(plugin_root: Path, new_version: str) -> list[tuple[bool, str]]:
    """Update version in SKILL.md frontmatter (YAML 'version:' field)."""
    results: list[tuple[bool, str]] = []
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return results
    for skill_md in skills_dir.rglob("SKILL.md"):
        try:
            content = skill_md.read_text(encoding="utf-8")
            pattern = r'^(version:\s*)(\d+\.\d+\.\d+)(.*)$'
            old_version = None

            def _replace_fm(match: re.Match[str]) -> str:
                nonlocal old_version
                old_version = match.group(2)
                return f"{match.group(1)}{new_version}{match.group(3)}"

            new_content, count = re.subn(pattern, _replace_fm, content, count=1, flags=re.MULTILINE)
            if count > 0:
                skill_md.write_text(new_content, encoding="utf-8")
                rel = str(skill_md.relative_to(plugin_root))
                results.append((True, f"{rel}: {old_version} → {new_version}"))
        except Exception as e:
            rel = str(skill_md.relative_to(plugin_root))
            results.append((False, f"{rel} error: {e}"))
    return results


# ── Version consistency ──────────────────────────────────────────────────────


def check_version_consistency(plugin_root: Path) -> tuple[bool, str]:
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
            m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pp.read_text(encoding="utf-8"), re.MULTILINE)
            if m:
                versions["pyproject.toml"] = m.group(1)
        except Exception:
            pass

    # SKILL.md frontmatter
    skills_dir = plugin_root / "skills"
    if skills_dir.is_dir():
        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                m = re.search(r'^version:\s*(\d+\.\d+\.\d+)', skill_md.read_text(encoding="utf-8"), re.MULTILINE)
                if m:
                    rel = str(skill_md.relative_to(plugin_root))
                    versions[rel] = m.group(1)
            except Exception:
                pass

    # Python __version__ variables
    gi = _get_gi(plugin_root)
    glob_source = gi if hasattr(gi, "rglob") else plugin_root
    for py_file in glob_source.rglob("*.py"):
        py_path = Path(py_file) if not isinstance(py_file, Path) else py_file
        parts_set = set(py_path.relative_to(plugin_root).parts)
        if parts_set & _EXCLUDE_DIRS or any(p.startswith(".") for p in py_path.relative_to(plugin_root).parts):
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
            m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if m:
                rel = str(py_path.relative_to(plugin_root))
                versions[rel] = m.group(1)
        except Exception:
            pass

    if not versions:
        return True, "No version sources found"

    unique = set(versions.values())
    if len(unique) == 1:
        return True, f"All {len(versions)} sources consistent: {next(iter(unique))}"

    lines = ["Version mismatch detected:"]
    for src, ver in sorted(versions.items()):
        lines.append(f"  {src}: {ver}")
    return False, "\n".join(lines)


# ── Bump all files ───────────────────────────────────────────────────────────


def do_bump(plugin_root: Path, new_version: str, dry_run: bool = False) -> bool:
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


# ── README badges ────────────────────────────────────────────────────────────

BADGES_BLOCK = """\
[![CI](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Emasoft/code-auditor-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-{version}-blue)](https://github.com/Emasoft/code-auditor-agent)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)"""


def update_readme_badges(plugin_root: Path, version: str, dry_run: bool) -> bool:
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
        if stripped.startswith("[![CI]") or stripped.startswith("[![Version]"):
            if badges_start is None:
                badges_start = i
            badges_end = i + 1
        elif badges_start is not None and stripped.startswith("[!["):
            badges_end = i + 1
        elif badges_start is not None:
            break

    badge_lines = [bl + "\n" for bl in badges.split("\n")]
    if badges_start is not None and badges_end is not None:
        new_lines = lines[:badges_start] + badge_lines + lines[badges_end:]
        action = "Replaced"
    else:
        new_lines = lines[: heading_idx + 1] + ["\n"] + badge_lines + lines[heading_idx + 1 :]
        action = "Inserted"

    if dry_run:
        print(f"  [DRY-RUN] Would {action.lower()} badges in README.md")
    else:
        readme.write_text("".join(new_lines), encoding="utf-8")
        print(f"  {GREEN}{action} badges in README.md{NC}")
    return True


def update_readme_version_text(plugin_root: Path, version: str, dry_run: bool) -> bool:
    """Update the '**Version:** X.Y.Z' line in README.md."""
    readme = plugin_root / "README.md"
    if not readme.exists():
        return True
    content = readme.read_text(encoding="utf-8")
    pattern = r"(\*\*Version:\*\*\s*)\d+\.\d+\.\d+"
    new_content, count = re.subn(pattern, rf"\g<1>{version}", content)
    if count == 0:
        print(f"  {YELLOW}No '**Version:**' pattern in README.md (skipped){NC}")
        return True
    if dry_run:
        print(f"  [DRY-RUN] Would update version text to {version}")
    else:
        readme.write_text(new_content, encoding="utf-8")
        print(f"  {GREEN}Updated version text to {version} in README.md{NC}")
    return True


# ── CHANGELOG ────────────────────────────────────────────────────────────────


def get_previous_tag(cwd: Path) -> str | None:
    """Get the most recent git tag by version sort."""
    result = subprocess.run(["git", "tag", "--sort=-v:refname"], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0]


def get_git_log_since_tag(prev_tag: str | None, cwd: Path) -> str:
    """Get formatted git log entries since the previous tag."""
    if prev_tag:
        cmd = ["git", "log", "--pretty=format:- %s (%h)", f"{prev_tag}..HEAD"]
    else:
        cmd = ["git", "log", "--pretty=format:- %s (%h)"]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def prepend_changelog_entry(plugin_root: Path, version: str, dry_run: bool) -> bool:
    """Prepend a new changelog entry generated from git log."""
    changelog = plugin_root / "CHANGELOG.md"

    prev_tag = get_previous_tag(plugin_root)
    log_entries = get_git_log_since_tag(prev_tag, plugin_root)
    if not log_entries:
        log_entries = "- No changes recorded"

    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    new_entry = f"## [{version}] - {today}\n\n### Changes\n{log_entries}\n"

    if not changelog.exists():
        preamble = "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n"
        if dry_run:
            print(f"  [DRY-RUN] Would create CHANGELOG.md with entry for {version}")
        else:
            changelog.write_text(f"{preamble}{new_entry}\n", encoding="utf-8")
            print(f"  {GREEN}Created CHANGELOG.md with entry for {version}{NC}")
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
        new_lines = lines_list[:insert_idx] + entry_lines + ["\n"] + lines_list[insert_idx:]
    else:
        new_lines = [content.rstrip("\n"), "\n\n", new_entry, "\n"]

    if dry_run:
        print(f"  [DRY-RUN] Would prepend changelog entry for {version}")
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
        print(f"    ... and {len(log_entries.splitlines()) - 10} more")

    return True


# ── Main pipeline ────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Publish pipeline: clean → test → sync CPV → lint"
            " → validate (strict) → bump → README → CHANGELOG → commit → push"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --patch              # 1.0.0 → 1.0.1, commit, push
  %(prog)s --minor              # 1.0.0 → 1.1.0, commit, push
  %(prog)s --major              # 1.0.0 → 2.0.0, commit, push
  %(prog)s --patch --dry-run    # preview only, no changes
  %(prog)s --patch --skip-tests # skip pytest step
        """,
    )
    bump_group = parser.add_mutually_exclusive_group(required=True)
    bump_group.add_argument("--major", action="store_true", help="Bump major version")
    bump_group.add_argument("--minor", action="store_true", help="Bump minor version")
    bump_group.add_argument("--patch", action="store_true", help="Bump patch version")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest step")
    args = parser.parse_args()

    root = get_plugin_root()
    bump_type = "major" if args.major else "minor" if args.minor else "patch"

    print(f"\n{BOLD}{'=' * 60}{NC}")
    print(f"{BOLD}  Publish Pipeline{' (DRY RUN)' if args.dry_run else ''}{NC}")
    print(f"{BOLD}{'=' * 60}{NC}")

    # ── Step 1: Clean working tree ──
    print(f"\n{BLUE}═══ Step 1: Check working tree ═══{NC}")
    result = run(["git", "status", "--porcelain"], cwd=root, check=False)
    if result.stdout.strip():
        print(f"{RED}✗ Uncommitted changes detected. Commit or stash first.{NC}", file=sys.stderr)
        print(result.stdout.strip())
        return 1
    print(f"{GREEN}✓ Working tree clean{NC}")

    # ── Step 2: Tests ──
    tests_dir = root / "tests"
    if not args.skip_tests and tests_dir.is_dir():
        print(f"\n{BLUE}═══ Step 2: Run tests ═══{NC}")
        run(["uv", "run", "pytest", "tests/", "-x", "-q", "--tb=short"], cwd=root)
        print(f"{GREEN}✓ All tests passed{NC}")
    else:
        reason = "--skip-tests" if args.skip_tests else "no tests/ directory"
        print(f"\n{YELLOW}═══ Step 2: Tests skipped ({reason}) ═══{NC}")

    # ── Step 3: Sync CPV validator scripts from upstream ──
    print(f"\n{BLUE}═══ Step 3: Sync CPV validator scripts ═══{NC}")
    sync_script = root / "scripts" / "sync_cpv_scripts.py"
    if sync_script.exists():
        sync_result = run(["uv", "run", "python", str(sync_script)], cwd=root, check=False)
        if sync_result.returncode != 0:
            print(f"{YELLOW}⚠ CPV sync had errors (non-blocking){NC}")
        else:
            print(f"{GREEN}✓ CPV validator scripts synced{NC}")
    else:
        print(f"{YELLOW}sync_cpv_scripts.py not found (skipped){NC}")

    # ── Step 4: Lint ──
    print(f"\n{BLUE}═══ Step 4: Lint files ═══{NC}")
    lint_script = root / "scripts" / "lint_files.py"
    if lint_script.exists():
        run(["uv", "run", "python", str(lint_script), str(root)], cwd=root)
        print(f"{GREEN}✓ Linting passed{NC}")
    else:
        print(f"{YELLOW}lint_files.py not found (skipped){NC}")

    # ── Step 5: Validate plugin (strict) ──
    # Exit codes: 0=pass, 1=CRITICAL, 2=MAJOR, 3=MINOR, 4=NIT (strict)
    # ALL non-zero exit codes block publishing. Only WARNINGs pass through.
    print(f"\n{BLUE}═══ Step 5: Validate plugin (strict) ═══{NC}")
    validate_script = root / "scripts" / "validate_plugin.py"
    if validate_script.exists():
        val_result = run(["uv", "run", "python", str(validate_script), ".", "--strict"], cwd=root, check=False)
        if val_result.returncode != 0:
            sev_map = {1: "CRITICAL", 2: "MAJOR", 3: "MINOR", 4: "NIT"}
            severity = sev_map.get(val_result.returncode, f"exit {val_result.returncode}")
            print(f"{RED}✗ Plugin validation failed ({severity} issues){NC}", file=sys.stderr)
            print(f"{RED}  Fix ALL issues before publishing.{NC}", file=sys.stderr)
            return val_result.returncode
        print(f"{GREEN}✓ Plugin validation passed (strict){NC}")
    else:
        print(f"{YELLOW}validate_plugin.py not found (skipped){NC}")

    # ── Step 6: Version consistency ──
    print(f"\n{BLUE}═══ Step 6: Check version consistency ═══{NC}")
    ok, msg = check_version_consistency(root)
    print(f"  {msg}")
    if not ok:
        print(f"{RED}✗ Fix version mismatches before publishing.{NC}", file=sys.stderr)
        return 1
    print(f"{GREEN}✓ Version consistency OK{NC}")

    # ── Step 7: Bump version ──
    current = get_current_version(root)
    if current is None:
        print(f"{RED}✗ Cannot read current version from plugin.json{NC}", file=sys.stderr)
        return 1

    new_version = bump_semver(current, bump_type)
    if new_version is None:
        print(f"{RED}✗ Current version '{current}' is not valid semver{NC}", file=sys.stderr)
        return 1

    print(f"\n{BLUE}═══ Step 7: Bump version ({bump_type}: {current} → {new_version}) ═══{NC}")
    if not do_bump(root, new_version, dry_run=args.dry_run):
        print(f"{RED}✗ Version bump failed{NC}", file=sys.stderr)
        return 1
    print(f"{GREEN}✓ Version bumped to {new_version}{NC}")

    # ── Step 8: Update README badges ──
    print(f"\n{BLUE}═══ Step 8: Update README badges ═══{NC}")
    if not update_readme_badges(root, new_version, args.dry_run):
        print(f"{RED}✗ README badge update failed{NC}", file=sys.stderr)
        return 1
    print(f"{GREEN}✓ README badges updated{NC}")

    # ── Step 9: Update README version text ──
    print(f"\n{BLUE}═══ Step 9: Update README version text ═══{NC}")
    if not update_readme_version_text(root, new_version, args.dry_run):
        print(f"{RED}✗ README version text update failed{NC}", file=sys.stderr)
        return 1
    print(f"{GREEN}✓ README version text updated{NC}")

    # ── Step 10: Prepend CHANGELOG entry ──
    print(f"\n{BLUE}═══ Step 10: Prepend CHANGELOG entry ═══{NC}")
    if not prepend_changelog_entry(root, new_version, args.dry_run):
        print(f"{RED}✗ CHANGELOG update failed{NC}", file=sys.stderr)
        return 1
    print(f"{GREEN}✓ CHANGELOG updated{NC}")

    if args.dry_run:
        print(f"\n{GREEN}✓ Dry run complete — no changes made.{NC}")
        return 0

    # ── Step 11: Commit + tag ──
    print(f"\n{BLUE}═══ Step 11: Commit and tag ═══{NC}")
    tag = f"v{new_version}"
    # Use -u (tracked files only) instead of -A to avoid staging untracked files
    run(["git", "add", "-u"], cwd=root)
    run(["git", "commit", "-m", f"release: {tag}"], cwd=root)
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], cwd=root)
    print(f"{GREEN}✓ Committed and tagged {tag}{NC}")

    # ── Step 12: Push ──
    print(f"\n{BLUE}═══ Step 12: Push to origin ═══{NC}")
    # Detect current branch
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, capture_output=True, text=True
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"
    # Set env var so pre-push hook knows this is a legitimate publish pipeline push
    push_env = {**os.environ, "CAA_PUBLISH_PIPELINE": "1"}
    run(["git", "push", "origin", branch], cwd=root, env=push_env)
    run(["git", "push", "origin", tag], cwd=root, env=push_env)

    print(f"\n{GREEN}{'=' * 60}{NC}")
    print(f"{GREEN}  ✓ Published {tag} successfully!{NC}")
    print(f"{GREEN}{'=' * 60}{NC}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
