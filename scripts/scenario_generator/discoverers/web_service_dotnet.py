"""ASP.NET Core HTTP route discoverer.

Finds HTTP route registrations across C# files for the
`web_service_dotnet` software type. Two idiomatic ASP.NET Core
dialects are covered:

- **Attribute routing** (Controllers/*.cs, MVC + Web API style):
  ``[HttpGet("/foo")]``, ``[HttpPost(...)]``, ``[HttpPut(...)]``,
  ``[HttpDelete(...)]``, ``[HttpPatch(...)]``, ``[HttpHead(...)]``,
  ``[HttpOptions(...)]``. ``[Route("/foo")]`` is also recognised,
  emitting an EntryPoint with ``method=ANY`` (the controller class's
  ``[Route("...")]`` is treated as a path prefix; we record the
  prefix in metadata for the walker).
- **Minimal APIs** (Program.cs style, ASP.NET Core 6+):
  ``app.MapGet("/foo", ...)``, ``app.MapPost(...)``, ``app.MapPut(...)``,
  ``app.MapDelete(...)``, ``app.MapPatch(...)``, ``app.MapMethods(...)``.
  ``app.Map("/foo", ...)`` (any verb) is recognised; the binding name
  is captured so multiple ``WebApplication`` instances are
  distinguishable.

Emits one EntryPoint per (file, line, HTTP method, path) triple.
The ``framework`` field in ``metadata`` flags ``aspnetcore_attr``
vs ``aspnetcore_minimal`` so the walker can apply per-dialect
defaults (e.g. ``[Authorize]`` middleware on attribute routes,
``RequireAuthorization()`` on minimal API endpoints).

Heuristic, not AST-perfect, but deterministic — files are sorted,
regexes iterate in source order, and a final dedup + sort pass
guarantees byte-identical output across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Filename matches the canonical type name, so the dispatcher loads
# this via _load_discoverer first. TYPE_ORIGIN is set for completeness
# and to allow framework-variant modules (e.g. web_service_dotnet_blazor)
# to opt-in to the same type later.
TYPE_ORIGIN = "web_service_dotnet"


# ---- Regex contracts -------------------------------------------------------

# Attribute routing: ``[HttpGet("/foo")]`` and friends. The route path
# is the first quoted string inside the attribute's argument list; it
# is OPTIONAL — ``[HttpGet]`` without a path means the action inherits
# from the controller's ``[Route("...")]`` prefix. When the path is
# absent we emit an EntryPoint with ``path=""`` and rely on the
# controller-prefix capture (below) to assemble the effective path.
_HTTP_ATTR_RE = re.compile(
    r"\[\s*(?P<method>HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch|HttpHead|HttpOptions)"
    r"\s*(?:\(\s*(?P<args>[^\)]*)\))?\s*\]",
)

# Generic ``[Route("/foo")]`` attribute on an action method. Without
# an HTTP-verb attribute, Route() matches any verb; emitted as ANY.
_ROUTE_ATTR_RE = re.compile(
    r"\[\s*Route\s*\(\s*(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)"
    r"(?P<rest>[^\)]*)\)\s*\]",
)

# Pull the first quoted string out of an attribute's argument list.
_FIRST_QUOTED_RE = re.compile(r"['\"](?P<path>[^'\"]*)['\"]")

# Capture the controller-level ``[Route("api/[controller]")]`` prefix.
# We find it via class-declaration proximity: any [Route("...")] within
# 8 lines above a ``public class FooController : ControllerBase`` is
# treated as the controller's route prefix.
_CLASS_DECL_RE = re.compile(
    r"^[ \t]*(?:public|internal|private|protected)?\s*(?:abstract|sealed|static)?\s*"
    r"(?:partial\s+)?class\s+(?P<name>[A-Za-z_]\w*)"
    r"(?:\s*:\s*[\w.,<> \t]+)?",
    re.MULTILINE,
)

# C# method declaration following the attribute block — the symbol.
_CSHARP_METHOD_DEF_RE = re.compile(
    r"^[ \t]*(?:public|internal|private|protected)\s+"
    r"(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+)*"
    r"(?:Task<[^>]+>|Task|ActionResult<[^>]+>|ActionResult|IActionResult|[A-Za-z_]\w*(?:<[^>]+>)?)"
    r"\s+(?P<name>[A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)

# Minimal-API ``app.MapGet("/foo", ...)`` and friends. The binding can
# be any identifier (typically ``app``); we capture it for metadata.
_MINIMAL_MAP_RE = re.compile(
    r"\b(?P<binding>[A-Za-z_]\w*)\s*\.\s*"
    r"(?P<method>MapGet|MapPost|MapPut|MapDelete|MapPatch|MapHead|MapOptions|Map)\s*\(\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)",
)

# Minimal-API ``app.MapMethods("/foo", new[]{ "GET", "POST" }, ...)``.
# The methods array follows the path argument; we parse the quoted
# verb strings out of it.
_MINIMAL_MAP_METHODS_RE = re.compile(
    r"\b(?P<binding>[A-Za-z_]\w*)\s*\.\s*MapMethods\s*\(\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)\s*,\s*"
    r"(?:new\s*(?:string)?\s*\[\s*\]\s*)?[\{\[](?P<methods>[^\}\]]+)[\}\]]",
)


# ---- Skip dirs + file filters ---------------------------------------------

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "bin",
        "obj",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        ".vs",
        ".vscode",
        "publish",
        "dist",
        "build",
        "out",
        "target",
        "packages",
        "TestResults",
        "tests",
        "test",
        "Tests",
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


CONTENT_PREVIEW_BYTES = 131072  # 128 KB — enough for big controller files


def _read(path: Path) -> str:
    """Read the head of `path` as UTF-8 with replacement decoding."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """True if any directory on the way from `repo_root` to `path` is in `_SKIP_DIRS`.

    Skip check uses `relative_to(repo_root).parts` (NOT absolute parts)
    so fixtures under `tests/fixtures/...` aren't mis-skipped.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _parse_methods_array(blob: str) -> list[str]:
    """Pull quoted verbs out of a C# methods array fragment.

    Accepts ``"GET", "POST"`` and ``"GET","POST"`` (whitespace is
    tolerated). Returns upper-cased verbs in source order.
    """
    out: list[str] = []
    for m in _FIRST_QUOTED_RE.finditer(blob):
        s = m.group("path").strip()
        if s:
            out.append(s.upper())
    return out


