"""Go HTTP framework route discoverer.

Finds HTTP route registrations across Go source files for the
`web_service_go` software type. Supports the most common Go HTTP
frameworks:

- **net/http**:
    `http.HandleFunc("/path", handler)`
    `mux.HandleFunc("/path", handler)` — any `*http.ServeMux` instance
    `router.HandleFunc(...)` — generic *ServeMux-like binding

- **gin** (`github.com/gin-gonic/gin`):
    `r.GET("/path", handler)`, `r.POST(...)`, etc. on any
    `*gin.Engine` / `*gin.RouterGroup` instance.

- **echo** (`github.com/labstack/echo`):
    `e.GET("/path", handler)`, `e.POST(...)`, etc. on any
    `*echo.Echo` / group instance.

- **fiber** (`github.com/gofiber/fiber`):
    `app.Get("/path", handler)`, `app.Post(...)`, etc. on any
    `*fiber.App` / group instance. Note: Fiber uses Capitalized verb
    method names (Get vs GET).

- **chi** (`github.com/go-chi/chi`):
    `r.Get("/path", handler)`, `r.Post(...)`, etc. on any
    `chi.Router` / `chi.Mux` instance. Same capitalization as Fiber.

Emits one EntryPoint per (file, line, HTTP method, path) tuple.

Heuristic, not AST-perfect, but deterministic. We grep on the route
registration line and read the path from the first quoted string
argument.

Intended-behaviour sources: nearest leading `//` comment block above
the route registration (Go-idiomatic doc comment).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Filename matches the canonical type name, so TYPE_ORIGIN is not strictly
# required for dispatch — but we set it anyway for explicitness and for
# parity with the framework-variant discoverers (web_node_express, etc.).
TYPE_ORIGIN = "web_service_go"


# Match `<binding>.<METHOD>("<path>", ...` for gin / echo style — ALL-CAPS
# verb method names. The binding may be any Go identifier. Path is from
# the first quoted string after the open paren.
_UPPER_VERB_RE = re.compile(
    r"\b(?P<binding>[A-Za-z_][\w]*)\s*"
    r"\.(?P<method>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*"
    r'(?P<quote>["`])(?P<path>[^"`]*)(?P=quote)',
)

# Match `<binding>.<Method>("<path>", ...` for fiber / chi style — Title-Case
# verb method names. Must include backtick support — Go uses backtick-quoted
# raw strings, common in route definitions.
_TITLE_VERB_RE = re.compile(
    r"\b(?P<binding>[A-Za-z_][\w]*)\s*"
    r"\.(?P<method>Get|Post|Put|Delete|Patch|Head|Options)\s*\(\s*"
    r'(?P<quote>["`])(?P<path>[^"`]*)(?P=quote)',
)

# Match `http.HandleFunc("/path", handler)` / `mux.HandleFunc(...)` —
# the net/http stdlib pattern. Method is always inferred as GET because
# the stdlib handler is method-agnostic (handler can branch on
# r.Method internally); the walker treats this conservatively.
_HANDLEFUNC_RE = re.compile(
    r"\b(?P<binding>[A-Za-z_][\w]*)\s*"
    r"\.(?P<fn>HandleFunc|Handle)\s*\(\s*"
    r'(?P<quote>["`])(?P<path>[^"`]*)(?P=quote)',
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "vendor",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "out",
        "bin",
        "target",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "testdata",
        "coverage",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — enough for big route files


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dirs check uses RELATIVE parts so a fixture under
    tests/fixtures/... isn't mis-skipped.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _strip_comments(text: str) -> str:
    """Replace Go comments (`//` and `/* */`) with same-length whitespace
    so character offsets — and therefore line numbers — are preserved.

    Same logic as the JS comment stripper: blanking comments prevents
    documentation examples like `// e.g. r.GET("/foo", h)` from firing
    as false positives, while keeping all line numbers stable so we
    can still extract the original docstring text from the unstripped
    source.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        # Line comment: //... → blank to end of line, keep the \n.
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        # Block comment: /* ... */ → blank but preserve any \n.
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


