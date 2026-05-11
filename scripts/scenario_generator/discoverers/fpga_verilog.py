"""FPGA Verilog / SystemVerilog discoverer.

Finds the top-level Verilog or SystemVerilog module in a hardware design
and emits one EntryPoint per input/output/inout port. Submodule ports
and testbench ports are intentionally NOT emitted: the walker reasons
about FPGA scenarios at the pin boundary (signal integrity, timing
closure, metastability), so only the design's external pins are
interesting entry points.

Design notes
------------

Top-module heuristic
~~~~~~~~~~~~~~~~~~~~

1. Look for an FPGA constraint file (`*.xdc` for Xilinx Vivado,
   `*.lpf` for Lattice Diamond, `*.sdc` for Synopsys/Altera Quartus)
   at the repo root or under `constraints/`.
2. Parse `set_property ... [get_ports {<name>}]` lines (Vivado/SDC) and
   `LOCATE COMP "<name>" SITE ...` lines (LPF) for pin-mapped signal
   names.
3. The module whose port list contains the most of those pin-mapped
   names is the top. Vector-indexed pin names like `data_in[0]` are
   matched against the bare port name `data_in` (the discoverer strips
   `[...]` subscripts on the constraint side).
4. If no constraint file is present, the module with the most ports
   wins. Ties are broken by file path then by module name (deterministic).

Port parsing
~~~~~~~~~~~~

The discoverer handles both port-list styles:

- **ANSI** (Verilog-2001 and later) — direction declared inline in the
  module header:

  ```
  module top (
      input        clk,
      output [7:0] led
  );
  ```

- **Pre-ANSI** (Verilog-1995) — direction declared in the body after
  the bare port-name list:

  ```
  module top (clk, led);
      input        clk;
      output [7:0] led;
  ```

Both forms are reduced to the same `(name, direction, width, line)`
tuple before being emitted.

Width parsing
~~~~~~~~~~~~~

The width field is the bit count, parsed from packed ranges like
`[7:0]`, `[31:0]`, `[N-1:0]`. If the high or low bound is a parameter
(non-numeric), the width is recorded as `-1` so the walker can detect
"parametric width" without confusing it with `0`. Bare ports
(`input clk`) are width `1`.

Skipped paths
~~~~~~~~~~~~~

Vendor IP cores (`ipcore/`, `xilinx_ip/`, `altera_ip/`), generic
libraries (`lib/`), and testbenches (`tb/`) are skipped — those are
either third-party blackbox modules or simulation-only wrappers, never
the design's external pinout.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

CONTENT_PREVIEW_BYTES = 262144  # 256KB — big enough for any realistic top-level module.

_DIRECTION_KEYWORDS: frozenset[str] = frozenset({"input", "output", "inout"})

# Directories that are never scanned. Vendor IP and testbenches do not
# define the FPGA top; lib/ contains shared modules that are instantiated
# but not pinned.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "ipcore",
        "xilinx_ip",
        "altera_ip",
        "lib",
        "tb",
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

# Match a module header up to its terminating `);`. The body is everything
# between the closing `)` of the header and `endmodule`. We capture them
# in two steps because regex alone cannot reliably handle nested parens
# inside parameter lists, so we do header-and-body extraction by hand.
_MODULE_START_RE = re.compile(r"\bmodule\s+(?P<name>\w+)\b", re.MULTILINE)
_ENDMODULE_RE = re.compile(r"\bendmodule\b")

# A single ANSI port declaration inside the header parens.
#
# Captures direction, optional `reg`/`wire`/`logic`, optional packed range,
# and the port identifier. Multiple identifiers on one declaration
# (e.g. `input a, b, c;`) are split on commas by the caller after the
# direction has been resolved.
_ANSI_PORT_RE = re.compile(
    r"\b(?P<dir>input|output|inout)\b"
    r"(?:\s+(?:reg|wire|logic|signed|unsigned))*"
    r"(?:\s*\[\s*(?P<hi>[^\]:]+)\s*:\s*(?P<lo>[^\]:]+)\s*\])?"
    r"\s+(?P<names>[^,;)]+)"
)

# A pre-ANSI port declaration inside the body (between header `);` and
# `endmodule`). Same shape, but each declaration ends with `;` and only
# lives in the body, not the header.
_PREANSI_PORT_RE = re.compile(
    r"^\s*(?P<dir>input|output|inout)\b"
    r"(?:\s+(?:reg|wire|logic|signed|unsigned))*"
    r"(?:\s*\[\s*(?P<hi>[^\]:]+)\s*:\s*(?P<lo>[^\]:]+)\s*\])?"
    r"\s+(?P<names>[^;]+);",
    re.MULTILINE,
)

# Comment stripping. Verilog has // line comments and /* block */ comments;
# stripping is necessary because a stray "input" in a comment would
# otherwise be parsed as a port.
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# Xilinx/Synopsys constraint files: `set_property ... [get_ports {<name>}]`.
# The name may be bare (`clk`) or vector-indexed (`data_in[0]`). We capture
# the bare base name so it lines up with the Verilog port-list identifier.
_GET_PORTS_RE = re.compile(r"\[get_ports\s*\{?\s*(?P<name>[A-Za-z_][\w]*)(?:\[[^\]]+\])?\s*\}?\s*\]")

# Lattice LPF constraint files: `LOCATE COMP "<name>" SITE "<pin>"`. The
# name is quoted; vector indices appear in the name like `"data_in[0]"`.
_LOCATE_COMP_RE = re.compile(r'LOCATE\s+COMP\s+"(?P<name>[A-Za-z_][\w]*)(?:\[[^\]]+\])?"', re.IGNORECASE)


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path` and strip comments.

    Comment stripping is done here because every downstream regex assumes
    its input is comment-free; doing it once at read time is cheaper than
    running negative lookaheads in every port regex.
    """
    try:
        raw = path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""
    # Block comments first — otherwise a `// /* ... */` line-comment-inside-block
    # would be partially stripped twice.
    no_block = _BLOCK_COMMENT_RE.sub("", raw)
    return _LINE_COMMENT_RE.sub("", no_block)


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number for a byte offset, matching the reference discoverer."""
    return text.count("\n", 0, offset) + 1


def _parse_width(hi: str | None, lo: str | None) -> int:
    """Return bit count for a packed range `[hi:lo]`.

    Bare ports (no range) are 1 bit. Parametric ranges (`[N-1:0]`, etc.)
    return `-1` so the walker can detect "parametric width" instead of
    confusing it with a literal zero.
    """
    if hi is None or lo is None:
        return 1
    try:
        hi_i = int(hi.strip())
        lo_i = int(lo.strip())
    except ValueError:
        return -1
    return abs(hi_i - lo_i) + 1


def _split_module(text: str) -> list[tuple[str, int, str, str]]:
    """Cut `text` into (module_name, module_start_line, header, body) tuples.

    `header` is the content between `module name (` and the matching `);`
    that closes the port list. `body` is everything from after `);` to the
    next `endmodule`. This explicit split is what makes ANSI vs pre-ANSI
    handling possible: ANSI ports live in `header`, pre-ANSI live in `body`.
    """
    results: list[tuple[str, int, str, str]] = []
    for m_start in _MODULE_START_RE.finditer(text):
        name = m_start.group("name")
        # Find the opening paren of the port list after `module <name>`.
        open_idx = text.find("(", m_start.end())
        if open_idx == -1:
            continue
        # Match nested parens to find the closing `)`. Parameter lists
        # can also use parens, so a naive `.find(")")` is wrong.
        depth = 0
        close_idx = -1
        for i in range(open_idx, len(text)):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    close_idx = i
                    break
        if close_idx == -1:
            continue
        # If a `#(...)` parameter list comes before the port list, skip past
        # it and find the *real* port-list opening paren.
        after_close = text[close_idx + 1 : close_idx + 32].lstrip()
        if not (after_close.startswith(";") or after_close.startswith("(") or after_close == ""):
            # Look for a second `(` — this would be the port-list paren if
            # the first paren-balanced group was actually `#(...)`. We
            # already consumed the first `(...)`, so search forward.
            pass
        # If the bracket we matched was actually `#(params)`, the next char
        # should be `(` (after optional whitespace) — re-enter the matcher.
        sep = text[close_idx + 1 :]
        sep_lstripped = sep.lstrip()
        if sep_lstripped.startswith("("):
            port_open = close_idx + 1 + (len(sep) - len(sep_lstripped))
            depth = 0
            port_close = -1
            for i in range(port_open, len(text)):
                ch = text[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        port_close = i
                        break
            if port_close == -1:
                continue
            header = text[port_open + 1 : port_close]
            body_start = port_close + 1
        else:
            header = text[open_idx + 1 : close_idx]
            body_start = close_idx + 1
        end_m = _ENDMODULE_RE.search(text, body_start)
        if end_m is None:
            continue
        body = text[body_start : end_m.start()]
        results.append((name, _line_of(text, m_start.start()), header, body))
    return results


def _extract_ports(header: str, body: str, module_text_offset: int, full_text: str) -> list[tuple[str, str, int, int]]:
    """Return a list of `(name, direction, width_bits, line_in_full_text)` for one module.

    ANSI ports come from the header. If the header has no `input`/`output`/
    `inout` keyword, the module is pre-ANSI: parse direction from the body.
    Both styles are normalised into the same tuple shape so the caller
    treats them identically.

    `module_text_offset` and `full_text` are used so that the returned line
    number is relative to the full file, not relative to the slice.
    """
    has_ansi = any(kw in header for kw in _DIRECTION_KEYWORDS)
    ports: list[tuple[str, str, int, int]] = []
    seen: set[str] = set()

    # The header offset inside the full file is the position where the
    # header substring starts; we compute it by anchoring on the leading
    # newline count up to that point.
    header_offset = module_text_offset

    iter_source: tuple[tuple[re.Pattern[str], str, int], ...]
    if has_ansi:
        iter_source = ((_ANSI_PORT_RE, header, header_offset),)
    else:
        # The body sits after the header in the file, so the offset is the
        # header's start offset PLUS the header length PLUS 2 (for `);`).
        body_offset = header_offset + len(header) + 2
        iter_source = ((_PREANSI_PORT_RE, body, body_offset),)

    for regex, slice_text, slice_offset in iter_source:
        for m in regex.finditer(slice_text):
            direction = m.group("dir")
            width = _parse_width(m.group("hi"), m.group("lo"))
            names_blob = m.group("names")
            # `input a, b, c` declares three ports; split on `,` and trim.
            for raw_name in names_blob.split(","):
                # Strip trailing `=` initialisers and any whitespace.
                bare = raw_name.split("=")[0].strip()
                # Strip trailing `[...]` (rare in port-name positions but
                # possible in some SystemVerilog forms with packed arrays).
                bare = re.sub(r"\s*\[.*", "", bare).strip()
                if not bare or not re.match(r"^[A-Za-z_]\w*$", bare):
                    continue
                if bare in seen:
                    # Pre-ANSI: the port name appeared in the header
                    # port-list AND in the body direction declaration.
                    # Skip the duplicate.
                    continue
                seen.add(bare)
                line = _line_of(full_text, slice_offset + m.start())
                ports.append((bare, direction, width, line))
    return ports


def _find_constraint_files(repo_root: Path) -> list[Path]:
    """Find FPGA constraint files at the repo root and under `constraints/`.

    Order: deterministic sort by relative path.
    """
    candidates: list[Path] = []
    for ext in ("*.xdc", "*.lpf", "*.sdc"):
        candidates.extend(repo_root.glob(ext))
        candidates.extend((repo_root / "constraints").glob(ext))
    return sorted(set(candidates))


def _parse_pinned_ports(constraint_file: Path) -> set[str]:
    """Read pin-mapped port names from a constraint file.

    Handles `set_property ... [get_ports {<name>}]` (XDC/SDC) and
    `LOCATE COMP "<name>"` (LPF). Vector indices are stripped on the
    constraint side so `data_in[0]` collapses to `data_in` and lines up
    with the bare port identifier in the Verilog header.
    """
    try:
        text = constraint_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for m in _GET_PORTS_RE.finditer(text):
        names.add(m.group("name"))
    for m in _LOCATE_COMP_RE.finditer(text):
        names.add(m.group("name"))
    return names


def _select_top_module(
    modules: dict[str, tuple[str, int, list[tuple[str, str, int, int]]]],
    pinned: set[str],
) -> str | None:
    """Pick the top-level module from a name -> (file, line, ports) map.

    1. If `pinned` is non-empty, pick the module whose port-name set
       intersects `pinned` the most. Ties broken by file path then by
       module name.
    2. Otherwise pick the module with the most ports. Same tiebreak.
    3. If still ambiguous (e.g. empty repo), return None.
    """
    if not modules:
        return None
    scored: list[tuple[int, str, str]] = []
    for name, (file_rel, _line, ports) in modules.items():
        port_names = {p[0] for p in ports}
        score = len(port_names & pinned) if pinned else len(ports)
        scored.append((score, file_rel, name))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    top_score = scored[0][0]
    if top_score == 0:
        # Nothing matched any pin — fall back to port count.
        scored = sorted(
            ((len(modules[name][2]), modules[name][0], name) for name in modules),
            key=lambda t: (-t[0], t[1], t[2]),
        )
    return scored[0][2]


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find FPGA top-level ports. Deterministic order."""
    if "verilog" not in languages:
        return []
    repo_root = repo_root.resolve()

    # Step 1: enumerate Verilog/SystemVerilog source files, sorted.
    sources: list[Path] = []
    for ext in ("*.v", "*.sv"):
        for p in repo_root.rglob(ext):
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.is_file():
                sources.append(p)
    sources.sort()
    if not sources:
        return []

    # Step 2: parse every module declaration across every source file.
    # The map preserves insertion order (sorted by file then by module
    # position) so the deterministic tiebreak in _select_top_module is
    # honoured.
    modules: OrderedDict[str, tuple[str, int, list[tuple[str, str, int, int]]]] = OrderedDict()
    for path in sources:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for module_name, module_line, header, body in _split_module(text):
            # Compute the header's offset inside the full (comment-stripped)
            # file so port lines are reported against the file, not the slice.
            header_offset = text.find(header)
            if header_offset == -1:
                continue
            ports = _extract_ports(header, body, header_offset, text)
            if module_name in modules:
                # Duplicate module name across files: keep the first to
                # stay deterministic. A real design with two `module top`
                # declarations would already be broken.
                continue
            modules[module_name] = (rel, module_line, ports)

    if not modules:
        return []

    # Step 3: read FPGA constraint files (xdc/lpf/sdc) and collect pin-mapped
    # port names. The first constraint file that yields a non-empty set wins.
    constraint_files = _find_constraint_files(repo_root)
    pinned: set[str] = set()
    constraint_path_rel: str | None = None
    for cf in constraint_files:
        pinned_here = _parse_pinned_ports(cf)
        if pinned_here:
            pinned = pinned_here
            constraint_path_rel = str(cf.relative_to(repo_root))
            break

    # Step 4: pick the top module.
    top_name = _select_top_module(modules, pinned)
    if top_name is None:
        return []
    top_file, _top_line, top_ports = modules[top_name]

    # Step 5: emit one EntryPoint per top-module port.
    entries: list[EntryPoint] = []
    for port_name, direction, width, line in top_ports:
        entries.append(
            EntryPoint(
                kind=EntryPointKind.FPGA_TOPLEVEL_PORT,
                file=top_file,
                line=line,
                symbol=port_name,
                type_origin="fpga_verilog",
                metadata={
                    "port_direction": direction,
                    "port_width_bits": width,
                    "module": top_name,
                    "constraint_file": constraint_path_rel,
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )

    entries.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("port_direction", ""))))
    return entries
