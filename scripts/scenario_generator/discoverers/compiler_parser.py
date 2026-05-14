"""Compiler/parser discoverer.

Selective discoverer for the `compiler_parser` software type. Targets
two artefact families that idiomatic parser implementations expose:

1. **Grammar rule declarations** in dedicated grammar files —
   ANTLR (`*.g4`), Yacc/Bison (`*.y`), Lex/Flex (`*.lex`), Pest
   (`*.pest`), tree-sitter (`*.tree-sitter`). Each top-level rule
   becomes a PARSER_INPUT entry whose `symbol` is the rule name.

2. **Recursive-descent or table-driven parser functions** in source
   files — `def parse_*` / `def tokenize_*` in Python, `fn parse_*`
   / `fn tokenize_*` in Rust, `<name>_parse(...)` / `<name>_tokenize(...)`
   in C. Each function becomes a PARSER_INPUT entry whose `symbol`
   is the function name.

`type_origin` is hard-coded to `"compiler_parser"`. Output is
sorted by (file, line, symbol) plus a `kind`/`metadata.format`
tiebreaker so that two co-located rules in different syntax flavours
order identically across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Grammar-file rule regexes. Each grammar dialect spells "rule = ..." a
# little differently; we cover the four idiomatic spellings:
#
#   ANTLR (g4):   ruleName : alternative ;
#   Yacc (y):     ruleName : alternative ;
#   Bison (y):    ruleName : alternative ;
#   Pest:         rule_name = { ... }
#   Lex/Flex:     %%   then    pattern   action
#   tree-sitter:  rule: $ => seq(...) inside a JS grammar.js — out of
#                   scope here; .tree-sitter is rare as a file extension
#                   in idiomatic repos.
#
# The walker only needs the rule's name + line; metadata.format records
# which dialect produced it so adversarial-input families can pick the
# right stimulus shape.
# ---------------------------------------------------------------------------

# ANTLR / Yacc / Bison rule: `rule_name : alternative ;` at start of line.
# We match the FIRST occurrence of `:` after a lowercase identifier on
# its own line.
_GRAMMAR_RULE_RE = re.compile(
    r"^(?P<name>[a-z_][a-zA-Z0-9_]*)\s*:\s*",
    re.MULTILINE,
)

# Pest grammar rule: `rule_name = { ... }` or `rule_name = _{ ... }`
# or `rule_name = @{ ... }` (silent / atomic markers tolerated).
_PEST_RULE_RE = re.compile(
    r"^(?P<name>[a-z_][a-zA-Z0-9_]*)\s*=\s*[_@!\$]?\s*\{",
    re.MULTILINE,
)

# Python parser/tokenizer functions: `def parse_xxx(` or `def tokenize_xxx(`.
# Module scope by convention; nested defs are deliberately permitted —
# parser combinators routinely live inside helper closures.
_PY_PARSE_FN_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(?P<name>(?:parse|tokenize)_[A-Za-z0-9_]+)\s*\(",
    re.MULTILINE,
)

# Rust parser/tokenizer functions: `fn parse_xxx(` or `fn tokenize_xxx(`.
_RUST_PARSE_FN_RE = re.compile(
    r"^\s*(?:pub\s+(?:\([^)]*\)\s+)?)?(?:async\s+|unsafe\s+|const\s+|extern\s+(?:\"[^\"]+\"\s+)?)*"
    r"fn\s+(?P<name>(?:parse|tokenize)_[A-Za-z0-9_]+)\s*\(",
    re.MULTILINE,
)

# C parser/tokenizer functions: `<type> <prefix>_parse(...)` or
# `<type> <prefix>_tokenize(...)`. We accept any return type token; the
# function name is the load-bearing bit. `[\s\*]` (rather than `\s+`)
# tolerates `struct ast *foo_parse(` — a pointer-glued name.
_C_PARSE_FN_RE = re.compile(
    r"^[A-Za-z_][\*\sA-Za-z0-9_]*?[\s\*](?P<name>[A-Za-z_][A-Za-z0-9_]*_(?:parse|tokenize))\s*\(",
    re.MULTILINE,
)


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


CONTENT_PREVIEW_BYTES = 262144  # 256KB — generous for grammar files


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path`. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True if any DIRECTORY component (relative to repo_root) is skipped.

    Uses the path RELATIVE to repo_root — checking the absolute path
    would mis-skip fixtures under `tests/...`.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])


def _iter_files(repo_root: Path, ext_globs: tuple[str, ...]) -> list[Path]:
    """Return a deterministic sorted list of files matching any of the globs."""
    seen: set[Path] = set()
    for glob in ext_globs:
        for p in repo_root.rglob(glob):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            seen.add(p)
    return sorted(seen)


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find compiler/parser entry points. Deterministic order.

    Unlike most discoverers, this one does NOT gate on `languages` —
    grammar files like `*.g4` are dialect-agnostic and the host
    language list may not contain any of the dialects the discoverer
    handles. We still examine *.py / *.rs / *.c only when those
    languages are detected.
    """
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # ---- 1. Grammar files (ANTLR / Yacc / Bison) ---------------------------
    for path in _iter_files(repo_root, ("*.g4", "*.y", "*.lex")):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        # ANTLR/Yacc/Bison/Flex use `rule_name : alternative ;` syntax.
        for m in _GRAMMAR_RULE_RE.finditer(text):
            name = m.group("name")
            # Skip ALL-CAPS lexer terminals (ANTLR convention: terminals
            # are uppercase). They are tokens, not parser rules.
            if name.isupper():
                continue
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.PARSER_INPUT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="compiler_parser",
                    metadata={
                        "format": "grammar",
                        "dialect": path.suffix.lstrip("."),
                        "language": "grammar",
                    },
                )
            )

    # ---- 2. Pest grammar files --------------------------------------------
    for path in _iter_files(repo_root, ("*.pest",)):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _PEST_RULE_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.PARSER_INPUT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="compiler_parser",
                    metadata={
                        "format": "grammar",
                        "dialect": "pest",
                        "language": "grammar",
                    },
                )
            )

    # ---- 3. Python parser/tokenizer functions ------------------------------
    if "python" in languages:
        for path in _iter_files(repo_root, ("*.py",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for m in _PY_PARSE_FN_RE.finditer(text):
                name = m.group("name")
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PARSER_INPUT,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="compiler_parser",
                        metadata={
                            "format": "function",
                            "language": "python",
                            "category": "tokenize" if name.startswith("tokenize_") else "parse",
                        },
                    )
                )

    # ---- 4. Rust parser/tokenizer functions --------------------------------
    if "rust" in languages:
        for path in _iter_files(repo_root, ("*.rs",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for m in _RUST_PARSE_FN_RE.finditer(text):
                name = m.group("name")
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PARSER_INPUT,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="compiler_parser",
                        metadata={
                            "format": "function",
                            "language": "rust",
                            "category": "tokenize" if name.startswith("tokenize_") else "parse",
                        },
                    )
                )

    # ---- 5. C parser/tokenizer functions -----------------------------------
    if "c" in languages:
        for path in _iter_files(repo_root, ("*.c",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for m in _C_PARSE_FN_RE.finditer(text):
                name = m.group("name")
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PARSER_INPUT,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="compiler_parser",
                        metadata={
                            "format": "function",
                            "language": "c",
                            "category": "tokenize" if name.endswith("_tokenize") else "parse",
                        },
                    )
                )

    # Dedup by (file, line, symbol) and deterministic sort. The same
    # symbol cannot legitimately appear twice on the same line; the
    # defensive dedup protects against pathological regex backtracking
    # on hand-crafted fixtures.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("dialect", ""))))
    return unique
