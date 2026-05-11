"""PlatformIO firmware discoverer — multi-framework dispatcher.

PlatformIO is a build-system layer that hosts many embedded frameworks
(arduino, espidf, stm32cube, mbed, baremetal). Each `[env:<name>]`
section in `platformio.ini` declares one (framework, board) target.

Per env we:
1. Parse `platformio.ini` with stdlib `configparser` (it's a real INI).
2. Read `framework` + `board` keys from the env section.
3. Dispatch to a per-framework extractor that scans `src/` (and `main/`
   for espidf) for the framework's natural entry-point patterns.

Each extractor yields EntryPoints with:
- `type_origin = "firmware_platformio"` (the dispatcher owns the rows
  even when arduino sketches also produce a separate firmware_arduino
  detection — that's a separate detection row, not duplicated here).
- `metadata.framework` = "arduino"|"espidf"|"stm32cube"|"mbed"|"baremetal"
- `metadata.board` = board string from the env section
- `metadata.env`   = env section name (without the "env:" prefix)

Deterministic at every step: files sorted alphabetically, envs iterated
in the order configparser yields them (which is the declaration order
in the .ini), kinds emitted in a fixed sequence per framework.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---- shared helpers ---------------------------------------------------------

_CONTENT_PREVIEW_BYTES = 131072  # 128KB — enough for typical firmware files

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".pio",  # PlatformIO build cache
        ".pioenvs",
        ".piolibdeps",
        "build",
        "dist",
        "target",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "tests",
        "test",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
    }
)


def _read(path: Path) -> str:
    try:
        return path.read_bytes()[:_CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _docstring_above(text: str, line_1based: int) -> str:
    """Return the first non-empty `//`-style comment line directly above `line_1based`.

    Best-effort: scans up to 5 lines above and stops at the first blank or
    code line. Used as the EntryPoint.docstring for firmware symbols which
    rarely have proper docstrings.
    """
    lines = text.splitlines()
    if line_1based < 2:
        return ""
    out: list[str] = []
    for i in range(line_1based - 2, max(-1, line_1based - 7), -1):
        s = lines[i].strip()
        if not s:
            break
        if s.startswith(("//", "/*", "*", "#")):
            out.append(s.lstrip("/* #").rstrip("*/").strip())
            continue
        break
    return " ".join(reversed(out)).strip()


def _iter_sources(roots: list[Path], extensions: tuple[str, ...]) -> list[Path]:
    """Sorted list of source files under `roots` with the given extensions.

    Skip-dir filtering is applied to the *relative* path parts between each
    walked file and its containing `root` — NOT to the absolute path parts.
    This is critical: when the caller runs the discoverer on a fixture
    living under `tests/fixtures/...`, the absolute path contains "tests"
    as one of its parts, but those parts are above the project root and
    must not trigger the skip filter. Walking from `root` and only
    checking `p.relative_to(root).parts` makes skip filtering local to
    the project tree, where it belongs.
    """
    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for ext in extensions:
            for p in root.rglob(f"*{ext}"):
                try:
                    rel_parts = p.relative_to(root).parts
                except ValueError:
                    rel_parts = p.parts
                if any(part in _SKIP_DIRS for part in rel_parts):
                    continue
                if not p.is_file():
                    continue
                rp = p.resolve()
                if rp in seen:
                    continue
                seen.add(rp)
                out.append(p)
    out.sort()
    return out


# ---- INI parsing ------------------------------------------------------------


def _parse_platformio_ini(ini_path: Path) -> list[tuple[str, str, str]]:
    """Return ordered list of (env_name, framework, board) tuples.

    `env_name` is the section name minus the "env:" prefix. `framework`
    and `board` default to "" when the env doesn't declare them.
    Frameworks listed as a comma-separated list are normalised to the
    first entry (deterministic, mirrors PlatformIO's primary-framework
    resolution).
    """
    parser = configparser.ConfigParser(strict=False, inline_comment_prefixes=(";", "#"))
    try:
        parser.read(ini_path, encoding="utf-8")
    except (configparser.Error, OSError):
        return []
    envs: list[tuple[str, str, str]] = []
    for section in parser.sections():
        if not section.startswith("env:"):
            continue
        env_name = section[len("env:") :].strip()
        framework_raw = (parser.get(section, "framework", fallback="") or "").strip()
        board = (parser.get(section, "board", fallback="") or "").strip()
        # Normalise: first framework in a comma-separated list wins.
        framework = framework_raw.split(",")[0].strip().lower() if framework_raw else ""
        # PlatformIO accepts both "espidf" and "esp-idf"; canonicalise.
        if framework == "esp-idf":
            framework = "espidf"
        envs.append((env_name, framework, board))
    return envs


# ---- per-framework extractors ----------------------------------------------

# Arduino: setup(), loop(), attachInterrupt(...)
_ARDUINO_SETUP_RE = re.compile(r"^\s*void\s+(setup)\s*\(\s*\)", re.MULTILINE)
_ARDUINO_LOOP_RE = re.compile(r"^\s*void\s+(loop)\s*\(\s*\)", re.MULTILINE)
# attachInterrupt's first arg is often `digitalPinToInterrupt(PIN)` — a
# nested call. The arg0 capture allows balanced parens one level deep,
# which covers the canonical Arduino form without growing into a full
# expression parser.
_ARDUINO_ATTACH_INT_RE = re.compile(
    r"\battachInterrupt\s*\(\s*"
    r"(?P<arg0>[^,\)]+(?:\([^\)]*\)[^,\)]*)?)\s*,\s*"
    r"(?P<isr>[A-Za-z_][A-Za-z0-9_]*)",
)


def _extract_arduino(repo_root: Path, env_name: str, board: str) -> list[EntryPoint]:
    src_dirs = [repo_root / "src"]
    files = _iter_sources(src_dirs, (".ino", ".cpp", ".c", ".h"))
    out: list[EntryPoint] = []
    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _ARDUINO_SETUP_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="setup",
                    type_origin="firmware_platformio",
                    metadata={"framework": "arduino", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
        for m in _ARDUINO_LOOP_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="loop",
                    type_origin="firmware_platformio",
                    metadata={"framework": "arduino", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
        for m in _ARDUINO_ATTACH_INT_RE.finditer(text):
            line = _line_of(text, m.start())
            isr = m.group("isr")
            arg0 = m.group("arg0").strip()
            out.append(
                EntryPoint(
                    kind=EntryPointKind.GPIO_INTERRUPT,
                    file=rel,
                    line=line,
                    symbol=isr,
                    type_origin="firmware_platformio",
                    metadata={
                        "framework": "arduino",
                        "board": board,
                        "env": env_name,
                        "pin_or_interrupt": arg0,
                    },
                    docstring=_docstring_above(text, line),
                )
            )
    return out


# ESP-IDF: app_main(), esp_event_handler_register(...)
_ESPIDF_APPMAIN_RE = re.compile(r"^\s*void\s+(app_main)\s*\(\s*(?:void)?\s*\)", re.MULTILINE)
# Match esp_event_handler_register CALLS only, not function declarations.
# The regex captures every textual occurrence; the extractor then filters
# out declarations by checking whether the match line starts with a C
# return-type pattern (`extern`, `esp_err_t`, `static`, etc.) — the call
# site instead begins with whitespace + the symbol or `;` + the symbol.
_ESPIDF_EVENT_HANDLER_RE = re.compile(
    r"\besp_event_handler_register\s*\(\s*"
    r"(?P<base>[^,\)]+)\s*,\s*(?P<id>[^,\)]+)\s*,\s*&?(?P<handler>[A-Za-z_][A-Za-z0-9_]*)",
)
# Token that, when it leads the line containing the match, means we are
# looking at a function declaration / prototype — NOT a call. We skip these.
_ESPIDF_DECL_PREFIXES: tuple[str, ...] = (
    "extern ",
    "static ",
    "inline ",
    "esp_err_t ",
    "void ",
    "int ",
    "uint ",
)


def _extract_espidf(repo_root: Path, env_name: str, board: str) -> list[EntryPoint]:
    src_dirs = [repo_root / "src", repo_root / "main"]
    files = _iter_sources(src_dirs, (".c", ".cpp", ".cc"))
    out: list[EntryPoint] = []
    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _ESPIDF_APPMAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="app_main",
                    type_origin="firmware_platformio",
                    metadata={"framework": "espidf", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
        text_lines = text.splitlines()
        for m in _ESPIDF_EVENT_HANDLER_RE.finditer(text):
            line = _line_of(text, m.start())
            # Filter out function declarations / prototypes (e.g.
            # `extern esp_err_t esp_event_handler_register(...)`). A call
            # at statement level cannot be preceded on the same line by a
            # C return-type keyword — that's what distinguishes the two.
            try:
                line_text = text_lines[line - 1].lstrip()
            except IndexError:
                line_text = ""
            if any(line_text.startswith(p) for p in _ESPIDF_DECL_PREFIXES):
                continue
            handler = m.group("handler")
            base = m.group("base").strip()
            event_id = m.group("id").strip()
            out.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=handler,
                    type_origin="firmware_platformio",
                    metadata={
                        "framework": "espidf",
                        "board": board,
                        "env": env_name,
                        "event_base": base,
                        "event_id": event_id,
                    },
                    docstring=_docstring_above(text, line),
                )
            )
    return out


# STM32Cube: main(), ISR functions ending with `_IRQHandler`
_STM32_MAIN_RE = re.compile(r"^\s*int\s+(main)\s*\(\s*(?:void)?\s*\)", re.MULTILINE)
_STM32_IRQ_RE = re.compile(
    r"^\s*(?:void|__attribute__\s*\([^\)]*\)\s*void)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*_IRQHandler)\s*\(",
    re.MULTILINE,
)


def _extract_stm32cube(repo_root: Path, env_name: str, board: str) -> list[EntryPoint]:
    src_dirs = [repo_root / "src"]
    files = _iter_sources(src_dirs, (".c", ".cpp", ".cc", ".h"))
    out: list[EntryPoint] = []
    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _STM32_MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="firmware_platformio",
                    metadata={"framework": "stm32cube", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
        for m in _STM32_IRQ_RE.finditer(text):
            line = _line_of(text, m.start())
            name = m.group("name")
            out.append(
                EntryPoint(
                    kind=EntryPointKind.ISR_VECTOR,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="firmware_platformio",
                    metadata={
                        "framework": "stm32cube",
                        "board": board,
                        "env": env_name,
                        "vector": name,
                    },
                    docstring=_docstring_above(text, line),
                )
            )
    return out


# Mbed: main() — best-effort, MAIN_FUNCTION kind
_MBED_MAIN_RE = re.compile(r"^\s*int\s+(main)\s*\(\s*(?:void)?\s*\)", re.MULTILINE)


def _extract_mbed(repo_root: Path, env_name: str, board: str) -> list[EntryPoint]:
    src_dirs = [repo_root / "src"]
    files = _iter_sources(src_dirs, (".c", ".cpp", ".cc"))
    out: list[EntryPoint] = []
    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _MBED_MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="firmware_platformio",
                    metadata={"framework": "mbed", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
            # Mbed's main is also the program's natural MAIN_FUNCTION;
            # emit both kinds so walkers using either taxonomy match.
            out.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="firmware_platformio",
                    metadata={"framework": "mbed", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
    return out


# Baremetal: _start, Reset_Handler
_BAREMETAL_START_RE = re.compile(
    r"^\s*(?:void|extern\s+\"C\"\s+void|__attribute__\s*\([^\)]*\)\s*void)\s+(_start)\s*\(",
    re.MULTILINE,
)
_BAREMETAL_RESET_RE = re.compile(
    r"^\s*(?:void|extern\s+\"C\"\s+void|__attribute__\s*\([^\)]*\)\s*void)\s+(Reset_Handler)\s*\(",
    re.MULTILINE,
)


def _extract_baremetal(repo_root: Path, env_name: str, board: str) -> list[EntryPoint]:
    src_dirs = [repo_root / "src"]
    files = _iter_sources(src_dirs, (".c", ".cpp", ".cc", ".s", ".S"))
    out: list[EntryPoint] = []
    for path in files:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))
        for m in _BAREMETAL_START_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="_start",
                    type_origin="firmware_platformio",
                    metadata={"framework": "baremetal", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
        for m in _BAREMETAL_RESET_RE.finditer(text):
            line = _line_of(text, m.start())
            out.append(
                EntryPoint(
                    kind=EntryPointKind.RESET_PATH,
                    file=rel,
                    line=line,
                    symbol="Reset_Handler",
                    type_origin="firmware_platformio",
                    metadata={"framework": "baremetal", "board": board, "env": env_name},
                    docstring=_docstring_above(text, line),
                )
            )
    return out


# ---- dispatcher -------------------------------------------------------------

_FRAMEWORK_DISPATCH = {
    "arduino": _extract_arduino,
    "espidf": _extract_espidf,
    "stm32cube": _extract_stm32cube,
    "mbed": _extract_mbed,
    "baremetal": _extract_baremetal,
}


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Discover entry points across all `[env:*]` sections in `platformio.ini`.

    The `languages` parameter is informational only — PlatformIO projects
    are always C/C++/Arduino regardless of what the language detector
    reports. We never gate on it.
    """
    repo_root = repo_root.resolve()
    ini = repo_root / "platformio.ini"
    if not ini.exists():
        return []

    envs = _parse_platformio_ini(ini)
    if not envs:
        return []

    found: list[EntryPoint] = []
    # Process envs in a stable order — sort by env name so two declarations
    # in different orders still yield byte-identical output.
    for env_name, framework, board in sorted(envs, key=lambda t: t[0]):
        extractor = _FRAMEWORK_DISPATCH.get(framework)
        if extractor is None:
            # Unknown / missing framework: skip this env. The walker
            # surface stays type-blind; no EntryPoints for an env we
            # can't classify.
            continue
        found.extend(extractor(repo_root, env_name, board))

    # Dedup by (file, line, symbol, kind, env): two envs may legitimately
    # report the same symbol (e.g. shared `src/main.c` used in two envs)
    # and we want one row per (env, symbol) — the env name lives in
    # metadata, so include it in the key.
    seen: set[tuple[str, int, str, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        env = str(ep.metadata.get("env", ""))
        key = (ep.file, ep.line, ep.symbol, ep.kind.value, env)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(
        key=lambda e: (
            e.sort_key(),
            str(e.metadata.get("env", "")),
            e.kind.value,
        )
    )
    return unique
