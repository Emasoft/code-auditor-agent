"""Ruby HTTP framework route discoverer.

Finds HTTP route registrations across Ruby source files for the
`web_service_ruby` software type. Supports the most common Ruby web
frameworks:

- **Rails** (`config/routes.rb`): the Rails routing DSL inside a
  `Rails.application.routes.draw do ... end` block.
    `get "/path", to: "controller#action"`
    `post "/path", to: "..."` (and put/delete/patch/match)
    `resources :users` — RESTful collection (emitted once per resource;
      walker can expand to the 7 RESTful actions if desired).
    `resource :session` — singular RESTful resource.

- **Sinatra / Roda / Rack-style** (`app.rb`, `config.ru`, etc.):
    `get "/path" do ... end`
    `post "/path" do ... end` (and put/delete/patch/head/options)
  These are top-level DSL calls (not inside a `draw do` block).

Emits one EntryPoint per (file, line, HTTP method, path) tuple.

Heuristic, not AST-perfect, but deterministic. We grep on the route
DSL line; for Rails-style `get "/path", to: "..."` the "to:" target
is captured as the symbol when present (otherwise the route path
itself is used).

Intended-behaviour sources: nearest leading `#` comment block above
the route registration (Ruby-idiomatic doc comment).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Filename matches the canonical type name, so TYPE_ORIGIN is technically
# optional for dispatch — but we set it for explicitness.
TYPE_ORIGIN = "web_service_ruby"


# Rails routes DSL: `get "/path", to: "controller#action"` — the `to:`
# target is captured when present so the walker can name the action.
# Also matches Sinatra-style `get "/path" do` because the path/method
# extraction is identical.
_VERB_ROUTE_RE = re.compile(
    r"^\s*(?P<method>get|post|put|delete|patch|head|options|match)\s+"
    r'(?P<quote>["\'])(?P<path>/[^"\']*)(?P=quote)'
    r"(?P<rest>[^\n]*)",
    re.MULTILINE,
)

# Capture the `to: "controller#action"` argument from the route line.
_TO_TARGET_RE = re.compile(r"""to:\s*["'](?P<target>[^"']+)["']""")

# Rails resources:  resources :users  /  resource :session
# We capture the resource name and emit ONE EntryPoint per `resources`
# declaration (line number = the declaration's line). The walker can
# choose to expand a `resources :users` into the 7 RESTful actions if
# the family requires per-method scenarios; v1 emits the collection
# directive itself.
_RESOURCES_RE = re.compile(
    r"^\s*(?P<kind>resources|resource)\s+:(?P<name>[A-Za-z_][\w]*)",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bundle",
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
        "tmp",
        "log",
        "public",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "spec",
        "coverage",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
    }
)


# Files we scan for Ruby route definitions. config.ru is a Rack rackup
# file (frequently Sinatra entry points). Order is fixed.
_EXTENSIONS: tuple[str, ...] = (".rb", ".ru")


CONTENT_PREVIEW_BYTES = 131072


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
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
    """Replace Ruby comments (`# ...`) with same-length whitespace so
    character offsets — and therefore line numbers — are preserved.

    Ruby has no block comments in normal usage (the `=begin/=end`
    multiline form is rare and we deliberately don't handle it in v1).
    Same approach as the JS/Go strippers: prevents documentation
    examples from firing as false positives while keeping line numbers
    stable for the docstring extractor to still find the original text.

    Note: this is NOT a real lexer. A `#` inside a string literal will
    be over-eagerly blanked. For route DSL files this is acceptable
    because route paths don't typically contain literal `#` (Rails
    uses `#` as the controller/action separator, but that lives in
    the `to:` argument which we extract from the *original* text).
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "#":
            j = text.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _docstring_before(text: str, route_start: int) -> str:
    """First non-empty line of the `#` comment block immediately above the
    route registration, if any. Ruby's idiomatic doc comment is a
    contiguous run of `#` lines directly preceding the declaration.
    """
    head = text[:route_start]
    window = head[-1024:]
    lines = window.splitlines()
    if not lines:
        return ""

    collected: list[str] = []
    # Walk backwards over the lines preceding the route. If `window` ends
    # in `\n`, every line in `lines` is complete and is fair game; if not,
    # `lines[-1]` is the partial line containing the route start and must
    # be excluded. (splitlines() does NOT emit a trailing empty string
    # for a trailing newline, so a window ending in `\n` already has its
    # last comment line as the final element of `lines`.)
    iter_lines = lines if window.endswith("\n") else lines[:-1]
    for ln in reversed(iter_lines):
        s = ln.strip()
        if s.startswith("#"):
            collected.append(s.lstrip("#").strip())
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


