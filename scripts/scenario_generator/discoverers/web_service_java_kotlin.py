"""Java/Kotlin web-service route discoverer.

Finds HTTP route registrations in Java / Kotlin source files for the
`web_service_java_kotlin` software type. The fingerprint registry can
trigger on Spring Boot, Spring WebFlux, Jersey (JAX-RS), or vert.x-web
manifests, but the discoverer focuses on annotations that are *common*
across the major frameworks:

- Spring MVC / WebFlux:
    * `@GetMapping("/foo")`, `@PostMapping`, `@PutMapping`,
      `@DeleteMapping`, `@PatchMapping`, `@RequestMapping(...)`
    * `@RequestMapping(value="/foo", method=RequestMethod.POST)` — the
      explicit form with `method=` attribute
- JAX-RS (Jersey / Resteasy / Quarkus REST):
    * `@Path("/foo")` on a class or method PLUS one of `@GET` / `@POST`
      / `@PUT` / `@DELETE` / `@PATCH` / `@HEAD` / `@OPTIONS` on a method
- Micronaut:
    * `@Get("/foo")`, `@Post("/foo")`, etc. — annotation name (no
      "Mapping" suffix). Distinguished from Spring's `@Get` (which
      doesn't exist) by the package import; we do NOT import-check in
      v1, but we tag the framework as `micronaut` when the annotation
      spelling matches and no Spring `*Mapping` was seen in the file.
- Ktor (Kotlin only):
    * `get("/foo") { ... }`, `post("/foo") { ... }`, `put`, `delete`,
      etc. — function calls inside a `routing { ... }` block. We
      heuristically require either an outer `routing {` or `route(` to
      avoid matching unrelated `get(` calls in non-ktor Kotlin code.

Emitted EntryPoint shape:
- kind = HTTP_ROUTE
- file = repo-relative .java or .kt path
- line = 1-indexed line of the route registration / annotation
- symbol = handler function name when it can be parsed; otherwise a
  stable identifier built from `<framework>:<method>:<path>` so the
  golden dedup is meaningful
- type_origin = "web_service_java_kotlin"
- metadata = {method, path, framework, binding}

Heuristic — not AST-perfect — but deterministic. Files are sorted,
matches iterate in source order, final dedup + sort by
(sort_key(), method, framework) keeps output byte-identical across
runs.

Intended-behaviour sources: first non-empty line of the Javadoc /
KDoc / `//` comment block immediately above the route annotation /
ktor function call.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Module-level constant declaring which detected software type this
# discoverer applies to. Same name as the filename in this case, but
# we set it anyway so the dispatcher's TYPE_ORIGIN scan also picks us
# up (rule 2 in _load_framework_discoverers).
TYPE_ORIGIN = "web_service_java_kotlin"


# ---- Regex contracts -------------------------------------------------------
#
# All patterns operate on UTF-8 source text. They are intentionally
# loose to survive minor whitespace / formatting variation. We do NOT
# try to be a real parser — the failure modes (e.g. annotation inside
# a multi-line string, commented-out code) are documented and dedup
# at the end keeps duplicates from inflating the golden.

# Spring's verb-mapping annotations (@GetMapping, @PostMapping, ...).
# Captures method (lowercase verb without the "Mapping" suffix) and
# the route path from the FIRST quoted string argument (single or
# double quoted). Common forms supported:
#   @GetMapping("/foo")
#   @GetMapping(value="/foo")
#   @GetMapping(path="/foo")
# Forms NOT supported in v1:
#   @GetMapping  (no argument — class-level "" path, would need
#                 class-level @RequestMapping merging)
_SPRING_VERB_RE = re.compile(
    r"@(?P<verb>Get|Post|Put|Delete|Patch|Head|Options)Mapping\s*\("
    r"(?:[^)]*?(?:value|path)\s*=\s*)?"
    r"(?P<quote>[\"'])(?P<path>/[^\"']*)(?P=quote)",
)

# Spring's generic @RequestMapping with explicit method= attribute.
# Captures the first path string and the RequestMethod constant.
# We allow value=, path=, OR the first positional argument as path.
# `method=RequestMethod.POST` form: extract POST.
# `method={RequestMethod.GET, RequestMethod.POST}` (set form) is NOT
# expanded in v1 — only the first method is captured.
_SPRING_REQUEST_MAPPING_RE = re.compile(
    r"@RequestMapping\s*\("
    r"(?P<body>[^)]*)"
    r"\)",
    re.DOTALL,
)
_SPRING_RM_PATH_RE = re.compile(
    r"(?:value|path)\s*=\s*(?P<quote>[\"'])(?P<path>/[^\"']*)(?P=quote)"
    r"|^\s*(?P<quote2>[\"'])(?P<path2>/[^\"']*)(?P=quote2)",
    re.MULTILINE,
)
_SPRING_RM_METHOD_RE = re.compile(r"RequestMethod\.(?P<verb>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)")

# Micronaut verb annotations. The spelling is the same family of words
# but WITHOUT the "Mapping" suffix: @Get, @Post, @Put, @Delete, @Patch,
# @Head, @Options. We require an opening `(` and a quoted string to
# distinguish from Spring's `@Getter` / Lombok `@Get` / Kotlin's `get(`.
_MICRONAUT_RE = re.compile(
    r"@(?P<verb>Get|Post|Put|Delete|Patch|Head|Options)\s*\("
    r"(?:[^)]*?(?:uri|value)\s*=\s*)?"
    r"(?P<quote>[\"'])(?P<path>/[^\"']*)(?P=quote)",
)

# JAX-RS @Path annotation — appears on either the class or method.
# We capture all occurrences; method-level @Path values are the route
# tail, class-level @Path is the route prefix. Concatenation is done
# in the discover loop.
_JAXRS_PATH_RE = re.compile(
    r"@Path\s*\(\s*(?P<quote>[\"'])(?P<path>[^\"']*)(?P=quote)",
)

# JAX-RS HTTP-method annotations — bare annotations on the method,
# no arguments. The route path comes from the nearest preceding
# @Path on the same method, joined with the class-level @Path.
_JAXRS_VERB_RE = re.compile(r"@(?P<verb>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b(?!\w)")

# Method/function declarations — used to attach a symbol name to an
# annotation. We accept a permissive signature: optional modifiers,
# optional return type, then `<name>(`. The match starts at the
# beginning of the method definition (post-annotations).
# Java form: `public ResponseEntity<Foo> handler(...)` etc.
# Kotlin form: `fun handler(...): Response`
_METHOD_DEF_JAVA_RE = re.compile(
    r"^\s*(?:public|private|protected|static|final|abstract|synchronized|default|@\w+(?:\([^)]*\))?\s+)*"
    r"(?:<[^>]+>\s+)?"
    r"[A-Za-z_$][\w$<>,\s.?\[\]]*\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\(",
    re.MULTILINE,
)
_METHOD_DEF_KOTLIN_RE = re.compile(
    r"^\s*(?:public|private|protected|internal|inline|suspend|open|override|abstract|@\w+(?:\([^)]*\))?\s+)*"
    r"fun\s+"
    r"(?:<[^>]+>\s+)?"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\(",
    re.MULTILINE,
)

# Ktor routing DSL — function calls inside a `routing { ... }` block.
# We don't actually parse the block scope; we just require the file
# to contain `routing {` or `route(` somewhere, and then match each
# `<verb>("/path") {` call. This catches well-written ktor handlers
# at the cost of (theoretically) matching a `get(...)` call in
# unrelated Kotlin code — the file-level pre-filter mitigates that.
_KTOR_VERB_RE = re.compile(
    r"\b(?P<verb>get|post|put|delete|patch|head|options)\s*\(\s*"
    r"(?P<quote>[\"'])(?P<path>/[^\"']*)(?P=quote)",
)

# Class-level @RestController or @Controller annotation in Spring —
# used purely as a hint that this file is a Spring controller.
_SPRING_CONTROLLER_RE = re.compile(r"@(?:Rest)?Controller\b")

# Class declaration — used to attach the class-level @Path / class-level
# @RequestMapping prefix. We only need the OFFSET of the class header,
# not the name itself.
_CLASS_DECL_JAVA_RE = re.compile(
    r"\b(?:public\s+|abstract\s+|final\s+)*class\s+(?P<name>[A-Za-z_$][\w$]*)",
)
_CLASS_DECL_KOTLIN_RE = re.compile(
    r"\b(?:open\s+|abstract\s+|sealed\s+|data\s+)*class\s+(?P<name>[A-Za-z_$][\w$]*)",
)

# Comment patterns for docstring extraction. Javadoc (`/** */`) and KDoc
# share syntax; line comments are `//`.
_JAVADOC_RE = re.compile(r"/\*\*(?P<body>.*?)\*/", re.DOTALL)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".gradle",
        ".idea",
        ".vscode",
        ".cache",
        "out",
        "build",
        "target",
        "dist",
        "bin",
        "obj",
        "classes",
        "tests",
        "test",
        "__tests__",
        "src/test",
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


# Source files we scan — Java and Kotlin only. `.kts` is a Kotlin
# script extension typically used for Gradle build files; we skip it
# to avoid false-positive matches against build-script DSLs that
# happen to call functions named `get(`.
_EXTENSIONS: tuple[str, ...] = (".java", ".kt")


CONTENT_PREVIEW_BYTES = 131072  # 128KB — enough for big controller files


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


def _javadoc_before(text: str, annotation_start: int) -> str:
    """Return first non-empty line of the Javadoc / KDoc block immediately
    above an annotation, if any. Looks back up to 1024 chars.
    """
    head = text[:annotation_start]
    window = head[-1024:]
    last_doc: re.Match[str] | None = None
    for m in _JAVADOC_RE.finditer(window):
        between = window[m.end() :]
        # Allow only whitespace, newlines, or additional annotations
        # between the javadoc close and the matched annotation — annotation
        # blocks often appear in a stack and we want the docstring above
        # the WHOLE stack.
        if re.fullmatch(r"\s*(?:@\w+(?:\([^)]*\))?\s*)*", between):
            last_doc = m
    if last_doc is None:
        return ""
    body = last_doc.group("body")
    for ln in body.splitlines():
        s = ln.strip().lstrip("*").strip()
        if s:
            return s
    return ""


def _class_prefix_path(text: str, position: int) -> str:
    """Return the class-level @Path / @RequestMapping prefix that wraps
    a given file offset, if any. Used by JAX-RS and Spring to compose
    the full route path when method-level annotations supply only the
    tail.

    Heuristic: scan from the start of file up to `position` for the
    LAST class declaration whose body is still open (we don't actually
    track brace depth — we just take the last class declared above
    position). If that class is annotated with @Path("/prefix") or
    @RequestMapping(...) within the 200 chars preceding the class
    keyword, return the captured path. Otherwise return "".
    """
    head = text[:position]
    # Find the last class declaration. Java first, then Kotlin —
    # whichever has the larger end-offset wins. (Files normally have
    # one but not both languages; this just lets us reuse the function.)
    last_java = None
    last_kotlin = None
    for m in _CLASS_DECL_JAVA_RE.finditer(head):
        last_java = m
    for m in _CLASS_DECL_KOTLIN_RE.finditer(head):
        last_kotlin = m
    chosen: re.Match[str] | None = None
    if last_java and last_kotlin:
        chosen = last_java if last_java.start() > last_kotlin.start() else last_kotlin
    else:
        chosen = last_java or last_kotlin
    if chosen is None:
        return ""
    preamble_start = max(0, chosen.start() - 256)
    preamble = head[preamble_start : chosen.start()]
    m_path = _JAXRS_PATH_RE.search(preamble)
    if m_path:
        return m_path.group("path")
    # Try a Spring @RequestMapping at class level — usual case: only a
    # path value, no method= attribute. We parse via the body regex.
    m_rm = _SPRING_REQUEST_MAPPING_RE.search(preamble)
    if m_rm:
        body = m_rm.group("body")
        m_p = _SPRING_RM_PATH_RE.search(body)
        if m_p:
            return m_p.group("path") or m_p.group("path2") or ""
    return ""


def _join_path(prefix: str, tail: str) -> str:
    """Join a class-level path prefix and a method-level path tail with
    a single `/` separator. Empty prefix => return tail; empty tail =>
    return prefix; both empty => return "".
    """
    if not prefix and not tail:
        return ""
    if not prefix:
        return tail
    if not tail:
        return prefix
    if prefix.endswith("/") and tail.startswith("/"):
        return prefix + tail[1:]
    if not prefix.endswith("/") and not tail.startswith("/"):
        return prefix + "/" + tail
    return prefix + tail


def _method_name_after(text: str, offset: int, *, kotlin: bool) -> str:
    """Find the next method-definition name after `offset` in `text`.

    Returns "" if no method is found within a short window after the
    offset (annotation blocks should be followed by a method
    declaration within ~12 lines).
    """
    rest = text[offset : offset + 2048]
    rx = _METHOD_DEF_KOTLIN_RE if kotlin else _METHOD_DEF_JAVA_RE
    m = rx.search(rest)
    if m is None:
        return ""
    # Reject matches that are clearly past the next blank line block —
    # they belong to a later method.
    between = rest[: m.start()]
    if between.count("\n\n\n") > 0:
        return ""
    return m.group("name")


# ---------------------------------------------------------------------------
# Discoverer entry point
# ---------------------------------------------------------------------------


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Java/Kotlin web routes. Deterministic order."""
    if "java" not in languages and "kotlin" not in languages:
        return []
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    files: list[Path] = []
    for ext in _EXTENSIONS:
        for p in repo_root.rglob(f"*{ext}"):
            if _is_skipped(p, repo_root):
                continue
            if p.is_file():
                files.append(p)
    files.sort()

    for path in files:
        text = _read(path)
        if not text:
            continue
        is_kotlin = path.suffix == ".kt"
        rel = str(path.relative_to(repo_root))

        # File-level framework hints — used to set the `framework` field
        # in metadata when multiple framework patterns could match. If
        # the file contains a Spring `*Mapping` annotation anywhere, we
        # default to Spring; otherwise to JAX-RS (if @Path is present)
        # / Micronaut (if Micronaut-shaped annotations are present) /
        # Ktor (if routing { is present).
        has_spring_mapping = bool(_SPRING_CONTROLLER_RE.search(text)) or "Mapping(" in text or "@RequestMapping" in text
        has_jaxrs = "@Path(" in text and bool(_JAXRS_VERB_RE.search(text))
        has_micronaut = ("io.micronaut" in text) or ("micronaut.http" in text)
        has_ktor = ("routing {" in text or "routing{" in text) and is_kotlin

        # ---- Spring verb-mapping annotations ------------------------------
        for m in _SPRING_VERB_RE.finditer(text):
            verb = m.group("verb").upper()
            tail_path = m.group("path")
            prefix = _class_prefix_path(text, m.start())
            full_path = _join_path(prefix, tail_path)
            line = _line_of(text, m.start())
            symbol = _method_name_after(text, m.end(), kotlin=is_kotlin) or f"spring:{verb}:{full_path}"
            docstring = _javadoc_before(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": full_path,
                        "framework": "spring",
                        "binding": f"@{verb.title()}Mapping",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- Spring @RequestMapping(method=...) ---------------------------
        for m in _SPRING_REQUEST_MAPPING_RE.finditer(text):
            body = m.group("body")
            m_path = _SPRING_RM_PATH_RE.search(body)
            m_method = _SPRING_RM_METHOD_RE.search(body)
            # Class-level @RequestMapping (no method= attribute) is the
            # prefix used by other handlers — skip it here, we already
            # consumed it in _class_prefix_path.
            if not m_method:
                continue
            tail_path = (m_path.group("path") or m_path.group("path2") or "") if m_path else ""
            prefix = _class_prefix_path(text, m.start())
            full_path = _join_path(prefix, tail_path)
            verb = m_method.group("verb").upper()
            line = _line_of(text, m.start())
            symbol = _method_name_after(text, m.end(), kotlin=is_kotlin) or f"spring:{verb}:{full_path}"
            docstring = _javadoc_before(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.HTTP_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin=TYPE_ORIGIN,
                    metadata={
                        "method": verb,
                        "path": full_path,
                        "framework": "spring",
                        "binding": "@RequestMapping",
                    },
                    docstring=docstring,
                    intended_behaviour_sources=(),
                )
            )

        # ---- Micronaut verb annotations -----------------------------------
        # Only treat bare @Get/@Post as Micronaut when the file shows
        # Micronaut signals AND no Spring `*Mapping` was seen — Spring's
        # `@Getter` (Lombok) and other unrelated annotations would
        # otherwise misfire. We additionally require the path arg to
        # start with `/` (regex already enforces this).
        if has_micronaut and not has_spring_mapping:
            for m in _MICRONAUT_RE.finditer(text):
                verb = m.group("verb").upper()
                tail_path = m.group("path")
                prefix = _class_prefix_path(text, m.start())
                full_path = _join_path(prefix, tail_path)
                line = _line_of(text, m.start())
                symbol = _method_name_after(text, m.end(), kotlin=is_kotlin) or f"micronaut:{verb}:{full_path}"
                docstring = _javadoc_before(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=symbol,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "method": verb,
                            "path": full_path,
                            "framework": "micronaut",
                            "binding": f"@{verb.title()}",
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

        # ---- JAX-RS (Jersey / Quarkus REST) -------------------------------
        # For each method-level @<VERB>, scan BACKWARDS for the nearest
        # method-level @Path (within 256 chars) and combine with the
        # class-level prefix. The combination yields the route.
        if has_jaxrs:
            for m in _JAXRS_VERB_RE.finditer(text):
                verb = m.group("verb").upper()
                # Find the @Path that decorates this same method (i.e.
                # appears AFTER the previous method's body and BEFORE
                # the next `{`-introducing keyword like `class` or `fun`).
                # Heuristic: nearest preceding @Path within 256 chars
                # AND nearest following method declaration within 1024
                # chars.
                method_offset = m.start()
                window_before = text[max(0, method_offset - 256) : method_offset]
                m_path = None
                for pm in _JAXRS_PATH_RE.finditer(window_before):
                    m_path = pm  # take the LAST one — closest to the verb
                tail_path = m_path.group("path") if m_path else ""
                prefix = _class_prefix_path(text, m.start())
                full_path = _join_path(prefix, tail_path)
                if not full_path:
                    full_path = "/"
                line = _line_of(text, m.start())
                symbol = _method_name_after(text, m.end(), kotlin=is_kotlin) or f"jaxrs:{verb}:{full_path}"
                docstring = _javadoc_before(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=symbol,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "method": verb,
                            "path": full_path,
                            "framework": "jaxrs",
                            "binding": f"@{verb}",
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

        # ---- Ktor DSL -----------------------------------------------------
        if has_ktor:
            for m in _KTOR_VERB_RE.finditer(text):
                verb = m.group("verb").upper()
                tail_path = m.group("path")
                line = _line_of(text, m.start())
                # Ktor has no class-level path prefix; the symbol is the
                # path itself (no surrounding function name in the DSL).
                symbol = f"ktor:{verb}:{tail_path}"
                docstring = _javadoc_before(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.HTTP_ROUTE,
                        file=rel,
                        line=line,
                        symbol=symbol,
                        type_origin=TYPE_ORIGIN,
                        metadata={
                            "method": verb,
                            "path": tail_path,
                            "framework": "ktor",
                            "binding": verb.lower(),
                        },
                        docstring=docstring,
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by (file, line, symbol, method, framework). Two annotations
    # at the same line with the same framework/method are duplicates;
    # different frameworks at the same line (rare but possible if a
    # file mixes patterns) are KEPT.
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
