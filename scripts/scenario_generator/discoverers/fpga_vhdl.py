"""FPGA VHDL discoverer.

Finds VHDL ``entity`` declarations in a hardware design and emits one
``EntryPoint`` per entity. VHDL is structurally similar to Verilog —
the ``entity NAME is ... end NAME;`` declaration is the design-unit
boundary, and a separate ``architecture rtl of NAME is ... end rtl;``
provides the implementation. The discoverer:

1. Walks ``*.vhd`` / ``*.vhdl`` files recursively.
2. Splits each file into one entity per declaration.
3. Emits each entity as ``FPGA_TOPLEVEL_PORT`` (the closest schema
   match — the walker treats every entity boundary as an external
   pin-list for reasoning purposes).
4. Tags testbench entities (``entity NAME_tb is``, ``architecture
   testbench of ... is``) with ``metadata['role'] == 'testbench'`` so
   the walker can distinguish them from synthesisable entities.

The discoverer is intentionally permissive about port-list parsing:
unlike Verilog where the port direction lives on every declaration,
VHDL ports have shape ``signal_name : direction subtype`` in the
``port (...)`` block. We capture the port names + directions but
not the exact subtype (which can be a packaged record or array type
and is brittle to parse with regex). The walker reads the metadata
dict opaquely.

Skip-dir check uses ``p.relative_to(repo_root).parts`` (NOT
``p.parts``) so a fixture under ``tests/fixtures/...`` is not
mis-skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

CONTENT_PREVIEW_BYTES = 262144  # 256 KB — VHDL files can be verbose.

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "ipcore",
        "xilinx_ip",
        "altera_ip",
        "lib",
        "node_modules",
        "vendor",
        "__pycache__",
        "dist",
        "build",
        "target",
        "out",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
    }
)

# `entity NAME is` — VHDL entity declaration opening. Captures the name.
# Case-insensitive because VHDL identifiers and keywords are case-insensitive
# by language definition.
_ENTITY_RE = re.compile(
    r"\bentity\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+is\b",
    re.IGNORECASE,
)

# Matching `end <name>;` or bare `end;` — used to delimit the entity body
# so we only parse ports inside the right block.
_END_ENTITY_RE = re.compile(
    r"\bend\b(?:\s+entity)?(?:\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*))?\s*;",
    re.IGNORECASE,
)

# Inside an entity's port (...) block: one port declaration per line.
# Shape: ``name [, name2, name3] : direction subtype [:= default];``
# Examples (all valid VHDL):
#   ``clk : in std_logic;``
#   ``data_in, data_out : inout std_logic_vector(7 downto 0);``
#   ``led : out std_logic_vector(7 downto 0) := (others => '0');``
_PORT_DECL_RE = re.compile(
    r"^\s*(?P<names>[A-Za-z_][\w\s,]*?)\s*:"
    r"\s*(?P<dir>in|out|inout|buffer|linkage)\b",
    re.MULTILINE | re.IGNORECASE,
)

# `port (` ... `);` — extract the port list region inside an entity body.
# Depth-counted manually because port subtypes can themselves contain
# parens (e.g. ``std_logic_vector(7 downto 0)``).

# Single-line and block comments (VHDL uses ``--`` for line comments;
# no block comments).
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _read(path: Path) -> str:
    """Read up to ``CONTENT_PREVIEW_BYTES`` and strip ``--`` line comments.

    Comment stripping is done once at read time so the port-extraction
    regex doesn't have to dodge ``--`` inside otherwise-valid port lines.
    The walker uses the ORIGINAL file's line numbers (which we compute
    on the un-stripped text below), so comment stripping is a transform
    purely for pattern-matching.
    """
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number for a byte offset."""
    return text.count("\n", 0, offset) + 1


