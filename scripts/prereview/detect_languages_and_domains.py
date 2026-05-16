#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Step 0 — Domain detection pre-flight gate (TRDD-7e364ace cluster N0).

Pure-Python, zero-LLM, deterministic gate that classifies a repository by
language and domain, then emits `domains_detected.json`. Downstream
specialist agents (steps 20-21) read the `specialist_firing` block to
decide whether to fire — saving the entire token cost of a specialist
review when its domain is absent.

Detection sources per category:

LANGUAGES — extension count plus manifest evidence.
DOMAINS  — manifest text scan plus a bounded sample of source-file content.

A repository can match many domains simultaneously (a Flask + React + Postgres
monorepo with i18n is detected as all of {python, javascript, typescript,
frontend, rest_api, sql_migrations, monorepo, i18n} at once). Detection is
inclusive — false negatives are the failure mode we minimise here, since a
missing domain marker silently skips a specialist agent. Detection rules
are intentionally conservative on disambiguation but generous on inclusion.

Usage:
    python -m scripts.prereview.detect_languages_and_domains <repo_root> <out_dir>

Output:
    <out_dir>/<ts>-domains_detected.json  (always-on, gate emits even if
                                            nothing matched — downstream
                                            agents need the empty record).

Exit codes:
    0  — JSON file written. Detection results are inside the JSON, not in
         the exit code. A repo with zero matches still exits 0.
    1  — Infrastructure failure (bad CLI args, repo_root not a directory,
         out_dir unwritable). Stderr explains; nothing is written.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
CONTENT_PREVIEW_BYTES = 65536
MANIFEST_PREVIEW_BYTES = 131072  # manifests can be larger (Cargo.lock, package-lock)
SOURCE_SAMPLE_PER_LANGUAGE = 200  # cap source-file content scans per language
MAX_FILES_WALKED = 200_000  # hard ceiling — protects against runaway scans
MULTI_TENANT_MIN_HITS = 3  # need ≥3 distinct files mentioning a tenant marker

# Directories never traversed (caches, builds, deps, dev scratch).
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
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
        ".tox",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        ".cache",
        ".idea",
        ".vscode",
        ".gradle",
        ".cargo",
        ".terraform",
        ".pulumi",
        ".trashcan",
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

# Language → file-extension set (lowercase, leading dot). Order matters only
# for the `evidence` field; detection itself is order-independent.
_LANGUAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "python": (".py", ".pyi"),
    "javascript": (".js", ".mjs", ".cjs", ".jsx"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "go": (".go",),
    "rust": (".rs",),
    "swift": (".swift",),
    "elixir": (".ex", ".exs"),
    "solidity": (".sol",),
}

# Language → manifest globs (relative). Extension-only matches don't count
# as the language unless a manifest is also present OR the file count is
# large enough that "this is the language" is unambiguous.
_LANGUAGE_MANIFESTS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "poetry.lock"),
    "javascript": ("package.json",),
    "typescript": ("tsconfig.json", "package.json"),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "swift": ("Package.swift",),
    "elixir": ("mix.exs",),
    "solidity": ("foundry.toml", "hardhat.config.js", "hardhat.config.ts", "truffle-config.js"),
}

# Minimum file count for a language to be "detected" on extension alone
# (no manifest). Single stray .py in a Rust project shouldn't make it a
# Python project; but a 100-file .py tree without a manifest still should.
_LANGUAGE_FILES_WITHOUT_MANIFEST: int = 10


@dataclass(frozen=True, slots=True)
class _DomainRule:
    """One row of the domain registry."""

    name: str
    manifest_patterns: tuple[str, ...] = ()
    manifest_substrings: tuple[str, ...] = ()
    file_globs: tuple[str, ...] = ()
    source_patterns: tuple[str, ...] = ()  # regex, applied to first 64KB of source files
    requires_language: tuple[str, ...] = ()  # only relevant if one of these langs detected


