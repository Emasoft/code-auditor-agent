"""ESP-IDF (ESP32) firmware discoverer.

Finds the canonical entry points exposed by an ESP-IDF application
(`sdkconfig` + `main/CMakeLists.txt` + `main/main.c`):

- `void app_main(void)` → BOOT_PATH — ESP-IDF's post-bootloader entry.
- `xTaskCreate(<task_fn>, <name>, <stack>, <param>, <prio>, <handle>)`
  → RTOS_TASK — one entry per `<task_fn>` argument site. `<name>` (if a
  string literal) and `<stack>`, `<prio>` are kept on `metadata`.
- `xTaskCreatePinnedToCore(<task_fn>, <name>, <stack>, <param>, <prio>,
  <handle>, <core>)` → RTOS_TASK — same as above with the `core_id`
  metadata extra.
- `esp_event_handler_register(...)` callback target → EVENT_LISTENER —
  registered ESP event handler (the `event_handler_arg` symbol).

`type_origin` is hard-coded to `"firmware_espidf"`. The walker is
type-blind and reads only the EntryPoint schema fields; type knowledge
is crystallised into the metadata dict.

Heuristic, not AST-perfect, but deterministic. Output is sorted by
`(file, line, symbol, kind)` — required for byte-identical goldens.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# void app_main(void) { ... } — at column 0. Whitespace before `void`
# is tolerated; `\s*` at the start prevents matching nested declarations.
_APP_MAIN_RE = re.compile(r"^\s*void\s+app_main\s*\(\s*void\s*\)\s*\{", re.MULTILINE)

# xTaskCreate(fn, name, stack, param, prio, handle)
# DOTALL so multi-line invocations work. The string-literal `name` and
# numeric `stack` / `prio` are captured raw — we don't re-interpret them.
_XTASK_CREATE_RE = re.compile(
    r"\bxTaskCreate\s*\(\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r'"(?P<name>[^"]*)"\s*,\s*'
    r"(?P<stack>[^,]+?)\s*,\s*"
    r"(?P<param>[^,]+?)\s*,\s*"
    r"(?P<prio>[^,]+?)\s*,\s*"
    r"(?P<handle>[^)]+?)\s*\)",
    re.DOTALL,
)

# xTaskCreatePinnedToCore — same signature plus a trailing `core_id`.
_XTASK_CREATE_PINNED_RE = re.compile(
    r"\bxTaskCreatePinnedToCore\s*\(\s*"
    r"(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r'"(?P<name>[^"]*)"\s*,\s*'
    r"(?P<stack>[^,]+?)\s*,\s*"
    r"(?P<param>[^,]+?)\s*,\s*"
    r"(?P<prio>[^,]+?)\s*,\s*"
    r"(?P<handle>[^,]+?)\s*,\s*"
    r"(?P<core>[^)]+?)\s*\)",
    re.DOTALL,
)

# esp_event_handler_register(base, id, handler, arg) — the canonical IDF
# event registration. `<handler>` is the entry; `<base>` / `<id>` go on
# `metadata` as the event source descriptor.
_ESP_EVENT_REGISTER_RE = re.compile(
    r"\besp_event_handler_register\s*\(\s*"
    r"(?P<base>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<event_id>[^,]+?)\s*,\s*"
    r"(?P<handler>[A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
    r"(?P<arg>[^)]+?)\s*\)",
    re.DOTALL,
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
        # ESP-IDF generates these under the project root.
        "managed_components",
        "components",
        "sdkconfig.old",
        # Tests/examples shipped in nested folders.
        "tests",
        "test",
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


CONTENT_PREVIEW_BYTES = 131072  # 128 KiB — ESP-IDF main.c files almost never exceed this


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
    """Sorted list of *.c / *.cpp files under `repo_root`, with skip-dirs filtered.

    Skip-dir filtering uses path components RELATIVE to `repo_root` so we
    don't accidentally drop files under `tests/fixtures/...`.
    """
    out: list[Path] = []
    for ext in ("*.c", "*.cpp"):
        for p in repo_root.rglob(ext):
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


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find ESP-IDF entry points. Deterministic order.

    `languages` is the language list emitted by the language detector.
    We require `"c"` or `"cpp"` to be present.
    """
    if "c" not in languages and "cpp" not in languages:
        return []

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_c_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # ---- app_main → BOOT_PATH -----------------------------------------
        for m in _APP_MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol="app_main",
                    type_origin="firmware_espidf",
                    metadata={"role": "espidf_app_main"},
                )
            )

        # ---- xTaskCreate → RTOS_TASK --------------------------------------
        for m in _XTASK_CREATE_RE.finditer(text):
            fn = m.group("fn")
            name = m.group("name")
            stack = m.group("stack").strip()
            prio = m.group("prio").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RTOS_TASK,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin="firmware_espidf",
                    metadata={
                        "macro": "xTaskCreate",
                        "task_name": name,
                        "stack": stack,
                        "priority": prio,
                    },
                )
            )

        # ---- xTaskCreatePinnedToCore → RTOS_TASK --------------------------
        for m in _XTASK_CREATE_PINNED_RE.finditer(text):
            fn = m.group("fn")
            name = m.group("name")
            stack = m.group("stack").strip()
            prio = m.group("prio").strip()
            core = m.group("core").strip()
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.RTOS_TASK,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin="firmware_espidf",
                    metadata={
                        "macro": "xTaskCreatePinnedToCore",
                        "task_name": name,
                        "stack": stack,
                        "priority": prio,
                        "core_id": core,
                    },
                )
            )

        # ---- esp_event_handler_register → EVENT_LISTENER ------------------
        for m in _ESP_EVENT_REGISTER_RE.finditer(text):
            base = m.group("base")
            event_id = m.group("event_id").strip()
            handler = m.group("handler")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.EVENT_LISTENER,
                    file=rel,
                    line=line,
                    symbol=handler,
                    type_origin="firmware_espidf",
                    metadata={
                        "macro": "esp_event_handler_register",
                        "base": base,
                        "event_id": event_id,
                    },
                )
            )

    # Dedup by (file, line, symbol, kind) — pinned vs unpinned creates of
    # the same task fn at the same line are one entry; the same fn at two
    # different lines is two entries.
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
