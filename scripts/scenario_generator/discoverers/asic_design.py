"""ASIC design discoverer (SystemVerilog/Verilog + SDC/LEF/DEF).

ASIC and FPGA designs share the same HDL frontend (SystemVerilog or
Verilog) but diverge at the backend: ASICs care about timing
constraints (``*.sdc`` — Synopsys Design Constraints) and physical
implementation (``*.lef``, ``*.def``). The ``asic_design`` type is
distinguished from ``fpga_verilog`` by the presence of those backend
files plus the absence of FPGA-vendor constraint files (``*.xdc``,
``*.lpf``).

This discoverer:

1. Walks ``*.sv`` / ``*.v`` files and emits each ``module NAME(...)``
   declaration as a ``FPGA_TOPLEVEL_PORT`` (same kind as
   ``fpga_verilog`` — the walker is type-blind and reads only the
   ``type_origin`` field for ASIC-specific reasoning).
2. Tags testbench modules (``module NAME_tb`` /
   ``module testbench_*``) with ``metadata['role'] == 'testbench'``
   so the walker can route them to simulation-time scenarios.
3. Records the SDC timing-constraint file referenced for clock
   definitions in ``metadata['sdc_file']`` so the walker can
   reason about timing-constraint violations.

Skip-dir check uses ``p.relative_to(repo_root).parts`` (NOT
``p.parts``) so a fixture under ``tests/fixtures/...`` is not
mis-skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `asic_design` and `fpga_verilog` share the same HDL filename pattern;
# the dispatcher loads this module because the canonical filename
# matches the type name. If the filename is ever renamed, add
# ``TYPE_ORIGIN = "asic_design"`` to keep the dispatcher's framework
# scan honest.
TYPE_ORIGIN = "asic_design"

CONTENT_PREVIEW_BYTES = 262144  # 256 KB — same as fpga_verilog.

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "ipcore",
        "vendor_ip",
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

# ``module NAME`` declaration. ASIC SystemVerilog often has parameter
# lists (``#(...)``) before the port list, so we only capture the name
# here; port parsing is intentionally not done — the walker reads the
# constraint file for timing reasoning, not the port list.
_MODULE_RE = re.compile(
    r"\bmodule\s+(?P<name>[A-Za-z_]\w*)\b",
)

# ``create_clock -name <clk> -period <ns> [get_ports <port>]``. The
# walker's timing-constraint family reads this to derive the design's
# clock domain.
_CREATE_CLOCK_RE = re.compile(
    r"\bcreate_clock\b[^\n]*?-name\s+(?P<name>[A-Za-z_]\w*)",
)

# Single-line comments in SystemVerilog / SDC. We strip these to keep
# the simple ``module NAME`` regex from matching a commented-out module.
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _read(path: Path) -> str:
    """Read up to ``CONTENT_PREVIEW_BYTES`` and strip C-style comments.

    SystemVerilog uses both ``//`` and ``/* */`` comments. Stripping
    once at read time keeps the ``module`` regex from picking up a
    commented-out declaration as a real module.
    """
    try:
        raw = path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""
    no_block = _BLOCK_COMMENT_RE.sub("", raw)
    return _LINE_COMMENT_RE.sub("", no_block)


def _read_sdc(path: Path) -> str:
    """Read an SDC file as-is (line comments use ``#``, not ``//``)."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number for a byte offset."""
    return text.count("\n", 0, offset) + 1


def _find_sdc_files(repo_root: Path) -> list[Path]:
    """Find SDC timing-constraint files at the repo root and ``constraints/``.

    Returns a deterministically sorted list. The walker uses the first
    file that defines any ``create_clock`` as the canonical timing
    file; multiple SDC files (per IP / per scenario) are allowed.
    """
    candidates: list[Path] = []
    for p in repo_root.rglob("*.sdc"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if p.is_file():
            candidates.append(p)
    return sorted(set(candidates))


def _parse_clocks(sdc_file: Path) -> list[str]:
    """Return clock names declared via ``create_clock -name <clk>``."""
    text = _read_sdc(sdc_file)
    return sorted({m.group("name") for m in _CREATE_CLOCK_RE.finditer(text)})


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find ASIC module declarations. Deterministic order.

    Each ``module NAME`` becomes one EntryPoint of kind
    ``FPGA_TOPLEVEL_PORT`` (the closest schema match — the walker is
    type-blind and routes via ``type_origin``). Testbench modules are
    tagged with ``metadata['role'] == 'testbench'`` so simulation-time
    scenarios can be expanded without confusing them with
    synthesisable RTL.
    """
    # ASIC fixtures may include either SystemVerilog or Verilog, so we
    # accept both languages. If neither is present the discoverer
    # returns empty — the type-detection registry should have caught
    # this case, but we defend in depth.
    if "verilog" not in languages:
        return []
    repo_root = repo_root.resolve()

    sources: list[Path] = []
    for ext in ("*.sv", "*.v"):
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

    # Read the first SDC file with a `create_clock` definition; use it
    # as the timing-reference for every emitted EntryPoint. Multiple
    # SDC files exist in real designs (per-scenario, per-corner) but
    # the walker only needs ONE canonical reference to expand the
    # timing-constraint-violation family.
    sdc_files = _find_sdc_files(repo_root)
    sdc_ref: str | None = None
    sdc_clocks: list[str] = []
    for sf in sdc_files:
        clocks = _parse_clocks(sf)
        if clocks:
            sdc_ref = str(sf.relative_to(repo_root))
            sdc_clocks = clocks
            break

    entries: list[EntryPoint] = []
    seen: set[tuple[str, int, str]] = set()

    for path in sources:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _MODULE_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            key = (rel, line, name)
            if key in seen:
                continue
            seen.add(key)
            is_tb = name.lower().endswith("_tb") or name.lower().startswith("testbench")
            entries.append(
                EntryPoint(
                    kind=EntryPointKind.FPGA_TOPLEVEL_PORT,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="asic_design",
                    metadata={
                        "module": name,
                        "role": "testbench" if is_tb else "design",
                        "sdc_file": sdc_ref,
                        "sdc_clocks": list(sdc_clocks),
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    entries.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("role", ""))))
    return entries
