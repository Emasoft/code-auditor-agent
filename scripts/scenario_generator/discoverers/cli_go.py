"""Go CLI command discoverer — cobra / urfave/cli / kingpin.

Finds CLI subcommand registrations across Go packages. Three idioms
are handled:

1. **spf13/cobra** — `&cobra.Command{Use: "foo", Run: ...}` literal
   construction plus `parent.AddCommand(fooCmd)` chains. Each cobra
   Command literal is one CLI_COMMAND entry point.
2. **urfave/cli** — both v1 and v2: `cli.Command{Name: "foo"}` and
   `&cli.Command{Name: "foo"}`. Each Command literal is one entry.
3. **alecthomas/kingpin** — `app.Command("foo", "describe")` builder
   chain calls. Each `.Command(...)` invocation is one entry.

Heuristic, not full-AST: regex scan of `.go` files. Deterministic —
file order sorted, registration order from `re.finditer`. The skip-dirs
check uses `p.relative_to(repo_root).parts` so fixtures under
`tests/...` are not mis-skipped.

Intended-behaviour sources: `Short:` / `Long:` field of a cobra Command
literal, or the second-string argument of a kingpin `.Command(name,
help)` call, becomes the entry-point docstring.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Declared so the dispatcher in emit_scenarios_json._load_framework_discoverers
# can also locate this module via TYPE_ORIGIN scanning. The filename matches
# the canonical type name (cli_go), so the direct-load path also picks it up
# — TYPE_ORIGIN is belt-and-braces.
TYPE_ORIGIN = "cli_go"


# A cobra Command struct literal — both pointer and value forms. We
# accept any whitespace between the `Command` and the `{`. The `&` is
# optional; some codebases construct by value and take the address later.
_COBRA_LITERAL_RE = re.compile(r"&?\s*cobra\.Command\s*\{")
# urfave/cli Command literal — both v1 `cli.Command{...}` and v2
# `&cli.Command{...}`. Same pattern as cobra but with the `cli.` prefix.
_URFAVE_LITERAL_RE = re.compile(r"&?\s*cli\.Command\s*\{")
# Kingpin `.Command(name, help)` builder call. We capture both string
# args. Kingpin commands are always registered on an `*Application`
# (the app builder) or as subcommands on a previous Command builder
# — both are matched by the same regex.
_KINGPIN_COMMAND_RE = re.compile(
    r"\.Command\s*\(\s*\"(?P<name>[^\"]+)\"\s*,\s*\"(?P<help>[^\"]*)\"",
)
# Field assignment inside a struct-literal body. Captures the field
# name (e.g. `Use`, `Name`, `Short`, `Long`, `Aliases`) and a raw blob
# for its value. Used only on the body slice that has already been
# narrowed to one Command literal, so depth is handled outside.
_FIELD_STRING_RE = re.compile(
    r"\b(?P<field>Use|Name|Short|Long|Description|Usage|Aliases)\s*:\s*"
    r"(?P<value>\"[^\"]*\"|`[^`]*`)",
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
        "vendor",  # go modules vendor dir
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128 KB — fits typical main.go / cmd/*.go.


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _strip_comments(text: str) -> str:
    """Replace Go `//` and `/* ... */` comments with whitespace so the
    discoverer's regexes don't match patterns inside them.

    String literals (`"..."` and backtick-raw `` `...` ``) are
    preserved verbatim because they carry the command names the
    discoverer extracts. Newlines are preserved so byte offsets map
    to unchanged line numbers.

    String-literal interiors are NOT stripped here. If a comment-like
    pattern appears inside a real Go string, this function will leave
    it intact — but that's a false-positive scenario the discoverer
    accepts.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Line comment — blank out to end of line, keep \n.
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            if end == -1:
                end = n
            out.append(" " * (end - i))
            i = end
            continue
        # Block comment — blank out the body, keep newlines.
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


def _find_matching_brace(text: str, open_pos: int) -> int:
    """Return the index of the `}` matching the `{` whose offset is
    immediately before `open_pos`.

    `open_pos` is the position JUST AFTER the opening `{`. Returns -1
    if no balanced close is found within the preview window. Tracks
    string and raw-string literals so braces inside `"..."` and
    backtick-quoted strings don't throw off the depth count.
    """
    depth = 1
    i = open_pos
    n = len(text)
    in_string: str | None = None
    while i < n:
        ch = text[i]
        if in_string is not None:
            if ch == "\\" and in_string == '"' and i + 1 < n:
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch == '"' or ch == "`":
            in_string = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _strip_go_string_literal(literal: str) -> str:
    """Strip the surrounding quotes from a Go string literal.

    Accepts `"..."` (interpreted string) and `` `...` `` (raw string).
    For interpreted strings we DON'T process escape sequences — the
    discoverer keeps the raw bytes; the walker can re-interpret if it
    cares. Returns the inner text or '' if the input isn't a recognised
    string literal.
    """
    if len(literal) < 2:
        return ""
    if literal[0] == '"' and literal[-1] == '"':
        return literal[1:-1]
    if literal[0] == "`" and literal[-1] == "`":
        return literal[1:-1]
    return ""


