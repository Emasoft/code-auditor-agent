"""Express.js route discoverer.

Finds HTTP route registrations across JS/TS files for the
`web_service_node` software type, framework `express`:

- `app.get('/path', handler)`, `app.post(...)`, `app.put(...)`,
  `app.delete(...)`, `app.patch(...)`, `app.head(...)`, `app.options(...)`
  — registrations on an Express application instance.
- `router.get('/path', handler)` etc. — registrations on any
  `express.Router()` / `Router()` instance (the binding name is captured
  in metadata so multiple routers are distinguishable).

V1 scope: only `<binding>.<method>('<path>', ...)` registrations are
emitted. `app.all(...)`, `app.route('/x').get(...)` chains, and
mounted sub-apps via `app.use('/prefix', subRouter)` are deliberately
NOT recognised — adding them is the natural follow-up and the existing
regex makes that mechanical (see _ROUTE_RE comment).

The discoverer is heuristic (regex, not AST) but deterministic: files
are sorted, matches are iterated in source order, and a final dedup
+ sort pass guarantees byte-identical output across runs.

Intended-behaviour sources: nearest leading JSDoc / `//` comment block
(walker uses this when no OpenAPI / spec source is present).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Module-level constant declaring which detected software type this
# discoverer applies to. The dispatcher (emit_scenarios_json) reads this
# to find framework-specific discoverers — multiple modules may declare
# the same TYPE_ORIGIN and their results are combined.
TYPE_ORIGIN = "web_service_node"

# Match `<binding>.<method>('<path>', ...` where method is one of the
# seven Express HTTP-verb registrations. The path is captured from
# either single- or double-quoted string. Backticks (template literals)
# are NOT supported in v1 — Express allows them but they're rare for
# static route paths, and supporting them would require deeper parsing.
#
# To extend to `.all(`, add `|all` to the method alternation and emit
# one EntryPoint per HTTP verb (the universe is the same seven).
_ROUTE_RE = re.compile(
    r"(?P<binding>[A-Za-z_$][\w$]*)\s*"
    r"\.(?P<method>get|post|put|delete|patch|head|options)\s*\(\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)",
)

# Match `const|let|var <name> = express.Router(` or `= Router(`. Captures
# the binding name so we can label the metadata; we don't actually need
# to verify it's a router for v1 (Express's universal `.METHOD()` API
# means routes on routers and apps look identical at the call site), but
# we capture it so the walker can tell `app` apart from `apiRouter`.
_ROUTER_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:express\s*\.\s*Router|Router)\s*\(",
)

# Match `const|let|var <name> = express(` or `= express()` — the app
# binding. Used only to confirm the file is an Express entry-point file
# (cheap pre-filter alongside the substring check).
_APP_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*express\s*\(",
)

# Leading JSDoc block `/** ... */` immediately above a route line, or a
# run of `//` comments on the lines directly preceding the route. Both
# patterns are anchored to the end of the comment block followed by
# optional whitespace before the route registration.
_JSDOC_RE = re.compile(r"/\*\*(?P<body>.*?)\*/", re.DOTALL)


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


# Source files we scan. TypeScript route files are rare for plain Express
# (more typical for Nest/Fastify-on-TS), but we include `.ts` so the
# discoverer doesn't miss obvious cases. Order is fixed for determinism.
_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts")


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
    """Return True if any directory under `repo_root` on the way to `path`
    is in `_SKIP_DIRS`.

    We deliberately compute parts *relative to repo_root* — checking
    absolute parts would mis-skip every fixture whose repo_root happens
    to live under a directory named, say, `tests/` (e.g. our own
    `tests/fixtures/...`). The repo_root itself is whatever the caller
    asked us to scan; what's *inside* it is what matters.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        # Path outside repo_root — shouldn't happen via rglob, but be safe.
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _strip_comments(text: str) -> str:
    """Replace JS comments with same-length whitespace so character
    offsets are preserved. Block-comment-aware AND line-comment-aware.

    Why same-length: the discoverer reports line numbers based on
    offsets into the source. If we shrank the text, those line numbers
    would drift. Replacing with spaces (and keeping newlines) keeps
    every match's offset valid.

    This is intentionally NOT a real lexer — it doesn't track string
    state, so `"// not actually a comment"` inside a quoted string
    will be partially blanked. For the v1 discoverer scope (route
    registrations) this is acceptable; the false-positive cost of
    keeping comments verbatim (see the fixture's leading comment that
    enumerates `app.get('/path', ...)` as a doc example) is much
    higher than the false-negative cost of an over-eager comment
    stripper occasionally blanking a string literal.
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
        # Block comment: /* ... */ → blank including the /*...*/ markers
        # but preserve any \n inside so line numbers don't drift.
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                # Unterminated comment — blank to end of file.
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
    """First non-empty line of the JSDoc / // comment block immediately
    above the route registration, if any. Used as fallback
    intended_behaviour when no OpenAPI spec is present.
    """
    head = text[:route_start]
    # Last 1024 chars are usually enough — keeps the regex bounded.
    window = head[-1024:]

    # Try JSDoc first: walk all `/** ... */` blocks; pick the one whose
    # end is closest to (and immediately above) the route.
    last_jsdoc: re.Match[str] | None = None
    for m in _JSDOC_RE.finditer(window):
        between = window[m.end() :]
        # Allow only whitespace (incl. newlines) between the JSDoc close
        # and the route — anything else means an unrelated block.
        if between.strip() == "":
            last_jsdoc = m
    if last_jsdoc is not None:
        body = last_jsdoc.group("body")
        for ln in body.splitlines():
            s = ln.strip().lstrip("*").strip()
            if s:
                return s

    # Otherwise, look for a run of `//` comments directly above.
    lines = window.splitlines()
    collected: list[str] = []
    # Walk backwards from the line above the route, collecting `//` lines
    # until we hit a non-comment line.
    for ln in reversed(lines[:-1] if window.endswith("\n") else lines):
        s = ln.strip()
        if s.startswith("//"):
            collected.append(s.lstrip("/").strip())
            continue
        if s == "":
            # Blank line between comment block and route: stop only if we
            # already collected something; otherwise keep scanning past.
            if collected:
                break
            continue
        break
    if collected:
        # Reverse to source order, then return first non-empty.
        for s in reversed(collected):
            if s:
                return s
    return ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Express routes. Deterministic order."""
    if "javascript" not in languages and "typescript" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # Sort files deterministically across extensions.
    js_files: list[Path] = []
    for ext in _EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if _is_skipped(p, repo_root):
                continue
            if p.is_file():
                js_files.append(p)
    js_files.sort()

    for path in js_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter: file must mention `express` somewhere or use
        # a Router declaration. Skips MVC view files, utility scripts,
        # etc. that happen to share extensions.
        if "express" not in text and "Router" not in text:
            continue

        rel = str(path.relative_to(repo_root))

        # Strip comments before running regex matchers — JSDoc and `//`
        # blocks routinely contain example route registrations that would
        # otherwise fire as false positives. `_strip_comments` preserves
        # character offsets so line numbers stay correct, and the
        # ORIGINAL `text` is still used for JSDoc/docstring extraction
        # (the comment IS the docstring).
        stripped = _strip_comments(text)

        # Collect known bindings — the app and any routers declared in
        # this file. We don't enforce that a route's binding is in this
        # set (an import-from-another-file binding is still a legit
        # route), but we tag the metadata accordingly.
        known_router_names: set[str] = set()
        for m in _ROUTER_DECL_RE.finditer(stripped):
            known_router_names.add(m.group("name"))
        known_app_names: set[str] = set()
        for m in _APP_DECL_RE.finditer(stripped):
            known_app_names.add(m.group("name"))

        for m in _ROUTE_RE.finditer(stripped):
            binding = m.group("binding")
            method = m.group("method").upper()
            route_path = m.group("path")
            line = _line_of(stripped, m.start())
            # Docstring extraction reads the ORIGINAL text (preserves
            # the leading JSDoc / `//` block whose content IS the doc).
            docstring = _docstring_before(text, m.start())

            # Build a stable symbol per route: `<binding>.<method> <path>`.
            # This is unique within a file at a given line/method/path.
            symbol = f"{binding}.{method.lower()} {route_path}"

            # binding_kind disambiguates app vs router routes in metadata
            # without losing the original variable name.
            if binding in known_app_names:
                binding_kind = "app"
            elif binding in known_router_names:
                binding_kind = "router"
            else:
                binding_kind = "unknown"

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
                        "framework": "express",
                        "binding": binding,
                        "binding_kind": binding_kind,
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, method). Two identical registrations
    # at the same line are conceptually the same route — drop duplicates.
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
