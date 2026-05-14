"""Safari App Extension discoverer.

Finds entry points for the `browser_ext_safari` software type. Safari
App Extensions live in a hybrid place: a native `SafariExtensionHandler`
subclass (Swift) drives the extension's logic, while content scripts
(JS) inject into pages via the `safari.*` namespace.

Three recognised surfaces:

- `class <Name>: SFSafariExtensionHandler` Swift declaration — the
  principal handler the host instantiates. Each subclass becomes one
  BOOT_PATH EntryPoint; its `messageReceived(...)` / `toolbarItemClicked(...)`
  / `contextMenuItemSelected(...)` overrides each become one
  IPC_HANDLER or UI_EVENT_HANDLER (depending on whether the host is
  feeding the call from script messaging or a user gesture).
- `NSExtensionPrincipalClass` from Info.plist — the class name the
  host loads at extension launch. Emitted as BOOT_PATH so the walker
  can trace the launch sequence even when the Swift class can't be
  parsed (binary-only extensions).
- `safari.self.addEventListener('message', ...)` and
  `safari.extension.dispatchMessage(...)` in content JS — surfaces
  the bridge between the page and the native handler. Each
  addEventListener call is one IPC_HANDLER.

Regex-based heuristic (no AST for Swift / Objective-C / plist in
stdlib); deterministic at every step.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `class <Name>: SFSafariExtensionHandler` — the principal class.
# Modifier prefixes (`public`, `final`, `open`, `internal`) are
# optional. We anchor at start-of-line so we don't pick up a class
# embedded inside another class' body, which Swift doesn't allow at
# the file's principal level anyway.
_HANDLER_CLASS_RE = re.compile(
    r"^\s*(?:public\s+|open\s+|internal\s+|final\s+)?class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"SFSafariExtensionHandler",
    re.MULTILINE,
)

# Method overrides on the handler. The Safari runtime calls these in
# response to specific host events; each is one entry point.
#
# Method-name alternation must NOT include arbitrary identifiers — the
# walker needs to know the semantic name (`messageReceived` is IPC,
# `toolbarItemClicked` is UI) to apply the right family set. Future
# overrides (`messageReceivedFromContainingApp`, etc.) are added by
# extending the alternation.
_HANDLER_METHOD_RE = re.compile(
    r"^\s*override\s+func\s+(?P<method>messageReceived|messageReceivedFromContainingApp|"
    r"toolbarItemClicked|contextMenuItemSelected|popoverWillShow|validateToolbarItem)\b",
    re.MULTILINE,
)

# Methods that surface user/host UI input (gesture-driven) — emitted
# as UI_EVENT_HANDLER. Everything else from _HANDLER_METHOD_RE is
# treated as IPC_HANDLER (message-driven from script or container app).
_UI_METHODS: frozenset[str] = frozenset(
    {
        "toolbarItemClicked",
        "contextMenuItemSelected",
        "popoverWillShow",
        "validateToolbarItem",
    }
)

# `<key>NSExtensionPrincipalClass</key>\n<string>X</string>` — the
# Info.plist entry that names the principal class loaded by the host.
_PRINCIPAL_CLASS_RE = re.compile(
    r"<key>\s*NSExtensionPrincipalClass\s*</key>\s*<string>(?P<value>[^<]+)</string>",
    re.DOTALL,
)

# `safari.self.addEventListener('<name>', ...)` in content JS — each
# call is one message-bridge entry point.
_SAFARI_LISTENER_RE = re.compile(
    r"\bsafari\s*\.\s*self\s*\.\s*addEventListener\s*\(\s*"
    r"(?P<quote>['\"])(?P<event>[^'\"]+)(?P=quote)",
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
        ".cache",
        ".idea",
        ".vscode",
        "DerivedData",
        "Pods",
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


CONTENT_PREVIEW_BYTES = 131072


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dir check against RELATIVE parts only (fixtures live under tests/)."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _strip_swift_comments(text: str) -> str:
    """Blank out Swift `//` and `/* */` comments preserving offsets.

    Same offset-preserving comment stripper as the JS one — Swift uses
    the same comment syntax, so the implementation is identical.
    """
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
            out.append("".join("\n" if ch == "\n" else " " for ch in chunk))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _discover_handler(swift_path: Path, repo_root: Path) -> list[EntryPoint]:
    """Find SFSafariExtensionHandler subclasses and their method overrides."""
    text = _read(swift_path)
    if not text:
        return []
    if "SFSafariExtensionHandler" not in text:
        return []
    rel = str(swift_path.relative_to(repo_root))
    stripped = _strip_swift_comments(text)
    found: list[EntryPoint] = []

    # 1) Principal class declaration — one BOOT_PATH entry per subclass.
    for m in _HANDLER_CLASS_RE.finditer(stripped):
        name = m.group("name")
        line = _line_of(stripped, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.BOOT_PATH,
                file=rel,
                line=line,
                symbol=f"{name}:SFSafariExtensionHandler",
                type_origin="browser_ext_safari",
                metadata={
                    "surface": "extension_handler",
                    "class": name,
                    "parent": "SFSafariExtensionHandler",
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )

    # 2) Method overrides — each one is an entry point the runtime calls.
    for m in _HANDLER_METHOD_RE.finditer(stripped):
        method = m.group("method")
        line = _line_of(stripped, m.start())
        if method in _UI_METHODS:
            kind = EntryPointKind.UI_EVENT_HANDLER
            surface = "ui_event"
        else:
            kind = EntryPointKind.IPC_HANDLER
            surface = "message_bridge"
        found.append(
            EntryPoint(
                kind=kind,
                file=rel,
                line=line,
                symbol=f"SafariExtensionHandler.{method}",
                type_origin="browser_ext_safari",
                metadata={
                    "surface": surface,
                    "method": method,
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )

    return found


def _discover_plist(plist_path: Path, repo_root: Path) -> list[EntryPoint]:
    """Pull NSExtensionPrincipalClass from Info.plist."""
    text = _read(plist_path)
    if not text:
        return []
    if "NSExtensionPrincipalClass" not in text:
        return []
    rel = str(plist_path.relative_to(repo_root))
    found: list[EntryPoint] = []
    for m in _PRINCIPAL_CLASS_RE.finditer(text):
        value = m.group("value").strip()
        if not value:
            continue
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.BOOT_PATH,
                file=rel,
                line=line,
                symbol=f"NSExtensionPrincipalClass:{value}",
                type_origin="browser_ext_safari",
                metadata={
                    "surface": "extension_principal",
                    "principal_class": value,
                },
                docstring="",
                intended_behaviour_sources=(rel,),
            )
        )
    return found


def _discover_safari_js(js_path: Path, repo_root: Path) -> list[EntryPoint]:
    """Pull safari.self.addEventListener calls from content JS."""
    text = _read(js_path)
    if not text:
        return []
    if "safari.self" not in text and "safari.extension" not in text:
        return []
    rel = str(js_path.relative_to(repo_root))
    found: list[EntryPoint] = []
    # Listeners only — dispatchMessage is an OUTBOUND call (page → host),
    # which is interesting evidence but not itself an entry point.
    for m in _SAFARI_LISTENER_RE.finditer(text):
        event = m.group("event")
        line = _line_of(text, m.start())
        found.append(
            EntryPoint(
                kind=EntryPointKind.IPC_HANDLER,
                file=rel,
                line=line,
                symbol=f"safari.self:{event}",
                type_origin="browser_ext_safari",
                metadata={
                    "surface": "content_listener",
                    "event": event,
                    "api": "safari.self.addEventListener",
                },
                docstring="",
                intended_behaviour_sources=(),
            )
        )
    return found


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Safari extension entry points. Deterministic order."""
    del languages
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # 1) Swift handlers.
    swift_paths: list[Path] = []
    for p in repo_root.rglob("*.swift"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        swift_paths.append(p)
    swift_paths.sort()
    for sp in swift_paths:
        found.extend(_discover_handler(sp, repo_root))

    # 2) Info.plist files.
    plist_paths: list[Path] = []
    for p in repo_root.rglob("Info.plist"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        plist_paths.append(p)
    plist_paths.sort()
    for pp in plist_paths:
        found.extend(_discover_plist(pp, repo_root))

    # 3) Content JS files (safari.* namespace).
    js_paths: list[Path] = []
    for p in repo_root.rglob("*.js"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        js_paths.append(p)
    js_paths.sort()
    for jsp in js_paths:
        found.extend(_discover_safari_js(jsp, repo_root))

    # Dedup by (file, line, symbol, kind) and sort.
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
