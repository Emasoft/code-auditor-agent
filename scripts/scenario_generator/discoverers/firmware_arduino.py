"""Arduino firmware discoverer.

Finds Arduino-sketch entry points across `.ino`, `.cpp`, and `.h` files:

- `void setup() { ... }` — BOOT_PATH (one-time init at power-on / reset).
- `void loop()  { ... }` — MAIN_FUNCTION (cooperative scheduler body).
- `attachInterrupt(digitalPinToInterrupt(<pin>), <handler>, <mode>)` —
  GPIO_INTERRUPT, one entry per handler with metadata `{pin, mode}`.
- `Serial.onReceive(<handler>)`, `Wire.onReceive(...)`, `Wire.onRequest(...)`
  — EVENT_LISTENER with metadata `{bus, event}`.

The discoverer is heuristic (regex-based, not AST), but deterministic:
files are sorted, matches within a file are iterated in source order,
and a final dedup + sort pass guarantees byte-identical output across
runs on the same inputs.

The companion `setup()` and `loop()` symbols are also discovered when
they appear in `.cpp` files alongside an `.ino` sketch (the
Arduino-PlatformIO hybrid pattern), but only when at least one `.ino`
file is present in the repo so we don't mis-fire on plain C++ code.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `void setup()` or `void loop()` at column 0 — the Arduino sketch
# convention. Whitespace before `void` is tolerated for indented
# class-method-style sketches, but `\s*` at the start prevents matching
# `static void setup_foo()` and friends.
_SETUP_RE = re.compile(r"^\s*void\s+setup\s*\(\s*\)\s*\{", re.MULTILINE)
_LOOP_RE = re.compile(r"^\s*void\s+loop\s*\(\s*\)\s*\{", re.MULTILINE)

# `attachInterrupt(digitalPinToInterrupt(<pin>), <handler>, <mode>)`.
# The pin expression is kept verbatim (it may be a literal int, a #define,
# or `BUTTON_PIN`); the mode is the trailing identifier. DOTALL lets
# multi-line argument lists through.
_ATTACH_INTERRUPT_RE = re.compile(
    r"attachInterrupt\s*\(\s*"
    r"digitalPinToInterrupt\s*\(\s*(?P<pin>[^)]+?)\s*\)\s*,\s*"
    r"(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<mode>RISING|FALLING|CHANGE|LOW|HIGH)\s*\)",
    re.DOTALL,
)

# `Serial.onReceive(handler)`, `Wire.onReceive(handler)`,
# `Wire.onRequest(handler)` — common Arduino library event hooks.
# `Serial1`, `Serial2`, ... are normalised to bus="Serial" for the
# walker (the family logic is the same regardless of UART instance).
_EVENT_LISTENER_RE = re.compile(
    r"\b(?P<bus>Serial\d*|Wire\d*)\s*\.\s*"
    r"(?P<event>onReceive|onRequest)\s*\(\s*"
    r"(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*\)",
)

# Single-line `//`, multi-line `/* ... */`, and triple-slash `///`
# comments near a match — used as the docstring source for the
# generated EntryPoint.
_LINE_COMMENT_RE = re.compile(r"^\s*(?://+|\*)\s?(?P<text>.*?)\s*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*(?P<text>.*?)\*/", re.DOTALL)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".pio",
        ".pioenvs",
        ".piolibdeps",
        ".vscode",
        ".idea",
        "build",
        "dist",
        "out",
        "bin",
        "obj",
        ".cache",
        "node_modules",
        "vendor",
        "__pycache__",
        "tests",
        "test",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "examples_dev",
        "samples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Arduino sketches almost never exceed this


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES bytes, UTF-8 with replace."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _comment_before(text: str, offset: int) -> str:
    """Pull a short doc summary from comments immediately preceding `offset`.

    Walks backwards from the start-of-line containing `offset` and
    collects contiguous `//` / `///` / `*` comment lines, plus a single
    `/* ... */` block comment if it ends right before the symbol. The
    result is the first non-empty extracted line — kept short so the
    walker uses it as an intent hint, not a paragraph.
    """
    # Find the start of the line containing `offset`.
    line_start = text.rfind("\n", 0, offset) + 1
    # Walk back over preceding lines as long as they are comment lines.
    lines: list[str] = []
    cursor = line_start - 1  # position of the newline before our line
    while cursor > 0:
        prev_line_start = text.rfind("\n", 0, cursor) + 1
        prev_line = text[prev_line_start:cursor]
        stripped = prev_line.strip()
        if not stripped:
            # Blank line ends the comment block; stop.
            break
        if stripped.startswith(("//", "*")):
            m = _LINE_COMMENT_RE.match(prev_line)
            if m:
                lines.insert(0, m.group("text").strip())
            cursor = prev_line_start - 1
            continue
        # Look for a `*/` ending a block comment on this preceding line.
        if stripped.endswith("*/"):
            block_search = text.rfind("/*", 0, cursor)
            if block_search != -1:
                block = text[block_search : cursor + 1]
                bm = _BLOCK_COMMENT_RE.search(block)
                if bm:
                    body = bm.group("text").strip()
                    # First non-empty line of the block.
                    for ln in body.splitlines():
                        s = ln.strip().lstrip("*").strip()
                        if s:
                            lines.insert(0, s)
                            break
            break
        break

    for ln in lines:
        if ln:
            return ln
    return ""


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Return True if any directory under `repo_root` on the way to `path`
    is in `_SKIP_DIRS`.

    We deliberately compute parts *relative to repo_root* — checking
    absolute parts would mis-skip every fixture whose repo_root happens
    to live under a directory named, say, `tests/` (e.g. our own
    `tests/fixtures/...`). The repo_root itself is whatever the caller
    asked us to scan; what's *inside* it is what matters.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        # Path outside repo_root — shouldn't happen via rglob, but be safe.
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_source_files(repo_root: Path) -> list[Path]:
    """Return sorted .ino / .cpp / .h files, skipping junk dirs.

    `.cpp` and `.h` are only scanned when at least one `.ino` exists in
    the repo — otherwise we'd misidentify ordinary C++ projects as
    Arduino sketches.
    """
    ino_files = [p for p in repo_root.rglob("*.ino") if p.is_file() and not _is_skipped(p, repo_root)]
    if not ino_files:
        return []
    out: list[Path] = list(ino_files)
    for ext in (".cpp", ".h", ".hpp", ".cc", ".cxx"):
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            out.append(p)
    out.sort()
    return out


def _normalise_bus(raw: str) -> str:
    """`Serial`, `Serial1`, `Serial2`, ... → `Serial`. `Wire`, `Wire1` → `Wire`.

    The walker reasons about the bus *kind*, not the UART instance — two
    sketches that differ only by `Serial1` vs `Serial2` should produce
    the same scenarios.
    """
    if raw.startswith("Serial"):
        return "Serial"
    if raw.startswith("Wire"):
        return "Wire"
    return raw


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Arduino entry points. Deterministic order.

    `languages` is currently advisory — we run whenever any `.ino` file
    is present, regardless of the language list (the language detector
    in `emit_scenarios_json` maps `.ino` → `arduino`, but the discoverer
    must not gate on it because Arduino sketches frequently mix in
    `.cpp` and `.h` files that the detector classifies as `cpp`).
    """
    del languages  # advisory; gating is done by .ino presence below.

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    source_files = _iter_source_files(repo_root)
    if not source_files:
        return []

    for path in source_files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) void setup() { ... }  → BOOT_PATH
        for m in _SETUP_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="setup",
                    type_origin="firmware_arduino",
                    metadata={"role": "arduino_setup"},
                    docstring=_comment_before(text, m.start()),
                )
            )

        # 2) void loop() { ... }   → MAIN_FUNCTION
        for m in _LOOP_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="loop",
                    type_origin="firmware_arduino",
                    metadata={"role": "arduino_loop"},
                    docstring=_comment_before(text, m.start()),
                )
            )

        # 3) attachInterrupt(...) → GPIO_INTERRUPT, one per handler.
        for m in _ATTACH_INTERRUPT_RE.finditer(text):
            handler = m.group("handler")
            pin = m.group("pin").strip()
            mode = m.group("mode")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.GPIO_INTERRUPT,
                    file=rel,
                    line=line,
                    symbol=handler,
                    type_origin="firmware_arduino",
                    metadata={"pin": pin, "mode": mode},
                    docstring=_comment_before(text, m.start()),
                )
            )

        # 4) Serial.onReceive / Wire.onReceive / Wire.onRequest → EVENT_LISTENER.
        for m in _EVENT_LISTENER_RE.finditer(text):
            handler = m.group("handler")
            bus = _normalise_bus(m.group("bus"))
            event = m.group("event")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=handler,
                    type_origin="firmware_arduino",
                    metadata={"bus": bus, "event": event},
                    docstring=_comment_before(text, m.start()),
                )
            )

    # Dedup by (file, line, symbol, kind, bus|mode|pin) — same handler
    # registered twice on different pins is two distinct entries; same
    # registration that happens to also live in a header included from
    # the .ino is one entry.
    seen: set[tuple[str, int, str, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        # Choose a discriminator that captures registration uniqueness
        # without overcollapsing across different ISR pins or buses.
        if ep.kind == EntryPointKind.GPIO_INTERRUPT:
            disc = f"pin={ep.metadata.get('pin', '')}/mode={ep.metadata.get('mode', '')}"
        elif ep.kind == EntryPointKind.EVENT_LISTENER:
            disc = f"bus={ep.metadata.get('bus', '')}/event={ep.metadata.get('event', '')}"
        else:
            disc = ""
        key = (ep.file, ep.line, ep.symbol, ep.kind.value, disc)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(key=lambda e: (e.sort_key(), e.kind.value))
    return unique
