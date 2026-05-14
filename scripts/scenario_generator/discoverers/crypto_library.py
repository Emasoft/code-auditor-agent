"""Crypto-operation discoverer for the `crypto_library` software type.

A crypto library exposes primitives (block ciphers, AEAD modes, RSA/ECC
signatures, key derivation, MACs, random-byte sources, hash compares).
The discoverer identifies functions that implement or invoke these
primitives by NAME — names are the most reliable signal in published
crypto code because reviewers want them readable.

Heuristic, regex-based, language-aware:

- Rust: `pub fn <name>(...) [-> ...]` at column 0 — top-level public
  crate API.
- Python: `def <name>(...)` at column 0 — module scope (sync or async).
- Go: `func <name>(...) [-> ...]` at column 0 — exported (uppercase
  first letter) functions are the contract. Lowercase-first ones are
  package-private but we still pick them up so audit can see them.

The function name must match the crypto-operation regex
`encrypt|decrypt|sign|verify|hmac|kdf|hash|random|cipher|nonce` (case
insensitive). Generic names like `compare` are NOT included — that
trims false positives on non-crypto utility helpers.

The closest available `EntryPointKind` is `LIBRARY_EXPORT` (the schema
predates a dedicated CRYPTO_OPERATION kind). Metadata distinguishes
the crypto-op subtype via `op` and `language`.

Deterministic: files are sorted, matches are sorted by (file, line,
symbol), output is byte-identical across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Names matching this regex are recognised as crypto operations. The set
# is anchored to a frozen vocabulary to keep output stable across crypto
# library styles.
_CRYPTO_NAME_RE = re.compile(r"(?i)(?:^|_)(encrypt|decrypt|sign|verify|hmac|kdf|hash|random|cipher|nonce)(?:_|$)")

# Rust public function: `pub fn name(...)` at column 0, optionally
# preceded by `unsafe` / `async` and modifiers. `pub(crate)` and
# `pub(super)` are deliberately NOT recognised — they're crate-internal.
_RUST_PUB_FN_RE = re.compile(
    r"^pub\s+(?:unsafe\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_][\w]*)\s*",
    re.MULTILINE,
)

# Python module-scope function: column-0 `def name(` or `async def name(`.
_PY_DEF_RE = re.compile(
    r"^(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)

# Go function: column-0 `func name(`. Exported functions start with an
# uppercase letter; we capture both — audit cares about either.
_GO_FUNC_RE = re.compile(
    r"^func\s+(?P<name>[A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)

# Triple-quoted (Python) or `///` Rust doc-comment line directly above a
# definition. Used as the intended_behaviour fallback.
_PY_DOCSTRING_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)
_RUST_DOC_LINE_RE = re.compile(r"^\s*///\s*(?P<text>.+)$", re.MULTILINE)
_GO_DOC_LINE_RE = re.compile(r"^\s*//\s*(?P<text>.+)$", re.MULTILINE)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        "node_modules",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "_internal",
        "_private",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — generous for crypto modules


def _read(path: Path) -> str:
    """Read a file's text content; return '' on any I/O failure."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True iff any directory under repo_root on the way to path is skipped."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _classify_op(name: str) -> str:
    """Return the canonical crypto-op label for a matching name."""
    m = _CRYPTO_NAME_RE.search(name)
    return m.group(1).lower() if m else "unknown"


def _py_docstring_after(text: str, def_end_offset: int) -> str:
    """First non-empty line of the docstring directly after a `def`."""
    rest = text[def_end_offset : def_end_offset + 1200]
    m = _PY_DOCSTRING_RE.search(rest)
    if not m:
        return ""
    if m.start() > 600:
        return ""
    body = m.group(1) or m.group(2) or ""
    for ln in body.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _comment_above(text: str, def_start_offset: int, comment_re: re.Pattern[str]) -> str:
    """First non-empty line of the run of doc comments directly above a def."""
    head = text[:def_start_offset]
    window = head[-800:]
    # Walk lines backwards: keep collecting comment lines until non-comment.
    lines = window.splitlines()
    collected: list[str] = []
    for ln in reversed(lines):
        m = comment_re.match(ln)
        if m:
            collected.append(m.group("text").strip())
            continue
        if ln.strip() == "" and collected:
            break
        if ln.strip() == "":
            continue
        break
    if collected:
        for s in reversed(collected):
            if s:
                return s
    return ""


def _discover_rust(repo_root: Path) -> list[EntryPoint]:
    """Find Rust `pub fn` definitions whose names match the crypto regex."""
    found: list[EntryPoint] = []
    files: list[Path] = []
    for p in repo_root.rglob("*.rs"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        files.append(p)
    files.sort()

    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _RUST_PUB_FN_RE.finditer(text):
            name = m.group("name")
            if not _CRYPTO_NAME_RE.search(name):
                continue
            line = _line_of(text, m.start())
            doc = _comment_above(text, m.start(), _RUST_DOC_LINE_RE)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="crypto_library",
                    metadata={
                        "language": "rust",
                        "op": _classify_op(name),
                        "visibility": "pub",
                    },
                    docstring=doc,
                    intended_behaviour_sources=(),
                )
            )
    return found


def _discover_python(repo_root: Path) -> list[EntryPoint]:
    """Find Python module-scope `def`s whose names match the crypto regex."""
    found: list[EntryPoint] = []
    files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        files.append(p)
    files.sort()

    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _PY_DEF_RE.finditer(text):
            name = m.group("name")
            if name.startswith("_"):
                continue
            if not _CRYPTO_NAME_RE.search(name):
                continue
            line = _line_of(text, m.start())
            # Find end of the `def line:` — search for first `:` followed by a newline.
            colon_offset = text.find(":", m.end())
            def_end = colon_offset + 1 if colon_offset != -1 else m.end()
            doc = _py_docstring_after(text, def_end)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="crypto_library",
                    metadata={
                        "language": "python",
                        "op": _classify_op(name),
                        "visibility": "public",
                    },
                    docstring=doc,
                    intended_behaviour_sources=(),
                )
            )
    return found


def _discover_go(repo_root: Path) -> list[EntryPoint]:
    """Find Go package-scope `func`s whose names match the crypto regex."""
    found: list[EntryPoint] = []
    files: list[Path] = []
    for p in repo_root.rglob("*.go"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        files.append(p)
    files.sort()

    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _GO_FUNC_RE.finditer(text):
            name = m.group("name")
            if not _CRYPTO_NAME_RE.search(name):
                continue
            line = _line_of(text, m.start())
            doc = _comment_above(text, m.start(), _GO_DOC_LINE_RE)
            visibility = "exported" if name[:1].isupper() else "package_private"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="crypto_library",
                    metadata={
                        "language": "go",
                        "op": _classify_op(name),
                        "visibility": visibility,
                    },
                    docstring=doc,
                    intended_behaviour_sources=(),
                )
            )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find crypto operations across Rust / Python / Go source files.

    Each function whose name matches the crypto-op regex is emitted as
    one EntryPoint with kind=LIBRARY_EXPORT and metadata.op carrying
    the canonical operation label (encrypt / decrypt / sign / etc).
    """
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    if "rust" in languages:
        found.extend(_discover_rust(repo_root))
    if "python" in languages:
        found.extend(_discover_python(repo_root))
    if "go" in languages:
        found.extend(_discover_go(repo_root))

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
