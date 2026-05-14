"""Terraform HCL resource discoverer.

Finds Terraform `resource` and `module` blocks across `.tf` files and
emits one EntryPoint per declaration:

- `resource "<type>" "<name>" { ... }` — one EntryPoint per resource,
  symbol is `<type>.<name>` (Terraform's standard resource address).
- `module "<name>" { source = "..." }` — one EntryPoint per module
  reference, symbol is `module.<name>`.

Heuristic regex-only parsing (no HCL dependency). We grep on the
declaration line; nested braces are not balanced — we only need the
header line and (for modules) the `source = "..."` argument anywhere
in the block. The walker reasons about IaC scenarios at the
resource-declaration boundary, so the body's exact contents are not
material at discovery time.

Determinism: file order, declaration order within a file, and sort
keys (file, line, symbol) are all derived from sorted reads. No dict
ordering escapes the function.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_terraform"


# resource "aws_s3_bucket" "data" {
_RESOURCE_RE = re.compile(
    r"""^\s*resource\s+"(?P<type>[A-Za-z0-9_]+)"\s+"(?P<name>[A-Za-z0-9_\-]+)"\s*\{""",
    re.MULTILINE,
)

# module "vpc" {
_MODULE_RE = re.compile(
    r"""^\s*module\s+"(?P<name>[A-Za-z0-9_\-]+)"\s*\{""",
    re.MULTILINE,
)

# source = "terraform-aws-modules/vpc/aws"  (anywhere in module block)
_SOURCE_RE = re.compile(
    r"""^\s*source\s*=\s*"(?P<source>[^"]+)"\s*$""",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".terraform",
        ".terragrunt-cache",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — Terraform files can be large


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_source_in_block(text: str, block_start: int) -> str:
    """Scan forward from `block_start` for `source = "..."`, stopping at a
    balanced close-brace at depth 0. Best-effort; if braces are unbalanced
    we still return any source we find within a 4KB window.
    """
    window = text[block_start : block_start + 4096]
    # Simple depth-tracking scan to stop at the closing `}` of the block.
    depth = 0
    end = len(window)
    for i, ch in enumerate(window):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    sub = window[:end]
    m = _SOURCE_RE.search(sub)
    return m.group("source") if m else ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Terraform resources and modules. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    tf_files: list[Path] = []
    for p in repo_root.rglob("*.tf"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if p.is_file():
            tf_files.append(p)
    tf_files.sort()

    for path in tf_files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) `resource "<type>" "<name>" { ... }`
        for m in _RESOURCE_RE.finditer(text):
            res_type = m.group("type")
            res_name = m.group("name")
            symbol = f"{res_type}.{res_name}"
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.TERRAFORM_RESOURCE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "resource_type": res_type,
                        "resource_name": res_name,
                        "declaration": "resource",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) `module "<name>" { source = "..." }`
        for m in _MODULE_RE.finditer(text):
            mod_name = m.group("name")
            symbol = f"module.{mod_name}"
            line = _line_of(text, m.start())
            source = _find_source_in_block(text, m.end())
            metadata: dict[str, object] = {
                "module_name": mod_name,
                "declaration": "module",
            }
            if source:
                metadata["source"] = source
            found.append(
                EntryPoint(
                    kind=EntryPointKind.TERRAFORM_RESOURCE,
                    file=rel,
                    line=line,
                    symbol=symbol,
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