# Domain registry. Conservative on disambiguation; generous on inclusion.
# Source patterns are compiled lazily and applied only to languages present.
_DOMAIN_RULES: tuple[_DomainRule, ...] = (
    _DomainRule(
        name="graphql",
        manifest_substrings=(
            "graphql",
            "@apollo/server",
            "@apollo/client",
            "ariadne",
            "strawberry-graphql",
            "graphql-tag",
            "graphene",
            "gqlgen",
        ),
        file_globs=("**/*.graphql", "**/*.gql"),
        source_patterns=(r"\btype\s+Query\b", r"\bextend\s+type\s+Query\b", r"\bResolver\b"),
    ),
    _DomainRule(
        name="jwt",
        manifest_substrings=(
            "jsonwebtoken",
            "pyjwt",
            "python-jose",
            "@nestjs/jwt",
            "fastapi-jwt-auth",
            "jose",
            "jwt-decode",
            "ruby-jwt",
            "go-jwt",
            "jose4j",
        ),
        source_patterns=(r"\bjwt\.(sign|verify|decode)\b", r"\bjwt\.encode\b", r"\bRS256\b", r"\bHS256\b"),
    ),
    _DomainRule(
        name="docker",
        manifest_patterns=(
            "Dockerfile",
            "Containerfile",
            "Dockerfile.*",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ),
    ),
    _DomainRule(
        name="sql_migrations",
        manifest_patterns=(
            "alembic.ini",
            "schema.prisma",
            "**/migrations/**/*.sql",
            "**/migrations/**/*.py",
            "**/migrations/env.py",
            "**/migrations/versions/**",
            "**/db/migrate/**",
            "**/priv/repo/migrations/**",
            "**/*.sql",
        ),
        manifest_substrings=("sqlalchemy", "alembic", "prisma", "drizzle-orm", "knex", "django>="),
    ),
    _DomainRule(
        name="frontend",
        manifest_substrings=(
            '"react"',
            '"vue"',
            '"svelte"',
            "@angular/core",
            "@solidjs/start",
            "qwik",
            "next",
            "nuxt",
            "remix",
            "preact",
            "astro",
            '"vite"',
        ),
        file_globs=("**/*.tsx", "**/*.jsx", "**/*.vue", "**/*.svelte", "**/*.astro"),
    ),
    _DomainRule(
        name="mcp_server",
        manifest_substrings=(
            "@modelcontextprotocol/sdk",
            "modelcontextprotocol",
            "mcp-server",
            "fastmcp",
            "mcp[cli]",
        ),
        source_patterns=(
            r"@mcp\.tool\b",
            r"from\s+mcp\b",
            r"\bMcpServer\b",
            r"\bFastMCP\b",
        ),
    ),
    _DomainRule(
        name="multi_tenant",
        source_patterns=(
            r"\btenant_id\b",
            r"\borg_id\b",
            r"\borganization_id\b",
            r"\bworkspace_id\b",
            r"\baccount_id\b",
        ),
    ),
    _DomainRule(
        name="prompt_templates",
        manifest_substrings=(
            "openai",
            "anthropic",
            "langchain",
            "llamaindex",
            "litellm",
            "@ai-sdk",
            "vercel-ai",
            "cohere",
            "google-generativeai",
        ),
        source_patterns=(
            r"\bChatCompletion\b",
            r"\bclient\.messages\.create\b",
            r"\bsystem_prompt\b",
            r"\bPromptTemplate\b",
            r"\binvoke_model\b",
        ),
    ),
    _DomainRule(
        name="rest_api",
        manifest_substrings=(
            "fastapi",
            "flask",
            '"express"',
            "@nestjs/core",
            "django",
            "sinatra",
            "gin-gonic",
            "echo",
            "fiber",
            "starlette",
            "hono",
            "sanic",
        ),
        source_patterns=(
            r"@app\.(?:route|get|post|put|delete|patch)\b",
            r"@router\.(?:get|post|put|delete|patch)\b",
            r"\bapp\.(?:get|post|put|delete|patch)\s*\(",
        ),
    ),
    _DomainRule(
        name="ios_native",
        manifest_patterns=("**/*.xcodeproj", "**/*.xcworkspace", "Package.swift"),
        file_globs=("**/*.swift",),
        source_patterns=(r"\bimport\s+SwiftUI\b", r"\bimport\s+UIKit\b", r"\bimport\s+CryptoKit\b"),
        requires_language=("swift",),
    ),
    _DomainRule(
        name="elixir_phoenix",
        manifest_substrings=(":phoenix,", ":phoenix_live_view,", "{:phoenix,"),
        file_globs=("**/*.eex", "**/*.heex", "**/*_web/**", "**/lib/*_web/**"),
        requires_language=("elixir",),
    ),
    _DomainRule(
        name="solidity_contracts",
        file_globs=("**/*.sol",),
        requires_language=("solidity",),
    ),
    _DomainRule(
        name="i18n",
        file_globs=(
            "**/locale/**/*.po",
            "**/locales/**/*.json",
            "**/i18n/**/*.json",
            "**/translations/**",
            "**/messages/**/*.po",
        ),
        manifest_substrings=("react-intl", "next-intl", "i18next", "vue-i18n", "gettext"),
    ),
    _DomainRule(
        name="l10n",
        # Same dirs as i18n but signalled by manifest entries that go beyond
        # message catalogues (date/number/currency formatters, RTL support,
        # ICU MessageFormat).
        manifest_substrings=("formatjs", "@formatjs", "icu-messageformat", "globalize", "luxon"),
        source_patterns=(r"\bIntl\.NumberFormat\b", r"\bIntl\.DateTimeFormat\b", r"\bbabel-plugin-formatjs\b"),
    ),
    _DomainRule(
        name="monorepo",
        manifest_patterns=("pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json", "rush.json"),
        manifest_substrings=('"workspaces"', "[workspace]"),
    ),
    _DomainRule(
        name="logging_framework",
        manifest_substrings=(
            "structlog",
            "loguru",
            '"winston"',
            '"pino"',
            "log4j",
            "logback",
            "zap",
            "zerolog",
            "slog",
            "log/log",
            "tracing",
        ),
        source_patterns=(r"\bimport\s+logging\b", r"\blogger\s*=\s*logging\.getLogger\b"),
    ),
)

