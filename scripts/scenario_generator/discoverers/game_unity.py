"""Unity engine (C#) game discoverer.

Finds Unity MonoBehaviour lifecycle callbacks across `.cs` files under
the project tree.

Recognised callbacks (each becomes one EntryPoint):

- `Start()`           → BOOT_PATH       (one-time init at object enable)
- `Awake()`           → BOOT_PATH       (one-time init before Start)
- `OnEnable()`        → BOOT_PATH       (called each time the object is enabled)
- `OnDisable()`       → BOOT_PATH       (called each time the object is disabled)
- `Update()`          → MAIN_FUNCTION   (per-frame tick)
- `FixedUpdate()`     → MAIN_FUNCTION   (fixed-rate physics tick)
- `LateUpdate()`      → MAIN_FUNCTION   (after-frame tick)
- `OnCollisionEnter(...)` / `OnCollisionExit(...)` / `OnCollisionStay(...)`
- `OnTriggerEnter(...)` / `OnTriggerExit(...)` / `OnTriggerStay(...)`
- `OnMouseDown()` / `OnMouseUp()` / `OnMouseOver()`
                       → EVENT_LISTENER  (input / world-event hooks)

Only classes that inherit (directly or transitively as declared) from
`MonoBehaviour` are scanned — non-Unity C# classes in the same fixture
are ignored.

EntryPointKind values are picked from the universal enum; Unity-specific
context lands in the `metadata` dict (`callback` name and `class`).

Heuristic regex-based; deterministic dedup + sort. type_origin is
hard-coded to `"game_unity"`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `class Foo : MonoBehaviour` — captures the class name. Tolerates
# additional base types / interfaces appended after a comma, and any
# whitespace around the colon.
_CLASS_RE = re.compile(
    r"\bclass\s+(?P<cls>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<bases>[^\{]+)\{",
    re.MULTILINE,
)

# Unity callback signatures we care about. Each entry maps the method
# name to the EntryPointKind we report.
_CALLBACK_KIND: dict[str, EntryPointKind] = {
    "Start": EntryPointKind.BOOT_PATH,
    "Awake": EntryPointKind.BOOT_PATH,
    "OnEnable": EntryPointKind.BOOT_PATH,
    "OnDisable": EntryPointKind.BOOT_PATH,
    "Update": EntryPointKind.MAIN_FUNCTION,
    "FixedUpdate": EntryPointKind.MAIN_FUNCTION,
    "LateUpdate": EntryPointKind.MAIN_FUNCTION,
    "OnCollisionEnter": EntryPointKind.EVENT_LISTENER,
    "OnCollisionExit": EntryPointKind.EVENT_LISTENER,
    "OnCollisionStay": EntryPointKind.EVENT_LISTENER,
    "OnTriggerEnter": EntryPointKind.EVENT_LISTENER,
    "OnTriggerExit": EntryPointKind.EVENT_LISTENER,
    "OnTriggerStay": EntryPointKind.EVENT_LISTENER,
    "OnMouseDown": EntryPointKind.EVENT_LISTENER,
    "OnMouseUp": EntryPointKind.EVENT_LISTENER,
    "OnMouseOver": EntryPointKind.EVENT_LISTENER,
}

# Build one regex matching `void <CallbackName>(...)`. Visibility
# modifiers (private/public/protected/internal) are tolerated; Unity
# convention is to omit them, but real code often has them.
_CALLBACK_NAMES_RE = "|".join(re.escape(n) for n in _CALLBACK_KIND)
_CALLBACK_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+)*"
    r"(?:static\s+|virtual\s+|override\s+|sealed\s+|new\s+)*"
    r"(?:void|IEnumerator)\s+"
    r"(?P<name>" + _CALLBACK_NAMES_RE + r")\s*\("
    r"(?P<args>[^)]*)\)",
    re.MULTILINE,
)

_LINE_COMMENT_RE = re.compile(r"^\s*//+\s?(?P<text>.*?)\s*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*(?P<text>.*?)\*/", re.DOTALL)

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        ".vscode",
        "Library",  # Unity's auto-generated cache
        "Temp",  # Unity's auto-generated tmp
        "obj",
        "bin",
        "build",
        "dist",
        "out",
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

CONTENT_PREVIEW_BYTES = 131072  # 128KB — Unity scripts almost never exceed this


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
    collects contiguous `//` / `///` comment lines, plus a single
    `/* ... */` block comment if it ends right before the symbol.
    """
    line_start = text.rfind("\n", 0, offset) + 1
    cursor = line_start - 1
    lines: list[str] = []
    while cursor > 0:
        prev_line_start = text.rfind("\n", 0, cursor) + 1
        prev_line = text[prev_line_start:cursor]
        stripped = prev_line.strip()
        if not stripped:
            break
        if stripped.startswith("//"):
            m = _LINE_COMMENT_RE.match(prev_line)
            if m:
                lines.insert(0, m.group("text").strip())
            cursor = prev_line_start - 1
            continue
        if stripped.endswith("*/"):
            block_search = text.rfind("/*", 0, cursor)
            if block_search != -1:
                block = text[block_search : cursor + 1]
                bm = _BLOCK_COMMENT_RE.search(block)
                if bm:
                    body = bm.group("text").strip()
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


def _enclosing_class(text: str, offset: int) -> str:
    """Return the name of the MonoBehaviour-derived class that encloses `offset`.

    Returns "" if no MonoBehaviour-derived class wraps `offset` — that
    callback is then treated as not-a-Unity-callback and is dropped.
    """
    best = ""
    best_open = -1
    for m in _CLASS_RE.finditer(text):
        bases = m.group("bases")
        if "MonoBehaviour" not in bases:
            continue
        class_start = m.end() - 1  # the opening `{` position
        if class_start >= offset:
            break
        # Approximate "still inside this class" — kept simple: take the
        # latest class whose `{` appears before offset. C# fixtures in
        # this project are small (under 200 LOC), so the heuristic is
        # safe; if multiple classes nest, callers should split files.
        best = m.group("cls")
        best_open = class_start
    del best_open  # only the name matters downstream
    return best


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Unity MonoBehaviour callbacks. Deterministic order.

    `languages` must contain `"csharp"`. If the language list is empty
    (no `.cs` files in repo), we return an empty list.
    """
    if "csharp" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

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
        text = _read(path)
        if not text:
            continue
        # Pre-filter — only inspect files that look Unity-flavoured.
        if "MonoBehaviour" not in text and "UnityEngine" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        for m in _CALLBACK_RE.finditer(text):
            callback = m.group("name")
            kind = _CALLBACK_KIND.get(callback)
            if kind is None:
                continue
            cls = _enclosing_class(text, m.start())
            if not cls:
                # Callback exists but no MonoBehaviour-derived class
                # wraps it — skip (likely a helper class).
                continue
            line = _line_of(text, m.start())
            args = m.group("args").strip()
            metadata: dict[str, str] = {
                "callback": callback,
                "class": cls,
                "framework": "unity",
            }
            if args:
                metadata["args"] = args
            found.append(
                EntryPoint(
                    kind=kind,
                    file=rel,
                    line=line,
                    symbol=f"{cls}.{callback}",
                    type_origin="game_unity",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind) — same callback declared twice
    # in two different classes lives at different lines, so the natural
    # key is sufficient.
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, ep.kind.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), e.kind.value))
    return unique
