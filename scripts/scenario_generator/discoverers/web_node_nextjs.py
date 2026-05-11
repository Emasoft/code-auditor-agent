"""Next.js route discoverer (file-based routing).

Mirrors the structure of web_python_fastapi.py: regex-only, deterministic,
no AST. Two routers are supported because Next.js itself supports both:

- Pages router (legacy, but still widely used):
    pages/api/foo.ts          -> HTTP_ROUTE /api/foo
    pages/users.tsx           -> UI_ROUTE   /users
    pages/users/[id].tsx      -> UI_ROUTE   /users/[id]
    pages/index.tsx           -> UI_ROUTE   /

  HTTP methods for API handlers are inferred by scanning the file for
  `req.method === "GET"` / "POST" / etc. branches. If none are found,
  the handler is reported as GET (Next.js default for a handler with no
  explicit method gate).

- App router (Next.js 13+):
    app/api/orders/route.ts   -> HTTP_ROUTE /api/orders, one entry per
                                 exported HTTP verb function (GET, POST,
                                 PUT, DELETE, PATCH, HEAD, OPTIONS).
    app/dashboard/page.tsx    -> UI_ROUTE   /dashboard

  Files like layout.tsx, loading.tsx, error.tsx, not-found.tsx,
  template.tsx, default.tsx are NOT routes themselves and are skipped.

Emits one EntryPoint per (file, route_path, http_method) triple for
HTTP routes, one per file for UI routes. type_origin is always
"web_service_node". Metadata always contains
{"method", "path", "framework": "nextjs", "router": "pages"|"app"}.

Heuristic, not AST-perfect, but deterministic. Path derivation strips
the leading "pages/" or "app/" prefix and the trailing "route.ts(x|js|jsx)"
/ "page.ts(x|js|jsx)" / extension, then joins surviving segments with "/".
The literal segment "index" is collapsed to the empty string, so
`pages/index.tsx` maps to "/" (an empty derived path becomes "/" at the
final step).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Framework-variant dispatch tag. emit_scenarios_json._load_framework_discoverers
# scans every module under discoverers/ and matches it to a detected type
# either by filename prefix (`<type>_<framework>.py`) or by this constant.
# Our filename uses the short `web_node_nextjs` form rather than the full
# `web_service_node_nextjs`, so we rely on the TYPE_ORIGIN attribute to
# associate the discoverer with the `web_service_node` detection.
TYPE_ORIGIN = "web_service_node"

# Method check on req.method, e.g. `if (req.method === "GET")` or
# `if (req.method == 'POST')`. We accept ===/== and either quote style.
_PAGES_API_METHOD_RE = re.compile(
    r"""req\.method\s*={2,3}\s*["'](?P<method>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)["']""",
)

# Exported HTTP verb function in app/.../route.ts:
#   export async function GET(...) { ... }
#   export function POST(req: Request) { ... }
# Matches at start of a line; allows `async` modifier.
_APP_ROUTE_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:async\s+)?function\s+(?P<method>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(",
    re.MULTILINE,
)

# Default export for a Pages-router page component:
#   export default function Foo(...) { ... }
#   export default class Foo extends ... { ... }
#   export default Foo
# We only need the LINE of the symbol, not the symbol shape, so we
# capture a name where it appears.
_DEFAULT_EXPORT_RE = re.compile(
    r"^\s*export\s+default\s+(?:async\s+)?"
    r"(?:function\s+(?P<fn>\w+)?|class\s+(?P<cls>\w+)|(?P<name>\w+))",
    re.MULTILINE,
)

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".next",
        ".turbo",
        ".vercel",
        "node_modules",
        ".pnpm-store",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".env",
        "dist",
        "build",
        "target",
        "out",
        "coverage",
        ".cache",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "__tests__",
        "spec",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
    }
)

# File extensions recognised for Next.js route files.
_ROUTE_EXTS: frozenset[str] = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs"})

# Non-route App-router conventional files. If a file's stem (without
# extension) is one of these, it does NOT define a route on its own.
# Source: Next.js App-router file conventions.
_APP_NON_ROUTE_STEMS: frozenset[str] = frozenset(
    {
        "layout",
        "loading",
        "error",
        "global-error",
        "not-found",
        "template",
        "default",
        "head",
        # Route handlers and pages handled separately below.
    }
)

# Pages-router special files that are not routes.
_PAGES_NON_ROUTE_STEMS: frozenset[str] = frozenset(
    {
        "_app",
        "_document",
        "_error",
        "_middleware",
    }
)