# Map specialist agent → list of domain markers that gate its firing.
# A specialist fires if ANY of its gating markers is True.
_SPECIALIST_GATES: dict[str, tuple[str, ...]] = {
    "multi_tenant_detector": ("multi_tenant",),
    "graphql_reviewer": ("graphql",),
    "jwt_reviewer": ("jwt",),
    "api_design_reviewer": ("rest_api", "graphql"),
    "docker_reviewer": ("docker",),
    "prompt_injection_reviewer": ("prompt_templates",),
    "frontend_reviewer": ("frontend",),
    "ios_reviewer": ("ios_native",),
    "elixir_reviewer": ("elixir_phoenix",),
    "solidity_reviewer": ("solidity_contracts",),
    "mcp_server_reviewer": ("mcp_server",),
    "i18n_reviewer": ("i18n",),
    "l10n_reviewer": ("l10n",),
    "monorepo_reviewer": ("monorepo",),
    "logging_reviewer": ("logging_framework",),
}


@dataclass(slots=True)
class _DetectionState:
    """Mutable scratch state during scanning."""

    repo_root: Path
    all_files: list[Path] = field(default_factory=list)
    language_files: dict[str, list[Path]] = field(default_factory=dict)
    manifest_paths: list[Path] = field(default_factory=list)
    manifest_text: dict[Path, str] = field(default_factory=dict)
    files_walked: int = 0


