#!/usr/bin/env python3
"""Sync CPV validation scripts from the upstream claude-plugins-validation repo.

Auto-discovers all .py scripts in the upstream scripts/ directory via the GitHub
Contents API, then syncs them locally — skipping only files in LOCAL_ONLY_SCRIPTS
(locally-customized files that must not be overwritten).

Usage:
    uv run python scripts/sync_cpv_scripts.py             # sync all targets
    uv run python scripts/sync_cpv_scripts.py --dry-run    # show what would change
    uv run python scripts/sync_cpv_scripts.py --check      # exit 1 if any file is stale (CI mode)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Upstream repository coordinates
# ---------------------------------------------------------------------------

UPSTREAM_OWNER = "Emasoft"
UPSTREAM_REPO = "claude-plugins-validation"
UPSTREAM_REF = "master"

# ---------------------------------------------------------------------------
# Local-only scripts: filenames that must NOT be overwritten by upstream sync.
# These have local customizations (e.g. update_skill_md_versions in bump_version,
# version enforcement in pre-push, local publish pipeline).
# ---------------------------------------------------------------------------

LOCAL_ONLY_SCRIPTS: set[str] = {
    "bump_version.py",           # local version has update_skill_md_versions()
    "check_version_consistency.py",  # removed upstream, kept locally
    "prepare_release.py",        # local-only release orchestrator
    "publish.py",                # local-only unified publish pipeline
    "sync_cpv_scripts.py",       # this file itself — never overwrite
}

# ---------------------------------------------------------------------------
# Color helpers -- disabled on Windows cmd.exe / when stdout is not a tty
# ---------------------------------------------------------------------------


def _colors_supported() -> bool:
    """Return True when the terminal likely supports ANSI escape codes."""
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
_CYAN = "\033[0;36m" if _USE_COLOR else ""
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


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Derive the repository root from this script's location (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def _fetch_upstream_file_info(upstream_path: str) -> dict[str, object]:
    """Fetch file metadata (sha, content) from the upstream repo via gh api.

    Returns the parsed JSON dict with at least 'sha' and 'content' keys.
    Raises RuntimeError on API failure.
    """
    endpoint = f"repos/{UPSTREAM_OWNER}/{UPSTREAM_REPO}/contents/{upstream_path}?ref={UPSTREAM_REF}"
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api failed for {upstream_path}: {result.stderr.strip()}")
    data: dict[str, object] = json.loads(result.stdout)
    return data


def _local_blob_sha(file_path: Path) -> str | None:
    """Compute the git blob SHA for a local file using `git hash-object`.

    Returns None if the file does not exist.
    """
    if not file_path.exists():
        return None
    result = subprocess.run(
        ["git", "hash-object", str(file_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git hash-object failed for {file_path}: {result.stderr.strip()}")
    return result.stdout.strip()


def _decode_content(api_response: dict) -> bytes:
    """Base64-decode the 'content' field from a GitHub Contents API response."""
    raw = api_response.get("content", "")
    # GitHub returns base64 with newlines sprinkled in; strip them before decoding
    return base64.b64decode(raw.replace("\n", ""))


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------


def discover_upstream_scripts() -> list[tuple[str, str]]:
    """List the upstream scripts/ directory and return sync targets.

    Queries the GitHub Contents API for all .py files in the upstream
    scripts/ directory, filtering out LOCAL_ONLY_SCRIPTS.
    Returns list of (upstream_path, local_relative_path) tuples.
    """
    endpoint = (
        f"repos/{UPSTREAM_OWNER}/{UPSTREAM_REPO}/contents/scripts"
        f"?ref={UPSTREAM_REF}"
    )
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to list upstream scripts/: {result.stderr.strip()}"
        )

    entries: list[dict[str, object]] = json.loads(result.stdout)
    targets: list[tuple[str, str]] = []
    for entry in entries:
        name = str(entry.get("name", ""))
        if not name.endswith(".py"):
            continue
        if name in LOCAL_ONLY_SCRIPTS:
            continue
        upstream_path = f"scripts/{name}"
        # Map to same local path
        targets.append((upstream_path, upstream_path))

    targets.sort(key=lambda t: t[0])
    return targets


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


def sync_targets(
    repo_root: Path,
    targets: list[tuple[str, str]],
    dry_run: bool = False,
    check_only: bool = False,
) -> tuple[int, int, int, list[str]]:
    """Sync all targets from upstream.

    Returns (checked, updated, skipped, stale_names) counts.
    """
    checked = 0
    updated = 0
    skipped = 0
    errored = 0
    stale: list[str] = []

    for upstream_path, local_rel_path in targets:
        checked += 1
        local_path = repo_root / local_rel_path
        label = local_rel_path

        try:
            # Fetch upstream metadata
            api_data = _fetch_upstream_file_info(upstream_path)
            upstream_sha = api_data["sha"]

            # Compute local SHA
            local_sha = _local_blob_sha(local_path)

            if local_sha == upstream_sha:
                # Already in sync
                print(f"  {_GREEN}[in sync]{_NC}  {label}")
                skipped += 1
                continue

            # File is stale or missing locally
            status = "missing" if local_sha is None else "stale"
            stale.append(label)

            if check_only:
                print(f"  {_YELLOW}[{status}]{_NC}   {label}")
                continue

            if dry_run:
                print(f"  {_CYAN}[would update]{_NC} {label}  ({status})")
                continue

            # Actually update the file
            content = _decode_content(api_data)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            print(f"  {_BLUE}[updated]{_NC}  {label}  ({status})")
            updated += 1

        except Exception as exc:
            _err(f"  [error]   {label}: {exc}")
            errored += 1

    if errored > 0:
        _err(f"  {errored} file(s) failed to sync.")
        raise SystemExit(1)

    return checked, updated, skipped, stale


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync CPV validation scripts from upstream claude-plugins-validation repo.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing any files.",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any file is out of date (CI mode). Does not modify files.",
    )
    return parser


def main() -> int:
    """Entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args()

    repo_root = _repo_root()

    print()
    _info(f"{_BOLD}CPV Script Sync{_NC}")
    _info(f"Upstream: {UPSTREAM_OWNER}/{UPSTREAM_REPO}@{UPSTREAM_REF}")
    _info(f"Local root: {repo_root}")
    print()

    if args.check:
        _info("Mode: --check (read-only, CI mode)")
    elif args.dry_run:
        _info("Mode: --dry-run (no files will be written)")
    else:
        _info("Mode: sync (files will be updated)")
    print()

    # Auto-discover upstream scripts (minus LOCAL_ONLY_SCRIPTS)
    try:
        targets = discover_upstream_scripts()
    except RuntimeError as exc:
        _err(str(exc))
        return 1

    _info(f"Discovered {len(targets)} syncable scripts upstream")
    if LOCAL_ONLY_SCRIPTS:
        _info(f"Excluded (local-only): {', '.join(sorted(LOCAL_ONLY_SCRIPTS))}")
    print()

    try:
        checked, updated, skipped, stale = sync_targets(
            repo_root,
            targets,
            dry_run=args.dry_run,
            check_only=args.check,
        )
    except SystemExit:
        return 1

    # Summary
    print()
    _info("----------------------------------------")
    print(f"  Files checked:  {_BOLD}{checked}{_NC}")
    print(f"  Already in sync: {_GREEN}{skipped}{_NC}")

    if args.check:
        stale_count = len(stale)
        print(f"  Stale/missing:  {_YELLOW}{stale_count}{_NC}")
        if stale_count > 0:
            print()
            _warn("The following files are out of date:")
            for name in stale:
                print(f"    - {name}")
            print()
            _err("Run `uv run python scripts/sync_cpv_scripts.py` to update them.")
            return 1
        else:
            print()
            _ok("All CPV scripts are up to date.")
            return 0

    if args.dry_run:
        would_update = len(stale)
        print(f"  Would update:   {_CYAN}{would_update}{_NC}")
    else:
        print(f"  Updated:        {_BLUE}{updated}{_NC}")

    print()
    _ok("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
