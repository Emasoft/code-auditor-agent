"""yargs CLI command discoverer.

Mirrors the structure of web_python_fastapi.py: regex-only, deterministic,
no AST. yargs registrations come in two flavours, both handled here:

- Inline-string form:
    `yargs.command('foo <bar>', 'description', (yargs) => {...}, handler)`
  Where the FIRST positional is the command spec (`'foo <bar>'`) and the
  SECOND is the `describe` string. The third can be a builder lambda; the
  fourth is the handler. We extract the command name as the first token
  before any space (so `'foo <bar>'` -> `foo`).

- Object form:
    `yargs.command({command: 'foo', describe: '...', builder: {...}, handler: ...})`
  We pluck `command:` and `describe:` from the object literal body.

The two forms are detected by what follows `.command(` — either a quoted
string (string form) or a `{` (object form). The same yargs builder can
also be chained: `yargs().command(...).command(...).demandCommand(1).parse()`
— each `.command(` independently produces its own EntryPoint.

`.option('foo', ...)` calls found inside the immediate scope after a
.command(...) registration (best-effort: within the next ~2 KB of source,
which covers most realistic builders) are collected into
`metadata.options`. This is heuristic — a deeply-nested or
side-effect-imported builder may miss options — but it is deterministic
and sufficient for the v1 walker's adversarial-input scenarios.

Intended-behaviour sources: the `describe:` property or the second-string
arg of `.command(...)` becomes the entry-point's docstring.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `.command(<quote>...` — inline-string form. Captures the opening quote so
# we can find the matching close.
_CMD_STRING_RE = re.compile(
    r"\.command\s*\(\s*(?P<q>[\"'])(?P<spec>[^\"']*)(?P=q)",
)
# `.command({...` — object form. We don't capture the body here; we scan
# forward from the match end for `command:` / `describe:` properties.
_CMD_OBJECT_RE = re.compile(r"\.command\s*\(\s*\{")
# `command:` and `describe:` property assignments inside an object literal.
_OBJ_COMMAND_PROP_RE = re.compile(
    r"\bcommand\s*:\s*(?P<q>[\"'])(?P<spec>[^\"']*)(?P=q)",
)
_OBJ_DESCRIBE_PROP_RE = re.compile(
    r"\b(?:describe|description)\s*:\s*(?P<q>[\"'])(?P<text>[^\"']*)(?P=q)",
)
# Second positional string of `.command('cmd', 'describe', ...)`. We scan
# the tail after the first quoted spec for the next quoted literal that
# precedes the next comma at depth 0 — but as a deterministic approximation
# we just take the second quoted string within the same parenthesized call
# (handled inline below since regex can't track brace depth).
_NEXT_STRING_RE = re.compile(r"(?P<q>[\"'])(?P<text>[^\"']*)(?P=q)")
# `.option('name', ...)` — used to collect builder options. We only capture
# the option name; the option spec body is not interpreted.
_OPTION_RE = re.compile(
    r"\.option\s*\(\s*(?P<q>[\"'])(?P<name>[^\"']+)(?P=q)",
)
# `builder: {` — entry into an object-form builder. After this we walk
# brace depth to find the matching `}` and pull keys out one level deep.
_BUILDER_PROP_RE = re.compile(r"\bbuilder\s*:\s*\{")
# Top-level bare-identifier key inside an object literal, e.g.
# `  loud: {` / `  'dry-run': {`. Captures key names that are followed by
# `:` — handles both bare and quoted identifiers. Used only on a string
# slice that has already been narrowed to one builder body, so depth is 0.
_OBJECT_KEY_RE = re.compile(
    r"(?:^|[,{\s])\s*(?P<q>[\"']?)(?P<name>[A-Za-z_$][A-Za-z0-9_$-]*)(?P=q)\s*:",
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
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128 KB — enough for big CLI files.
# Window after `.command(` we scan for builder options and second-string args.
_BUILDER_WINDOW_BYTES = 2048


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _command_name_from_spec(spec: str) -> str:
    """`'foo <bar> [baz]'` -> `'foo'`. yargs spec syntax."""
    # Strip leading `$0`/whitespace; take the first whitespace-delimited token.
    spec = spec.strip()
    if not spec:
        return ""
    # `$0` is yargs' "this is the default command" sentinel.
    if spec.startswith("$0"):
        rest = spec[2:].strip()
        if not rest:
            return "$0"
        return rest.split()[0]
    return spec.split()[0]


def _find_matching_brace(text: str, open_pos: int) -> int:
    """Return index of `}` matching the `{` at `open_pos - 1`.

    `open_pos` is the position JUST AFTER the opening `{`. Returns -1
    if no balanced close is found within the preview window.
    """
    depth = 1
    i = open_pos
    n = len(text)
    in_string: str | None = None
    while i < n:
        ch = text[i]
        if in_string is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "\"'`":
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


def _extract_object_keys(body: str) -> list[str]:
    """Extract top-level (depth-1) keys from an object-literal body.

    `body` is the text BETWEEN the matching `{` and `}`. We scan for
    `key:` tokens that occur at brace depth 0 (relative to `body`).
    Deterministic order — first-occurrence wins on dupes.
    """
    names: list[str] = []
    seen: set[str] = set()
    depth = 0
    i = 0
    n = len(body)
    in_string: str | None = None
    # We need to know, for each `key:` candidate, the depth at the key's
    # start. We collect candidate positions at depth==0 only.
    while i < n:
        ch = body[i]
        if in_string is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "\"'`":
            in_string = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            m = _OBJECT_KEY_RE.match(body, i)
            if m is not None and m.start() == i:
                name = m.group("name")
                if name not in seen:
                    seen.add(name)
                    names.append(name)
                i = m.end()
                continue
        i += 1
    return names


def _collect_options(text: str, start: int, end: int) -> list[str]:
    """Find option names registered for the command starting at `start`.

    Two yargs forms are supported:
    - Lambda builder using `.option('name', ...)` chain calls.
    - Object-literal builder map `builder: { name: {...}, ... }`.

    The scan window is truncated at the next `.command(` so that options
    registered for a SUBSEQUENT command don't leak into the previous
    command's option list — yargs chains read left-to-right, so every
    `.command(...)` opens a fresh option scope from the discoverer's
    point of view. Deterministic order — first-occurrence wins on dupes.
    """
    if start >= end or start < 0:
        return []
    window = text[start:end]
    # Cap window at the next `.command(` — that's where the option scope
    # for THIS command effectively ends (yargs chains are linear).
    next_cmd = window.find(".command(")
    if next_cmd >= 0:
        window = window[:next_cmd]
    names: list[str] = []
    seen: set[str] = set()

    # Form A: `.option('name', ...)` chain calls.
    for m in _OPTION_RE.finditer(window):
        name = m.group("name")
        if name in seen:
            continue
        seen.add(name)
        names.append(name)

    # Form B: object-literal `builder: { ... }` map. We need the absolute
    # offsets to use _find_matching_brace, so search against the full text
    # within the bounded window.
    window_end_abs = start + len(window)
    for m in _BUILDER_PROP_RE.finditer(text, start, window_end_abs):
        body_start = m.end()  # one past `{`
        body_end = _find_matching_brace(text, body_start)
        if body_end < 0 or body_end > window_end_abs:
            continue
        for key in _extract_object_keys(text[body_start:body_end]):
            if key in seen:
                continue
            seen.add(key)
            names.append(key)

    return names


def _find_second_string_arg(text: str, after_offset: int) -> str:
    """For `.command('foo', 'describe text', ...)` — find the second string.

    We scan forward from `after_offset` (which sits AFTER the first quoted
    spec) for the next quoted literal that appears BEFORE we hit a `,` at
    paren-depth 0. If we hit `,` first we still take the string immediately
    following it. Best-effort; returns '' if not present.
    """
    window = text[after_offset : after_offset + _BUILDER_WINDOW_BYTES]
    # Find the first comma at depth 0 (in this window) — yargs's second positional.
    depth = 0
    comma_idx = -1
    for i, ch in enumerate(window):
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
            if depth < 0:
                break
        elif ch == "," and depth == 0:
            comma_idx = i
            break
    if comma_idx < 0:
        return ""
    rest = window[comma_idx + 1 :]
    m = _NEXT_STRING_RE.search(rest)
    if not m:
        return ""
    # Reject if there's a non-whitespace, non-`(`-style char before the quote
    # — that would mean we landed on a non-string second arg (e.g. an object).
    head = rest[: m.start()]
    if head.strip():
        return ""
    return m.group("text")


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find yargs command registrations. Deterministic order."""
    if "javascript" not in languages and "typescript" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    js_files: list[Path] = []
    for ext in (".js", ".mjs", ".cjs", ".ts"):
        for p in repo_root.rglob(f"*{ext}"):
            # Only skip if the SKIP_DIRS entry appears INSIDE the repo, not
            # if the repo itself is hosted under one (e.g. `tests/fixtures/`).
            try:
                rel_parts = p.relative_to(repo_root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            if p.is_file():
                js_files.append(p)
    js_files.sort()

    for path in js_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter: yargs must be imported or `.command(` must appear.
        if "yargs" not in text.lower() and ".command(" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) Inline-string form: `.command('foo', 'describe', ...)`.
        for m in _CMD_STRING_RE.finditer(text):
            spec = m.group("spec")
            cmd_name = _command_name_from_spec(spec)
            if not cmd_name:
                continue
            line = _line_of(text, m.start())
            # Second positional string (describe) — best-effort.
            describe = _find_second_string_arg(text, m.end())
            options = _collect_options(text, m.end(), m.end() + _BUILDER_WINDOW_BYTES)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.CLI_COMMAND,
                    file=rel,
                    line=line,
                    symbol=f"cmd_{cmd_name}",
                    type_origin="cli_node",
                    metadata={
                        "command": cmd_name,
                        "framework": "yargs",
                        "options": options,
                    },
                    docstring=describe,
                    intended_behaviour_sources=(),
                )
            )

        # 2) Object form: `.command({command: 'foo', describe: '...', ...})`.
        for m in _CMD_OBJECT_RE.finditer(text):
            obj_start = m.end()  # one past the `{`
            window = text[obj_start : obj_start + _BUILDER_WINDOW_BYTES]
            cmd_match = _OBJ_COMMAND_PROP_RE.search(window)
            if not cmd_match:
                continue
            cmd_name = _command_name_from_spec(cmd_match.group("spec"))
            if not cmd_name:
                continue
            line = _line_of(text, m.start())
            desc_match = _OBJ_DESCRIBE_PROP_RE.search(window)
            describe = desc_match.group("text") if desc_match else ""
            options = _collect_options(text, obj_start, obj_start + _BUILDER_WINDOW_BYTES)
            found.append(
                EntryPoint(
                    kind=EntryPointKind.CLI_COMMAND,
                    file=rel,
                    line=line,
                    symbol=f"cmd_{cmd_name}",
                    type_origin="cli_node",
                    metadata={
                        "command": cmd_name,
                        "framework": "yargs",
                        "options": options,
                    },
                    docstring=describe,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol) — same .command(...) call can't appear
    # twice at the same source location.
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
