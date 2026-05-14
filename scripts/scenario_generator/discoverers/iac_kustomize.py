"""Kustomize overlay discoverer.

Finds every `kustomization.yaml` (or `kustomization.yml`,
`Kustomization`) in the repo and emits one EntryPoint per entry under
its `resources:` list, plus one EntryPoint per patched resource
target. Sibling YAMLs referenced by a kustomization (base manifests
like `deployment.yaml` / `service.yaml`) also yield one EntryPoint per
embedded Kubernetes document (kind + name).

Two kinds of entry points:

1. **Resource reference** — one per entry under `resources:` in a
   kustomization. Symbol is the literal path string from the YAML (e.g.
   `../../base` or `deployment.yaml`); file/line points at the line in
   the kustomization where the reference lives.

2. **Patched resource** — one per entry under `patches:` (or the
   legacy `patchesStrategicMerge:` / `patchesJson6902:`). Symbol is
   `<kind>/<name>` reconstructed from the patch target stanza (or from
   the patch file's body if the patch is given as `path:`).

3. **Base manifest resource** — one per YAML doc inside any
   `.yaml`/`.yml` file co-located with a kustomization (sibling files,
   not referenced kustomizations). Symbol is `<kind>/<name>` from the
   doc's apiVersion/kind/metadata.name.

Heuristic regex only (no yaml dependency). The walker reasons about
overlays at the kustomization-edge boundary, so resource references +
patched targets are enough for the family expansion.

Determinism: file order is sorted; matches within a file are processed
in scan order; dedup by (file, line, symbol); final sort by sort_key().
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "iac_kustomize"


# Kustomization filenames per kustomize spec.
_KUSTOMIZATION_NAMES: frozenset[str] = frozenset(
    {
        "kustomization.yaml",
        "kustomization.yml",
        "Kustomization",
    }
)

# `apiVersion:` / `kind:` / `metadata.name:` — same shape as Helm/k8s.
_API_VERSION_RE = re.compile(r"""^\s*apiVersion\s*:\s*(?P<v>.+?)\s*$""", re.MULTILINE)
_KIND_RE = re.compile(r"""^\s*kind\s*:\s*(?P<k>.+?)\s*$""", re.MULTILINE)
_METADATA_NAME_RE = re.compile(
    r"""^metadata\s*:\s*\n(?:[ \t]+[^\n]*\n)*?[ \t]+name\s*:\s*(?P<n>.+?)\s*$""",
    re.MULTILINE,
)

# Top-level key block opener — anchors `resources:` and `patches:` lists.
_TOPLEVEL_LIST_RE = re.compile(
    r"""^(?P<key>resources|patches|patchesStrategicMerge|patchesJson6902|components|bases)\s*:\s*$""",
    re.MULTILINE,
)

# A list-item line in a kustomize section: `  - <value>`.
_LIST_ITEM_RE = re.compile(
    r"""^[ ]{2}-\s+(?P<value>[^\s#].+?)\s*(?:#.*)?$""",
    re.MULTILINE,
)

# A patch stanza target inside a `patches:` list item — `target: { kind: X, name: Y }`
# in either inline or block form.
_PATCH_TARGET_KIND_RE = re.compile(
    r"""^[ ]{4,}kind\s*:\s*(?P<k>[A-Za-z][A-Za-z0-9]*)\s*$""",
    re.MULTILINE,
)
_PATCH_TARGET_NAME_RE = re.compile(
    r"""^[ ]{4,}name\s*:\s*(?P<n>[A-Za-z][A-Za-z0-9_\-.]*)\s*$""",
    re.MULTILINE,
)
_PATCH_PATH_RE = re.compile(
    r"""^[ ]{2,}-?\s*path\s*:\s*(?P<p>[^\s#].+?)\s*(?:#.*)?$""",
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


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _split_docs(text: str) -> list[tuple[int, str]]:
    """Split multi-document YAML on `^---$` lines."""
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


def _find_section_end(text: str, section_start: int) -> int:
    """Find where a top-level `key:` section ends.

    A section ends at the next top-level key at column 0 (matched by
    `_TOPLEVEL_LIST_RE` or any `^[A-Za-z]\\w*:`), or EOF.
    """
    # Use a broad "next column-0 key" pattern.
    other_key_re = re.compile(r"""^[A-Za-z][A-Za-z0-9_]*\s*:""", re.MULTILINE)
    m = other_key_re.search(text, section_start)
    return m.start() if m else len(text)


def _scan_kustomization(text: str, rel: str) -> list[EntryPoint]:
    """Find entries under `resources:` / `patches:` etc. inside a kustomization."""
    found: list[EntryPoint] = []
    for sm in _TOPLEVEL_LIST_RE.finditer(text):
        section_key = sm.group("key")
        section_start = sm.end()
        section_end = _find_section_end(text, section_start)
        section_body = text[section_start:section_end]
        section_offset = section_start

        if section_key in ("resources", "components", "bases"):
            for im in _LIST_ITEM_RE.finditer(section_body):
                value = im.group("value").strip().strip("\"'")
                if not value:
                    continue
                abs_offset = section_offset + im.start()
                line = _line_of(text, abs_offset)
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.TERRAFORM_RESOURCE,
                        file=rel,
                        line=line,
                        symbol=value,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "section": section_key,
                            "reference": value,
                            "kind_role": "resource_reference",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )
        elif section_key in ("patches", "patchesStrategicMerge", "patchesJson6902"):
            # Each patch is a list-item — try to extract its target kind/name.
            # We split the section body at each `- ` item start (at 2-space
            # indent) and scan each chunk for kind/name inside `target:`.
            # patchesStrategicMerge is just a list of paths.
            if section_key == "patchesStrategicMerge":
                for im in _LIST_ITEM_RE.finditer(section_body):
                    value = im.group("value").strip().strip("\"'")
                    if not value:
                        continue
                    abs_offset = section_offset + im.start()
                    line = _line_of(text, abs_offset)
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.TERRAFORM_RESOURCE,
                            file=rel,
                            line=line,
                            symbol=value,
                            type_origin=TYPE_ORIGIN,
                            metadata={
                                "section": section_key,
                                "patch_path": value,
                                "kind_role": "patch_strategic_merge",
                            },
                            docstring="",
                            intended_behaviour_sources=(),
                        )
                    )
                continue

            # `patches:` items: each list item is a multi-line dict with
            # `path:` / `target:`. Iterate item starts (2-space dash).
            item_re = re.compile(r"""^[ ]{2}-[ ]""", re.MULTILINE)
            item_starts = [m.start() for m in item_re.finditer(section_body)]
            for i, start in enumerate(item_starts):
                end = item_starts[i + 1] if i + 1 < len(item_starts) else len(section_body)
                chunk = section_body[start:end]
                kind_m = _PATCH_TARGET_KIND_RE.search(chunk)
                name_m = _PATCH_TARGET_NAME_RE.search(chunk)
                path_m = _PATCH_PATH_RE.search(chunk)
                kind = kind_m.group("k") if kind_m else ""
                name = name_m.group("n") if name_m else ""
                patch_path = path_m.group("p").strip().strip("\"'") if path_m else ""
                if kind and name:
                    symbol = f"{kind}/{name}"
                elif patch_path:
                    symbol = patch_path
                else:
                    continue
                abs_offset = section_offset + start
                line = _line_of(text, abs_offset)
                metadata: dict[str, object] = {
                    "section": section_key,
                    "kind_role": "patch_target",
                }
                if kind:
                    metadata["target_kind"] = kind
                if name:
                    metadata["target_name"] = name
                if patch_path:
                    metadata["patch_path"] = patch_path
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
    return found