def _docstring_before(text: str, route_start: int) -> str:
    """First non-empty line of the `//` comment block immediately above the
    route registration, if any. Go's idiomatic doc comment is a contiguous
    run of `//` lines directly preceding the declaration.
    """
    head = text[:route_start]
    # Last 1024 chars are usually enough.
    window = head[-1024:]
    lines = window.splitlines()
    if not lines:
        return ""

    # Walk backwards over the lines preceding the route. If `window` ends
    # in `\n`, every line in `lines` is complete; otherwise `lines[-1]`
    # is the partial line containing the route start and must be skipped.
    collected: list[str] = []
    iter_lines = lines if window.endswith("\n") else lines[:-1]
    for ln in reversed(iter_lines):
        s = ln.strip()
        if s.startswith("//"):
            collected.append(s.lstrip("/").strip())
            continue
        if s == "":
            if collected:
                break
            continue
        break
    if collected:
        for s in reversed(collected):
            if s:
                return s
    return ""


def _detect_framework(text: str) -> str:
    """Best-effort framework label from import statements / package names.

    Falls back to "net/http" when no third-party router is detected.
    Used only for metadata tagging — the walker doesn't depend on it
    being exact.
    """
    if "gin-gonic/gin" in text or '"github.com/gin-gonic/gin"' in text:
        return "gin"
    if "labstack/echo" in text:
        return "echo"
    if "gofiber/fiber" in text:
        return "fiber"
    if "go-chi/chi" in text:
        return "chi"
    if "gorilla/mux" in text:
        return "gorilla_mux"
    return "net/http"


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Go HTTP routes. Deterministic order."""
    if "go" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    go_files: list[Path] = []
    for p in repo_root.rglob("*.go"):
        if _is_skipped(p, repo_root):
            continue
        if p.is_file():
            go_files.append(p)
    go_files.sort()

    for path in go_files:
        text = _read(path)
        if not text:
            continue

        # Cheap pre-filter: file must mention one of the known route APIs.
        if not any(
            sig in text
            for sig in (
                ".GET(",
                ".POST(",
                ".PUT(",
                ".DELETE(",
                ".PATCH(",
                ".HEAD(",
                ".OPTIONS(",
                ".Get(",
                ".Post(",
                ".Put(",
                ".Delete(",
                ".Patch(",
                ".Head(",
                ".Options(",
                "HandleFunc(",
                "Handle(",
            )
        ):
            continue

        rel = str(path.relative_to(repo_root))
        framework = _detect_framework(text)
        stripped = _strip_comments(text)

        # 1) ALL-CAPS verb methods (gin / echo).
        for m in _UPPER_VERB_RE.finditer(stripped):
            method = m.group("method").upper()
            route_path = m.group("path")
            line = _line_of(stripped, m.start())
            binding = m.group("binding")
            docstring = _docstring_before(text, m.start())
            symbol = f"{binding}.{method} {route_path}"
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
                        "framework": framework,
                        "binding": binding,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # 2) Title-Case verb methods (fiber / chi).
        for m in _TITLE_VERB_RE.finditer(stripped):
            method = m.group("method").upper()
            route_path = m.group("path")
            line = _line_of(stripped, m.start())
            binding = m.group("binding")
            docstring = _docstring_before(text, m.start())
            symbol = f"{binding}.{method} {route_path}"
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
                        "framework": framework,
                        "binding": binding,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # 3) net/http style HandleFunc / Handle.
        for m in _HANDLEFUNC_RE.finditer(stripped):
            route_path = m.group("path")
            line = _line_of(stripped, m.start())
            binding = m.group("binding")
            # HandleFunc/Handle is method-agnostic — tag as ANY so the
            # walker knows to expand stimulus over all verbs.
            method = "ANY"
            docstring = _docstring_before(text, m.start())
            symbol = f"{binding}.{m.group('fn')} {route_path}"
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
                        "framework": framework,
                        "binding": binding,
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
