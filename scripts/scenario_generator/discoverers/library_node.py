"""Library-export discoverer for npm packages (JavaScript / TypeScript).

Selective discoverer for the `library_node` software type. A function
or class is a LIBRARY EXPORT iff it is exposed through one of the
patterns idiomatic to a published npm library:

1. Named ES-module exports at module scope:
       export function foo(...) { ... }
       export async function foo(...) { ... }
       export class Bar { ... }
       export const baz = (...) => { ... }
       export let qux = function(...) { ... }
   The captured symbol is the identifier directly after `function`,
   `class`, `const`, or `let`. Object-binding `export const { a, b } = ...`
   is intentionally NOT recognised in v1 — it's rare in published
   library entry files.

2. Re-exports of single names:
       export { foo, Bar as Baz } from './core'
   Each comma-separated name is emitted; aliases use the right-hand
   side (the public-facing name).

3. CommonJS named exports:
       module.exports = { foo, Bar }
       exports.foo = function (...) { ... }
       exports.Bar = class { ... }
   For the object form, every comma-separated identifier inside the
   `{...}` body is emitted as a separate export.

4. TypeScript declaration-style named exports: same regex set as #1
   because `export function`, `export class`, `export const` carry
   over identically to .ts / .tsx.

Skipped: default exports (the name "default" carries no semantic
weight), internal `_underscore`-prefixed names, files inside
`tests/`, `__tests__/`, `node_modules/`, build dirs.

Heuristic, not AST-based — but deterministic. Output is sorted by
(file, line, symbol) and deduplicated before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Pattern 1 — `export function`, `export async function`, `export class`,
# `export const NAME = ...`, `export let NAME = ...`, `export var NAME = ...`.
# Anchored to start-of-line (with optional leading whitespace) so we don't
# match inline `export class` references inside string literals.
_EXPORT_DECL_RE = re.compile(
    r"^\s*export\s+"
    r"(?:default\s+)?"  # ignore `export default` — captured separately below
    r"(?:async\s+)?"
    r"(?P<kind>function|class|const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)

# Pattern 2 — `export { a, b as c } from './x'` and `export { a, b }`.
# The whole brace body is captured; the caller splits on commas.
_EXPORT_LIST_RE = re.compile(
    r"^\s*export\s*\{(?P<body>[^}]*)\}",
    re.MULTILINE,
)

# Pattern 3a — `module.exports = { ... }` (object form). Body is captured
# greedily up to the matching `}` on the same balanced level (we rely on
# the body not having nested objects at depth >0; sufficient for the
# typical "list of names" entry file).
_MODULE_EXPORTS_OBJ_RE = re.compile(
    r"^\s*module\.exports\s*=\s*\{(?P<body>[^}]*)\}",
    re.MULTILINE,
)

# Pattern 3b — `exports.NAME = ...` or `module.exports.NAME = ...`.
_EXPORTS_PROP_RE = re.compile(
    r"^\s*(?:module\.)?exports\.(?P<name>[A-Za-z_$][\w$]*)\s*=",
    re.MULTILINE,
)

# Identifier inside an `export { ... }` body. Captures both `name` and
# `name as alias` (where the alias is the public export). Underscores
# allowed inside the name but a leading `_` will be filtered later.
_LIST_ITEM_RE = re.compile(
    r"(?P<name>[A-Za-z_$][\w$]*)(?:\s+as\s+(?P<alias>[A-Za-z_$][\w$]*))?",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        ".yarn",
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".cache",
        ".turbo",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "__tests__",
        "spec",
        "coverage",
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
    }
)

# Source extensions scanned, in fixed order for determinism.
_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts", ".tsx")


CONTENT_PREVIEW_BYTES = 262144  # 256KB — generous for big index files


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path` as UTF-8 with replace
    error handling. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True if any directory on the way from repo_root to path is skipped.

    Skip-dir check uses parts RELATIVE to repo_root — checking the
    absolute path would mis-skip fixtures that happen to live under
    `tests/` (e.g. our own `tests/fixtures/...`).
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])


def _is_public(name: str) -> bool:
    """A name is public iff it doesn't start with `_` and isn't `default`."""
    if not name:
        return False
    if name == "default":
        return False
    return not name.startswith("_")


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find npm-library exports across .js / .mjs / .cjs / .ts / .tsx files.

    Returns an empty list when neither JS nor TS is present in the
    detected languages — keeps dispatch type-safe.
    """
    if "javascript" not in languages and "typescript" not in languages:
        return []
    repo_root = repo_root.resolve()

    js_files: list[Path] = []
    for ext in _EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            js_files.append(p)
    js_files.sort()

    found: list[EntryPoint] = []

    for path in js_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter — at least one export-y substring must appear.
        if "export " not in text and "module.exports" not in text and "exports." not in text:
            continue

        rel = str(path.relative_to(repo_root))
        # ".ts" / ".tsx" → typescript; otherwise javascript.
        lang = "typescript" if path.suffix in (".ts", ".tsx") else "javascript"

        # --- Pattern 1 — `export function/class/const/let/var NAME` ---
        for m in _EXPORT_DECL_RE.finditer(text):
            name = m.group("name")
            if not _is_public(name):
                continue
            kind_keyword = m.group("kind")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="library_node",
                    metadata={
                        "language": lang,
                        "form": "esm_named",
                        "declared_as": kind_keyword,
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # --- Pattern 2 — `export { a, b as c } [from ...]` ---
        for m in _EXPORT_LIST_RE.finditer(text):
            body = m.group("body")
            body_line = _line_of(text, m.start())
            for item in _LIST_ITEM_RE.finditer(body):
                public_name = item.group("alias") or item.group("name")
                if not _is_public(public_name):
                    continue
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.LIBRARY_EXPORT,
                        file=rel,
                        line=body_line,
                        symbol=public_name,
                        type_origin="library_node",
                        metadata={
                            "language": lang,
                            "form": "esm_reexport",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

        # --- Pattern 3a — `module.exports = { a, b }` ---
        for m in _MODULE_EXPORTS_OBJ_RE.finditer(text):
            body = m.group("body")
            body_line = _line_of(text, m.start())
            for item in _LIST_ITEM_RE.finditer(body):
                # In object literals, `{ foo: bar }` aliases the public
                # facing name to `foo` (the left). But the _LIST_ITEM_RE
                # only matches bare identifiers and `name as alias`; for
                # commonjs short-form `{ foo, bar }`, the identifier IS
                # the export name. We handle that by using `name`
                # (`alias` won't be set unless the source contained
                # `as`, which is invalid CJS — but the regex tolerates
                # it harmlessly).
                public_name = item.group("name")
                if not _is_public(public_name):
                    continue
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.LIBRARY_EXPORT,
                        file=rel,
                        line=body_line,
                        symbol=public_name,
                        type_origin="library_node",
                        metadata={
                            "language": lang,
                            "form": "cjs_object",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

        # --- Pattern 3b — `exports.NAME = ...` or `module.exports.NAME = ...` ---
        for m in _EXPORTS_PROP_RE.finditer(text):
            name = m.group("name")
            if not _is_public(name):
                continue
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="library_node",
                    metadata={
                        "language": lang,
                        "form": "cjs_property",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol). Two distinct export forms emitting
    # the same name at the same site (rare, but legitimate when a library
    # double-publishes via `module.exports.foo = foo` AND
    # `module.exports = { foo }` on adjacent lines) collapse to one.
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