def _next_method_name(text: str, after: int) -> str:
    """Find the next C# method declaration after `after`.

    Used to attach an attribute-routed verb to its action method.
    Returns "" if no method definition is close enough (within 1024
    chars).
    """
    rest = text[after : after + 1024]
    m = _CSHARP_METHOD_DEF_RE.search(rest)
    if m is None:
        return ""
    return m.group("name")


def _controller_prefix_before(text: str, attr_start: int) -> str:
    """Find the controller-level ``[Route("...")]`` prefix whose
    target class declaration encloses `attr_start`.

    Walk backwards from `attr_start`; if we find a ``class Foo``
    declaration before any other class, look for the most recent
    ``[Route("...")]`` attribute within 8 lines above that class
    declaration. The first quoted string is the prefix.
    """
    head = text[:attr_start]
    # Find the nearest class declaration above us.
    last_class: re.Match[str] | None = None
    for m in _CLASS_DECL_RE.finditer(head):
        last_class = m
    if last_class is None:
        return ""
    # Look for [Route("...")] in the 8 lines above the class declaration.
    class_line_start = head.rfind("\n", 0, last_class.start()) + 1
    # Compute the window: 8 lines above class_line_start.
    window_start = class_line_start
    for _ in range(8):
        prev = head.rfind("\n", 0, window_start - 1)
        if prev == -1:
            window_start = 0
            break
        window_start = prev + 1
    window = head[window_start:class_line_start]
    last_route: re.Match[str] | None = None
    for m in _ROUTE_ATTR_RE.finditer(window):
        last_route = m
    if last_route is None:
        return ""
    return last_route.group("path")


def _extract_xmldoc_above(text: str, offset: int) -> str:
    """Return the first content line of a C# XML doc-comment (``///``)
    block immediately above `offset`, if any. Only ``<summary>`` body
    content is returned; trivial empty summaries yield "".
    """
    head = text[:offset]
    window = head[-1024:]
    # Walk back collecting `///` lines.
    lines = window.splitlines()
    collected: list[str] = []
    # Reverse to walk from `offset` upward.
    for raw in reversed(lines):
        s = raw.strip()
        if s.startswith("///"):
            collected.append(s.lstrip("/").strip())
            continue
        if s == "":
            if collected:
                break
            continue
        # Anything else (attribute, method body, etc.) — stop.
        break
    if not collected:
        return ""
    # Reverse back to source order and pull <summary> content.
    body = "\n".join(reversed(collected))
    summary_match = re.search(r"<summary>\s*(.*?)\s*</summary>", body, re.DOTALL)
    if summary_match:
        first_line = next(
            (ln.strip() for ln in summary_match.group(1).splitlines() if ln.strip()),
            "",
        )
        if first_line:
            return first_line
    # No <summary> tags — take the first non-empty non-tag line.
    for ln in body.splitlines():
        s = ln.strip()
        if s and not s.startswith("<") and not s.endswith(">"):
            return s
    return ""


