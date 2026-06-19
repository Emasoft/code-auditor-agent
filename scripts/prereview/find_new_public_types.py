#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 16 gate — Find new public types added by a PR diff.

The Type-Design Analyzer agent (`caa-type-design-analyzer-agent`) fires
only when this script reports ≥ 1 hit. The orchestrator runs this
script first, then dispatches the agent only when its output is
non-empty — saving the entire token cost of a sonnet/opus run on
diffs that don't add any public types.

Public types recognised:
- Python   `class` / `dataclass` / `TypedDict` / `Protocol` /
           `NamedTuple` / `Enum` declared at module level whose name
           does NOT start with `_`.
- TypeScript `export interface` / `export type` / `export enum` /
             `export class` (also `export default <kind> Name`).
- Go       `type <Name> struct {` / `type <Name> interface {` where
           `Name` starts with an uppercase letter (Go's export
           convention).
- Rust     `pub struct <Name>` / `pub enum <Name>` / `pub trait <Name>`.

Input is the unified diff. We scan ONLY `+ ` lines (additions) and
require that the line is the type's declaration head — not a body
member, not a comment.

Usage:
    python -m scripts.prereview.find_new_public_types <diff_file> <out_dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class NewType:
    file: str
    line: int  # post-image line in the new file
    kind: str
    name: str
    language: str


# Pattern: each tuple is (language, kind, regex matching the declaration
# head). We anchor on the START of the diff line content (after the `+ `
# prefix has been stripped) to avoid matching `class` inside a comment or
# string. Leading whitespace is tolerated (methods can declare nested
# types but those are intentionally excluded).
# Specific subclasses (TypedDict / Protocol / NamedTuple / Enum) must be
# checked BEFORE the generic `class` pattern — otherwise the generic
# pattern eats `class X(Enum):` as kind="class". The decorator marker
# `@dataclass` is consumed separately, not via the `class` patterns.
_PY_DECL_RE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dataclass", re.compile(r"^@dataclass\b")),
    ("typeddict", re.compile(r"^class\s+(?P<name>[A-Z][\w]*)\s*\([^)]*TypedDict[^)]*\)\s*:")),
    ("protocol", re.compile(r"^class\s+(?P<name>[A-Z][\w]*)\s*\([^)]*Protocol[^)]*\)\s*:")),
    ("namedtuple", re.compile(r"^class\s+(?P<name>[A-Z][\w]*)\s*\([^)]*NamedTuple[^)]*\)\s*:")),
    ("enum", re.compile(r"^class\s+(?P<name>[A-Z][\w]*)\s*\([^)]*(?:Enum|IntEnum|StrEnum|Flag|IntFlag)[^)]*\)\s*:")),
    ("class", re.compile(r"^class\s+(?P<name>[A-Z][\w]*)\s*[(:]")),
)
_TS_DECL_RE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("interface", re.compile(r"^export\s+(?:default\s+)?interface\s+(?P<name>[A-Z][\w]*)\b")),
    ("type", re.compile(r"^export\s+(?:default\s+)?type\s+(?P<name>[A-Z][\w]*)\s*=")),
    ("enum", re.compile(r"^export\s+(?:default\s+)?enum\s+(?P<name>[A-Z][\w]*)\b")),
    ("class", re.compile(r"^export\s+(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>[A-Z][\w]*)\b")),
)
_GO_DECL_RE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("struct", re.compile(r"^type\s+(?P<name>[A-Z][\w]*)\s+struct\s*\{")),
    ("interface", re.compile(r"^type\s+(?P<name>[A-Z][\w]*)\s+interface\s*\{")),
)
_RUST_DECL_RE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("struct", re.compile(r"^pub\s+struct\s+(?P<name>[A-Z][\w]*)\b")),
    ("enum", re.compile(r"^pub\s+enum\s+(?P<name>[A-Z][\w]*)\b")),
    ("trait", re.compile(r"^pub\s+trait\s+(?P<name>[A-Z][\w]*)\b")),
)

_PY_EXT: frozenset[str] = frozenset({".py", ".pyi"})
_TS_EXT: frozenset[str] = frozenset({".ts", ".tsx", ".mts", ".cts"})
_GO_EXT: frozenset[str] = frozenset({".go"})
_RUST_EXT: frozenset[str] = frozenset({".rs"})