def _git_ls_files(repo_root: Path) -> list[Path] | None:
    """Try `git ls-files` for accurate gitignore-respecting enumeration.

    Returns None if the repo is not a git checkout or git is unavailable.
    The fall-back walker honours `_SKIP_DIRS` but cannot read `.gitignore`.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout
    if not raw:
        return []
    rels = raw.split(b"\0")
    paths: list[Path] = []
    for rel in rels:
        if not rel:
            continue
        try:
            decoded = rel.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(part in _SKIP_DIRS for part in decoded.split("/")):
            continue
        paths.append(repo_root / decoded)
    paths.sort()
    return paths


def _walk_files(repo_root: Path) -> Iterable[Path]:
    """Fallback walker (used when not a git checkout). Honours `_SKIP_DIRS`."""
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fname in sorted(filenames):
            yield Path(dirpath) / fname


def _enumerate_repo(repo_root: Path) -> list[Path]:
    """Return a deterministic, gitignore-respecting list of files."""
    git_paths = _git_ls_files(repo_root)
    if git_paths is not None:
        return git_paths
    out: list[Path] = []
    for p in _walk_files(repo_root):
        out.append(p)
        if len(out) >= MAX_FILES_WALKED:
            break
    return out


def _read_text_capped(path: Path, cap: int) -> str:
    """Read at most `cap` bytes, decoding as utf-8 ignoring errors."""
    try:
        with path.open("rb") as f:
            data = f.read(cap)
    except OSError:
        return ""
    return data.decode("utf-8", errors="ignore")


def _classify_languages(state: _DetectionState, files: list[Path]) -> None:
    """Bucket files by language extension; collect manifest paths."""
    by_lang: dict[str, list[Path]] = {lang: [] for lang in _LANGUAGE_EXTENSIONS}
    manifests: list[Path] = []
    # Build a flat set of manifest filenames for fast O(1) match.
    manifest_filenames: dict[str, list[str]] = {
        lang: [m for m in mans if "*" not in m and "/" not in m] for lang, mans in _LANGUAGE_MANIFESTS.items()
    }
    # Also pre-compute "is this filename a manifest" lookup.
    all_manifest_names: frozenset[str] = frozenset(name for names in manifest_filenames.values() for name in names)

    for path in files:
        state.files_walked += 1
        suffix = path.suffix.lower()
        name = path.name
        for lang, exts in _LANGUAGE_EXTENSIONS.items():
            if suffix in exts:
                by_lang[lang].append(path)
        if name in all_manifest_names:
            manifests.append(path)
        # xcodeproj / xcworkspace / Package.swift are directories or special
        # — we picked up Package.swift by name; the dir-form xcodeproj is
        # not in _LANGUAGE_MANIFESTS so we leave it for the domain pass.

    state.language_files = by_lang
    state.manifest_paths = manifests
    state.all_files = list(files)
    # Pre-load manifest text (capped) for use by both language detection
    # tiebreakers and domain pass.
    for manifest in manifests:
        state.manifest_text[manifest] = _read_text_capped(manifest, MANIFEST_PREVIEW_BYTES)


def _detect_languages(state: _DetectionState) -> dict[str, dict[str, object]]:
    """Decide for each language: detected? evidence?"""
    result: dict[str, dict[str, object]] = {}
    manifest_names_by_lang: dict[str, frozenset[str]] = {
        lang: frozenset(m for m in mans if "*" not in m and "/" not in m) for lang, mans in _LANGUAGE_MANIFESTS.items()
    }
    have_manifest: dict[str, list[str]] = {lang: [] for lang in _LANGUAGE_EXTENSIONS}
    for manifest in state.manifest_paths:
        for lang, names in manifest_names_by_lang.items():
            if manifest.name in names:
                have_manifest[lang].append(manifest.name)
    for lang in _LANGUAGE_EXTENSIONS:
        files = state.language_files.get(lang, [])
        manifests = sorted(set(have_manifest.get(lang, [])))
        # typescript / javascript share package.json as a manifest, so the
        # manifest alone is not proof — the matching source-file extensions
        # must also be present. A pure-TS project has package.json + tsconfig
        # + zero .js, so without the file-extension gate JS would falsely
        # fire. A pure-JS project has package.json + zero .ts, so without
        # the same gate TS would falsely fire. Cap with a no-manifest
        # threshold so language-by-extension-alone still works on Make-
        # built tarballs with no manifest at all.
        if lang == "typescript":
            tsconfig_present = "tsconfig.json" in manifests
            has_ts_files = len(files) > 0
            detected = (tsconfig_present and has_ts_files) or (len(files) >= _LANGUAGE_FILES_WITHOUT_MANIFEST)
        elif lang == "javascript":
            has_js_files = len(files) > 0
            detected = (bool(manifests) and has_js_files) or (len(files) >= _LANGUAGE_FILES_WITHOUT_MANIFEST)
        else:
            detected = bool(manifests) or len(files) >= _LANGUAGE_FILES_WITHOUT_MANIFEST
        evidence: list[str] = []
        ext_breakdown: dict[str, int] = {}
        for p in files:
            ext_breakdown[p.suffix.lower()] = ext_breakdown.get(p.suffix.lower(), 0) + 1
        for ext in sorted(ext_breakdown):
            count = ext_breakdown[ext]
            evidence.append(f"{count} {ext} file{'s' if count != 1 else ''}")
        for m in manifests:
            evidence.append(f"manifest: {m}")
        result[lang] = {
            "detected": detected,
            "file_count": len(files),
            "evidence": evidence,
        }
    return result


def _compile_source_patterns(domain: _DomainRule) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in domain.source_patterns]


def _domain_file_globs_match(repo_root: Path, files: list[Path], globs: tuple[str, ...]) -> list[str]:
    """Return relative paths of files matching any of the given globs.

    Globs use `Path.match` semantics (relative-path matching). Result is
    sorted and capped at 10 entries for the evidence list.
    """
    if not globs:
        return []
    matches: list[str] = []
    for f in files:
        try:
            rel = f.relative_to(repo_root)
        except ValueError:
            continue
        rel_posix = rel.as_posix()
        for g in globs:
            # `Path.match` supports basic globbing; we treat `**` as "any".
            # The cheapest correct check: substring match on the simplified
            # glob (drop the leading `**/`) for full-path semantics, then
            # final-segment match for filename-only globs.
            simplified = g.removeprefix("**/").removeprefix("/")
            if "/" in simplified:
                # full-path style: just substring-test the simplified shape.
                # Convert any remaining `**` to a path component wildcard.
                normalized = simplified.replace("**/", "").replace("**", "")
                if normalized and normalized in rel_posix:
                    matches.append(rel_posix)
                    break
            else:
                # filename style: match the basename via simple wildcard.
                if _filename_glob_match(f.name, simplified):
                    matches.append(rel_posix)
                    break
    matches = sorted(set(matches))
    return matches[:10]


def _filename_glob_match(name: str, pattern: str) -> bool:
    """Cheap, deterministic filename matcher supporting `*` only."""
    if pattern == name:
        return True
    if "*" not in pattern:
        return False
    # Translate pattern → regex anchored at both ends.
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.match(regex, name) is not None


def _detect_domains(state: _DetectionState, languages: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Apply each domain rule, collecting evidence.

    `manifest_patterns` and `file_globs` are both scanned against the
    repo-wide `state.all_files` so domain markers that aren't classified
    as language manifests (Dockerfile, docker-compose.yml, schema.prisma,
    *.graphql, alembic.ini, etc.) still surface.
    """
    detected_langs = {lang for lang, info in languages.items() if info["detected"]}
    repo_root = state.repo_root
    all_files = state.all_files
    result: dict[str, dict[str, object]] = {}

    for rule in _DOMAIN_RULES:
        if rule.requires_language and not (set(rule.requires_language) & detected_langs):
            result[rule.name] = {"detected": False, "evidence": []}
            continue
        evidence: list[str] = []
        # 1. Manifest filename globs — match against ALL files, not just
        # language manifests, so Dockerfile / *.graphql / schema.prisma fire.
        for fileset_match in _domain_file_globs_match(repo_root, all_files, rule.manifest_patterns):
            evidence.append(f"manifest-path: {fileset_match}")
        # 2. Manifest text substring scan (already cached).
        if rule.manifest_substrings:
            subs = tuple(rule.manifest_substrings)
            for mpath, text in state.manifest_text.items():
                try:
                    rel = mpath.relative_to(repo_root).as_posix()
                except ValueError:
                    rel = mpath.name
                # Find first matching substring per manifest for compact evidence.
                for sub in subs:
                    if sub in text:
                        evidence.append(f"manifest-dep: {rel} contains '{sub}'")
                        break
        # 3. Repo-wide file glob (looser than manifest globs).
        for hit in _domain_file_globs_match(repo_root, all_files, rule.file_globs):
            evidence.append(f"file: {hit}")
        # 4. Source-pattern regex sweep against a bounded sample.
        if rule.source_patterns:
            patterns = _compile_source_patterns(rule)
            sources_to_scan: list[Path] = []
            if rule.requires_language:
                for lang in rule.requires_language:
                    sources_to_scan.extend(state.language_files.get(lang, [])[:SOURCE_SAMPLE_PER_LANGUAGE])
            else:
                # Scan a sample across every detected language. Cap each
                # language's contribution so a giant monorepo doesn't blow
                # up the scan time.
                for lang in sorted(detected_langs):
                    sources_to_scan.extend(state.language_files.get(lang, [])[:SOURCE_SAMPLE_PER_LANGUAGE])
            file_hits: dict[str, str] = {}  # rel → matched pattern preview
            for src in sources_to_scan:
                text = _read_text_capped(src, CONTENT_PREVIEW_BYTES)
                if not text:
                    continue
                for pat in patterns:
                    m = pat.search(text)
                    if m:
                        try:
                            rel = src.relative_to(repo_root).as_posix()
                        except ValueError:
                            rel = src.name
                        file_hits[rel] = m.group(0)
                        break
            for rel in sorted(file_hits)[:10]:
                evidence.append(f"src: {rel} :: {file_hits[rel]}")
        # multi_tenant has an extra confidence gate — require ≥N distinct file
        # hits before claiming the project is genuinely multi-tenant.
        if rule.name == "multi_tenant":
            file_hits_n = sum(1 for e in evidence if e.startswith("src: "))
            detected = file_hits_n >= MULTI_TENANT_MIN_HITS
        else:
            detected = bool(evidence)
        # Evidence is deterministic via sorted insertion + dedup.
        seen: set[str] = set()
        deduped: list[str] = []
        for ev in evidence:
            if ev not in seen:
                seen.add(ev)
                deduped.append(ev)
        result[rule.name] = {"detected": detected, "evidence": deduped}
    return result