def _combine_paths(prefix: str, route: str) -> str:
    """Concatenate a controller-level route prefix with an action
    route. Mirrors ASP.NET Core's routing: a leading ``/`` on the
    action makes it absolute, otherwise it appends to the prefix.
    """
    if not prefix and not route:
        return ""
    if route.startswith("/"):
        return route
    p = prefix.rstrip("/")
    r = route.lstrip("/")
    if not p:
        return "/" + r if r else ""
    if not r:
        return "/" + p
    return "/" + p + "/" + r


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find ASP.NET Core HTTP routes. Deterministic order."""
    if "csharp" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    cs_files: list[Path] = []
    for p in repo_root.rglob("*.cs"):
        if _is_skipped(p, repo_root):
            continue
        if p.is_file():
            cs_files.append(p)
    cs_files.sort()

    for path in cs_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter — file must contain at least one route token.
        if not any(
            tok in text
            for tok in (
                "[Http",
                "[Route(",
                ".MapGet(",
                ".MapPost(",
                ".MapPut(",
                ".MapDelete(",
                ".MapPatch(",
                ".MapHead(",
                ".MapOptions(",
                ".MapMethods(",
                ".Map(",
            )
        ):
            continue
        rel = str(path.relative_to(repo_root))

        # ---- 1. Attribute routing: ``[HttpGet("/foo")]`` etc. -------------
        for m in _HTTP_ATTR_RE.finditer(text):
            method = m.group("method")[4:].upper()  # strip "Http" prefix
            args = m.group("args") or ""
            line = _line_of(text, m.start())
            path_match = _FIRST_QUOTED_RE.search(args)
            action_route = path_match.group("path") if path_match else ""
            prefix = _controller_prefix_before(text, m.start())
            effective_path = _combine_paths(prefix, action_route)
            symbol = _next_method_name(text, m.end()) or f"[{m.group('method')}] {effective_path}"
            docstring = _extract_xmldoc_above(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": method,
                        "path": effective_path,
                        "framework": "aspnetcore_attr",
                        "binding": m.group("method"),
                        "controller_prefix": prefix,
                        "action_route": action_route,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- 2. Bare ``[Route("...")]`` on an action (rare but legal) ----
        # Only attach when there is no HttpVerb attribute on the same
        # method — otherwise the verb attribute already covered it and
        # the Route is redundant. We detect "same method" by checking
        # whether _next_method_name(after Route) equals
        # _next_method_name(after the nearest preceding Http*).
        for m in _ROUTE_ATTR_RE.finditer(text):
            line = _line_of(text, m.start())
            action_route = m.group("path")
            # If there's a verb attribute within the next 6 lines, skip;
            # the verb attribute's emission has already covered this method.
            tail = text[m.end() : m.end() + 600]
            if _HTTP_ATTR_RE.search(tail):
                continue
            # Skip when this Route is on a class declaration (no verb
            # attribute, no immediate method — would be a controller prefix).
            method_match = _CSHARP_METHOD_DEF_RE.search(tail)
            class_match = _CLASS_DECL_RE.search(tail)
            if class_match is not None and (method_match is None or class_match.start() < method_match.start()):
                continue
            prefix = _controller_prefix_before(text, m.start())
            effective_path = _combine_paths(prefix, action_route)
            symbol = _next_method_name(text, m.end()) or f"[Route] {effective_path}"
            docstring = _extract_xmldoc_above(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": "ANY",
                        "path": effective_path,
                        "framework": "aspnetcore_attr",
                        "binding": "Route",
                        "controller_prefix": prefix,
                        "action_route": action_route,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- 3. Minimal API: ``app.MapGet("/foo", ...)`` ------------------
        # We exclude MapMethods here — it's handled by its own regex
        # below so we can split the verbs array.
        for m in _MINIMAL_MAP_RE.finditer(text):
            binding = m.group("binding")
            verb_token = m.group("method")
            route_path = m.group("path")
            line = _line_of(text, m.start())
            method = "ANY" if verb_token == "Map" else verb_token[3:].upper()
            symbol = f"{binding}.{verb_token} {route_path}"
            docstring = _extract_xmldoc_above(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": method,
                        "path": route_path,
                        "framework": "aspnetcore_minimal",
                        "binding": binding,
                        "map_call": verb_token,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- 4. Minimal API: ``app.MapMethods("/foo", new[]{...}, ...)`` --
        for m in _MINIMAL_MAP_METHODS_RE.finditer(text):
            binding = m.group("binding")
            route_path = m.group("path")
            verbs = _parse_methods_array(m.group("methods"))
            line = _line_of(text, m.start())
            docstring = _extract_xmldoc_above(text, m.start())
            for method in verbs:
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=f"{binding}.MapMethods:{method}:{route_path}",
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "method": method,
                            "path": route_path,
                            "framework": "aspnetcore_minimal",
                            "binding": binding,
                            "map_call": "MapMethods",
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by (file, line, symbol, method).
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
