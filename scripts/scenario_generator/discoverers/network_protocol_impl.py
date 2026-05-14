"""Network-protocol-implementation discoverer.

Selective discoverer for the `network_protocol_impl` software type.
Targets the symbols that an idiomatic packet-level protocol stack
exposes as adversarial attack surface:

1. **Encoder / decoder functions** —
   - Python: `def encode_*` / `def decode_*` / `def parse_*_message` /
     `def handle_*_packet` at module scope.
   - Rust: `fn encode_*` / `fn decode_*` / `fn parse_*_message` /
     `fn handle_*_packet`.
   - Go: `func *Encode(...)` / `func *Decode(...)` / `func parsePacket(...)`.
   - C: `<type> <prefix>_encode(...)` / `<type> <prefix>_decode(...)`.
   Each becomes a PROTOCOL_PACKET_HANDLER entry.

2. **Packet-type dispatch tables** — top-level constant arrays /
   structs whose name resembles `*_HANDLERS`, `*_DISPATCH`,
   `PACKET_DECODERS`. The symbol of the table itself is reported as
   one PROTOCOL_PACKET_HANDLER entry (one per table) with
   `metadata.category = "dispatch_table"`.

`type_origin` is hard-coded to `"network_protocol_impl"`. Output is
sorted by (file, line, symbol) with a category tiebreaker.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Regexes. We keep them tight on the function-name shape because protocol
# stacks tend to expose dozens of generic helpers (`fn read(`, `def
# write(`) we do NOT want to claim as protocol entry points. The names
# `encode_*`, `decode_*`, `parse_*_message`, `handle_*_packet`, plus the
# camel-case Go forms, are the load-bearing identifiers.
# ---------------------------------------------------------------------------

# Python encoder/decoder functions at module scope.
_PY_PROTO_FN_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+"
    r"(?P<name>(?:encode|decode)_[A-Za-z0-9_]+|parse_[A-Za-z0-9_]+_message|handle_[A-Za-z0-9_]+_packet)"
    r"\s*\(",
    re.MULTILINE,
)

# Rust encoder/decoder functions.
_RUST_PROTO_FN_RE = re.compile(
    r"^\s*(?:pub\s+(?:\([^)]*\)\s+)?)?(?:async\s+|unsafe\s+|const\s+|extern\s+(?:\"[^\"]+\"\s+)?)*"
    r"fn\s+"
    r"(?P<name>(?:encode|decode)_[A-Za-z0-9_]+|parse_[A-Za-z0-9_]+_message|handle_[A-Za-z0-9_]+_packet)"
    r"\s*\(",
    re.MULTILINE,
)

# Go encoder/decoder functions — both top-level (`func Foo`) and methods
# (`func (r *Receiver) FooEncode`). The receiver group is optional.
_GO_PROTO_FN_RE = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?"
    r"(?P<name>"
    r"[A-Za-z_][A-Za-z0-9_]*(?:Encode|Decode)"
    r"|parsePacket"
    r"|parse[A-Z][A-Za-z0-9_]*Message"
    r"|handle[A-Z][A-Za-z0-9_]*Packet"
    r")\s*\(",
    re.MULTILINE,
)

# C encoder/decoder functions: any of
#   `<type> <prefix>_encode(...)`      (proto-style suffix)
#   `<type> <prefix>_decode(...)`
#   `<type> encode_<name>(...)`        (prefix style)
#   `<type> decode_<name>(...)`
#   `<type> parse_<name>_message(...)`
#   `<type> handle_<name>_packet(...)`
# The function name is the load-bearing identifier.
_C_PROTO_FN_RE = re.compile(
    r"^[A-Za-z_][\*\sA-Za-z0-9_]*?[\s\*]"  # return-type + optional `*` glue
    r"(?P<name>"
    r"[A-Za-z_][A-Za-z0-9_]*_(?:encode|decode)"  # prefix_encode / prefix_decode
    r"|(?:encode|decode)_[A-Za-z0-9_]+"  # encode_x / decode_x
    r"|parse_[A-Za-z0-9_]+_message"  # parse_X_message
    r"|handle_[A-Za-z0-9_]+_packet"  # handle_X_packet
    r")"
    r"\s*\(",
    re.MULTILINE,
)

# Dispatch tables: module-scope identifiers whose name encodes a
# packet-dispatch role, with an `=` / `:` assignment on the same line.
# The leading `\b` anchors on a word boundary so the identifier can
# appear at start-of-line OR after a Go `var`/Rust `let`/etc. qualifier.
_DISPATCH_TABLE_RE = re.compile(
    r"\b(?P<name>"
    r"[A-Za-z_][A-Za-z0-9_]*(?:_HANDLERS|_DISPATCH|_DECODERS)"  # SNAKE_CASE
    r"|[A-Za-z_][A-Za-z0-9_]*(?:PacketHandlers|PacketDispatch|PacketDecoders)"  # CamelSuffix
    r"|PacketHandlers|PacketDispatch|PacketDecoders"  # bare CamelCase
    r")\b\s*[:=]"
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
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "benches",
        "bench",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB


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
    """True if any DIRECTORY component (relative to repo_root) is skipped."""
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


def _scan(
    text: str,
    pattern: re.Pattern[str],
    category: str,
    language: str,
) -> list[tuple[str, int, str]]:
    """Run a function-name pattern over `text`, returning (name, line, category)."""
    out: list[tuple[str, int, str]] = []
    for m in pattern.finditer(text):
        name = m.group("name")
        line = _line_of(text, m.start())
        out.append((name, line, language))
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find protocol encoder/decoder/handler entry points. Deterministic."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # ---- 1. Python encoder/decoder functions ------------------------------
    if "python" in languages:
        for path in _iter_files(repo_root, ("*.py",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for name, line, _ in _scan(text, _PY_PROTO_FN_RE, "handler", "python"):
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PROTOCOL_PACKET_HANDLER,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="network_protocol_impl",
                        metadata={
                            "language": "python",
                            "category": _classify_proto_fn(name),
                        },
                    )
                )

    # ---- 2. Rust encoder/decoder functions --------------------------------
    if "rust" in languages:
        for path in _iter_files(repo_root, ("*.rs",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for name, line, _ in _scan(text, _RUST_PROTO_FN_RE, "handler", "rust"):
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PROTOCOL_PACKET_HANDLER,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="network_protocol_impl",
                        metadata={
                            "language": "rust",
                            "category": _classify_proto_fn(name),
                        },
                    )
                )

    # ---- 3. Go encoder/decoder functions ----------------------------------
    if "go" in languages:
        for path in _iter_files(repo_root, ("*.go",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for name, line, _ in _scan(text, _GO_PROTO_FN_RE, "handler", "go"):
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PROTOCOL_PACKET_HANDLER,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="network_protocol_impl",
                        metadata={
                            "language": "go",
                            "category": _classify_proto_fn(name),
                        },
                    )
                )

    # ---- 4. C encoder/decoder functions -----------------------------------
    if "c" in languages:
        for path in _iter_files(repo_root, ("*.c",)):
            text = _read(path)
            if not text:
                continue
            rel = str(path.relative_to(repo_root))
            for name, line, _ in _scan(text, _C_PROTO_FN_RE, "handler", "c"):
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.PROTOCOL_PACKET_HANDLER,
                        file=rel,
                        line=line,
                        symbol=name,
                        type_origin="network_protocol_impl",
                        metadata={
                            "language": "c",
                            "category": _classify_proto_fn(name),
                        },
                    )
                )

    # ---- 5. Dispatch tables (any language) --------------------------------
    for path in _iter_files(repo_root, ("*.py", "*.rs", "*.go", "*.c", "*.h")):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _DISPATCH_TABLE_RE.finditer(text):
            name = m.group("name")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.PROTOCOL_PACKET_HANDLER,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="network_protocol_impl",
                    metadata={
                        "language": _lang_of(path),
                        "category": "dispatch_table",
                    },
                )
            )

    # Dedup by (file, line, symbol) and sort deterministically.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("category", ""))))
    return unique


def _classify_proto_fn(name: str) -> str:
    """Map a function name to a coarse role for the walker."""
    lname = name.lower()
    if lname.startswith("encode_") or lname.endswith("encode"):
        return "encoder"
    if lname.startswith("decode_") or lname.endswith("decode"):
        return "decoder"
    if "parse" in lname and "message" in lname:
        return "message_parser"
    if "handle" in lname and "packet" in lname:
        return "packet_handler"
    return "handler"


def _lang_of(path: Path) -> str:
    """Map a file extension to a coarse language tag for metadata."""
    return {
        ".py": "python",
        ".rs": "rust",
        ".go": "go",
        ".c": "c",
        ".h": "c",
    }.get(path.suffix.lower(), "unknown")
