"""docker-compose service discoverer.

Finds the top-level `services:` mapping inside `docker-compose.yml`,
`compose.yaml`, or `compose.yml` and emits one EntryPoint per service.

The service name is the YAML key at the second level of indentation
under `services:`. The line recorded is the line of the service-name
key itself (the `service-name:` line). Each entry is treated as an
"infrastructure resource" the walker can reason about — image, ports,
environment, restart policy, depends_on, etc. are captured in
metadata when visible on simple `key: value` lines inside the service
block.

Heuristic regex-only parsing (no yaml dependency). We assume the
canonical 2-space indentation that nearly every compose file uses;
anything more exotic is ignored. The walker still gets the service
name and file path, which is enough for the scenario family expansion
(happy_path, persistence_corruption, upgrade_migration, ...).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_docker_compose"


# Top-level `services:` key (column 0, no indent).
_SERVICES_RE = re.compile(r"""^services\s*:\s*$""", re.MULTILINE)

# A service name is a 2-space-indented YAML key — `  <name>:` — directly
# under `services:`. We require the key to start with a letter or digit
# and be followed by `:` and either EOL or whitespace+EOL/comment.
_SERVICE_NAME_RE = re.compile(
    r"""^[ ]{2}(?P<name>[A-Za-z0-9][A-Za-z0-9_\-.]*)\s*:\s*(?:#.*)?$""",
    re.MULTILINE,
)

# Inside a service block, simple `    key: value` lines (4-space indent).
_SERVICE_KEY_RE = re.compile(
    r"""^[ ]{4}(?P<key>image|build|restart|container_name|hostname)\s*:\s*(?P<val>.+?)\s*(?:#.*)?$""",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — compose files rarely larger


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_service_block_end(text: str, block_start: int) -> int:
    """Return the offset where the current service block ends.

    A block ends at the next 2-space-indented key (`^  <name>:`) or at
    the next 0-indent top-level section (`^<key>:`), whichever comes
    first. End-of-file is the fallback.
    """
    # Find next service-name boundary (2-space indent) or top-level (0-indent).
    next_service = _SERVICE_NAME_RE.search(text, block_start)
    # Top-level keys at column 0.
    top_level_re = re.compile(r"""^[A-Za-z][A-Za-z0-9_\-]*\s*:\s*$""", re.MULTILINE)
    next_toplevel = top_level_re.search(text, block_start)

    candidates: list[int] = []
    if next_service:
        candidates.append(next_service.start())
    if next_toplevel:
        candidates.append(next_toplevel.start())
    if not candidates:
        return len(text)
    return min(candidates)


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find docker-compose services. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    compose_files: list[Path] = []
    candidate_names = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
    for p in repo_root.rglob("*"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        if p.name not in candidate_names:
            continue
        compose_files.append(p)
    compose_files.sort()

    for path in compose_files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        services_m = _SERVICES_RE.search(text)
        if not services_m:
            continue
        services_start = services_m.end()

        # Find where `services:` block ends — the first line at column 0
        # that is itself a top-level key (not blank).
        top_level_re = re.compile(r"""^[A-Za-z][A-Za-z0-9_\-]*\s*:\s*$""", re.MULTILINE)
        end_of_services = top_level_re.search(text, services_start)
        services_block = text[services_start : end_of_services.start()] if end_of_services else text[services_start:]
        services_block_offset = services_start

        # Iterate 2-space-indented service-name keys inside this block.
        for sm in _SERVICE_NAME_RE.finditer(services_block):
            name = sm.group("name")
            abs_offset = services_block_offset + sm.start()
            line = _line_of(text, abs_offset)

            # Bounded service-body slice for extracting image/build/etc.
            body_start_abs = services_block_offset + sm.end()
            body_end_abs = _find_service_block_end(text, body_start_abs)
            body = text[body_start_abs:body_end_abs]

            metadata: dict[str, object] = {"service": name}
            for km in _SERVICE_KEY_RE.finditer(body):
                metadata[km.group("key")] = km.group("val").strip().strip("\"'")

            found.append(
                EntryPoint(
                    kind=EntryPointKind.TERRAFORM_RESOURCE,
                    file=rel,
                    line=line,
                    symbol=f"services.{name}",
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
