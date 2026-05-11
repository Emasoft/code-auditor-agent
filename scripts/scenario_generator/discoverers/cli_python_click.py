"""Click CLI command discoverer — Python `click` library.

Finds Click command registrations across the codebase:
- @click.command() / @click.command(name="...") — top-level command
- @click.group()   / @click.group(name="...")   — top-level group
- @<binding>.command() / @<binding>.command(name="...") — subcommand of a
  click.group binding (e.g. `@cli.command()` where `cli = click.group()`)
- @<binding>.group()   / @<binding>.group(name="...")   — nested group

Emits one EntryPoint per command decorator. The symbol is the `def` name
following the decorator block; options preceding the decorator
(`@click.option('--flag')`, `@click.argument('arg')`) are collected into
`metadata.options`.

Heuristic, not AST-perfect, but deterministic. We grep on the command
DECORATOR line; the function definition is the next `def ...:` line.
Stacked `@click.option`/`@click.argument` decorators (between options and
the command decorator, or between the command decorator and the def) are
collected best-effort by scanning lines in a small window.

Determinism: file order, decorator order within a file, and option
extraction order are all from `re.finditer` over a deterministically-read
text plus sorted file lists. No dict ordering escapes the function.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Command/group decorators. Two flavours:
#  1. @click.command()      — binding is the literal "click", method is the kind
#  2. @<binding>.command()  — binding is a user-named group variable
# We accept both via the same regex; the discover() function decides
# whether the binding makes it a top-level command or a subcommand.
_COMMAND_DECORATOR_RE = re.compile(
    r"^(?P<indent>[ \t]*)@(?P<binding>[A-Za-z_][A-Za-z0-9_]*)\.(?P<kind>command|group)\s*\(",
    re.MULTILINE,
)

# Option / argument stacked decorators — match the FIRST quoted token
# in the argument list. `--flag` for options; argument name for arguments.
_OPTION_DECORATOR_RE = re.compile(
    r"^[ \t]*@(?:[A-Za-z_][A-Za-z0-9_]*)\.(?P<kind>option|argument)\s*\(\s*"
    r"(?P<quote>['\"])(?P<token>[^'\"]+)(?P=quote)",
)

# Explicit `name="..."` kwarg inside a command/group decorator call. We
# tolerate single or double quotes and an optional leading positional
# (rare for click.command but not impossible).
_NAME_KWARG_RE = re.compile(r"""name\s*=\s*(?P<quote>['"])(?P<name>[^'"]+)(?P=quote)""")

_DEF_RE = re.compile(r"^[ \t]*(?:async\s+)?def\s+(?P<name>\w+)\s*\(", re.MULTILINE)
_DOCSTRING_RE = re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL)


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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — enough for big CLI command modules


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _docstring_after_def(text: str, def_match: re.Match[str]) -> str:
    """Extract the docstring directly following a `def ...:` line, if any."""
    rest = text[def_match.end() :]
    m = _DOCSTRING_RE.search(rest)
    if not m:
        return ""
    # Only count it as the function's docstring if it's within the first
    # ~600 characters after the def (anything farther is unrelated).
    if m.start() > 600:
        return ""
    body = m.group(1) or m.group(2) or ""
    for ln in body.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _parse_decorator_call(text: str, start_offset: int) -> tuple[str, int]:
    """Return (decorator_args_blob, offset_after_close_paren).

    Starts at `start_offset` (the index of the `(` after `.command`/`.group`).
    Tracks parenthesis depth so multi-line decorator args with nested
    tuples/dicts are handled. Returns ('', start_offset) if no matching
    close paren is found within the preview window.
    """
    depth = 0
    i = start_offset
    n = len(text)
    while i < n:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return (text[start_offset + 1 : i], i + 1)
        i += 1
    return ("", start_offset)


def _collect_preceding_options(text: str, decorator_line_start: int) -> list[str]:
    """Walk backwards line-by-line from the command decorator collecting
    consecutive @click.option / @click.argument tokens.

    Stops at the first line that is not a stacked option/argument decorator
    or that is blank/comment-only. Returns options in source order
    (top-down), with `--flag` for options and the literal arg name for
    arguments — best-effort, but deterministic.
    """
    # Walk back to find the start of the preceding line, repeatedly.
    options_reverse: list[str] = []
    cursor = decorator_line_start - 1  # step onto the newline before this line
    while cursor > 0:
        # Find start of the previous line.
        prev_newline = text.rfind("\n", 0, cursor)
        line_start = prev_newline + 1 if prev_newline != -1 else 0
        line = text[line_start:cursor]
        cursor = line_start - 1  # next iteration: line before this one
        stripped = line.strip()
        if not stripped:
            # Blank line — stop scanning (Click decorators stack with no
            # blank lines between them).
            break
        if stripped.startswith("#"):
            # Comment line — tolerate and keep scanning.
            continue
        m = _OPTION_DECORATOR_RE.match(line)
        if m is None:
            break
        options_reverse.append(m.group("token"))
    options_reverse.reverse()
    return options_reverse


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Click commands. Deterministic order."""
    if "python" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # IMPORTANT: skip-dir check is against the path RELATIVE to repo_root,
    # not the absolute path — otherwise a fixture located under a `tests/`
    # ancestor (or a user home with `dist`, etc.) would cause the entire
    # tree to be excluded. Mirrors the same fix used in library_python.py.
    py_files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        py_files.append(p)
    py_files.sort()

    for path in py_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter: skip files with no click reference at all.
        if "click" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        for dec_match in _COMMAND_DECORATOR_RE.finditer(text):
            binding = dec_match.group("binding")
            kind = dec_match.group("kind")  # "command" or "group"
            paren_offset = dec_match.end() - 1  # position of '(' just matched
            args_blob, after_close = _parse_decorator_call(text, paren_offset)

            # The function definition is the next `def ...` line, after
            # any stacked option/argument decorators between the command
            # decorator and the def.
            def_match = _DEF_RE.search(text, after_close)
            if def_match is None:
                continue
            between = text[after_close : def_match.start()]
            if between.count("\n") > 16:
                # Too far — not the function this decorator targets.
                continue

            symbol = def_match.group("name")
            line = _line_of(text, dec_match.start())

            # Explicit name= kwarg wins; otherwise derive from fn-name.
            name_match = _NAME_KWARG_RE.search(args_blob)
            command_name = name_match.group("name") if name_match else symbol.replace("_", "-")

            is_group = kind == "group"

            # Options preceding the command decorator (above it in source).
            decorator_line_start = text.rfind("\n", 0, dec_match.start()) + 1
            options = _collect_preceding_options(text, decorator_line_start)

            docstring = _docstring_after_def(text, def_match)

            metadata: dict[str, object] = {
                "command": command_name,
                "framework": "click",
                "is_group": is_group,
                "options": options,
            }
            # Subcommand bindings (e.g. @cli.command) — record the binding
            # so the walker can reconstruct the command path. For top-level
            # @click.command we omit it (binding == "click" is redundant).
            if binding != "click":
                metadata["binding"] = binding

            found.append(
                EntryPoint(
                    kind=EntryPointKind.CLI_COMMAND,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="cli_python",
                    metadata=metadata,
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol) — two decorators on the same line for
    # the same function would be a pathological case and we keep the first.
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
