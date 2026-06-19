#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 11 — Agent-Written-Code extension scanner (TRDD-7e364ace G11-G14).

Three deterministic checks that complement the existing
`caa-code-correctness-agent` AWC sub-checklist:

1. **`UNDECLARED_DEP`** — `import X` (or JS `import x from 'pkg'`) for
   a top-level package that does NOT appear in the project's
   dependency manifest (pyproject.toml/setup.py/Pipfile,
   package.json, Cargo.toml, go.mod). Common cause: agent
   hallucinates an import without remembering to add the dep.
2. **`UNUSED_DEP`** — manifest declares a dependency that is never
   imported anywhere in the source tree. Common cause: agent adds
   a dep "just in case" and never uses it; the bloat lingers.
3. **`HARDCODED_CONFIG`** — literals that smell like configuration
   (URLs, IPv4/IPv6, file paths starting with `/`, ports, magic
   numbers > 100). Agent-written code tends to hardcode these.
   Severity is `nit` — the agent confirms.

For Python, the import-name → distribution-name gap (e.g.
`import yaml` from `pyyaml`) is partially closed by a small known-
mappings table for the most common cases. Anything outside the
table relies on the agent for confirmation.

Stdlib / Node-builtin / Go-stdlib imports are excluded — they're
never declared in a manifest and would dominate the false-positive
rate otherwise.

Usage:
    python -m scripts.prereview.awc_extensions <repo_root> <out_dir>
        [--pr-files-from <txt>]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1
SCAN_CAP_BYTES = 200_000
MAGIC_NUMBER_THRESHOLD = 100  # numbers above this trigger HARDCODED_CONFIG

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        "target",
        ".cache",
        ".idea",
        ".vscode",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
        "samples_dev",
        "examples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
        ".trashcan",
    }
)

# Known Python `import X` ↔ pyproject distribution name mappings — the
# usual suspects that bite us most often. Keys: import module name,
# values: distribution name (lowercase, hyphenated as on PyPI).
_PY_IMPORT_TO_DIST: dict[str, str] = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "google.protobuf": "protobuf",
    "google": "google-api-core",
    "rest_framework": "djangorestframework",
    "OpenSSL": "pyopenssl",
    "magic": "python-magic",
    "memcache": "python-memcached",
    "Crypto": "pycryptodome",
    "skimage": "scikit-image",
    "_pytest": "pytest",
    "mss": "mss",
}


# Reverse: distribution → set of import names it provides. Used to
# decide "is THIS declared dep ever imported?". A single dist can map
# to multiple import names.
def _build_dist_to_imports() -> dict[str, frozenset[str]]:
    accumulator: dict[str, set[str]] = {}
    for imp, dist in _PY_IMPORT_TO_DIST.items():
        accumulator.setdefault(dist, set()).add(imp)
    return {k: frozenset(v) for k, v in accumulator.items()}


_PY_DIST_TO_IMPORTS: dict[str, frozenset[str]] = _build_dist_to_imports()

# Node built-in modules — never appear in package.json dependencies.
_NODE_BUILTINS: frozenset[str] = frozenset(
    {
        "assert",
        "buffer",
        "child_process",
        "cluster",
        "crypto",
        "dgram",
        "dns",
        "events",
        "fs",
        "fs/promises",
        "http",
        "http2",
        "https",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "querystring",
        "readline",
        "stream",
        "string_decoder",
        "timers",
        "tls",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "worker_threads",
        "zlib",
        "node:assert",
        "node:buffer",
        "node:child_process",
        "node:crypto",
        "node:fs",
        "node:fs/promises",
        "node:http",
        "node:https",
        "node:os",
        "node:path",
        "node:process",
        "node:stream",
        "node:url",
        "node:util",
    }
)


@dataclass(frozen=True, slots=True)
class Finding:
    tool: str
    category: str
    file: str
    line: int
    severity: str
    code: str
    message: str


# ---- IO helpers ------------------------------------------------------------