CONTENT_PREVIEW_BYTES = 131072  # 128KB


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True if `path` lies under a skip directory, RELATIVE TO `repo_root`.

    Why relative: a fixture or test corpus may itself live under a
    directory whose name (e.g. `tests/`) happens to appear in
    `_SKIP_DIRS`. Filtering the absolute path's parts would then drop
    every file in the fixture — which is exactly what we don't want.
    Resolving against `repo_root` first means the skip rules only
    apply inside the repo, never outside it.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _has_nextjs_package_json(repo_root: Path) -> bool:
    """Check if any package.json in the repo declares a `next` dependency.

    Cheap substring scan — full JSON parse is unnecessary because the
    detector already enforces this same shape; we just gate the
    discoverer so it returns [] for non-Next.js repos.
    """
    for pkg in sorted(repo_root.rglob("package.json")):
        if _is_skipped(pkg, repo_root):
            continue
        if not pkg.is_file():
            continue
        try:
            text = pkg.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
        except OSError:
            continue
        # Match `"next":` followed by a version string. The regex is
        # forgiving on whitespace so both compact and pretty-printed
        # package.json files match.
        if re.search(r'"next"\s*:\s*"', text):
            return True
    return False


def _strip_route_ext(name: str) -> str:
    """Strip a recognised route file extension from the basename, else ''."""
    for ext in _ROUTE_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return ""


def _segments_to_path(segments: list[str]) -> str:
    """Join derived URL segments. Empty list -> '/' (root)."""
    # Drop the literal 'index' segment everywhere — it collapses to
    # the directory it sits in. Next.js semantics: pages/index.tsx ->
    # '/', pages/users/index.tsx -> '/users'.
    out: list[str] = []
    for s in segments:
        if s == "index":
            continue
        out.append(s)
    if not out:
        return "/"
    return "/" + "/".join(out)


def _route_from_pages_file(rel_parts: tuple[str, ...]) -> str | None:
    """Derive the URL path for a file under `pages/`.

    Returns None if the file is not a route (special files, partials).
    `rel_parts` is the path tuple WITHOUT the leading 'pages' segment.
    """
    if not rel_parts:
        return None
    last = rel_parts[-1]
    stem = _strip_route_ext(last)
    if not stem:
        return None
    # Files whose basename (without extension) starts with '_' are
    # Next.js partials/private and never become routes.
    if stem.startswith("_") or stem in _PAGES_NON_ROUTE_STEMS:
        return None
    segments = list(rel_parts[:-1]) + [stem]
    return _segments_to_path(segments)


def _route_from_app_file(rel_parts: tuple[str, ...]) -> tuple[str, str] | None:
    """Derive (kind, url_path) for a file under `app/`.

    Returns None if the file is not a route file. `kind` is one of
    "page" or "route" — caller decides UI_ROUTE vs HTTP_ROUTE.
    """
    if not rel_parts:
        return None
    last = rel_parts[-1]
    stem = _strip_route_ext(last)
    if not stem:
        return None
    if stem == "page":
        kind = "page"
    elif stem == "route":
        kind = "route"
    else:
        # layout/loading/error/etc. — not a route, even though they
        # live next to one.
        return None
    # Parent-dir segments form the URL path (App-router omits the
    # final filename). Route groups like `(marketing)` and private
    # folders like `_components` are conventions but don't appear in
    # the URL.
    segments: list[str] = []
    for seg in rel_parts[:-1]:
        # Route group: parenthesised segment — does not appear in URL.
        if seg.startswith("(") and seg.endswith(")"):
            continue
        # Private folder: underscore prefix — does not appear in URL.
        if seg.startswith("_"):
            continue
        segments.append(seg)
    return (kind, _segments_to_path(segments))


def _pages_api_methods(text: str) -> list[str]:
    """Return the sorted list of HTTP methods a Pages-router API handler
    explicitly gates on. Empty list when the handler has no method
    check — caller falls back to GET in that case.
    """
    seen: set[str] = set()
    for m in _PAGES_API_METHOD_RE.finditer(text):
        seen.add(m.group("method"))
    return sorted(seen)


def _default_export_line(text: str) -> int:
    """1-indexed line of the file's `export default ...` declaration,
    or 1 if none is found (Pages-router files without a default export
    still register as a route — we point at line 1 deterministically).
    """
    m = _DEFAULT_EXPORT_RE.search(text)
    if m is None:
        return 1
    return _line_of(text, m.start())


def _default_export_symbol(text: str) -> str:
    """Best-effort name of the default-exported component. Falls back
    to 'default' when the export is anonymous (`export default
    function () {}`) or the name can't be pinned down.
    """
    m = _DEFAULT_EXPORT_RE.search(text)
    if m is None:
        return "default"
    return m.group("fn") or m.group("cls") or m.group("name") or "default"


