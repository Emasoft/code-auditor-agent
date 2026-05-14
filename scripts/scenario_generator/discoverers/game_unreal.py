"""Unreal Engine (C++) game discoverer.

Finds Unreal `UCLASS()`-decorated actor classes and `UFUNCTION()`-
decorated methods across `.h` and `.cpp` files under the project tree.

Recognised shapes (each becomes one EntryPoint):

- `UCLASS(...) class FOO_API <Name> : public AActor`     → BOOT_PATH
  (one entry per `UCLASS()`-decorated class — the actor itself is the
  "entity" entry; downstream lifecycle methods are reported separately)

- `virtual void BeginPlay() override;`                   → BOOT_PATH
  (one-time init when the actor enters play)

- `virtual void Tick(float DeltaTime) override;`         → MAIN_FUNCTION
  (per-frame tick)

- `UFUNCTION(Server, ...) void <Name>(...);`             → IPC_HANDLER
  (server-side RPC entry point)

- `UFUNCTION(Client, ...) / UFUNCTION(NetMulticast, ...)` → IPC_HANDLER
  (client-side / multicast RPC entry point)

- `UFUNCTION(BlueprintCallable, ...) void <Name>(...);`  → EVENT_LISTENER
  (input / blueprint-exposed entry point — often the binding for
  player-driven actions like Jump, Fire, etc.)

The discoverer is regex-based, deterministic, and idempotent. The
walker is type-blind: Unreal-specific context lands in `metadata`
(`category`, `rpc`, `blueprint`, etc.).

type_origin is hard-coded to `"game_unreal"`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `UCLASS(args) class <FOO_API> <Name> : public AActor` — captures the
# class name. Tolerates multi-line UCLASS argument lists by using a
# non-greedy match up to the next `)`.
_UCLASS_RE = re.compile(
    r"^\s*UCLASS\s*\((?P<args>[^)]*)\)\s*\n+"
    r"\s*class\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?(?P<cls>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*public\s+(?P<base>[A-Za-z_][A-Za-z0-9_:]*)",
    re.MULTILINE,
)

# `UFUNCTION(args) ... void <Name>(...)`. The decorator and the method
# declaration may live on consecutive lines. Captures the args (we
# inspect them for "Server", "Client", "BlueprintCallable", etc.) and
# the method name. The return type is fixed to `void` here — Unreal
# RPCs nearly always return void; non-void UFUNCTIONs are blueprint-
# pure helpers we deliberately ignore.
_UFUNCTION_RE = re.compile(
    r"^\s*UFUNCTION\s*\((?P<args>[^)]*)\)\s*\n+"
    r"\s*(?:virtual\s+)?(?:static\s+)?void\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*\((?P<params>[^)]*)\)",
    re.MULTILINE,
)

# `virtual void BeginPlay() override;` and friends. Captured separately
# from UFUNCTION because Unreal lifecycle overrides are NOT decorated
# with UFUNCTION — they are plain virtual overrides.
_LIFECYCLE_RE = re.compile(
    r"^\s*virtual\s+void\s+(?P<name>BeginPlay|Tick|EndPlay|PostInitializeComponents|NotifyActorBeginOverlap|NotifyActorEndOverlap)"
    r"\s*\((?P<params>[^)]*)\)\s*override",
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
        "Binaries",  # Unreal build output
        "Intermediate",  # Unreal generated headers / object files
        "DerivedDataCache",
        "Saved",
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

CONTENT_PREVIEW_BYTES = 131072  # 128KB — Unreal headers can be sizable


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
    """Pull a short doc summary from comments immediately preceding `offset`."""
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


def _classify_ufunction(args: str) -> tuple[EntryPointKind, str]:
    """Map UFUNCTION arguments to (kind, role).

    Server/Client/NetMulticast RPCs are IPC_HANDLER (cross-network entry).
    BlueprintCallable / BlueprintImplementableEvent are EVENT_LISTENER
    (input / Blueprint-exposed entry). Anything else is also
    EVENT_LISTENER — Unreal's UFUNCTION is fundamentally an
    event-dispatch decorator.
    """
    a = args.replace(" ", "")
    if "Server" in a or "Client" in a or "NetMulticast" in a:
        if "Server" in a:
            return (EntryPointKind.IPC_HANDLER, "server")
        if "Client" in a:
            return (EntryPointKind.IPC_HANDLER, "client")
        return (EntryPointKind.IPC_HANDLER, "multicast")
    if "BlueprintCallable" in a:
        return (EntryPointKind.EVENT_LISTENER, "blueprint_callable")
    if "BlueprintImplementableEvent" in a:
        return (EntryPointKind.EVENT_LISTENER, "blueprint_event")
    return (EntryPointKind.EVENT_LISTENER, "ufunction")


def _classify_lifecycle(name: str) -> EntryPointKind:
    """Map Unreal lifecycle override name to EntryPointKind."""
    if name in ("BeginPlay", "PostInitializeComponents"):
        return EntryPointKind.BOOT_PATH
    if name == "Tick":
        return EntryPointKind.MAIN_FUNCTION
    return EntryPointKind.EVENT_LISTENER


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Unreal C++ UCLASS / UFUNCTION / lifecycle entries.

    Runs whenever `cpp` or `c` is present in `languages`; Unreal C++
    headers are `.h` (detected as `c`), and the implementation files
    are `.cpp` (detected as `cpp`).
    """
    if "cpp" not in languages and "c" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    source_files: list[Path] = []
    for ext in (".h", ".hpp", ".cpp", ".cc", ".cxx"):
        for p in repo_root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            try:
                rel_parts = p.relative_to(repo_root).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            source_files.append(p)
    source_files.sort()

    for path in source_files:
        text = _read(path)
        if not text:
            continue
        # Pre-filter — only inspect files with Unreal markers.
        if "UCLASS(" not in text and "UFUNCTION(" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) UCLASS() class declarations
        for m in _UCLASS_RE.finditer(text):
            cls = m.group("cls")
            base = m.group("base")
            args = m.group("args").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=cls,
                    type_origin="game_unreal",
                    metadata={
                        "decorator": "UCLASS",
                        "base": base,
                        "args": args,
                        "framework": "unreal",
                    },
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

        # 2) UFUNCTION() method declarations
        for m in _UFUNCTION_RE.finditer(text):
            name = m.group("name")
            args = m.group("args").strip()
            params = m.group("params").strip()
            kind, role = _classify_ufunction(args)
            line = _line_of(text, m.start())
            metadata: dict[str, str] = {
                "decorator": "UFUNCTION",
                "role": role,
                "args": args,
                "framework": "unreal",
            }
            if params:
                metadata["params"] = params
            found.append(
                EntryPoint(
                    kind=kind,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="game_unreal",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

        # 3) Lifecycle virtual overrides (BeginPlay, Tick, etc.)
        for m in _LIFECYCLE_RE.finditer(text):
            name = m.group("name")
            params = m.group("params").strip()
            kind = _classify_lifecycle(name)
            line = _line_of(text, m.start())
            metadata = {
                "callback": name,
                "framework": "unreal",
                "kind": "lifecycle_override",
            }
            if params:
                metadata["params"] = params
            found.append(
                EntryPoint(
                    kind=kind,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="game_unreal",
                    metadata=metadata,
                    docstring=_comment_before(text, m.start()),
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, kind) — separate UFUNCTION and
    # lifecycle entries at the same line should both be preserved, so
    # `kind` participates in the key.
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
