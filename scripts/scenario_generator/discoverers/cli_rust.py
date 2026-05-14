"""Rust CLI command discoverer — clap / structopt / argh / pico-args.

Finds CLI command/subcommand registrations across Rust crates. The two
dominant idioms are handled:

1. **clap derive macros** — `#[derive(Subcommand)]` enum whose variants
   are subcommands; `#[derive(Parser)]` struct that names the binary;
   per-variant `#[command(name = "...")]` attribute overrides. Each
   variant of a `Subcommand` enum is one CLI_COMMAND entry point.
2. **clap builder API** — `Command::new("foo")` / `App::new("foo")`
   followed by chained `.subcommand(Command::new("bar"))` calls.

Also recognises:
- `#[structopt(...)]` attributes for the older `structopt` crate (which
  uses the same derive macros, mapped to clap≥3).
- `argh::FromArgs` derive — `#[argh(subcommand)]` enum entries.

Emits one EntryPoint per detected command/subcommand definition.

Heuristic, not full-AST: regex scan of `.rs` files. Deterministic — file
order sorted, decorator order from `re.finditer`. The skip-dirs check
uses `p.relative_to(repo_root).parts` so fixtures under `tests/...` are
not mis-skipped.

Intended-behaviour sources: nearby `///` doc comments or `about = "..."`
attribute arg become the entry point's docstring.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Declared so the dispatcher in emit_scenarios_json._load_framework_discoverers
# can also locate this module via TYPE_ORIGIN scanning. The filename matches
# the canonical type name (cli_rust), so the direct-load path also picks it
# up — TYPE_ORIGIN is belt-and-braces.
TYPE_ORIGIN = "cli_rust"


# A `#[derive(...Subcommand...)]` line — clap derive that turns an enum into
# subcommands. We accept any whitespace and any ordering of derive args, and
# we tolerate either `Subcommand` or the older `clap::Subcommand` qualified
# spelling.
_DERIVE_SUBCOMMAND_RE = re.compile(
    r"#\[derive\s*\([^)]*\b(?:clap::)?Subcommand\b[^)]*\)\]",
)
# `enum Name {` line — captures the enum identifier. Used together with
# the derive match above to locate the start of a Subcommand enum body.
_ENUM_DEF_RE = re.compile(r"\benum\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{")
# A variant inside a clap Subcommand enum body. We strip preceding `///` and
# `#[command(...)]` attributes off and capture the variant identifier plus
# any inline `name = "..."` override. Each variant is one CLI_COMMAND entry.
_VARIANT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<name>[A-Z][A-Za-z0-9_]*)\s*(?:\{|\(|,|$)",
    re.MULTILINE,
)
# `#[command(name = "foo", ...)]` or `#[clap(name = "foo", ...)]` immediately
# above a variant — overrides the default command name (which would be the
# variant identifier lowercased).
_CMD_NAME_ATTR_RE = re.compile(
    r"#\[(?:command|clap)\s*\(\s*[^)]*\bname\s*=\s*\"(?P<name>[^\"]+)\"",
)
# `about = "..."` inside a `#[command(...)]` or `#[clap(...)]` attribute —
# becomes the docstring for the entry.
_CMD_ABOUT_ATTR_RE = re.compile(
    r"#\[(?:command|clap)\s*\(\s*[^)]*\babout\s*=\s*\"(?P<about>[^\"]*)\"",
)
# Builder-API form: `Command::new("foo")` or `App::new("foo")`. We capture
# the literal name passed as the first arg. Subcommands are chained via
# `.subcommand(Command::new("bar"))` — each one independently matches here.
_BUILDER_NEW_RE = re.compile(
    r"\b(?:Command|App)::new\s*\(\s*\"(?P<name>[^\"]+)\"",
)
# `///` doc-comment line above a variant — first non-empty line becomes
# the docstring when no `about = "..."` attribute is present.
_DOC_COMMENT_LINE_RE = re.compile(r"^[ \t]*///\s?(?P<text>.*)$", re.MULTILINE)


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


CONTENT_PREVIEW_BYTES = 131072  # 128 KB — covers main.rs / cli.rs in real crates.


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _strip_comments(text: str) -> str:
    """Replace plain Rust comments with spaces so the discoverer's
    regexes don't match patterns inside `//` or `/* ... */` comments.

    Crucially, we PRESERVE:
    - `///` and `//!` doc comments — they carry the per-variant
      docstring that `_preceding_attrs_and_doc` extracts.
    - String literals (`"..."`, `r"..."`, `r#"..."#`) — they're the
      first-class source of clap command names and `about = "..."`
      text, which the discoverer regexes match against verbatim.

    Newlines are preserved so byte offsets continue to map to the same
    line numbers — `_line_of(text, offset)` returns the correct line in
    the stripped text just as it would in the original.

    String-literal interiors are NOT stripped here. If a comment-like
    pattern (`// foo`) appears inside a normal string, this function
    will mis-handle it — but Rust source files rarely embed `//`
    inside a non-doc string, and the false-positive cost is just a
    spurious entry-point match in a string that happens to contain
    `Command::new("foo")` text, which is acceptable.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Doc comments — preserve verbatim. `///` is outer doc, `//!`
        # is inner doc. We require a third char that is `/` or `!` to
        # distinguish from a plain `//` line comment.
        if ch == "/" and i + 2 < n and text[i + 1] == "/" and text[i + 2] in "/!":
            end = text.find("\n", i)
            if end == -1:
                end = n
            out.append(text[i:end])
            i = end
            continue
        # Plain line comment — blank out to end of line, keep \n.
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            if end == -1:
                end = n
            out.append(" " * (end - i))
            i = end
            continue
        # Block comment `/* ... */` — blank out the body, keep newlines.
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                end = n
            else:
                end += 2  # past the `*/`
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
    if no balanced close is found within the preview window. We
    intentionally ignore strings/comments here — Rust enum bodies don't
    typically contain `{`/`}` characters inside string literals at the
    depth that matters, and we'd rather over-scan than under-scan.
    """
    depth = 1
    i = open_pos
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _preceding_attrs_and_doc(text: str, variant_start: int) -> tuple[str, str]:
    """Walk backwards from a variant's start collecting `#[...]` attrs
    and `///` doc-comment lines that belong to it.

    Returns `(joined_attr_text, doc_first_line)`:
    - `joined_attr_text` is every contiguous attribute block above the
      variant joined into one string (so `_CMD_NAME_ATTR_RE` can be run
      once on it to find an explicit `name = "..."`).
    - `doc_first_line` is the first non-empty `///` line above the
      variant — used as a fallback docstring when no `about` attribute
      is present in the attrs.
    """
    attrs_blocks: list[str] = []
    doc_lines_reverse: list[str] = []
    cursor = variant_start - 1
    while cursor > 0:
        prev_nl = text.rfind("\n", 0, cursor)
        line_start = prev_nl + 1 if prev_nl != -1 else 0
        line = text[line_start:cursor]
        cursor = line_start - 1
        stripped = line.strip()
        if not stripped:
            # Blank line — Rust attributes / doc comments stack with no
            # blanks; once we hit a blank, we are out of the variant's
            # docblock.
            break
        if stripped.startswith("#["):
            attrs_blocks.append(line)
            continue
        m = _DOC_COMMENT_LINE_RE.match(line)
        if m is not None:
            doc_lines_reverse.append(m.group("text").strip())
            continue
        # Anything else (code, comment, struct opening) terminates the docblock.
        break
    doc_lines_reverse.reverse()
    first_doc = ""
    for ln in doc_lines_reverse:
        if ln:
            first_doc = ln
            break
    return ("\n".join(attrs_blocks), first_doc)


def _discover_derive_subcommand_enums(text: str, rel: str) -> list[EntryPoint]:
    """Find every `#[derive(Subcommand)] enum Name { ... }` block and
    emit one EntryPoint per variant.

    The enum body is bounded by the first `{`/`}` pair after the derive
    attribute. Variants are matched by `_VARIANT_RE` against the slice
    of the enum body that lies between the opening `{` and its matching
    `}`. Each variant's preceding `#[command(...)]` attributes (if any)
    are scanned for `name = "..."` overrides and `about = "..."` text.
    """
    found: list[EntryPoint] = []
    for derive_match in _DERIVE_SUBCOMMAND_RE.finditer(text):
        # The enum keyword should appear within ~256 chars of the derive
        # — anything farther is unrelated.
        tail_start = derive_match.end()
        tail = text[tail_start : tail_start + 512]
        enum_match = _ENUM_DEF_RE.search(tail)
        if enum_match is None:
            continue
        enum_name = enum_match.group("name")
        enum_brace_open = tail_start + enum_match.end()  # one past `{`
        body_end = _find_matching_brace(text, enum_brace_open)
        if body_end < 0:
            continue
        body_start = enum_brace_open
        body = text[body_start:body_end]

        for var_match in _VARIANT_RE.finditer(body):
            variant_name = var_match.group("name")
            variant_abs_start = body_start + var_match.start()
            # Filter out spurious top-level `Self`, `Result`, etc. by
            # requiring the variant identifier to be the first non-attr
            # token at that line (the regex already requires it to be
            # capitalised). Skip the four reserved Rust keywords that
            # are also CamelCase (`Self`, `Ok`, `Err`, `None`/`Some`) —
            # they cannot be a clap variant name.
            if variant_name in {"Self", "Ok", "Err", "None", "Some"}:
                continue
            attrs_blob, doc_first = _preceding_attrs_and_doc(text, variant_abs_start)
            name_override = _CMD_NAME_ATTR_RE.search(attrs_blob)
            command_name = name_override.group("name") if name_override is not None else variant_name.lower()
            about_attr = _CMD_ABOUT_ATTR_RE.search(attrs_blob)
            docstring = about_attr.group("about") if about_attr is not None else doc_first

            line = _line_of(text, variant_abs_start)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.CLI_COMMAND,
                    file=rel,
                    line=line,
                    symbol=f"{enum_name}::{variant_name}",
                    type_origin="cli_rust",
                    metadata={
                        "command": command_name,
                        "framework": "clap",
                        "style": "derive",
                        "enum": enum_name,
                        "variant": variant_name,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )
    return found


def _discover_builder_commands(text: str, rel: str) -> list[EntryPoint]:
    """Find every `Command::new("foo")` / `App::new("foo")` call.

    These can be either the root command of a `clap::Command` builder
    chain or a subcommand. We emit one EntryPoint per call site — the
    walker treats each one as an independent CLI invocation surface.
    """
    found: list[EntryPoint] = []
    for m in _BUILDER_NEW_RE.finditer(text):
        command_name = m.group("name")
        line = _line_of(text, m.start())
        # Heuristic about-string extraction: scan the next ~256 chars
        # for `.about("...")` or `.about(...)` arg.
        tail = text[m.end() : m.end() + 256]
        about_match = re.search(r"\.about\s*\(\s*\"(?P<about>[^\"]*)\"", tail)
        docstring = about_match.group("about") if about_match is not None else ""
        found.append(
            EntryPoint(
                kind=EntryPointKind.CLI_COMMAND,
                file=rel,
                line=line,
                symbol=f"Command::new({command_name})",
                type_origin="cli_rust",
                metadata={
                    "command": command_name,
                    "framework": "clap",
                    "style": "builder",
                },
                docstring=docstring,
                intended_behaviour_sources=(),
            )
        )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Rust CLI commands. Deterministic order."""
    if "rust" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # IMPORTANT: skip-dir check is against the path RELATIVE to repo_root,
    # not the absolute path — otherwise a fixture located under a `tests/`
    # ancestor would cause the entire tree to be excluded. Mirrors the
    # same fix used in library_python.py and cli_python_click.py.
    rs_files: list[Path] = []
    for p in repo_root.rglob("*.rs"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        rs_files.append(p)
    rs_files.sort()

    for path in rs_files:
        raw_text = _read(path)
        if not raw_text:
            continue
        # Cheap pre-filter — skip files with no CLI markers at all.
        if (
            "clap" not in raw_text
            and "structopt" not in raw_text
            and "argh" not in raw_text
            and "Command::new" not in raw_text
            and "App::new" not in raw_text
        ):
            continue
        rel = str(path.relative_to(repo_root))

        # Strip plain `//` and `/* */` comments so the discoverer's
        # regexes don't match patterns inside them. Doc comments
        # (`///`, `//!`) and string literals are preserved.
        text = _strip_comments(raw_text)
        found.extend(_discover_derive_subcommand_enums(text, rel))
        found.extend(_discover_builder_commands(text, rel))

    # Dedup by (file, line, symbol). Two distinct command-name overrides
    # at the same source location would be a pathological case and we
    # keep the first.
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
