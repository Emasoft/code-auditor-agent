#!/usr/bin/env python3
"""Version bumping script for code-auditor-agent.

Bumps version in .claude-plugin/plugin.json and pyproject.toml.

Usage:
    bump_version.py major
    bump_version.py minor
    bump_version.py patch
    bump_version.py set X.Y.Z
    bump_version.py patch --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    """Walk up from start directory until .claude-plugin/plugin.json is found."""
    current = start.resolve()
    while True:
        candidate = current / ".claude-plugin" / "plugin.json"
        if candidate.exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "Could not find .claude-plugin/plugin.json in any parent directory"
            )
        current = parent


def parse_semver(version_str: str) -> tuple[int, int, int]:
    """Parse 'X.Y.Z' string into (major, minor, patch) ints."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version_str.strip())
    if not match:
        raise ValueError(f"Invalid semver string: {version_str!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_semver(major: int, minor: int, patch: int, part: str) -> tuple[int, int, int]:
    """Return new (major, minor, patch) after bumping the requested part."""
    if part == "major":
        return major + 1, 0, 0
    if part == "minor":
        return major, minor + 1, 0
    if part == "patch":
        return major, minor, patch + 1
    raise ValueError(f"Unknown bump part: {part!r}")


def read_plugin_json(path: Path) -> dict[str, object]:
    """Read and return parsed plugin.json content."""
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, object] = json.load(f)
        return data


def write_plugin_json(path: Path, data: dict) -> None:
    """Write dict back to plugin.json with 2-space indent and trailing newline (atomic)."""
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    # Atomic rename: either the full write succeeds or the original is untouched.
    tmp.rename(path)


def update_pyproject_version(pyproject_path: Path, new_version: str, dry_run: bool) -> bool:
    """Replace version = "X.Y.Z" line in pyproject.toml. Returns True if changed."""
    if not pyproject_path.exists():
        print(f"WARNING: {pyproject_path} not found — skipping pyproject.toml update")
        return False

    text = pyproject_path.read_text(encoding="utf-8")

    # Match version = "X.Y.Z" under [project] or [tool.poetry] tables.
    # We use a simple pattern that replaces the first occurrence of:
    #   version = "X.Y.Z"
    # which is the canonical location for both PEP 517 and Poetry.
    pattern = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
    match = pattern.search(text)
    if not match:
        print("WARNING: Could not find version = \"...\" in pyproject.toml — skipping")
        return False

    new_text = pattern.sub(rf"\g<1>{new_version}\2", text, count=1)
    if new_text == text:
        print("pyproject.toml version already up to date")
        return False

    if not dry_run:
        # Atomic write: write to a temp file then rename so a partial write never
        # leaves pyproject.toml in a corrupted/intermediate state.
        tmp = pyproject_path.with_suffix(".toml.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.rename(pyproject_path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump version in plugin.json and pyproject.toml"
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # Positional bump commands: major / minor / patch
    for part in ("major", "minor", "patch"):
        sp = subparsers.add_parser(part, help=f"Bump {part} version component")
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing files",
        )

    # Explicit set command
    sp_set = subparsers.add_parser("set", help="Set version to an explicit X.Y.Z value")
    sp_set.add_argument("version", metavar="X.Y.Z", help="Version string to set")
    sp_set.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    # Locate project root
    script_dir = Path(__file__).parent
    try:
        root = find_project_root(script_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    plugin_json_path = root / ".claude-plugin" / "plugin.json"
    pyproject_path = root / "pyproject.toml"

    # Read current version from plugin.json
    try:
        plugin_data = read_plugin_json(plugin_json_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR reading {plugin_json_path}: {exc}", file=sys.stderr)
        return 1

    current_version_str = str(plugin_data.get("version", ""))
    if not current_version_str:
        print("ERROR: 'version' key not found in plugin.json", file=sys.stderr)
        return 1

    try:
        major, minor, patch = parse_semver(current_version_str)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Determine new version
    if args.command == "set":
        try:
            new_major, new_minor, new_patch = parse_semver(args.version)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    else:
        new_major, new_minor, new_patch = bump_semver(major, minor, patch, args.command)

    new_version_str = f"{new_major}.{new_minor}.{new_patch}"
    dry_run: bool = args.dry_run

    print(f"Version: {current_version_str} → {new_version_str}")
    if dry_run:
        print("(dry-run: no files written)")
        return 0

    # Save originals for rollback in case the second write fails.
    original_plugin_text = plugin_json_path.read_text(encoding="utf-8")

    # Update pyproject.toml FIRST so that if plugin.json write fails we only
    # need to rollback the less-critical file (pyproject may not even exist).
    changed = update_pyproject_version(pyproject_path, new_version_str, dry_run=False)
    if changed:
        print(f"Updated: {pyproject_path.relative_to(root)}")

    # Update plugin.json; rollback pyproject.toml if this write fails.
    try:
        plugin_data["version"] = new_version_str
        write_plugin_json(plugin_json_path, plugin_data)
        print(f"Updated: {plugin_json_path.relative_to(root)}")
    except OSError as exc:
        # Rollback pyproject.toml to its original content so both files stay
        # in sync even when plugin.json could not be written.
        if changed:
            try:
                tmp = pyproject_path.with_suffix(".toml.tmp")
                tmp.write_text(original_plugin_text, encoding="utf-8")
                tmp.rename(pyproject_path)
                print("Rolled back pyproject.toml to original version", file=sys.stderr)
            except OSError as rollback_exc:
                print(
                    f"ERROR: Failed to rollback pyproject.toml: {rollback_exc}",
                    file=sys.stderr,
                )
        print(f"ERROR: Failed to write plugin.json: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