def _enumerate_repo(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fname in sorted(filenames):
            out.append(Path(dirpath) / fname)
    return out


def _load_pr_files(repo_root: Path, path: Path | None) -> list[Path] | None:
    if path is None:
        return None
    if not path.is_file():
        raise FileNotFoundError(f"--pr-files-from: not found: {path}")
    files: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rel = line.strip()
        if not rel or rel.startswith("#"):
            continue
        abs_path = (repo_root / rel).resolve()
        # Confine to the repo tree: a `../../etc/hosts` listing entry resolves
        # outside repo_root (out-of-tree read). Mirrors concurrency.py's fix.
        if abs_path.is_file() and abs_path.is_relative_to(repo_root.resolve()):
            files.append(abs_path)
    return sorted(set(files))


def _read_text_capped(path: Path) -> str:
    try:
        with path.open("rb") as f:
            data = f.read(SCAN_CAP_BYTES)
    except OSError:
        return ""
    return data.decode("utf-8", errors="ignore")


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.name


# ---- Manifest parsers ------------------------------------------------------


_REQUIREMENTS_DEP_RE = re.compile(
    r"^\s*(?:-e\s+)?([A-Za-z0-9_.\-]+)(?:\[[^]]*\])?\s*(?:[<>=!~].*)?",
)


_INLINE_QUOTED_DEP_RE = re.compile(
    r'"([A-Za-z0-9_.\-]+)(?:\[[^]]*\])?\s*(?:[<>=!~^].*?)?"',
)


def _parse_pyproject_dependencies(text: str) -> set[str]:
    """Extract dependency names from `[project] dependencies = [...]` /
    `[project.optional-dependencies] *` / `[tool.poetry.dependencies]`
    blocks. Conservative — uses regex rather than a TOML parser so this
    script keeps zero dependencies.

    Handles both single-line (`dependencies = ["x", "y"]`) and multi-line
    forms. The single-line form is parsed by scanning every quoted token
    on the trigger line itself.
    """
    deps: set[str] = set()
    in_deps_block = False
    in_poetry_deps = False
    in_optional_deps_table = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            in_deps_block = False
            in_poetry_deps = (
                section.startswith("tool.poetry.dependencies")
                or section.startswith("tool.poetry.dev-dependencies")
                or section.startswith("tool.poetry.group.")
            )
            # PEP-621 [project.optional-dependencies] and PEP-735
            # [dependency-groups] are TABLES whose entries are `extra = [...]`
            # (key is the extra/group name, not "dependencies"), so the
            # is_trigger gate below misses them — the dominant uv/PEP-621 shape.
            in_optional_deps_table = section in {
                "project.optional-dependencies",
                "dependency-groups",
            }
            continue
        # PEP-621/735 dep-table entry: `name = ["pkg", ...]` keyed by the
        # extra/group name. Parse it (and its multi-line continuation) as a
        # dependency list, which the "dependencies"-keyed trigger would skip.
        if in_optional_deps_table and "=" in line and "[" in line:
            for m in _INLINE_QUOTED_DEP_RE.finditer(raw):
                deps.add(m.group(1).lower())
            if "]" not in raw.split("[", 1)[1]:
                in_deps_block = True
            continue
        # Trigger line — `dependencies = [...]` / `optional-dependencies.foo = [...]`.
        # If the trigger and closing `]` are on the same line, we extract
        # every quoted name from this line directly.
        is_trigger = "dependencies" in line.split("=", 1)[0].lower() and "=" in line and "[" in line
        if is_trigger:
            for m in _INLINE_QUOTED_DEP_RE.finditer(raw):
                deps.add(m.group(1).lower())
            if "]" not in raw.split("[", 1)[1]:
                in_deps_block = True
            continue
        if in_deps_block:
            if "]" in raw:
                in_deps_block = False
                # The closing bracket may share its line with a final dep
                # name — still parse the line.
                for m in _INLINE_QUOTED_DEP_RE.finditer(raw):
                    deps.add(m.group(1).lower())
                continue
            for m in _INLINE_QUOTED_DEP_RE.finditer(raw):
                deps.add(m.group(1).lower())
            continue
        # Poetry: `name = "version"` lines inside [tool.poetry.dependencies]
        if in_poetry_deps and "=" in line and "[" not in line:
            key = line.split("=", 1)[0].strip()
            if key and key not in {"python"} and not key.startswith("#"):
                deps.add(key.lower())
    return deps


def _parse_requirements_txt(text: str) -> set[str]:
    deps: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _REQUIREMENTS_DEP_RE.match(line)
        if m:
            deps.add(m.group(1).lower())
    return deps


_PACKAGE_JSON_DEP_RE = re.compile(r'"([@\w/\-_.]+)"\s*:\s*"[^"]+"')


def _parse_package_json_dependencies(text: str) -> set[str]:
    """Extract dependency names from package.json (regex-based)."""
    deps: set[str] = set()
    # Find each `dependencies` / `devDependencies` / `peerDependencies`
    # / `optionalDependencies` block — they're shallow JSON objects.
    for block_key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        m = re.search(rf'"{block_key}"\s*:\s*\{{(?P<body>[^{{}}]*)\}}', text)
        if m:
            for dep_match in _PACKAGE_JSON_DEP_RE.finditer(m.group("body")):
                deps.add(dep_match.group(1))
    return deps


_CARGO_DEP_RE = re.compile(r'^\s*([\w\-]+)\s*=\s*(?:"[^"]+"|\{)')


def _parse_cargo_toml_dependencies(text: str) -> set[str]:
    deps: set[str] = set()
    in_dep_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            in_dep_block = (
                section == "dependencies"
                or section == "dev-dependencies"
                or section == "build-dependencies"
                or section.startswith("target.")
                and "dependencies" in section
            )
            continue
        if not in_dep_block:
            continue
        m = _CARGO_DEP_RE.match(raw)
        if m:
            deps.add(m.group(1))
    return deps


_GO_MOD_REQUIRE_RE = re.compile(r"^\s*([\w./\-]+)\s+v[\w.\-+]+")


def _parse_go_mod(text: str) -> set[str]:
    deps: set[str] = set()
    in_require_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block and line == ")":
            in_require_block = False
            continue
        if in_require_block:
            m = _GO_MOD_REQUIRE_RE.match(raw)
            if m:
                deps.add(m.group(1))
        elif line.startswith("require "):
            after = line[len("require ") :].strip()
            m = _GO_MOD_REQUIRE_RE.match(after) or re.match(r"^([\w./\-]+)", after)
            if m:
                deps.add(m.group(1))
    return deps


def _collect_manifest_deps(_repo_root: Path, files: Iterable[Path]) -> dict[str, set[str]]:
    """Return {manifest_kind: set_of_dep_names} for every manifest found."""
    out: dict[str, set[str]] = {
        "python": set(),
        "node": set(),
        "rust": set(),
        "go": set(),
    }
    for path in files:
        name = path.name
        try:
            text = _read_text_capped(path)
        except OSError:
            continue
        if name == "pyproject.toml":
            out["python"] |= _parse_pyproject_dependencies(text)
        elif name == "requirements.txt":
            out["python"] |= _parse_requirements_txt(text)
        elif name == "package.json":
            out["node"] |= _parse_package_json_dependencies(text)
        elif name == "Cargo.toml":
            out["rust"] |= _parse_cargo_toml_dependencies(text)
        elif name == "go.mod":
            out["go"] |= _parse_go_mod(text)
    return out


# ---- Import collectors -----------------------------------------------------


def _collect_python_imports(files: Iterable[Path]) -> dict[str, list[tuple[Path, int]]]:
    """Top-level module → list of (file, line) where it was imported."""
    imports: dict[str, list[tuple[Path, int]]] = {}
    for path in files:
        if path.suffix.lower() not in {".py", ".pyi"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    imports.setdefault(top, []).append((path, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative import
                if not node.module:
                    continue
                top = node.module.split(".", 1)[0]
                imports.setdefault(top, []).append((path, node.lineno))
    return imports


_JS_IMPORT_RE = re.compile(
    r"""^\s*(?:import\s+(?:[\w*{}\s,$]+\s+from\s+)?["'](?P<a>[^"']+)["']
        |const\s+[\w{}\s,$]+\s*=\s*require\(\s*["'](?P<b>[^"']+)["']\s*\)
        )""",
    re.VERBOSE,
)


def _js_pkg_root(spec: str) -> str:
    """`@scope/pkg/sub` → `@scope/pkg`; `pkg/sub` → `pkg`."""
    if spec.startswith("@"):
        parts = spec.split("/", 2)
        return "/".join(parts[:2])
    return spec.split("/", 1)[0]


def _collect_node_imports(files: Iterable[Path]) -> dict[str, list[tuple[Path, int]]]:
    imports: dict[str, list[tuple[Path, int]]] = {}
    for path in files:
        if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        for line_idx, line in enumerate(text.splitlines(), start=1):
            m = _JS_IMPORT_RE.match(line)
            if not m:
                continue
            spec = m.group("a") or m.group("b") or ""
            if spec.startswith((".", "/")):
                continue
            if spec in _NODE_BUILTINS:
                continue
            pkg = _js_pkg_root(spec)
            imports.setdefault(pkg, []).append((path, line_idx))
    return imports


# ---- Drift checks ----------------------------------------------------------


def _python_is_stdlib(name: str) -> bool:
    """Detect Python stdlib module via `sys.stdlib_module_names`."""
    return name in sys.stdlib_module_names


def _check_python_deps(
    repo_root: Path,
    manifest_deps: set[str],
    code_imports: dict[str, list[tuple[Path, int]]],
) -> list[Finding]:
    out: list[Finding] = []
    declared_lc = {d.lower() for d in manifest_deps}
    # 1) Imported but not declared.
    for imp, sites in sorted(code_imports.items()):
        if _python_is_stdlib(imp):
            continue
        # Skip the current project's own top-level package — its imports
        # are first-party. The heuristic: the project name in pyproject
        # matches a top-level module in src/. We don't parse the package
        # name here; instead skip names with no PyPI-shape AND no mapping.
        dist_guess = _PY_IMPORT_TO_DIST.get(imp, imp).lower()
        if dist_guess in declared_lc:
            continue
        # Also accept hyphen/underscore variants.
        if dist_guess.replace("_", "-") in declared_lc or dist_guess.replace("-", "_") in declared_lc:
            continue
        # First-occurrence site for the finding.
        first_path, first_line = sites[0]
        out.append(
            Finding(
                tool="awc_extensions",
                category="undeclared_dep",
                file=_rel(repo_root, first_path),
                line=first_line,
                severity="warning",
                code="UNDECLARED_DEP",
                message=(
                    f"`import {imp}` referenced from {len(sites)} site(s) but not declared in any "
                    f"pyproject.toml / requirements.txt / Pipfile"
                ),
            )
        )
    # 2) Declared but not imported. Map dist → known import names; check if
    # ANY of those import names appears in code_imports.
    imported_lc = {k for k in code_imports}
    for dist in sorted(declared_lc):
        candidates: set[str] = set()
        candidates.add(dist)
        candidates.add(dist.replace("-", "_"))
        candidates.add(dist.replace("_", "-"))
        if dist in _PY_DIST_TO_IMPORTS:
            candidates |= set(_PY_DIST_TO_IMPORTS[dist])
        if any(c in imported_lc or c.replace("-", "_") in imported_lc for c in candidates):
            continue
        out.append(
            Finding(
                tool="awc_extensions",
                category="unused_dep",
                file="pyproject.toml",  # canonical site for declarations
                line=1,
                severity="nit",
                code="UNUSED_DEP",
                message=(f"manifest declares `{dist}` but no `import` of {sorted(candidates)} found in source"),
            )
        )
    return out


def _check_node_deps(
    repo_root: Path,
    manifest_deps: set[str],
    code_imports: dict[str, list[tuple[Path, int]]],
) -> list[Finding]:
    out: list[Finding] = []
    declared = manifest_deps
    # 1) Imported but not declared.
    for imp, sites in sorted(code_imports.items()):
        if imp in declared:
            continue
        first_path, first_line = sites[0]
        out.append(
            Finding(
                tool="awc_extensions",
                category="undeclared_dep",
                file=_rel(repo_root, first_path),
                line=first_line,
                severity="warning",
                code="UNDECLARED_DEP",
                message=(
                    f"`import` from `{imp}` referenced from {len(sites)} site(s) but not declared in any "
                    f"package.json dependencies block"
                ),
            )
        )
    # 2) Declared but not imported.
    imported = set(code_imports.keys())
    for dep in sorted(declared - imported):
        out.append(
            Finding(
                tool="awc_extensions",
                category="unused_dep",
                file="package.json",
                line=1,
                severity="nit",
                code="UNUSED_DEP",
                message=f"package.json declares `{dep}` but no source file imports it",
            )
        )
    return out


# ---- Hardcoded-config literal scan ----------------------------------------


_URL_RE = re.compile(r"https?://[\w.:/\-?&=#@%]+")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# A path that LOOKS like a config artefact: absolute path with at least
# two segments, not under /tmp/.
_PATH_RE = re.compile(r"\"\s*(/[A-Za-z][\w./\-]+/[\w./\-]+)\s*\"|\'(/[A-Za-z][\w./\-]+/[\w./\-]+)\'")
# Accept the field-name `port` followed by an optional closing quote, then
# the colon/equals separator. Matches both `port: 5432` (Python dict) and
# `"port": 5432` (JSON-like) and `'port':5432`.
_PORT_RE = re.compile(r"""['"]?\bport\b['"]?\s*[:=]\s*(\d{2,5})\b""", re.IGNORECASE)
_MAGIC_NUM_RE = re.compile(r"\b(\d{3,})\b")

# Allow-list of common values that aren't really "magic" — HTTP status
# codes, power-of-two byte sizes, well-known ports. Anything else > 100
# is surfaced for agent review.
_COMMON_NON_MAGIC_NUMBERS: frozenset[int] = frozenset(
    {
        200,
        201,
        204,
        301,
        302,
        400,
        401,
        403,
        404,
        500,
        502,
        503,
        1000,
        1024,
        8080,
    }
)


def _check_hardcoded(repo_root: Path, files: Iterable[Path]) -> list[Finding]:
    out: list[Finding] = []
    for path in files:
        if path.suffix.lower() not in {".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs"}:
            continue
        text = _read_text_capped(path)
        if not text:
            continue
        rel = _rel(repo_root, path)
        for line_idx, line in enumerate(text.splitlines(), start=1):
            # Skip obvious test-data / fixture / sample lines so the report
            # isn't dominated by them. Conservative: lines mentioning
            # `example.com`/`localhost`/`127.0.0.1` are likely fixtures.
            lower = line.lower()
            if any(s in lower for s in ("example.com", "localhost", "127.0.0.1", "::1")):
                continue
            # Skip comments-only lines (Python `#`, JS `//`, Rust/Go `//`).
            stripped = line.lstrip()
            if stripped.startswith(("#", "//")):
                continue
            url_m = _URL_RE.search(line)
            if url_m:
                out.append(
                    Finding(
                        tool="awc_extensions",
                        category="hardcoded_config",
                        file=rel,
                        line=line_idx,
                        severity="nit",
                        code="HARDCODED_URL",
                        message=f"URL literal `{url_m.group(0)[:80]}` — consider config / env var",
                    )
                )
                continue  # one finding per line
            ipv4 = _IPV4_RE.search(line)
            if ipv4:
                ip = ipv4.group(0)
                # 0.x / 255.x / 169.254.x / 224.x and the like are unusual
                # config; we still flag them — the agent decides.
                parts = [int(p) for p in ip.split(".")]
                if all(0 <= p < 256 for p in parts) and ip not in {"0.0.0.0"}:
                    out.append(
                        Finding(
                            tool="awc_extensions",
                            category="hardcoded_config",
                            file=rel,
                            line=line_idx,
                            severity="nit",
                            code="HARDCODED_IP",
                            message=f"IPv4 literal `{ip}` — consider config / env var",
                        )
                    )
                    continue
            path_m = _PATH_RE.search(line)
            if path_m:
                raw_path = path_m.group(1) or path_m.group(2)
                if raw_path and not raw_path.startswith("/tmp"):
                    out.append(
                        Finding(
                            tool="awc_extensions",
                            category="hardcoded_config",
                            file=rel,
                            line=line_idx,
                            severity="nit",
                            code="HARDCODED_PATH",
                            message=f"Absolute path literal `{raw_path}` — consider config / env var",
                        )
                    )
                    continue
            port_m = _PORT_RE.search(line)
            if port_m:
                port = int(port_m.group(1))
                if 1 <= port <= 65535:
                    out.append(
                        Finding(
                            tool="awc_extensions",
                            category="hardcoded_config",
                            file=rel,
                            line=line_idx,
                            severity="nit",
                            code="HARDCODED_PORT",
                            message=f"port literal `{port}` — consider config / env var",
                        )
                    )
                    continue
            magic = _MAGIC_NUM_RE.findall(line)
            for m in magic:
                value = int(m)
                if value > MAGIC_NUMBER_THRESHOLD and value not in _COMMON_NON_MAGIC_NUMBERS:
                    out.append(
                        Finding(
                            tool="awc_extensions",
                            category="hardcoded_config",
                            file=rel,
                            line=line_idx,
                            severity="nit",
                            code="MAGIC_NUMBER",
                            message=f"magic number `{value}` — consider named constant or config",
                        )
                    )
                    break  # one per line
    return out


# ---- Driver ---------------------------------------------------------------


def _local_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S%z", time.localtime())


def detect(repo_root: Path, pr_files: list[Path] | None = None) -> dict[str, object]:
    if not repo_root.is_dir():
        raise NotADirectoryError(f"repo_root is not a directory: {repo_root}")
    all_files = pr_files if pr_files is not None else _enumerate_repo(repo_root)
    # Manifests come from the WHOLE repo even when --pr-files-from is set —
    # the manifest is the source of truth and probably isn't in the PR
    # subset itself.
    manifest_source_files = all_files if pr_files is None else _enumerate_repo(repo_root)
    manifest_deps = _collect_manifest_deps(repo_root, manifest_source_files)
    findings: list[Finding] = []
    # Python deps
    py_imports = _collect_python_imports(all_files)
    if manifest_deps["python"]:
        findings.extend(_check_python_deps(repo_root, manifest_deps["python"], py_imports))
    # Node deps
    node_imports = _collect_node_imports(all_files)
    if manifest_deps["node"]:
        findings.extend(_check_node_deps(repo_root, manifest_deps["node"], node_imports))
    # Hardcoded config literals
    findings.extend(_check_hardcoded(repo_root, all_files))
    findings.sort(key=lambda f: (f.category, f.file, f.line, f.code))
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "repo_root": str(repo_root.resolve()),
        "manifest_dep_counts": {k: len(v) for k, v in manifest_deps.items()},
        "total_findings": len(findings),
        "by_category": dict(sorted(by_category.items())),
        "findings": [asdict(f) for f in findings],
    }


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 11 — Agent-Written-Code extension scanner.",
        prog="awc_extensions",
    )
    parser.add_argument("repo_root")
    parser.add_argument("out_dir")
    parser.add_argument("--pr-files-from")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_argv(argv[1:])
    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"out_dir unwritable: {exc}", file=sys.stderr)
        return 1
    try:
        pr_files = _load_pr_files(repo_root, Path(args.pr_files_from) if args.pr_files_from else None)
        payload = detect(repo_root, pr_files)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = out_dir / f"{payload['timestamp']}-awc_extensions.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
