"""PHP HTTP route discoverer.

Finds HTTP route registrations across PHP files for the
`web_service_php` software type. Three idiomatic frameworks are
covered:

- **Laravel**: ``Route::get('/path', ...)``, ``Route::post(...)``,
  ``Route::put(...)``, ``Route::delete(...)``, ``Route::patch(...)``,
  ``Route::options(...)``, ``Route::any(...)``, and the resource
  helpers ``Route::resource('/foo', FooController::class)`` /
  ``Route::apiResource(...)`` which expand into the seven REST verbs.
- **Symfony**: PHP-8 attribute routing ``#[Route('/foo', methods: ['GET'])]``
  (and the older ``@Route("/foo", methods={"GET"})`` annotation form
  found above class/method docblocks).
- **Slim 3/4 (and similar fluent routers)**: ``$app->get('/foo',
  ...)``, ``$app->post(...)``, etc. The leading dollar-sign binding
  disambiguates the call from a Laravel facade.

Emits one EntryPoint per (file, line, HTTP method, path) triple. The
``framework`` field in ``metadata`` reflects which dialect matched
the registration so the walker can apply per-framework defaults
(e.g. CSRF middleware in Laravel, sessions in Symfony).

Heuristic, not AST-perfect, but deterministic — files are sorted,
regexes iterate in source order, and a final dedup + sort pass
guarantees byte-identical output across runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# This module's filename matches the canonical type name, so the
# dispatcher loads it via _load_discoverer first; TYPE_ORIGIN is
# defined for completeness and for any framework-variant module
# that might be added later (e.g. web_service_php_symfony.py).
TYPE_ORIGIN = "web_service_php"


# ---- Regex contracts -------------------------------------------------------

# Laravel: ``Route::get('/path', ...)`` and the other HTTP verbs.
# The method alternation includes ``any`` and ``match`` so the
# discoverer can find catch-all routes; ``match`` carries an explicit
# methods array that is parsed separately.
_LARAVEL_VERB_RE = re.compile(
    r"\bRoute::(?P<method>get|post|put|delete|patch|options|head|any)\s*\(\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)",
)

# Laravel: ``Route::match(['get', 'post'], '/path', ...)`` — first arg
# is an array of verbs, second arg is the route path. We capture both
# and emit one EntryPoint per method.
_LARAVEL_MATCH_RE = re.compile(
    r"\bRoute::match\s*\(\s*\[(?P<methods>[^\]]+)\]\s*,\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)",
)

# Laravel: ``Route::resource('/foo', FooController::class)`` and
# ``Route::apiResource(...)``. RESTful resource — expanded into the
# canonical seven (resource) or four (apiResource, API-only) verbs.
_LARAVEL_RESOURCE_RE = re.compile(
    r"\bRoute::(?P<kind>apiResource|resource)\s*\(\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)\s*,\s*"
    r"(?P<controller>[A-Za-z_\\][\w\\]*)",
)

# Symfony: PHP-8 attribute syntax. Path is the first quoted string
# inside ``#[Route(...)]``; an optional ``methods: [...]`` kwarg
# constrains the HTTP verbs. When ``methods`` is absent, Symfony
# accepts every verb — we emit a single EntryPoint with method=ANY.
_SYMFONY_ATTR_RE = re.compile(
    r"#\[Route\s*\(\s*(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)"
    r"(?P<rest>[^\]]*)\]",
)

# Symfony: older ``@Route("/foo", methods={"GET"})`` annotation form
# (found in PHP doc-blocks). Identical shape to the attribute except
# for the leading ``@`` and the curly-brace methods array.
_SYMFONY_ANNOT_RE = re.compile(
    r"@Route\s*\(\s*(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)"
    r"(?P<rest>[^)]*)\)",
)

# Symfony: parse ``methods: ['GET', 'POST']`` (PHP-8 named-arg syntax)
# AND ``methods={"GET", "POST"}`` (older annotation curly syntax) AND
# ``methods=["GET"]`` (annotation array syntax) out of the ``rest``
# fragment of a Route(...) call.
_SYMFONY_METHODS_RE = re.compile(
    r"methods\s*[:=]\s*[\[\{](?P<list>[^\]\}]+)[\]\}]",
)

# Slim / fluent app routers. The binding starts with ``$`` to
# disambiguate from Laravel facades (which use ``Route::``). Common
# bindings in idiomatic PHP: ``$app``, ``$router``, ``$slim``.
_SLIM_VERB_RE = re.compile(
    r"\$(?P<binding>[A-Za-z_]\w*)\s*->\s*(?P<method>get|post|put|delete|patch|options|head|any)\s*\(\s*"
    r"(?P<quote>['\"])(?P<path>[^'\"]*)(?P=quote)",
)

# Symfony method name following a Route attribute / annotation. PHP
# uses ``public function name(...)`` for controller actions; we accept
# any visibility qualifier (or none) plus optional ``static``.
_PHP_METHOD_DEF_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?:public|private|protected)?\s*(?:static\s+)?function\s+(?P<name>[A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)


# ---- Skip dirs + file filters ---------------------------------------------

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "vendor",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "out",
        "target",
        "var",
        "storage",
        "bootstrap/cache",
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


CONTENT_PREVIEW_BYTES = 131072  # 128 KB — enough for big route files

# Verbs that ``Route::resource`` expands to (Laravel docs §controllers/
# resource-controllers). The order is the documented order in the
# Laravel source so users skimming the golden see the same shape they
# see in `php artisan route:list`.
_RESOURCE_VERBS: tuple[tuple[str, str], ...] = (
    ("GET", "index"),
    ("GET", "create"),
    ("POST", "store"),
    ("GET", "show"),
    ("GET", "edit"),
    ("PUT", "update"),
    ("DELETE", "destroy"),
)

# apiResource is identical except ``create`` and ``edit`` (the form
# views) are omitted — those would only be useful for HTML-form
# scaffolding which an API does not serve.
_API_RESOURCE_VERBS: tuple[tuple[str, str], ...] = (
    ("GET", "index"),
    ("POST", "store"),
    ("GET", "show"),
    ("PUT", "update"),
    ("DELETE", "destroy"),
)


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
    so fixtures under `tests/fixtures/...` aren't mis-skipped — the
    discoverer's caller decides what `repo_root` is; we only care
    about what's inside it.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _next_function_name(text: str, after: int) -> str:
    """Find the next PHP function/method definition after `after`.

    Used to attach a Symfony Route attribute to its controller-action
    method. Returns "" if no function definition is reasonably close.
    """
    rest = text[after : after + 1024]
    m = _PHP_METHOD_DEF_RE.search(rest)
    if m is None:
        return ""
    return m.group("name")


def _parse_methods(blob: str) -> list[str]:
    """Parse a quoted-string list from a methods= fragment.

    Accepts ``'GET', 'POST'``, ``"GET", "POST"`` (annotation curlies
    are stripped by the caller's regex). Returns upper-cased verbs in
    source order.
    """
    out: list[str] = []
    for raw in blob.split(","):
        s = raw.strip().strip("'").strip('"').strip()
        if s:
            out.append(s.upper())
    return out


def _extract_docblock_above(text: str, offset: int) -> str:
    """Return the first non-empty content line of the docblock that
    sits immediately above `offset`, if any. PHP docblocks are
    ``/** ... */`` — we walk back from `offset` to find the most
    recent one and only treat it as "attached" if nothing but
    whitespace separates the docblock close and `offset`.
    """
    head = text[:offset]
    window = head[-1024:]
    end = window.rfind("*/")
    if end == -1:
        return ""
    # Anything between `end + 2` and the end of `window` must be only
    # whitespace for the docblock to count as the immediately-preceding
    # block. (Allows attribute lines, but a real bug would have other
    # tokens here.)
    tail = window[end + 2 :]
    if tail.strip() != "":
        return ""
    start = window.rfind("/**", 0, end)
    if start == -1:
        return ""
    body = window[start + 3 : end]
    for raw in body.splitlines():
        s = raw.strip().lstrip("*").strip()
        if s and not s.startswith("@"):
            return s
    return ""


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find PHP HTTP routes. Deterministic order."""
    if "php" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    php_files: list[Path] = []
    for p in repo_root.rglob("*.php"):
        if _is_skipped(p, repo_root):
            continue
        if p.is_file():
            php_files.append(p)
    php_files.sort()

    for path in php_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter — at least one route registration token must
        # appear or we move on. Keeps unrelated view-template PHP and
        # config files from being scanned in full.
        _pre_tokens = (
            "Route::",
            "#[Route",
            "@Route",
            "->get(",
            "->post(",
            "->put(",
            "->delete(",
            "->patch(",
        )
        if not any(tok in text for tok in _pre_tokens):
            continue
        rel = str(path.relative_to(repo_root))

        # ---- 1. Laravel ``Route::verb(...)`` ------------------------------
        for m in _LARAVEL_VERB_RE.finditer(text):
            method = m.group("method").upper()
            route_path = m.group("path")
            line = _line_of(text, m.start())
            # Symbol identifies the registration uniquely within a file/line.
            symbol = f"Route::{method.lower()} {route_path}"
            docstring = _extract_docblock_above(text, m.start())
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
                        "framework": "laravel",
                        "binding": "Route",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- 2. Laravel ``Route::match([...], '/path', ...)`` --------------
        for m in _LARAVEL_MATCH_RE.finditer(text):
            methods = _parse_methods(m.group("methods"))
            route_path = m.group("path")
            line = _line_of(text, m.start())
            docstring = _extract_docblock_above(text, m.start())
            for method in methods:
                if not method:
                    continue
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=f"Route::match:{method}:{route_path}",
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "method": method,
                            "path": route_path,
                            "framework": "laravel",
                            "binding": "Route",
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

        # ---- 3. Laravel ``Route::resource`` / ``Route::apiResource`` ------
        for m in _LARAVEL_RESOURCE_RE.finditer(text):
            kind = m.group("kind")
            route_path = m.group("path")
            controller = m.group("controller")
            line = _line_of(text, m.start())
            verbs = _API_RESOURCE_VERBS if kind == "apiResource" else _RESOURCE_VERBS
            docstring = _extract_docblock_above(text, m.start())
            for method, action in verbs:
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=f"{controller}@{action}",
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "method": method,
                            "path": route_path,
                            "framework": "laravel",
                            "binding": f"Route::{kind}",
                            "action": action,
                            "controller": controller,
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

        # ---- 4. Symfony ``#[Route('/foo', methods: ['GET'])]`` ------------
        for m in _SYMFONY_ATTR_RE.finditer(text):
            route_path = m.group("path")
            rest = m.group("rest") or ""
            line = _line_of(text, m.start())
            symbol = _next_function_name(text, m.end()) or f"#[Route] {route_path}"
            docstring = _extract_docblock_above(text, m.start())
            method_match = _SYMFONY_METHODS_RE.search(rest)
            methods = _parse_methods(method_match.group("list")) if method_match else ["ANY"]
            for method in methods:
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
                            "framework": "symfony",
                            "binding": "attribute",
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

        # ---- 5. Symfony ``@Route("/foo", methods={"GET"})`` annotations ---
        for m in _SYMFONY_ANNOT_RE.finditer(text):
            route_path = m.group("path")
            rest = m.group("rest") or ""
            line = _line_of(text, m.start())
            symbol = _next_function_name(text, m.end()) or f"@Route {route_path}"
            docstring = _extract_docblock_above(text, m.start())
            method_match = _SYMFONY_METHODS_RE.search(rest)
            methods = _parse_methods(method_match.group("list")) if method_match else ["ANY"]
            for method in methods:
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
                            "framework": "symfony",
                            "binding": "annotation",
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

        # ---- 6. Slim / fluent ``$app->verb('/path', ...)`` ----------------
        for m in _SLIM_VERB_RE.finditer(text):
            binding = m.group("binding")
            method = m.group("method").upper()
            route_path = m.group("path")
            line = _line_of(text, m.start())
            symbol = f"${binding}->{method.lower()} {route_path}"
            docstring = _extract_docblock_above(text, m.start())
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
                        "framework": "slim",
                        "binding": f"${binding}",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol, method) — the same registration
    # never appears twice in the output even if a regex over-matches.
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
