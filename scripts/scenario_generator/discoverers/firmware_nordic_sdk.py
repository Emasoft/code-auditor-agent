"""Nordic nRF5 SDK firmware discoverer.

Finds the canonical entry points exposed by a Nordic nRF5 SDK application
(Makefile-driven, pre-Zephyr; the SDK headers all live under
`components/`, `libraries/`, and similar with `nrf_` / `nrfx_` /
`NRF_SDK` substrings — which is what the fingerprint matches on).

- `int main(void)` → MAIN_FUNCTION — the Nordic SDK boot entry.
- `ble_evt_handler` (or any function whose name ends in
  `_ble_evt_handler`) → EVENT_LISTENER with metadata `{event_source:
  "ble"}` — these handle SoftDevice BLE events.
- `*_timeout_handler` → EVENT_LISTENER with metadata `{event_source:
  "app_timer"}` — these are app-timer expiry callbacks. (Nordic SDK
  convention: any callback ending in `_timeout_handler` is wired via
  `app_timer_create`.)
- `*_event_handler` (suffix, excluding the `_ble_*` and `_timeout_*`
  cases already handled above) → EVENT_LISTENER with metadata
  `{event_source: "gpiote"}` — covers GPIOTE / button-driver / SAADC /
  TWI / etc. event-handler callbacks. The walker reasons over the
  callback regardless of the underlying peripheral.

`type_origin` is hard-coded to `"firmware_nordic_sdk"`. The walker is
type-blind and reads only the EntryPoint schema fields; type knowledge
is crystallised into the metadata dict.

Heuristic, not AST-perfect, but deterministic. Output is sorted by
`(file, line, symbol, kind)` — required for byte-identical goldens.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# int main(void) — column-zero, void-arg. Nordic SDK boilerplate uses
# this signature exclusively (no `int main(int, char**)` variant exists
# in any nRF5 SDK sample).
_MAIN_RE = re.compile(r"^\s*int\s+main\s*\(\s*void\s*\)\s*\{", re.MULTILINE)

# Function-definition shape we use for callback discovery:
#   static? <return-type> <name>(...)\s*\{
# The return type is one C-style word (we don't try to handle pointer
# returns or complex type expressions — those are vanishingly rare in
# callback signatures the SDK exposes).
_FN_DEF_RE = re.compile(
    r"^\s*(?:static\s+)?(?:void|int|uint8_t|uint16_t|uint32_t|bool|ret_code_t)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "out",
        "bin",
        "obj",
        # Pre-shipped SDK components live under one of these — they aren't
        # the user's application code so they don't contribute scenarios.
        "components",
        "external",
        "libraries",
        "softdevice",
        "modules",
        # Tests / fixtures bundled in nested example apps.
        "tests",
        "test",
        "samples",
        "sample",
        "examples",
        "example",
        "doc",
        "docs",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "samples_dev",
        "examples_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128 KiB — nRF SDK application files almost never exceed this


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path`. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _iter_c_files(repo_root: Path) -> list[Path]:
    """Sorted list of *.c files under `repo_root`, with skip-dirs filtered.

    Skip-dir filtering uses path components RELATIVE to `repo_root` so
    fixtures under `tests/fixtures/...` aren't dropped.
    """
    out: list[Path] = []
    for p in repo_root.rglob("*.c"):
        if not p.is_file():
            continue
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        out.append(p)
    out.sort()
    return out


def _classify_callback(name: str) -> str | None:
    """Return the event-source string for a known callback-suffix pattern.

    Order matters: `_ble_evt_handler` and `_timeout_handler` are matched
    first because they're more specific than the generic `_event_handler`
    suffix. Names that don't match any of the three patterns return None
    and are not emitted as entry points.
    """
    if name == "ble_evt_handler" or name.endswith("_ble_evt_handler"):
        return "ble"
    if name.endswith("_timeout_handler"):
        return "app_timer"
    if name.endswith("_event_handler"):
        return "gpiote"
    return None


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find nRF5 SDK entry points. Deterministic order.

    `languages` is the language list emitted by the language detector.
    We require `"c"` to be present.
    """
    if "c" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_c_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # ---- int main(void) → MAIN_FUNCTION -------------------------------
        for m in _MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="firmware_nordic_sdk",
                    metadata={"role": "nrf_main"},
                )
            )

        # ---- function-def → callback classification → EVENT_LISTENER ------
        for m in _FN_DEF_RE.finditer(text):
            name = m.group("name")
            source = _classify_callback(name)
            if source is None:
                continue
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=name,
                    type_origin="firmware_nordic_sdk",
                    metadata={"event_source": source},
                )
            )

    # Dedup by (file, line, symbol, kind) — the same callback declared in
    # a header AND defined in a .c file would otherwise appear twice; we
    # keep one entry per source location.
    seen: set[tuple[str, int, str, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol, ep.kind.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)

    unique.sort(key=lambda e: (e.sort_key(), e.kind.value))
    return unique
