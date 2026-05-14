"""Pulumi resource discoverer (TypeScript / Python entrypoints).

Pulumi programs are ordinary application code (TS / JS / Python / Go / .NET)
co-located with a `Pulumi.yaml` project manifest. The runtime side-effect
that creates infrastructure is the instantiation of a Pulumi resource
class:

- TypeScript / JavaScript:  `new aws.s3.Bucket("my-bucket", {...})`
- Python:                   `aws.s3.Bucket("my-bucket", ...)`
                            or `aws.s3.BucketV2("my-bucket")`

Each instantiation becomes one EntryPoint. Symbol is the Pulumi logical
resource name (the first string arg, which the user supplies and which
also forms part of Pulumi's URN). Metadata records the provider /
resource type chain so the walker can reason about the resource family
(s3.Bucket vs dynamodb.Table vs sqs.Queue, etc.).

Heuristic regex only — no JS/TS parser, no AST. The patterns are deliberately
narrow:

- TS/JS: `new <provider>.<...>.<Resource>(\"<name>\", {...})` — at least
  one `.` between provider and resource class. We accept any number of
  segments between (`aws.s3.Bucket`, `aws.iam.policies.Policy`).
- Python: `<provider>.<...>.<Resource>(\"<name>\"` — same shape minus
  the `new` keyword. Python resource constructors don't use `new`; the
  detector requires the line to look like a CONSTRUCTOR call (not a
  method call), so we require the leading dotted path to start with a
  segment that looks like a Pulumi provider (lowercase identifier).

Determinism: file order is sorted, matches within a file are processed
in scan order, dedup by (file, line, symbol), final sort by sort_key().
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_pulumi"


# TS / JS: `new <provider>.<...>.<Resource>("<name>"`
_TS_NEW_RE = re.compile(
    r"""new\s+(?P<chain>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\s*\(\s*["'](?P<name>[A-Za-z0-9_\-\.:/]+)["']""",
)

# Python: `<provider>.<...>.<Resource>("<name>"`
# Restricted to start-of-line / after assignment / after `(` so plain
# method calls like `bucket.id` don't match.
_PY_CTOR_RE = re.compile(
    r"""(?:^|[\s=,\(\[])(?P<chain>[a-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\s*\(\s*["'](?P<name>[A-Za-z0-9_\-\.:/]+)["']""",
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
        ".pulumi",
    }
)


# Common Pulumi provider package roots — used to filter out the noise of
# plain stdlib / app constructor calls in Python (where `new` is absent).
_PULUMI_PROVIDER_ROOTS: frozenset[str] = frozenset(
    {
        "aws",
        "pulumi_aws",
        "azure",
        "pulumi_azure",
        "azure_native",
        "pulumi_azure_native",
        "gcp",
        "pulumi_gcp",
        "google_native",
        "pulumi_google_native",
        "kubernetes",
        "pulumi_kubernetes",
        "k8s",
        "docker",
        "pulumi_docker",
        "random",
        "pulumi_random",
        "tls",
        "pulumi_tls",
        "cloudflare",
        "pulumi_cloudflare",
        "digitalocean",
        "pulumi_digitalocean",
        "github",
        "pulumi_github",
        "vault",
        "pulumi_vault",
        "consul",
        "pulumi_consul",
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB — Pulumi programs are rarely huge


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _split_chain(chain: str) -> tuple[str, str]:
    """Split `aws.s3.Bucket` → (provider='aws', resource_type='s3.Bucket')."""
    parts = chain.split(".")
    if len(parts) < 2:
        return (parts[0], "")
    return (parts[0], ".".join(parts[1:]))


def _iter_relevant_files(repo_root: Path) -> list[Path]:
    """Sorted list of .ts/.js/.py files outside SKIP_DIRS."""
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
        if p.suffix.lower() not in (".ts", ".js", ".mjs", ".cjs", ".py"):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Pulumi resource instantiations. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_relevant_files(repo_root):
        text = _read(path)
        if not text:
            continue
        # Cheap skip — file must reference Pulumi somewhere or it cannot
        # be a Pulumi program.
        lower = text.lower()
        if "pulumi" not in lower and "@pulumi/" not in text:
            continue
        rel = str(path.relative_to(repo_root))
        suffix = path.suffix.lower()

        if suffix in (".ts", ".js", ".mjs", ".cjs"):
            for m in _TS_NEW_RE.finditer(text):
                chain = m.group("chain")
                provider, resource_type = _split_chain(chain)
                # Filter out obvious non-Pulumi `new` calls (e.g.
                # `new Date()`, `new pulumi.Config()`, ...).
                if provider == "pulumi":
                    # Allow pulumi.<something>.<Resource> but not bare
                    # `new pulumi.Config()` which has only one dot.
                    if chain.count(".") < 2:
                        continue
                else:
                    # Must look like a provider — lowercase first segment.
                    if not provider[:1].islower():
                        continue
                name = m.group("name")
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.TERRAFORM_RESOURCE,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "provider": provider,
                            "resource_type": resource_type,
                            "language": "typescript" if suffix == ".ts" else "javascript",
                            "chain": chain,
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )
        elif suffix == ".py":
            for m in _PY_CTOR_RE.finditer(text):
                chain = m.group("chain")
                provider, resource_type = _split_chain(chain)
                # Python: only accept calls where the root segment is a
                # known Pulumi provider — keeps the signal-to-noise ratio
                # high on a fixture that may also contain unrelated code.
                if provider not in _PULUMI_PROVIDER_ROOTS:
                    continue
                if not resource_type:
                    # Bare `aws("name")` isn't a resource — skip.
                    continue
                name = m.group("name")
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.TERRAFORM_RESOURCE,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "provider": provider,
                            "resource_type": resource_type,
                            "language": "python",
                            "chain": chain,
                        },
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
