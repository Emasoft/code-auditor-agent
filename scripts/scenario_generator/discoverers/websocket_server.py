"""WebSocket connection / message handler discoverer.

For the `websocket_server` software type, the discoverer finds handler
registrations for incoming WebSocket connections and messages across
the three common patterns:

1. **Plain ws (Node.js)** —
   `new WebSocketServer({...})` followed by `wss.on('connection', cb)`,
   and inside that callback `socket.on('message', cb)`, `'close'`,
   `'error'`, etc.

2. **Socket.io** —
   `new Server(port)` followed by `io.on('connection', cb)`, and
   inside that callback `socket.on('<custom-event>', cb)`.

3. **Raw WebSocket** —
   client-side `new WebSocket(url)` instances with `onmessage` / `onopen`
   handlers, plus `addEventListener('message', cb)` style.

Each `.on('<event>', handler)` call is one EntryPoint with kind
`WS_MESSAGE_HANDLER` and metadata.event carrying the event name.

The closest available `EntryPointKind` is `WS_MESSAGE_HANDLER`; the
schema already provides this category.

Scans .ts / .tsx / .js / .mjs / .cjs / .jsx files. Heuristic but
deterministic — files sorted, matches sorted, output deduped.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `<binding>.on('<event>', ...)` — the universal WebSocket handler
# registration shape used by `ws`, `socket.io`, and most other libraries.
# Single- or double-quoted event names; we anchor on `.on(` to avoid
# matching `.once(`, `.off(`, etc.
_ON_HANDLER_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*on\s*\(\s*"
    r"(?P<quote>['\"])(?P<event>[^'\"]+)(?P=quote)\s*,",
)

# `<binding>.addEventListener('<event>', ...)` — the DOM-style alias used
# on raw WebSocket instances client-side.
_ADD_LISTENER_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*addEventListener\s*\(\s*"
    r"(?P<quote>['\"])(?P<event>[^'\"]+)(?P=quote)\s*,",
)

# `<binding>.onmessage = <handler>` — the property-assignment style on
# raw WebSocket instances. Other shapes: `onopen`, `onclose`, `onerror`.
_PROP_HANDLER_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*"
    r"on(?P<event>message|open|close|error)\s*=",
)

# Declarations we recognise to label the binding context: `ws`,
# `socket.io`, or `raw WebSocket`. Captures the binding NAME so the
# corresponding handler registrations can be tagged in metadata.
_WSS_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"new\s+WebSocketServer\s*\(",
)
_IO_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"new\s+(?:[A-Za-z_$][\w$.]*\.)?Server\s*\(",
)
_RAW_WS_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"new\s+WebSocket\s*\(",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".pnpm-store",
        ".yarn",
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".cache",
        ".turbo",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "__tests__",
        "spec",
        "coverage",
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


_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


CONTENT_PREVIEW_BYTES = 131072  # 128KB


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True iff any directory under repo_root on the way to path is skipped."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _strip_comments(text: str) -> str:
    """Blank JS/TS comments to spaces (preserving length and newlines)."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                j = n
            else:
                j += 2
            chunk = text[i:j]
            blanked = "".join("\n" if ch == "\n" else " " for ch in chunk)
            out.append(blanked)
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find WebSocket message/event handler registrations.

    Returns deterministic, deduped list sorted by (file, line, symbol,
    event).
    """
    if "javascript" not in languages and "typescript" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    js_files: list[Path] = []
    for ext in _EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if _is_skipped(p, repo_root):
                continue
            if p.is_file():
                js_files.append(p)
    js_files.sort()

    for path in js_files:
        raw = _read(path)
        if not raw:
            continue
        # Cheap pre-filter — file must mention at least one WS construct.
        if not any(
            kw in raw
            for kw in (
                "WebSocketServer",
                "socket.io",
                "WebSocket",
                "ws.on",
                "wss.on",
                "io.on",
                "onmessage",
                "addEventListener",
            )
        ):
            continue
        rel = str(path.relative_to(repo_root))
        text = _strip_comments(raw)

        # Identify the role of each binding: WebSocketServer instance,
        # socket.io Server instance, raw WebSocket instance. This lets
        # us tag handlers in metadata with their connection style.
        binding_role: dict[str, str] = {}
        for m in _WSS_DECL_RE.finditer(text):
            binding_role[m.group("name")] = "ws_server"
        for m in _IO_DECL_RE.finditer(text):
            # Don't overwrite a prior ws_server label — Server is too
            # generic and may match unrelated classes. The previous
            # match is more specific.
            binding_role.setdefault(m.group("name"), "socket_io_server")
        for m in _RAW_WS_DECL_RE.finditer(text):
            binding_role.setdefault(m.group("name"), "raw_websocket")

        # 1) `.on('<event>', cb)` registrations.
        for m in _ON_HANDLER_RE.finditer(text):
            line = _line_of(text, m.start())
            binding = m.group("binding")
            event = m.group("event")
            role = binding_role.get(binding, "unknown")
            symbol = f"{binding}.on:{event}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.WS_MESSAGE_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="websocket_server",
                    metadata={
                        "event": event,
                        "binding": binding,
                        "role": role,
                        "api": "on",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) `.addEventListener('<event>', cb)` registrations.
        for m in _ADD_LISTENER_RE.finditer(text):
            line = _line_of(text, m.start())
            binding = m.group("binding")
            event = m.group("event")
            role = binding_role.get(binding, "unknown")
            symbol = f"{binding}.addEventListener:{event}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.WS_MESSAGE_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="websocket_server",
                    metadata={
                        "event": event,
                        "binding": binding,
                        "role": role,
                        "api": "addEventListener",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 3) `.onmessage = cb` / `.onopen = ...` etc. property-assign.
        for m in _PROP_HANDLER_RE.finditer(text):
            line = _line_of(text, m.start())
            binding = m.group("binding")
            event = m.group("event")
            role = binding_role.get(binding, "unknown")
            symbol = f"{binding}.on{event}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.WS_MESSAGE_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="websocket_server",
                    metadata={
                        "event": event,
                        "binding": binding,
                        "role": role,
                        "api": "property_assign",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, str(ep.metadata.get("event", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("event", ""))))
    return unique
