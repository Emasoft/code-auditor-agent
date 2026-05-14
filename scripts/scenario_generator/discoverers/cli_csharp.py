"""C# CLI command discoverer — System.CommandLine / CommandLineParser.

Finds CLI command registrations across C# (.NET) source files. Two
dominant idioms are handled:

1. **System.CommandLine** — Microsoft's modern CLI library. Commands
   are constructed via `new Command("name", "description")` or
   `new RootCommand("description")`, then composed with `.AddCommand(...)`
   or `.Add(...)`. Each `new Command(...)` / `new RootCommand(...)` call
   is one CLI_COMMAND entry point.
2. **CommandLineParser** — older but still common attribute-based
   library. Each verb class carries a `[Verb("name", HelpText = "...")]`
   attribute that declares the command name and help text.

Heuristic, not full-AST: regex scan of `.cs` files. Deterministic —
file order sorted, registration order from `re.finditer`. The skip-dirs
check uses `p.relative_to(repo_root).parts` so fixtures under
`tests/...` are not mis-skipped.

Intended-behaviour sources: the second-string argument of a
`new Command(name, description)` call, or the `HelpText` arg of a
`[Verb]` attribute, becomes the entry-point docstring.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Declared so the dispatcher in emit_scenarios_json._load_framework_discoverers
# can also locate this module via TYPE_ORIGIN scanning. The filename matches
# the canonical type name (cli_csharp), so the direct-load path also picks
# it up — TYPE_ORIGIN is belt-and-braces.
TYPE_ORIGIN = "cli_csharp"


# `new Command("name", ...)` — System.CommandLine subcommand. We capture
# the literal name. The second positional arg (description) is extracted
# separately if present. We DO accept the no-description form `new
# Command("name")`.
_NEW_COMMAND_RE = re.compile(
    r"\bnew\s+Command\s*\(\s*\"(?P<name>[^\"]+)\"",
)
# `new RootCommand("description")` — System.CommandLine top-level
# command. The "name" here is conceptual — RootCommand maps to argv[0],
# which we record as `<root>`.
_NEW_ROOT_COMMAND_RE = re.compile(
    r"\bnew\s+RootCommand\s*\(\s*(?P<rest>[^)]*)\)",
)
# Second-string argument of `new Command("name", "description")`. We
# scan forward from after the name's closing quote and accept whitespace
# + a comma + optional whitespace before the next quoted literal. The
# match ends at the close paren or the next constructor argument.
_NEW_COMMAND_DESC_RE = re.compile(
    r'^\s*,\s*"(?P<description>[^"]*)"',
)
# `[Verb("name", HelpText = "...")]` — CommandLineParser attribute. We
# capture both the verb name and (optionally) the HelpText. Whitespace
# is tolerated. The attribute MAY span multiple lines, but the typical
# usage is single-line — we'll match either by using DOTALL on the body
# capture.
_VERB_ATTR_RE = re.compile(
    r"\[\s*Verb\s*\(\s*\"(?P<name>[^\"]+)\"(?P<rest>[^\]]*)\]",
    re.DOTALL,
)
# `HelpText = "..."` inside a Verb attribute's body — extracted from
# the `rest` capture of `_VERB_ATTR_RE`.
_VERB_HELP_RE = re.compile(r'\bHelpText\s*=\s*"(?P<help>[^"]*)"')
# `class Name` declaration — used to find the class carrying a `[Verb]`
# attribute, so the EntryPoint's symbol can be the class name (which is
# how the application reflects on verbs at runtime).
_CLASS_DEF_RE = re.compile(
    r"^[ \t]*(?:public\s+|internal\s+|private\s+|sealed\s+|abstract\s+|static\s+|partial\s+)*"
    r"class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
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
        "bin",  # standard .NET build output
        "obj",  # standard .NET build output
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128 KB — covers typical Program.cs.


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _strip_comments(text: str) -> str:
    """Replace C# `//` and `/* ... */` comments with whitespace so the
    discoverer's regexes don't match patterns inside them.

    String literals (`"..."`, verbatim `@"..."`) are preserved verbatim
    because they carry the command names and HelpText that the
    discoverer extracts. Newlines are preserved so byte offsets map
    to unchanged line numbers.

    C# XML doc comments (`///`) are treated as plain `//` line
    comments and stripped — this discoverer doesn't currently consume
    XML doc text for docstring extraction (it reads from attribute
    arguments instead).

    String-literal interiors are NOT stripped here.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            if end == -1:
                end = n
            out.append(" " * (end - i))
            i = end
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                end = n
            else:
                end += 2
            for j in range(i, end):
                out.append("\n" if text[j] == "\n" else " ")
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_next_class_name(text: str, after_offset: int) -> str:
    """Find the next `class Name` declaration after `after_offset`.

    Used to associate a `[Verb("...")]` attribute with the class it
    annotates. Returns the class identifier or '' if none is found
    within the next ~512 chars (anything farther is unrelated to the
    attribute).
    """
    window = text[after_offset : after_offset + 512]
    m = _CLASS_DEF_RE.search(window)
    return m.group("name") if m is not None else ""


