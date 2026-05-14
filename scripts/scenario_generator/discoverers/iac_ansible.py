"""Ansible playbook / role task discoverer.

Finds each Ansible task across:
- `playbook.yml` / `playbook.yaml` at the repo root or under any
  inventory directory
- `roles/<name>/tasks/*.yml` / `*.yaml` — role-shipped task lists

A "task" is any YAML list item with a `name:` key on the same line as a
list-item dash (`- name: foo`). The task name is the value of that
`name:` key; the line recorded is the line where the list-item begins.
Each task becomes one EntryPoint (Ansible's natural unit of work —
one task is one infrastructure mutation step).

The play-level `- name: ...` (the playbook header
`- name: Configure X hosts` at column 0) is ALSO emitted as an entry
point — at the play level Ansible reasons about hosts/become/handlers,
all of which can be analysed by the walker's family expansion.

Heuristic regex only (no yaml dependency). We split multi-document
files on a literal `---` line and within each document find lines
matching a list-item dash followed by a `name:` key. Bare `name: foo`
lines inside a module call (e.g. `apt:` with `name: nginx`) are NOT
tasks and are filtered out — task-name lines ALWAYS lead with `-`.

Determinism: file order is sorted; matches within a file are processed
in scan order; dedup by (file, line, symbol); final sort by sort_key().
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_ansible"


# Match `- name: <value>` — the dash is REQUIRED. The list-item dash is
# what distinguishes a task header from a bare module argument
# (`name: nginx` inside `apt:`). The dash sits at the same indent level
# as its list parent; we capture leading whitespace just for the
# play/task scope classification (column 0 → play; deeper → task).
_TASK_NAME_RE = re.compile(
    r"""^(?P<indent>[ \t]*)-\s+name\s*:\s*(?P<value>.+?)\s*(?:#.*)?$""",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        "tests",
        "test",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB


# Files we consider Ansible-shaped without requiring content sniff.
_FIXED_FILENAMES: frozenset[str] = frozenset(
    {
        "playbook.yml",
        "playbook.yaml",
        "site.yml",
        "site.yaml",
        "main.yml",
        "main.yaml",
    }
)


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _split_docs(text: str) -> list[tuple[int, str]]:
    """Split multi-document YAML on `^---$` lines. Return [(start_line, body), ...]."""
    docs: list[tuple[int, str]] = []
    lines = text.splitlines(keepends=True)
    current_start_line = 1
    current_buf: list[str] = []
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            if current_buf:
                docs.append((current_start_line, "".join(current_buf)))
                current_buf = []
            current_start_line = i + 2
            continue
        current_buf.append(ln)
    if current_buf:
        body = "".join(current_buf)
        if body.strip():
            docs.append((current_start_line, body))
    return docs


def _is_ansible_file(path: Path, rel_parts: tuple[str, ...]) -> bool:
    """Is this path Ansible-shaped by location/name?

    - filename in _FIXED_FILENAMES (playbook.yml, site.yml, main.yml, ...)
    - any path component is `tasks` (role tasks dir) or `handlers` /
      `vars` / `defaults` (role subfolders)
    """
    name = path.name
    if name in _FIXED_FILENAMES:
        return True
    return any(part in ("tasks", "handlers", "vars", "defaults", "roles") for part in rel_parts)


def _iter_ansible_files(repo_root: Path) -> list[Path]:
    """Sorted list of .yml/.yaml files that LOOK Ansible-shaped."""
    out: list[Path] = []
    for p in repo_root.rglob("*"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".yml", ".yaml"):
            continue
        if not _is_ansible_file(p, rel_parts):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Ansible plays + tasks. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_ansible_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # Is this a role task file (under roles/<role>/tasks/...) or a
        # top-level playbook? Used purely for metadata enrichment.
        rel_parts = path.relative_to(repo_root).parts
        is_role_task = "roles" in rel_parts and "tasks" in rel_parts
        role_name = ""
        if is_role_task:
            try:
                roles_idx = rel_parts.index("roles")
                role_name = rel_parts[roles_idx + 1] if roles_idx + 1 < len(rel_parts) else ""
            except ValueError:
                role_name = ""

        for doc_start_line, body in _split_docs(text):
            for m in _TASK_NAME_RE.finditer(body):
                indent = m.group("indent")
                value = m.group("value").strip().strip("\"'")
                if not value:
                    continue
                # The line number in the original file = doc_start_line
                # + offset-to-newline-count within the doc body.
                line_in_doc = body.count("\n", 0, m.start())
                line = doc_start_line + line_in_doc
                metadata: dict[str, object] = {
                    "name": value,
                    "indent": len(indent),
                }
                if role_name:
                    metadata["role"] = role_name
                # Classify by indent + filename: a top-level play (`- name:`
                # at column 0) only appears in a playbook file. A
                # role-task file at column 0 is the role's task list
                # itself, so column 0 there is a task.
                if len(indent) == 0 and not is_role_task:
                    metadata["scope"] = "play"
                else:
                    metadata["scope"] = "task"
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.TERRAFORM_RESOURCE,
                        file=rel,
                        line=line,
                        symbol=value,
                        type_origin=TYPE_ORIGIN,
                        metadata=metadata,
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by (file, line, symbol).
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: e.sort_key())
    return unique
