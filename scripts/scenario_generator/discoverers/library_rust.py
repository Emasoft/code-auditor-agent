"""Library-export discoverer for Rust crates (lib-target, not bin).

Selective discoverer for the `library_rust` software type. A symbol is
a LIBRARY EXPORT iff:

1. It is declared at module scope (column 0 with optional leading
   whitespace — `^\\s*pub\\s+...`) — items inside `impl` blocks,
   inline `mod foo { ... }` bodies, or other nested scopes are
   skipped. We approximate module scope with leading-indentation = 0
   because Rust files conventionally indent inner items.
2. It has the `pub` visibility modifier. `pub(crate)` and
   `pub(super)` are intentionally NOT recognised — those are
   crate-internal, not part of the public API the crate ships.
3. The item kind is one of `fn`, `struct`, `trait`, `enum`. Other
   item kinds (`type`, `const`, `static`, `mod`, `use`) are also
   public-API-relevant but rarer in audits; v1 limits the surface
   to keep golden output bounded.

Skipped subtrees: `tests/`, `examples/`, `benches/`, `target/`,
build artifacts.

Heuristic (regex on lines starting with `pub`), not AST-based — but
deterministic. Output is sorted by (file, line, symbol) and
deduplicated before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `pub fn name`, `pub struct Name`, `pub trait Name`, `pub enum Name`
# at column-0 with optional leading whitespace (always 0 in practice
# for crate-root items; we tolerate a small indent to handle
# documented files).
#
# `^\s*` plus `re.MULTILINE` anchors per-line; we then require zero
# indentation manually below by checking the captured leading
# whitespace.
#
# `pub` MAY be followed by `(crate)` or `(super)` — those are NOT
# part of the crate's published API, so they're excluded by the regex
# (the `\s+` after `pub` insists on a space, not `(`).
_PUB_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)pub\s+"
    r"(?:async\s+|unsafe\s+|const\s+|extern\s+(?:\"[^\"]+\"\s+)?)*"
    r"(?P<kind>fn|struct|trait|enum)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)

# A leading triple-slash doc comment block on the line(s) immediately
# above the item. We pull the first non-empty body line as the
# docstring.
_DOC_COMMENT_RE = re.compile(r"^[ \t]*///[ \t]?(?P<text>.*)$", re.MULTILINE)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".env",
        ".cache",
        ".cargo",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "out",
        "bin",
        "obj",
        "target",
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "benches",
        "bench",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — generous for lib.rs files


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path` as UTF-8. Empty on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True if any DIRECTORY component (not the filename) on the way from
    repo_root to path is skipped.

    Skip-dir check uses parts RELATIVE to repo_root — checking the
    absolute path would mis-skip fixtures that happen to live under
    `tests/` (e.g. our own `tests/fixtures/...`).
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])


def _docstring_before(text: str, item_start: int) -> str:
    """First non-empty line of the `///` doc-comment block directly above
    the item, if any. Walks backwards line by line.
    """
    # Slice text up to the item — the doc comments live in this prefix.
    head = text[:item_start]
    lines = head.splitlines()
    collected: list[str] = []
    # Walk backwards from the line above the item.
    for ln in reversed(lines):
        stripped = ln.strip()
        if stripped.startswith("///"):
            # Strip the `///` and an optional leading space.
            body = stripped[3:]
            if body.startswith(" "):
                body = body[1:]
            collected.append(body)
            continue
        if stripped == "":
            # Blank line between doc-block and item is allowed only if we
            # haven't collected anything yet (the doc block hasn't started).
            if collected:
                break
            continue
        break

    # `collected` is in reverse source order — flip for first-line-first.
    for s in reversed(collected):
        if s.strip():
            return s.strip()
    return ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Rust crate-level `pub fn/struct/trait/enum` declarations.

    Returns an empty list when `rust` is not in the detected languages.
    """
    if "rust" not in languages:
        return []
    repo_root = repo_root.resolve()

    rs_files: list[Path] = []
    for p in repo_root.rglob("*.rs"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        rs_files.append(p)
    rs_files.sort()

    found: list[EntryPoint] = []

    for path in rs_files:
        text = _read(path)
        if not text:
            continue
        if "pub " not in text:
            continue
        rel = str(path.relative_to(repo_root))

        for m in _PUB_ITEM_RE.finditer(text):
            indent = m.group("indent")
            # Enforce module scope by requiring zero indentation. Items
            # inside `impl` blocks / nested `mod foo { ... }` bodies are
            # conventionally indented and so are excluded by this check.
            if indent:
                continue
            kind_keyword = m.group("kind")
            name = m.group("name")
            line = _line_of(text, m.start())
            docstring = _docstring_before(text, m.start())

            # Map the Rust item kind to a stable metadata field; the
            # walker uses this to pick adversarial-input strategies
            # (a `fn` and a `trait` get different treatment).
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="library_rust",
                    metadata={
                        "language": "rust",
                        "item_kind": kind_keyword,
                        "visibility": "pub",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol). The regex can't legitimately match
    # the same site twice, but defensive dedup keeps the contract
    # consistent with other discoverers.
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


# Reference: _DOC_COMMENT_RE retained for future expansion. It is not
# yet used because _docstring_before walks line-by-line; keeping the
# pattern compiled avoids re-defining it when a future PR switches the
# extraction to a single regex sweep.
_ = _DOC_COMMENT_RE