def _detect_framework(text: str, rel: str) -> str:
    """Best-effort framework label.

    `config/routes.rb` → Rails. `app.rb` / files importing sinatra →
    Sinatra. Otherwise default to "rack".
    """
    # Path-based hint first — Rails projects have a canonical routes file.
    if rel.endswith("config/routes.rb") or rel.endswith("config\\routes.rb"):
        return "rails"
    lower = text.lower()
    if "rails.application.routes.draw" in lower:
        return "rails"
    if "require 'sinatra'" in lower or 'require "sinatra"' in lower:
        return "sinatra"
    if "sinatra::base" in lower:
        return "sinatra"
    if "roda" in lower and ("class " in lower and "< roda" in lower):
        return "roda"
    return "rack"


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Ruby HTTP routes. Deterministic order."""
    if "ruby" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    rb_files: list[Path] = []
    for ext in _EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if _is_skipped(p, repo_root):
                continue
            if p.is_file():
                rb_files.append(p)
    rb_files.sort()

    for path in rb_files:
        text = _read(path)
        if not text:
            continue

        # Cheap pre-filter: file must contain at least one route-like token.
        lower_preview = text.lower()
        if not any(
            tok in lower_preview
            for tok in (
                "get ",
                "post ",
                "put ",
                "delete ",
                "patch ",
                "head ",
                "options ",
                "match ",
                "resources ",
                "resource ",
            )
        ):
            continue

        rel = str(path.relative_to(repo_root))
        framework = _detect_framework(text, rel)
        stripped = _strip_comments(text)

        # 1) HTTP-verb-prefixed route declarations.
        for m in _VERB_ROUTE_RE.finditer(stripped):
            method = m.group("method").upper()
            route_path = m.group("path")
            # Anchor line number to the VERB token (`m.start('method')`),
            # not `m.start()`. The `^\s*` prefix can absorb a preceding
            # blanked-out comment line (the stripped copy of a `# ...`
            # line is all whitespace and the `^` re-anchors after that
            # line's newline), which would otherwise put `m.start()` on
            # the comment line and skew the reported line number by one.
            verb_start = m.start("method")
            line = _line_of(stripped, verb_start)
            # Extract Rails-style `to: "controller#action"` if present —
            # use that as a more meaningful symbol than the raw path.
            # Read the `rest` portion from the ORIGINAL text (not the
            # comment-stripped copy) because Rails uses `#` as the
            # controller/action separator inside the `to:` argument
            # ("widgets#index"), which our naive comment stripper would
            # blank out. Pluck the verb's actual source line by offset.
            line_start = text.rfind("\n", 0, verb_start) + 1
            line_end = text.find("\n", verb_start)
            if line_end == -1:
                line_end = len(text)
            rest = text[line_start:line_end]
            to_match = _TO_TARGET_RE.search(rest)
            target = to_match.group("target") if to_match else ""
            symbol = f"{method} {route_path}"
            if target:
                symbol = f"{symbol} -> {target}"
            # Use the original-text line start as the docstring anchor —
            # `m.start()` may sit on the previous comment line in the
            # stripped copy, which would then include that comment in
            # the walked window. The verb's actual line start is the
            # clean upper boundary for "what's above the route".
            docstring = _docstring_before(text, line_start)
            metadata: dict[str, str] = {
                "method": method,
                "path": route_path,
                "framework": framework,
            }
            if target:
                metadata["target"] = target
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata=metadata,
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # 2) Rails resources / resource directives.
        for m in _RESOURCES_RE.finditer(stripped):
            kind = m.group("kind")
            name = m.group("name")
            # Same off-by-one defence as the verb-route branch: anchor on
            # the `resources`/`resource` keyword, not `m.start()`, since
            # the `^\s*` prefix can absorb a blanked-out preceding line.
            kind_start = m.start("kind")
            line = _line_of(stripped, kind_start)
            line_start = text.rfind("\n", 0, kind_start) + 1
            docstring = _docstring_before(text, line_start)
            symbol = f"{kind} :{name}"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": "RESTFUL",
                        "path": f"/{name}",
                        "framework": framework,
                        "resource_kind": kind,
                        "resource_name": name,
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
