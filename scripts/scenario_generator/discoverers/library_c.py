"""Library-export discoverer for C libraries (header-declared API).

Selective discoverer for the `library_c` software type. A symbol is a
LIBRARY EXPORT iff it is declared (prototype, terminating with `;`)
in a public header file (`.h` / `.hpp` inside `include/` or at the
repo root). The header IS the published contract of a C library —
symbols defined only in `.c` files are implementation, not API.

Patterns recognised in headers:

1. Standard prototypes (with or without `extern`):
       int   foo_bar(const char *s);
       extern void quux(void);
       size_t libname_count(const struct thing *t);
   The return type may span types like `int`, `void`, `size_t`,
   `const char *`, `unsigned long`, `struct foo *`, etc. — we use
   a permissive type-blob regex bounded by the function name.

2. Function-pointer typedef declarations are NOT recognised in v1
   (`typedef int (*foo_cb_t)(...);`) — those are callback shapes,
   not entry points.

3. Macro `#define FOO_API ...` decorators (common in cross-platform
   C libraries, e.g. `LIBFOO_API`) are tolerated as the first token
   of a declaration — we strip them via a leading-token swallow.

Skipped subtrees: `tests/`, `examples/`, `samples/`, `build/`,
`target/`, `node_modules/`, `vendor/` and the .c / .cpp source tree
itself (we only look at .h / .hpp files).

Functions declared `static` inside a header are intentionally NOT
emitted (file-local linkage in C, not part of the published API).

Heuristic regex on header files. Deterministic. Output is sorted by
(file, line, symbol) and deduplicated.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# A C declaration line for a function prototype. The structure is:
#   [extern] [<return type blob>] <name> ( <args> ) ;
#
# Return type blob = one or more whitespace-separated tokens that can
# include `const`, `unsigned`, `signed`, `long`, `short`, `*`,
# `struct`, `enum`, `union`, a type-name identifier — but NOT
# `static` (we want to exclude file-local declarations).
#
# We use a permissive `[\w\s*]+` for the return-type blob and then
# require `name(`...`);` to anchor the match. The negative lookahead
# `(?!.*\bstatic\b)` on the leading slice excludes static prototypes.
#
# Two-part match: (1) the prototype's leading `^...name(` and (2) the
# trailing `);` on the same line (or a few lines later). We restrict
# to single-line declarations in v1; multi-line signatures with the
# closing paren on a later line are caught by a fallback regex below.
_PROTOTYPE_SINGLE_LINE_RE = re.compile(
    r"^(?P<lead>(?:extern\s+)?(?:[A-Z][A-Z0-9_]+_API\s+)?)"
    r"(?P<rettype>"
    r"(?:const\s+|volatile\s+|unsigned\s+|signed\s+|long\s+|short\s+)*"
    r"(?:struct\s+|enum\s+|union\s+)?"
    r"[A-Za-z_][\w]*"
    r"(?:\s*\*+)*"
    r")\s+"
    r"(?P<name>[A-Za-z_][\w]*)\s*"
    r"\((?P<args>[^;{}]*)\)\s*;",
    re.MULTILINE,
)

# A leading `/** ... */` doxygen-style block directly above the
# prototype. The walker can use the first non-empty body line as
# `intended_behaviour`.
_DOXYGEN_RE = re.compile(r"/\*\*(?P<body>.*?)\*/", re.DOTALL)

# Names whose return-type token is one of these are NOT functions
# but type-name declarations that happened to fit the prototype regex
# spuriously — we filter at extraction time. Empty for now; kept as a
# pluggable list for future hardening.
_FALSE_POSITIVE_NAMES: frozenset[str] = frozenset(
    {
        # C keywords accidentally matched if `rettype name(` shape
        # appears in a comment or macro body.
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "typeof",
    }
)


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
        ".idea",
        ".vscode",
        "dist",
        "build",
        "out",
        "bin",
        "obj",
        "target",
        "Debug",
        "Release",
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "doc",
        "docs",
        "Documentation",
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

# We scan only header files. The public C API lives in .h / .hpp; symbols
# defined only in .c / .cpp are implementation, not API.
_EXTENSIONS: tuple[str, ...] = (".h", ".hpp")


CONTENT_PREVIEW_BYTES = 262144  # 256KB — generous for big header files


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


def _strip_block_comments(text: str) -> str:
    """Replace `/* ... */` blocks with equal-length whitespace so character
    offsets are preserved. This prevents prototypes inside comments
    (e.g. doxygen examples) from being matched. Same-length blanking
    keeps `_line_of` accurate.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                # Unterminated — blank to end.
                j = n
            else:
                j += 2
            chunk = text[i:j]
            blanked = "".join("\n" if ch == "\n" else " " for ch in chunk)
            out.append(blanked)
            i = j
            continue
        # Line comments `//` (valid in C99/C++): blank to end of line,
        # keeping the trailing newline so line numbers stay correct.
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _docstring_before(original_text: str, item_start: int) -> str:
    """First non-empty body line of a /** ... */ doxygen block directly
    above the prototype, if any. Uses the ORIGINAL text (with comments
    intact) since the comment IS the docstring.
    """
    head = original_text[:item_start]
    # Last 2048 chars are usually enough — keeps the regex bounded.
    window = head[-2048:]

    last_doxy: re.Match[str] | None = None
    for m in _DOXYGEN_RE.finditer(window):
        between = window[m.end() :]
        # Allow only whitespace between the comment close and the prototype.
        if between.strip() == "":
            last_doxy = m
    if last_doxy is None:
        return ""
    body = last_doxy.group("body")
    for ln in body.splitlines():
        # Strip the leading ` * ` decoration commonly used inside
        # doxygen blocks.
        s = ln.strip()
        if s.startswith("*"):
            s = s[1:].strip()
        if s:
            return s
    return ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find C-library function prototypes in public header files.

    Returns an empty list when `c` is not in the detected languages.
    """
    if "c" not in languages and "cpp" not in languages:
        return []
    repo_root = repo_root.resolve()

    header_files: list[Path] = []
    for ext in _EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            header_files.append(p)
    header_files.sort()

    found: list[EntryPoint] = []

    for path in header_files:
        original_text = _read(path)
        if not original_text:
            continue
        # Strip comments so we don't match prototypes inside doxygen
        # examples or inline `//` annotations.
        text = _strip_block_comments(original_text)
        rel = str(path.relative_to(repo_root))

        for m in _PROTOTYPE_SINGLE_LINE_RE.finditer(text):
            name = m.group("name")
            rettype = m.group("rettype").strip()
            # Filter accidental matches against control-flow keywords.
            if name in _FALSE_POSITIVE_NAMES:
                continue
            # `static` declarations in a header have file-local linkage —
            # they aren't published API. The regex disallows `static` in
            # `lead`, but a `static <rettype>` would put `static` into
            # the rettype slot. Filter here defensively.
            if "static" in m.group(0).split(name, 1)[0].split():
                continue
            line = _line_of(text, m.start())
            docstring = _docstring_before(original_text, m.start())

            found.append(
                EntryPoint(
                    kind=EntryPointKind.LIBRARY_EXPORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="library_c",
                    metadata={
                        "language": "c",
                        "return_type": rettype,
                        "scope": "header",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol). Same prototype legitimately can't
    # appear twice in a single header, but defensive dedup keeps the
    # contract consistent.
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