def _language_for(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in _PY_EXT:
        return "python"
    if suffix in _TS_EXT:
        return "typescript"
    if suffix in _GO_EXT:
        return "go"
    if suffix in _RUST_EXT:
        return "rust"
    return None


def _parse_diff(diff_text: str) -> list[NewType]:
    """Walk the unified diff. For each `+` line in a recognised-language
    file, try every declaration regex for that language and emit a NewType
    on match.

    Tracks post-image line numbers via the `@@ -a,b +c,d @@` hunk headers.
    """
    out: list[NewType] = []
    current_file: str | None = None
    current_language: str | None = None
    new_line_no = 0  # post-image cursor
    pending_dataclass = False  # True when we just saw `@dataclass` on a `+` line
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            # `+++ b/path/to/file.py` (sometimes with a `\ttimestamp`)
            after = raw[len("+++ ") :].strip().split("\t", 1)[0]
            current_file = after[2:] if after.startswith("b/") else (after if after != "/dev/null" else None)
            current_language = _language_for(current_file) if current_file else None
            new_line_no = 0
            pending_dataclass = False
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("@@ "):
            # `@@ -old_start,old_count +new_start,new_count @@ context`
            m = re.match(r"@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@", raw)
            if m:
                new_line_no = int(m.group("start")) - 1
            pending_dataclass = False
            continue
        if not current_file or current_language is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new_line_no += 1
            content = raw[1:]
            stripped = content.lstrip()
            # Only MODULE-LEVEL declarations are "new public types"; a class/type
            # nested in another class or a function is intentionally excluded
            # (contract). `stripped` erased the indentation that marks a nested
            # decl, so guard on the raw indentation of `content` here.
            if content[:1].isspace():
                pending_dataclass = False
                continue
            # `@dataclass` may appear on the line BEFORE the `class` head.
            # The decorator marker is the first row in `_PY_DECL_RE`.
            if current_language == "python" and _PY_DECL_RE[0][1].match(stripped):
                pending_dataclass = True
                continue
            matched = _match_declaration(current_language, stripped)
            if matched is None:
                pending_dataclass = False
                continue
            kind, name = matched
            if pending_dataclass and kind == "class":
                kind = "dataclass"
            pending_dataclass = False
            out.append(
                NewType(
                    file=current_file,
                    line=new_line_no,
                    kind=kind,
                    name=name,
                    language=current_language,
                )
            )
        elif raw.startswith(" "):
            # Context line — advances the new-image cursor.
            new_line_no += 1
            pending_dataclass = False
        elif raw.startswith("-"):
            # Deletion — does NOT advance the new-image cursor.
            pending_dataclass = False
    return out


def _match_declaration(language: str, stripped: str) -> tuple[str, str] | None:
    if language == "python":
        # Specific subclasses first; plain `class` last.
        for kind, pat in _PY_DECL_RE:
            if kind == "dataclass":
                continue  # decorator marker handled separately
            m = pat.match(stripped)
            if m and "name" in m.groupdict():
                return (kind, m.group("name"))
        return None
    if language == "typescript":
        for kind, pat in _TS_DECL_RE:
            m = pat.match(stripped)
            if m:
                return (kind, m.group("name"))
        return None
    if language == "go":
        for kind, pat in _GO_DECL_RE:
            m = pat.match(stripped)
            if m:
                return (kind, m.group("name"))
        return None
    if language == "rust":
        for kind, pat in _RUST_DECL_RE:
            m = pat.match(stripped)
            if m:
                return (kind, m.group("name"))
        return None
    return None


def _local_timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S%z", time.localtime())


def detect(diff_file: Path) -> dict[str, object]:
    if not diff_file.is_file():
        raise FileNotFoundError(f"diff_file not found: {diff_file}")
    text = diff_file.read_text(encoding="utf-8", errors="ignore")
    types = _parse_diff(text)
    # Deterministic sort.
    types.sort(key=lambda t: (t.file, t.line, t.name))
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "diff_file": str(diff_file.resolve()),
        "total": len(types),
        "types": [asdict(t) for t in types],
    }


def _parse_argv(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 16 gate — find new public types added by a diff.",
        prog="find_new_public_types",
    )
    parser.add_argument("diff_file")
    parser.add_argument("out_dir")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_argv(argv[1:])
    diff_file = Path(args.diff_file).resolve()
    out_dir = Path(args.out_dir).resolve()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"out_dir unwritable: {exc}", file=sys.stderr)
        return 1
    try:
        payload = detect(diff_file)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = out_dir / f"{payload['timestamp']}-new_public_types.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