def _compute_specialist_firing(domains: dict[str, dict[str, object]]) -> dict[str, bool]:
    """Map specialist agent → bool from domain detection."""
    fired: dict[str, bool] = {}
    for spec, gates in _SPECIALIST_GATES.items():
        fired[spec] = any(domains.get(g, {}).get("detected") for g in gates)
    return fired


def _local_timestamp() -> str:
    """`%Y%m%d_%H%M%S%z` — local time with GMT offset, per agent-reports rule."""
    return time.strftime("%Y%m%d_%H%M%S%z", time.localtime())


def detect(repo_root: Path) -> dict[str, object]:
    """Pure detection — returns the assembled JSON-ready dict.

    Does NOT write to disk. The CLI wrapper handles file output. Exposed
    separately so the unit tests can call it on fixture trees without
    needing a temp out_dir.
    """
    if not repo_root.is_dir():
        raise NotADirectoryError(f"repo_root is not a directory: {repo_root}")
    state = _DetectionState(repo_root=repo_root)
    files = _enumerate_repo(repo_root)
    _classify_languages(state, files)
    languages = _detect_languages(state)
    domains = _detect_domains(state, languages)
    specialist_firing = _compute_specialist_firing(domains)
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _local_timestamp(),
        "repo_root": str(repo_root.resolve()),
        "files_walked": state.files_walked,
        "languages": languages,
        "domains": domains,
        "specialist_firing": specialist_firing,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: python -m scripts.prereview.detect_languages_and_domains <repo_root> <out_dir>",
            file=sys.stderr,
        )
        return 1
    repo_root = Path(argv[1]).resolve()
    out_dir = Path(argv[2]).resolve()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"out_dir unwritable: {exc}", file=sys.stderr)
        return 1
    try:
        payload = detect(repo_root)
    except NotADirectoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_path = out_dir / f"{payload['timestamp']}-domains_detected.json"
    # `sort_keys=True` makes byte-identical output deterministic across runs
    # (modulo the timestamp field, which the byte-identical test pins).
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