def _discover_system_commandline(text: str, rel: str) -> list[EntryPoint]:
    """Emit one EntryPoint per `new Command(...)` / `new RootCommand(...)`."""
    found: list[EntryPoint] = []

    # `new Command("name", ...)` — subcommand / arbitrary command.
    for m in _NEW_COMMAND_RE.finditer(text):
        name = m.group("name")
        # Look just after the matched literal for a second string arg.
        tail_offset = m.end()
        tail = text[tail_offset : tail_offset + 512]
        desc_match = _NEW_COMMAND_DESC_RE.match(tail)
        description = desc_match.group("description") if desc_match is not None else ""
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol=f"Command({name})",
                type_origin="cli_csharp",
                metadata={
                    "command": name,
                    "framework": "System.CommandLine",
                    "style": "subcommand",
                },
                docstring=description,
                intended_behaviour_sources=(),
            )
        )

    # `new RootCommand("description")` — top-level root, no name (the
    # binary name supplies it at runtime). We record `<root>` as the
    # conceptual command name.
    for m in _NEW_ROOT_COMMAND_RE.finditer(text):
        rest = m.group("rest").strip()
        # The lone positional, if any, is the description.
        description = ""
        if rest:
            inner = re.match(r'^\s*"([^"]*)"', rest)
            if inner is not None:
                description = inner.group(1)
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol="RootCommand",
                type_origin="cli_csharp",
                metadata={
                    "command": "<root>",
                    "framework": "System.CommandLine",
                    "style": "root",
                },
                docstring=description,
                intended_behaviour_sources=(),
            )
        )
    return found


def _discover_commandlineparser(text: str, rel: str) -> list[EntryPoint]:
    """Emit one EntryPoint per `[Verb("name", HelpText = "...")]` attribute."""
    found: list[EntryPoint] = []
    if "Verb" not in text:
        return found
    for m in _VERB_ATTR_RE.finditer(text):
        name = m.group("name")
        rest = m.group("rest")
        help_match = _VERB_HELP_RE.search(rest)
        help_text = help_match.group("help") if help_match is not None else ""
        line = _line_of(text, m.start())
        # The class annotated by this attribute is the symbol that the
        # walker can reference. Fall back to the verb name if the
        # attribute is somehow not attached to a class.
        class_name = _find_next_class_name(text, m.end())
        symbol = class_name if class_name else f"Verb({name})"
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol=symbol,
                type_origin="cli_csharp",
                metadata={
                    "command": name,
                    "framework": "CommandLineParser",
                    "style": "verb_attribute",
                    "class": class_name or "",
                },
                docstring=help_text,
                intended_behaviour_sources=(),
            )
        )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find C# CLI commands. Deterministic order."""
    if "csharp" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # IMPORTANT: skip-dir check is against the path RELATIVE to repo_root,
    # not the absolute path — otherwise a fixture located under a `tests/`
    # ancestor would cause the entire tree to be excluded. Mirrors the
    # same fix used in library_python.py and cli_python_click.py.
    cs_files: list[Path] = []
    for p in repo_root.rglob("*.cs"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        cs_files.append(p)
    cs_files.sort()

    for path in cs_files:
        raw_text = _read(path)
        if not raw_text:
            continue
        # Cheap pre-filter — skip files with no CLI framework markers.
        if (
            "System.CommandLine" not in raw_text
            and "RootCommand" not in raw_text
            and "new Command(" not in raw_text
            and "CommandLine" not in raw_text
            and "[Verb" not in raw_text
        ):
            continue
        rel = str(path.relative_to(repo_root))

        # Strip C# comments so the discoverer's regexes don't match
        # patterns inside `//` (including `///` XML docs) or `/* */`
        # blocks. String literals are preserved.
        text = _strip_comments(raw_text)
        found.extend(_discover_system_commandline(text, rel))
        found.extend(_discover_commandlineparser(text, rel))

    # Dedup by (file, line, symbol). Two distinct frameworks emitting on
    # the same source line would be a pathological overlap and we keep
    # the first.
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