def _extract_port_block(body: str) -> str:
    """Pull the ``port (...);`` region out of an entity body.

    Returns the textual contents BETWEEN the opening ``port (`` and the
    matching closing ``)``. Empty string if no port block is present
    (some entities have generics but no ports).
    """
    # Find `port (` (case-insensitive, with arbitrary whitespace).
    m = re.search(r"\bport\s*\(", body, re.IGNORECASE)
    if m is None:
        return ""
    open_idx = m.end() - 1  # position of `(`
    depth = 0
    for i in range(open_idx, len(body)):
        ch = body[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return body[open_idx + 1 : i]
    return ""


def _parse_ports(port_block: str) -> list[tuple[str, str]]:
    """Return list of ``(port_name, direction)`` tuples.

    Multi-name declarations (``a, b, c : in std_logic;``) are expanded
    into one tuple per name so the walker sees each port individually.
    Order is the order they appear in the source — deterministic.
    """
    stripped = _LINE_COMMENT_RE.sub("", port_block)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _PORT_DECL_RE.finditer(stripped):
        direction = m.group("dir").lower()
        names_blob = m.group("names")
        for raw in names_blob.split(","):
            name = raw.strip()
            if not name or not re.match(r"^[A-Za-z_]\w*$", name):
                continue
            if name in seen:
                continue
            seen.add(name)
            out.append((name, direction))
    return out


def _split_entities(text: str) -> list[tuple[str, int, str]]:
    """Yield ``(name, header_line, body_text)`` for every entity in `text`.

    Bodies are bounded by the entity's matching ``end NAME;`` /
    ``end entity NAME;`` / ``end;``. Overlap between entities is not
    possible in well-formed VHDL.
    """
    results: list[tuple[str, int, str]] = []
    for m in _ENTITY_RE.finditer(text):
        name = m.group("name")
        start_line = _line_of(text, m.start())
        body_start = m.end()
        # Find the matching end — first `end NAME;` whose name matches,
        # OR the first bare `end;` if no named end exists.
        body: str | None = None
        named_close = re.search(
            r"\bend\b(?:\s+entity)?\s+" + re.escape(name) + r"\s*;",
            text[body_start:],
            re.IGNORECASE,
        )
        if named_close is not None:
            body = text[body_start : body_start + named_close.start()]
        else:
            bare_close = re.search(r"\bend\b(?:\s+entity)?\s*;", text[body_start:], re.IGNORECASE)
            if bare_close is not None:
                body = text[body_start : body_start + bare_close.start()]
        if body is None:
            continue
        results.append((name, start_line, body))
    return results


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find VHDL entities. Deterministic order.

    Each entity becomes one EntryPoint of kind ``FPGA_TOPLEVEL_PORT``,
    carrying the port list in ``metadata['ports']``. Testbench entities
    are tagged with ``metadata['role'] == 'testbench'`` so the walker
    can route them to simulation-time scenarios.
    """
    if "vhdl" not in languages:
        return []
    repo_root = repo_root.resolve()

    sources: list[Path] = []
    for ext in ("*.vhd", "*.vhdl"):
        for p in repo_root.rglob(ext):
            try:
                rel_parts = p.relative_to(repo_root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            if p.is_file():
                sources.append(p)
    sources.sort()
    if not sources:
        return []

    entries: list[EntryPoint] = []
    seen: set[tuple[str, int, str]] = set()

    for path in sources:
        raw = _read(path)
        if not raw:
            continue
        rel = str(path.relative_to(repo_root))
        # Comment stripping happens AFTER `_line_of` calculations so the
        # reported line numbers match the on-disk file.
        for name, header_line, body in _split_entities(raw):
            key = (rel, header_line, name)
            if key in seen:
                continue
            seen.add(key)
            port_block = _extract_port_block(body)
            ports = _parse_ports(port_block)
            is_tb = name.lower().endswith("_tb") or name.lower().endswith("_testbench")
            entries.append(
                EntryPoint(
                    kind=EntryPointKind.FPGA_TOPLEVEL_PORT,
                    file=rel,
                    line=header_line,
                    symbol=name,
                    type_origin="fpga_vhdl",
                    metadata={
                        "entity": name,
                        "ports": [{"name": pn, "direction": pd} for pn, pd in ports],
                        "port_count": len(ports),
                        "role": "testbench" if is_tb else "design",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    entries.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("role", ""))))
    return entries