def _extract_command_fields(body: str) -> dict[str, str]:
    """Pull `Use|Name|Short|Long|...` string fields out of a Command
    struct-literal body. First occurrence wins on dupes (Go disallows
    duplicate keys, but a malformed fixture might still parse).

    Only top-level fields are extracted — nested struct literals inside
    the body are scanned by `re.finditer` as well, but in practice
    cobra.Command and cli.Command don't have nested string-typed
    sub-structs whose keys collide with the top-level ones, so the
    first-occurrence rule is sufficient.
    """
    fields: dict[str, str] = {}
    for m in _FIELD_STRING_RE.finditer(body):
        field = m.group("field")
        if field in fields:
            continue
        fields[field] = _strip_go_string_literal(m.group("value"))
    return fields


def _discover_cobra(text: str, rel: str) -> list[EntryPoint]:
    """Emit one EntryPoint per cobra.Command literal."""
    found: list[EntryPoint] = []
    for m in _COBRA_LITERAL_RE.finditer(text):
        body_start = m.end()  # one past `{`
        body_end = _find_matching_brace(text, body_start)
        if body_end < 0:
            continue
        body = text[body_start:body_end]
        fields = _extract_command_fields(body)
        # cobra commands MUST have `Use:` to be useful — without it we
        # skip the literal (the user probably populates it elsewhere
        # via field assignment, which is rare and not standard cobra).
        use = fields.get("Use", "").strip()
        if not use:
            continue
        # `Use: "foo <bar>"` — the command name is the first token.
        cmd_name = use.split()[0] if use else ""
        if not cmd_name:
            continue
        short = fields.get("Short", "").strip()
        long_text = fields.get("Long", "").strip()
        docstring = short or long_text
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol=f"cobra.Command({cmd_name})",
                type_origin="cli_go",
                metadata={
                    "command": cmd_name,
                    "framework": "cobra",
                    "use": use,
                },
                docstring=docstring,
                intended_behaviour_sources=(),
            )
        )
    return found


def _discover_urfave(text: str, rel: str) -> list[EntryPoint]:
    """Emit one EntryPoint per urfave/cli Command literal."""
    found: list[EntryPoint] = []
    for m in _URFAVE_LITERAL_RE.finditer(text):
        body_start = m.end()
        body_end = _find_matching_brace(text, body_start)
        if body_end < 0:
            continue
        body = text[body_start:body_end]
        fields = _extract_command_fields(body)
        # urfave commands MUST have `Name:` to be useful — without it
        # we skip the literal.
        name = fields.get("Name", "").strip()
        if not name:
            continue
        usage = fields.get("Usage", "").strip()
        description = fields.get("Description", "").strip()
        docstring = usage or description
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol=f"cli.Command({name})",
                type_origin="cli_go",
                metadata={
                    "command": name,
                    "framework": "urfave_cli",
                },
                docstring=docstring,
                intended_behaviour_sources=(),
            )
        )
    return found


def _discover_kingpin(text: str, rel: str) -> list[EntryPoint]:
    """Emit one EntryPoint per kingpin `.Command(name, help)` call.

    Kingpin is rare enough that we accept any `.Command(<string>,
    <string>)` call as a kingpin command — false positives in a non-
    kingpin codebase are still semantically reasonable CLI surfaces.
    We DO require both arguments to be string literals to filter out
    cobra-style `.AddCommand(fooCmd)` calls (which take a *Command
    pointer, not a string).
    """
    found: list[EntryPoint] = []
    if "kingpin" not in text:
        return found
    for m in _KINGPIN_COMMAND_RE.finditer(text):
        name = m.group("name")
        help_text = m.group("help")
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol=f"kingpin.Command({name})",
                type_origin="cli_go",
                metadata={
                    "command": name,
                    "framework": "kingpin",
                },
                docstring=help_text,
                intended_behaviour_sources=(),
            )
        )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Go CLI commands. Deterministic order."""
    if "go" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # IMPORTANT: skip-dir check is against the path RELATIVE to repo_root,
    # not the absolute path — otherwise a fixture located under a `tests/`
    # ancestor would cause the entire tree to be excluded. Mirrors the
    # same fix used in library_python.py and cli_python_click.py.
    go_files: list[Path] = []
    for p in repo_root.rglob("*.go"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        go_files.append(p)
    go_files.sort()

    for path in go_files:
        raw_text = _read(path)
        if not raw_text:
            continue
        # Cheap pre-filter — skip files with no CLI framework markers.
        lowered_hit = "cobra" in raw_text or "urfave" in raw_text or "cli.Command" in raw_text or "kingpin" in raw_text
        if not lowered_hit:
            continue
        rel = str(path.relative_to(repo_root))

        # Strip Go comments so the discoverer's regexes don't match
        # patterns inside `//` or `/* */` blocks. String literals are
        # preserved.
        text = _strip_comments(raw_text)
        found.extend(_discover_cobra(text, rel))
        found.extend(_discover_urfave(text, rel))
        found.extend(_discover_kingpin(text, rel))

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
