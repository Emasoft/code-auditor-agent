"""Three.js / WebGL scene + animation-frame discoverer.

For the `webgl_three` software type, the discoverer finds:

1. **Scene constructors** — `new THREE.Scene()` and `new Scene()` calls.
   Each is a shader-entry-like setup point (the scene graph that a
   shader will rasterise).

2. **WebGLRenderer constructors** — `new THREE.WebGLRenderer()` and
   `new WebGLRenderer()`. Same family — the renderer owns the GL
   context and the shader compile pipeline.

3. **PerspectiveCamera / OrthographicCamera constructors** —
   `new THREE.PerspectiveCamera(...)` etc. Useful for the auditor to
   see what projection matrix is in play.

4. **Animation-frame callbacks** — `renderer.setAnimationLoop(fn)` and
   `requestAnimationFrame(fn)`. These are GAME_TICK-like — they run on
   every vertical sync.

The closest available `EntryPointKind`s in the schema are
`EVENT_LISTENER` for the constructor sites (a one-shot setup event)
and `UI_EVENT_HANDLER` for the per-frame callbacks (recurring UI
event). The metadata.kind field carries the precise WebGL concept
("scene_construct", "renderer_construct", "camera_construct",
"animation_frame").

Scans .ts / .tsx / .js / .mjs / .cjs / .jsx files. The discoverer is
heuristic (regex) but deterministic — files are sorted, matches are
deduped, output is sorted by (file, line, symbol).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `new THREE.Scene()` or `new Scene()`. The optional `THREE.` namespace
# is captured so we can record it in metadata.
_NEW_SCENE_RE = re.compile(
    r"\bnew\s+(?:THREE\.)?Scene\s*\(",
)

# `new THREE.WebGLRenderer(...)` or `new WebGLRenderer(...)`.
_NEW_RENDERER_RE = re.compile(
    r"\bnew\s+(?:THREE\.)?WebGLRenderer\s*\(",
)

# `new THREE.PerspectiveCamera(...)` / `new THREE.OrthographicCamera(...)`.
_NEW_CAMERA_RE = re.compile(
    r"\bnew\s+(?:THREE\.)?(?P<kind>Perspective|Orthographic)Camera\s*\(",
)

# `<binding>.setAnimationLoop(fnName)` — captures the callback identifier
# directly. Inline arrow functions and anonymous callbacks are NOT
# captured by symbol — we use the binding name as the symbol instead.
_SET_ANIMATION_LOOP_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*\.\s*setAnimationLoop\s*\(\s*"
    r"(?P<arg>[^)]*)\)",
)

# `requestAnimationFrame(fnName)` — top-level call. Same handling: if
# the argument is a bare identifier, use it as the symbol; otherwise
# use "requestAnimationFrame_inline".
_REQUEST_AF_RE = re.compile(
    r"\brequestAnimationFrame\s*\(\s*(?P<arg>[^)]*)\)",
)

# Identify bindings that are likely the WebGLRenderer instance so we
# can confirm a `setAnimationLoop` call is on a renderer (best-effort).
_RENDERER_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"new\s+(?:THREE\.)?WebGLRenderer\s*\(",
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
    """Blank JS/TS comments to spaces (preserving length and newlines).

    Same reason as the Express discoverer: we report line numbers based
    on offsets into the source text; shrinking would drift them. Blanking
    keeps every match's line number correct.
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
            blanked = "".join("\n" if ch == "\n" else " " for ch in chunk)
            out.append(blanked)
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _extract_arg_name(arg: str) -> str:
    """Return the identifier name if `arg` is a bare identifier; else ''.

    Trims whitespace and a possible trailing `,` (defensive — the regex
    already excludes commas, but the arg blob may have a leading
    annotation in TypeScript like `(t: number) => void` which we treat
    as inline).
    """
    s = arg.strip()
    # Reject anything that isn't a plain identifier.
    if not s:
        return ""
    if not re.fullmatch(r"[A-Za-z_$][\w$]*", s):
        return ""
    return s


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Three.js scene constructors and animation-frame callbacks.

    Returns deterministic, deduped list sorted by (file, line, symbol).
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
        # Cheap pre-filter — any of these substrings must appear or skip.
        if (
            "THREE" not in raw
            and "Scene(" not in raw
            and "WebGLRenderer" not in raw
            and "requestAnimationFrame" not in raw
            and "setAnimationLoop" not in raw
        ):
            continue
        rel = str(path.relative_to(repo_root))
        text = _strip_comments(raw)

        # Identify the WebGLRenderer binding name (best-effort; used for
        # metadata on setAnimationLoop calls). Multiple renderers are
        # supported — we collect every binding name.
        renderer_bindings: set[str] = set()
        for m in _RENDERER_DECL_RE.finditer(text):
            renderer_bindings.add(m.group("name"))

        # 1) Scene constructors.
        for m in _NEW_SCENE_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol="Scene",
                    type_origin="webgl_three",
                    metadata={
                        "kind": "scene_construct",
                        "library": "three",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) WebGLRenderer constructors.
        for m in _NEW_RENDERER_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol="WebGLRenderer",
                    type_origin="webgl_three",
                    metadata={
                        "kind": "renderer_construct",
                        "library": "three",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 3) Camera constructors.
        for m in _NEW_CAMERA_RE.finditer(text):
            line = _line_of(text, m.start())
            camera_kind = m.group("kind") + "Camera"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=camera_kind,
                    type_origin="webgl_three",
                    metadata={
                        "kind": "camera_construct",
                        "projection": m.group("kind").lower(),
                        "library": "three",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 4) renderer.setAnimationLoop(fn) — per-frame callback.
        for m in _SET_ANIMATION_LOOP_RE.finditer(text):
            line = _line_of(text, m.start())
            binding = m.group("binding")
            callback_name = _extract_arg_name(m.group("arg"))
            symbol = callback_name or f"{binding}.setAnimationLoop_inline"
            metadata = {
                "kind": "animation_frame",
                "api": "setAnimationLoop",
                "binding": binding,
                "is_renderer": binding in renderer_bindings,
            }
            if callback_name:
                metadata["callback"] = callback_name
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_EVENT_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="webgl_three",
                    metadata=metadata,
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 5) requestAnimationFrame(fn) — raw RAF callback.
        for m in _REQUEST_AF_RE.finditer(text):
            line = _line_of(text, m.start())
            callback_name = _extract_arg_name(m.group("arg"))
            symbol = callback_name or "requestAnimationFrame_inline"
            metadata = {
                "kind": "animation_frame",
                "api": "requestAnimationFrame",
            }
            if callback_name:
                metadata["callback"] = callback_name
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_EVENT_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="webgl_three",
                    metadata=metadata,
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, str(ep.metadata.get("kind", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("kind", ""))))
    return unique