def _candidate_route_files(repo_root: Path) -> list[Path]:
    """All files under any `pages/` or `app/` directory that COULD be a
    route. Sorted, deterministic. Skip dirs and non-route extensions
    are honoured (skip dirs are evaluated RELATIVE TO `repo_root` so a
    fixture path that itself sits under `tests/` is not falsely
    excluded — see `_is_skipped`).
    """
    out: list[Path] = []
    for base in ("pages", "app"):
        for path in sorted(repo_root.rglob(f"{base}/**/*")):
            if _is_skipped(path, repo_root):
                continue
            if not path.is_file():
                continue
            if path.suffix not in _ROUTE_EXTS:
                continue
            # Confirm the candidate genuinely sits under a `pages/` or
            # `app/` directory — rglob with `{base}/**/*` ensures this,
            # but we re-check to defend against odd layouts.
            try:
                parts = path.relative_to(repo_root).parts
            except ValueError:
                continue
            if base not in parts:
                continue
            out.append(path)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Next.js routes. Deterministic order.

    The discoverer only fires when (a) TypeScript or JavaScript is in
    the detected languages and (b) at least one package.json declares
    a `next` dependency. Both gates are needed because the detector
    runs a substring match that can be tricked by an unrelated
    dependency name — gating on both keeps us honest.
    """
    if "typescript" not in languages and "javascript" not in languages:
        return []
    repo_root = repo_root.resolve()
    if not _has_nextjs_package_json(repo_root):
        return []

    found: list[EntryPoint] = []

    for path in _candidate_route_files(repo_root):
        rel = path.relative_to(repo_root)
        parts = rel.parts
        # Identify whether this file sits under pages/ or app/. The
        # first matching segment wins — if a project has both
        # `pages/` and `app/`, each file is classified by its own
        # location, exactly as Next.js itself does.
        try:
            pages_idx = parts.index("pages")
        except ValueError:
            pages_idx = -1
        try:
            app_idx = parts.index("app")
        except ValueError:
            app_idx = -1

        if pages_idx >= 0 and (app_idx < 0 or pages_idx < app_idx):
            router = "pages"
            tail = parts[pages_idx + 1 :]
        elif app_idx >= 0:
            router = "app"
            tail = parts[app_idx + 1 :]
        else:
            continue

        text = _read(path)
        if not text:
            continue
        rel_str = str(rel)

        if router == "pages":
            url_path = _route_from_pages_file(tail)
            if url_path is None:
                continue
            # Files under `pages/api/...` are HTTP routes; everything
            # else is a UI page.
            if tail and tail[0] == "api":
                methods = _pages_api_methods(text) or ["GET"]
                base_symbol = _default_export_symbol(text)
                base_line = _default_export_line(text)
                # When the Pages-router handler explicitly gates on
                # multiple methods, suffix the symbol with the method
                # so each (method, route) becomes its own scenario in
                # the emitter (whose dedup key is file+line+symbol+
                # family, not method). Keep the symbol bare when only
                # one method is involved — that's the common case and
                # the simpler representation reads better.
                disambiguate = len(methods) > 1
                for method in methods:
                    symbol = f"{base_symbol}:{method}" if disambiguate else base_symbol
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.HTTP_ROUTE,
                            file=rel_str,
                            line=base_line,
                            symbol=symbol,
                            type_origin="web_service_node",
                            metadata={
                                "method": method,
                                "path": url_path,
                                "framework": "nextjs",
                                "router": "pages",
                            },
                            docstring="",
                            intended_behaviour_sources=(),
                        )
                    )
            else:
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_ROUTE,
                        file=rel_str,
                        line=_default_export_line(text),
                        symbol=_default_export_symbol(text),
                        type_origin="web_service_node",
                        metadata={
                            "method": "GET",
                            "path": url_path,
                            "framework": "nextjs",
                            "router": "pages",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )
        else:  # router == "app"
            classified = _route_from_app_file(tail)
            if classified is None:
                continue
            kind_str, url_path = classified
            if kind_str == "route":
                # One EntryPoint per exported HTTP verb function.
                hits = list(_APP_ROUTE_EXPORT_RE.finditer(text))
                for m in hits:
                    method = m.group("method")
                    line = _line_of(text, m.start())
                    found.append(
                        EntryPoint(
                            kind=EntryPointKind.HTTP_ROUTE,
                            file=rel_str,
                            line=line,
                            symbol=method,
                            type_origin="web_service_node",
                            metadata={
                                "method": method,
                                "path": url_path,
                                "framework": "nextjs",
                                "router": "app",
                            },
                            docstring="",
                            intended_behaviour_sources=(),
                        )
                    )
            else:  # "page"
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_ROUTE,
                        file=rel_str,
                        line=_default_export_line(text),
                        symbol=_default_export_symbol(text),
                        type_origin="web_service_node",
                        metadata={
                            "method": "GET",
                            "path": url_path,
                            "framework": "nextjs",
                            "router": "app",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by sort_key + method — same file/line/symbol must not appear
    # twice for the same HTTP method (mirrors FastAPI discoverer).
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, str(ep.metadata.get("method", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("method", ""))))
    return unique
