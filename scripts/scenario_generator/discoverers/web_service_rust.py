"""Rust web-service route discoverer.

Finds HTTP route registrations in Rust source files for the
`web_service_rust` software type. Covers the major frameworks in
common use (and that the fingerprint registry recognises):

- **actix-web** — attribute macro form `#[get("/foo")]`, `#[post(...)]`,
  etc. above an `async fn handler`. Also the imperative form
  `App::new().service(web::resource("/foo").to(handler))` and
  `.route("/foo", web::get().to(handler))`.
- **axum** — `Router::new().route("/foo", get(handler))` chained with
  `.route(...)` calls. Verb constructors (`get`, `post`, `put`, ...)
  are functions from `axum::routing`.
- **rocket** — attribute macro form `#[get("/foo")]` above a function.
  Same syntax as actix-web for the macro; we tag the framework based
  on Cargo.toml signals or, failing that, the import lines in the
  source file.
- **warp** — `warp::path!("foo")` combined with `.and(warp::get())`
  using filter combinators. Heuristic-only in v1: we recognise
  `warp::path` followed by a filter chain mentioning a verb filter
  on the same statement block.

Emitted EntryPoint shape:
- kind = HTTP_ROUTE
- file = repo-relative .rs path
- line = 1-indexed line of the attribute / call expression
- symbol = handler fn name when known; otherwise a stable identifier
  built from `<framework>:<method>:<path>`
- type_origin = "web_service_rust"
- metadata = {method, path, framework, binding}

Heuristic — not AST-perfect — but deterministic. Files are sorted,
matches iterate in source order, final dedup + sort by
(sort_key(), method, framework) keeps output byte-identical across
runs.

Intended-behaviour sources: first non-empty line of the doc comment
(`///`) immediately above the attribute macro / route registration.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Module-level constant declaring which detected software type this
# discoverer applies to. Same name as the filename in this case, but
# we set it anyway so the dispatcher's TYPE_ORIGIN scan also picks us
# up (rule 2 in _load_framework_discoverers).
TYPE_ORIGIN = "web_service_rust"


# ---- Regex contracts -------------------------------------------------------

# Attribute-macro routes — actix-web and rocket share this exact form.
# `#[get("/path")]`, `#[post("/path")]`, etc. The path is captured from
# the first quoted-string argument (only "double-quoted" in Rust).
_ATTR_VERB_RE = re.compile(
    r"#\[\s*(?P<verb>get|post|put|delete|patch|head|options)\s*\(\s*"
    r"\"(?P<path>/[^\"]*)\"",
)

# Function declaration following an attribute. Used to capture the
# handler symbol. `pub async fn handler(...)` / `pub fn ...` / `async fn`.
_FN_DECL_RE = re.compile(
    r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_][\w]*)\s*[<(]",
    re.MULTILINE,
)

# Axum `.route("/path", VERB(handler))` chain. We capture the path and
# the verb constructor name. The handler argument can be a path
# expression like `handler` or `crate::handlers::handler` — we capture
# the LAST identifier of that path as the symbol.
_AXUM_ROUTE_RE = re.compile(
    r"\.route\s*\(\s*"
    r"\"(?P<path>/[^\"]*)\""
    r"\s*,\s*"
    r"(?P<verb>get|post|put|delete|patch|head|options|trace)\s*\(\s*"
    r"(?P<handler>[A-Za-z_][\w:]*)",
)

# Actix imperative form: `.route("/path", web::VERB().to(handler))`
# OR `web::resource("/path").route(web::VERB().to(handler))`
# OR `web::resource("/path").to(handler)` (verb defaults to GET in
# this form — we tag it as GET, since the actix default is to handle
# all methods, but the discoverer must pick one for the EntryPoint).
_ACTIX_ROUTE_RE = re.compile(
    r"\.route\s*\(\s*"
    r"\"(?P<path>/[^\"]*)\""
    r"\s*,\s*"
    r"web\s*::\s*(?P<verb>get|post|put|delete|patch|head|options)\s*\(\s*\)"
    r"\s*\.\s*to\s*\(\s*(?P<handler>[A-Za-z_][\w:]*)",
)

# Actix `web::resource("/path").route(...)` — note that the actual verb
# is BURIED inside the `.route(web::VERB().to(handler))` chunk; we let
# _ACTIX_ROUTE_RE catch the inner `.route(...)` form, but we ALSO
# recognise the standalone `web::resource("/path").to(handler)` form
# (no verb specified) here — uncommon but real, and we'd otherwise
# miss it.
_ACTIX_RESOURCE_TO_RE = re.compile(
    r"web\s*::\s*resource\s*\(\s*\"(?P<path>/[^\"]*)\"\s*\)"
    r"\s*\.\s*to\s*\(\s*(?P<handler>[A-Za-z_][\w:]*)",
)

# Warp path + verb filter — heuristic. We look for `warp::path!(...)`
# followed by `.and(warp::VERB())` on the same statement. The path
# segments inside `warp::path!(...)` can be string literals or
# identifier segments (typed parameters). For v1 we only handle the
# string-literal form `warp::path!("foo" / "bar")` → "/foo/bar".
_WARP_RE = re.compile(
    r"warp\s*::\s*path\s*!\s*\(\s*(?P<segments>[^)]*)\)"
    r"(?P<chain>(?:\s*\.\s*and\s*\([^)]*\))*)",
    re.DOTALL,
)
_WARP_VERB_RE = re.compile(r"warp\s*::\s*(?P<verb>get|post|put|delete|patch|head|options)\s*\(")
_WARP_SEG_STR_RE = re.compile(r"\"(?P<seg>[^\"]+)\"")

# Doc-comment line (Rust `///`). Used to extract intended_behaviour.
_DOC_LINE_RE = re.compile(r"^\s*///\s?(?P<body>.*)$", re.MULTILINE)

# Cargo.toml framework hints — read once per discoverer run.
_CARGO_FRAMEWORK_KEYS: tuple[tuple[str, str], ...] = (
    ("actix-web", "actix-web"),
    ("axum", "axum"),
    ("rocket", "rocket"),
    ("warp", "warp"),
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".cargo",
        ".idea",
        ".vscode",
        ".cache",
        "target",
        "out",
        "build",
        "dist",
        "vendor",
        "node_modules",
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "benches",
        "bench",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — enough for any single Rust file we scan


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path`. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Return True if any directory between repo_root and path is in _SKIP_DIRS.

    We compute parts RELATIVE to repo_root so a fixture sitting under
    `tests/fixtures/...` isn't mis-skipped — the absolute path would
    contain "tests" and skip everything.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _detect_cargo_framework(repo_root: Path) -> str:
    """Read Cargo.toml at the root and return the first matched framework
    name, or "" if none. We don't parse TOML — substring matching is
    enough for fingerprinting, same approach the type detector uses.
    """
    cargo = repo_root / "Cargo.toml"
    if not cargo.exists():
        return ""
    try:
        text = cargo.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for needle, name in _CARGO_FRAMEWORK_KEYS:
        if needle in text:
            return name
    return ""


def _file_framework_hint(text: str) -> str:
    """Best-effort framework detection from a single Rust file's imports.

    Returns "" if no strong signal. When the discoverer sees multiple
    frameworks in one file (legitimate for a workspace `lib.rs` that
    just re-exports), we pick the FIRST one that matched.
    """
    for needle, name in (
        ("use actix_web", "actix-web"),
        ("actix_web::", "actix-web"),
        ("use axum", "axum"),
        ("axum::", "axum"),
        ("#[macro_use] extern crate rocket", "rocket"),
        ("use rocket", "rocket"),
        ("rocket::", "rocket"),
        ("use warp", "warp"),
        ("warp::", "warp"),
    ):
        if needle in text:
            return name
    return ""


def _doc_comment_before(text: str, position: int) -> str:
    """Return first non-empty line of the `///` doc-comment block
    immediately above `position`, if any.

    Walk backwards from `position` collecting consecutive `///` lines.
    Stop at the first non-`///`, non-blank line.
    """
    head = text[:position]
    lines = head.splitlines()
    collected: list[str] = []
    for ln in reversed(lines):
        m = _DOC_LINE_RE.match(ln)
        if m:
            collected.append(m.group("body").strip())
            continue
        # Allow blank lines IF we've already collected something —
        # they separate paragraphs inside the doc block.
        if ln.strip() == "":
            if collected:
                continue
            else:
                continue
        # Hit a non-comment, non-blank line — stop.
        break
    # Reverse to source order, return first non-empty.
    for s in reversed(collected):
        if s:
            return s
    return ""


def _next_fn_name(text: str, offset: int) -> str:
    """Return the name of the next `fn` declaration after `offset`, or "".

    Used to attach a handler symbol to an attribute macro.
    """
    rest = text[offset : offset + 2048]
    m = _FN_DECL_RE.search(rest)
    if m is None:
        return ""
    # Reject matches separated by a blank-line block — they belong to
    # a later function.
    between = rest[: m.start()]
    if between.count("\n\n\n") > 0:
        return ""
    return m.group("name")


def _warp_segments_to_path(segments_text: str) -> str:
    """Convert `warp::path!("a" / "b" / String)` segment list to a route path.

    Only string-literal segments are kept; typed parameter segments
    (`u32`, `String`, etc.) are placeholdered as `{}` in the path.
    """
    parts: list[str] = []
    # We split by `/` but inside the `path!(...)` macro segments are
    # divided by `/` tokens; regex extraction of string literals first.
    str_matches = list(_WARP_SEG_STR_RE.finditer(segments_text))
    if not str_matches:
        # Identifier-only path (typed-parameter only) — represent as `/{}`.
        return "/{}"
    for m in str_matches:
        parts.append(m.group("seg"))
    return "/" + "/".join(parts)


def _last_identifier(handler_path: str) -> str:
    """For a Rust path like `crate::handlers::list_users`, return
    `list_users`. For a bare ident, return it unchanged.
    """
    if "::" in handler_path:
        return handler_path.rsplit("::", 1)[-1]
    return handler_path


# ---------------------------------------------------------------------------
# Discoverer entry point
# ---------------------------------------------------------------------------


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Rust web routes. Deterministic order."""
    if "rust" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    cargo_framework = _detect_cargo_framework(repo_root)

    rs_files: list[Path] = []
    for p in repo_root.rglob("*.rs"):
        if _is_skipped(p, repo_root):
            continue
        if p.is_file():
            rs_files.append(p)
    rs_files.sort()

    for path in rs_files:
        text = _read(path)
        if not text:
            continue

        rel = str(path.relative_to(repo_root))
        file_hint = _file_framework_hint(text)
        # Tiebreaker for attribute-macro form (actix vs rocket): prefer
        # the file-local import hint over the Cargo dependency hint.
        # `framework` reported in metadata reflects the most specific
        # available signal.
        attr_framework = file_hint or cargo_framework or "rust"

        # ---- Attribute-macro routes: actix-web AND rocket -----------------
        for m in _ATTR_VERB_RE.finditer(text):
            verb = m.group("verb").upper()
            route_path = m.group("path")
            line = _line_of(text, m.start())
            fn_name = _next_fn_name(text, m.end()) or f"{attr_framework}:{verb}:{route_path}"
            docstring = _doc_comment_before(text, m.start())
            # If the file shows neither actix nor rocket signals, default
            # to "actix-web" (more common). The framework tag is used
            # for downstream filtering only.
            framework = attr_framework if attr_framework in ("actix-web", "rocket") else "actix-web"
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=fn_name,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": route_path,
                        "framework": framework,
                        "binding": f"#[{m.group('verb')}]",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- axum: .route("/path", VERB(handler)) ------------------------
        for m in _AXUM_ROUTE_RE.finditer(text):
            verb = m.group("verb").upper()
            route_path = m.group("path")
            handler_path = m.group("handler")
            line = _line_of(text, m.start())
            symbol = _last_identifier(handler_path)
            docstring = _doc_comment_before(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": route_path,
                        "framework": "axum",
                        "binding": ".route",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- actix: .route("/path", web::VERB().to(handler)) -------------
        for m in _ACTIX_ROUTE_RE.finditer(text):
            verb = m.group("verb").upper()
            route_path = m.group("path")
            handler_path = m.group("handler")
            line = _line_of(text, m.start())
            symbol = _last_identifier(handler_path)
            docstring = _doc_comment_before(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": route_path,
                        "framework": "actix-web",
                        "binding": ".route(web::*)",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- actix: web::resource("/path").to(handler) (verb unspecified)
        for m in _ACTIX_RESOURCE_TO_RE.finditer(text):
            # Verb defaults to GET in the actix `resource().to()` form
            # for the EntryPoint emission (actix actually accepts any
            # method here). Tag the binding accordingly so the walker
            # can tell it apart from the explicit-verb form.
            verb = "GET"
            route_path = m.group("path")
            handler_path = m.group("handler")
            line = _line_of(text, m.start())
            symbol = _last_identifier(handler_path)
            docstring = _doc_comment_before(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": route_path,
                        "framework": "actix-web",
                        "binding": "web::resource.to",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- warp: warp::path!(...) chained with warp::VERB() ------------
        for m in _WARP_RE.finditer(text):
            segments = m.group("segments")
            chain = m.group("chain")
            route_path = _warp_segments_to_path(segments)
            mv = _WARP_VERB_RE.search(chain)
            if not mv:
                # No verb filter chained — skip; not a route registration.
                continue
            verb = mv.group("verb").upper()
            line = _line_of(text, m.start())
            symbol = f"warp:{verb}:{route_path}"
            docstring = _doc_comment_before(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": route_path,
                        "framework": "warp",
                        "binding": "warp::path",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, method, framework).
    seen: set[tuple[str, int, str, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (
            ep.file,
            ep.line,
            ep.symbol,
            str(ep.metadata.get("method", "")),
            str(ep.metadata.get("framework", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    # Deterministic sort. Tiebreakers on (method, framework) keep two
    # entries that share file/line/symbol stable.
    unique.sort(
        key=lambda e: (
            e.sort_key(),
            str(e.metadata.get("method", "")),
            str(e.metadata.get("framework", "")),
        )
    )
    return unique