def _scan_manifest(text: str, rel: str) -> list[EntryPoint]:
    """Find Kubernetes resources in a sibling manifest file (multi-doc YAML)."""
    found: list[EntryPoint] = []
    for doc_start_line, body in _split_docs(text):
        kind_m = _KIND_RE.search(body)
        api_m = _API_VERSION_RE.search(body)
        name_m = _METADATA_NAME_RE.search(body)
        kind_val = kind_m.group("k").strip() if kind_m else ""
        api_val = api_m.group("v").strip() if api_m else ""
        name_val = name_m.group("n").strip() if name_m else ""
        if not kind_val:
            continue
        symbol = f"{kind_val}/{name_val}" if name_val else kind_val
        found.append(
            EntryPoint(
                kind=EntryPointKind.TERRAFORM_RESOURCE,
                file=rel,
                line=doc_start_line,
                symbol=symbol,
                type_origin=TYPE_ORIGIN,
                metadata={
                    "kind": kind_val,
                    "apiVersion": api_val,
                    "name": name_val,
                    "kind_role": "base_manifest",
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )
    return found


def _iter_relevant_files(repo_root: Path) -> tuple[list[Path], list[Path]]:
    """Returns (kustomization_files, sibling_manifest_files) — sorted, disjoint.

    A sibling manifest is any .yaml/.yml file that lives in a directory
    that also contains a kustomization file (so it is a candidate base
    manifest the kustomization references).
    """
    kustom: list[Path] = []
    yaml_files: list[Path] = []
    for p in repo_root.rglob("*"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        if p.name in _KUSTOMIZATION_NAMES:
            kustom.append(p)
        elif p.suffix.lower() in (".yaml", ".yml"):
            yaml_files.append(p)
    kustom.sort()
    yaml_files.sort()

    # A sibling manifest is one whose parent dir contains a
    # kustomization file. Determine the set of dirs holding a kustom.
    kustom_dirs = {p.parent for p in kustom}
    siblings = [p for p in yaml_files if p.parent in kustom_dirs]
    return kustom, siblings


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Kustomize resource refs + patched targets + base manifests."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    kustomizations, siblings = _iter_relevant_files(repo_root)

    for path in kustomizations:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        found.extend(_scan_kustomization(text, rel))

    for path in siblings:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        found.extend(_scan_manifest(text, rel))

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
