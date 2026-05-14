"""AWS CloudFormation template discoverer.

Finds each resource declaration inside the top-level `Resources:` map of
a CloudFormation template (`.template`, `.yaml`, `.yml`, `.json`).

Each resource entry is the YAML map key directly under `Resources:`,
whose value is a map containing `Type: AWS::<Service>::<Resource>`. We
emit one EntryPoint per resource — symbol is the logical resource name
(the user-supplied key), and metadata captures the `Type` and the
extracted properties' top-level keys when easy to find.

Heuristic regex only (no yaml/json dependency). We anchor on the
`Resources:` block opening line and then look for lines matching
a 2-space-indented capitalised key whose value is a map, stopping at
the next column-0 top-level key (Outputs, Parameters, etc.) or EOF.

JSON templates are also supported via a separate scan that looks for
`"Resources"` followed by `{` and then iterates `"<Name>": {` entries
with a nested `"Type": "AWS::..."` line.

Determinism: file order is sorted; matches within a file are processed
in scan order; dedup by (file, line, symbol); final sort by sort_key().
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_cloudformation"


# Top-level `Resources:` key (column 0, no indent) in YAML.
_YAML_RESOURCES_RE = re.compile(r"""^Resources\s*:\s*$""", re.MULTILINE)

# Resource entry: `  MyName:` at 2-space indent.
_YAML_RESOURCE_NAME_RE = re.compile(
    r"""^[ ]{2}(?P<name>[A-Za-z][A-Za-z0-9]*)\s*:\s*(?:#.*)?$""",
    re.MULTILINE,
)

# Inside a resource block, find `    Type: AWS::Service::Resource`.
_YAML_TYPE_RE = re.compile(
    r"""^[ ]{4}Type\s*:\s*[\"']?(?P<type>AWS::[A-Za-z0-9]+(?:::[A-Za-z0-9]+)+)[\"']?\s*(?:#.*)?$""",
    re.MULTILINE,
)

# Next column-0 top-level key (delimits the Resources block end).
_YAML_TOPLEVEL_KEY_RE = re.compile(r"""^[A-Za-z][A-Za-z0-9_]*\s*:""", re.MULTILINE)


# JSON: `"Resources"` block opener.
_JSON_RESOURCES_RE = re.compile(r"""["']Resources["']\s*:\s*\{""")
# JSON: `"<Name>": {` entries. Restricted to alphanumeric names (CFN
# logical IDs are AlphaNumeric, no dashes/underscores per CFN spec).
_JSON_RESOURCE_NAME_RE = re.compile(
    r"""["'](?P<name>[A-Za-z][A-Za-z0-9]*)["']\s*:\s*\{""",
)
# JSON: `"Type": "AWS::Service::Resource"` inside a resource block.
_JSON_TYPE_RE = re.compile(
    r"""["']Type["']\s*:\s*["'](?P<type>AWS::[A-Za-z0-9]+(?:::[A-Za-z0-9]+)+)["']""",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — CFN templates can be large


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _looks_like_cfn(text: str) -> bool:
    """Cheap pre-check: file must contain `AWSTemplateFormatVersion` or
    a `Resources:` block with `AWS::` typed entries."""
    if "AWSTemplateFormatVersion" in text:
        return True
    return "Resources" in text and "AWS::" in text


def _find_resources_block_end(text: str, block_start: int) -> int:
    """Return offset where the YAML `Resources:` block ends.

    Ends at the next column-0 top-level key (e.g. `Outputs:`,
    `Parameters:`) or EOF.
    """
    m = _YAML_TOPLEVEL_KEY_RE.search(text, block_start)
    return m.start() if m else len(text)


def _yaml_scan(text: str, rel: str) -> list[EntryPoint]:
    """Find resources in a YAML CFN template. Skip if Resources block absent."""
    found: list[EntryPoint] = []
    res_m = _YAML_RESOURCES_RE.search(text)
    if not res_m:
        return found
    block_start = res_m.end()
    block_end = _find_resources_block_end(text, block_start)
    block = text[block_start:block_end]
    block_offset = block_start

    for nm in _YAML_RESOURCE_NAME_RE.finditer(block):
        name = nm.group("name")
        abs_offset = block_offset + nm.start()
        line = _line_of(text, abs_offset)

        # Find the `Type:` line inside THIS resource block — bounded by
        # the next sibling resource name or the block end.
        sib_search = _YAML_RESOURCE_NAME_RE.search(block, nm.end())
        sib_end = sib_search.start() if sib_search else len(block)
        sub = block[nm.end() : sib_end]
        type_m = _YAML_TYPE_RE.search(sub)
        if not type_m:
            continue  # not a real resource — could be a comment or stray key
        res_type = type_m.group("type")

        found.append(
            EntryPoint(
                kind=EntryPointKind.TERRAFORM_RESOURCE,
                file=rel,
                line=line,
                symbol=name,
                type_origin=TYPE_ORIGIN,
                metadata={
                    "logical_id": name,
                    "resource_type": res_type,
                    "format": "yaml",
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )
    return found


def _json_scan(text: str, rel: str) -> list[EntryPoint]:
    """Find resources in a JSON CFN template."""
    found: list[EntryPoint] = []
    res_m = _JSON_RESOURCES_RE.search(text)
    if not res_m:
        return found
    # We don't track brace depth — instead, for each resource-name
    # match after the Resources opener, we look for its nearest
    # following `"Type": "AWS::..."` and accept it if no other
    # resource-name intervenes between the two.
    block_start = res_m.end()
    # Find candidate resource names; record their offsets.
    candidates: list[tuple[int, str]] = []
    for nm in _JSON_RESOURCE_NAME_RE.finditer(text, block_start):
        candidates.append((nm.start(), nm.group("name")))
    for i, (offset, name) in enumerate(candidates):
        next_off = candidates[i + 1][0] if i + 1 < len(candidates) else len(text)
        sub = text[offset:next_off]
        type_m = _JSON_TYPE_RE.search(sub)
        if not type_m:
            continue
        res_type = type_m.group("type")
        line = _line_of(text, offset)
        found.append(
            EntryPoint(
                kind=EntryPointKind.TERRAFORM_RESOURCE,
                file=rel,
                line=line,
                symbol=name,
                type_origin=TYPE_ORIGIN,
                metadata={
                    "logical_id": name,
                    "resource_type": res_type,
                    "format": "json",
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )
    return found


def _iter_relevant_files(repo_root: Path) -> list[Path]:
    """Sorted list of .yaml/.yml/.template/.json files outside SKIP_DIRS."""
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
        if p.suffix.lower() not in (".yaml", ".yml", ".template", ".json"):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find CloudFormation resources. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_relevant_files(repo_root):
        text = _read(path)
        if not text:
            continue
        if not _looks_like_cfn(text):
            continue
        rel = str(path.relative_to(repo_root))
        if path.suffix.lower() == ".json":
            found.extend(_json_scan(text, rel))
        else:
            found.extend(_yaml_scan(text, rel))

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
