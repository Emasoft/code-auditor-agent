"""GTK desktop-app discoverer.

Finds entry points declared in GTK C / Rust desktop applications for
the `desktop_gtk` software type:

- `g_signal_connect(<emitter>, "<signal>", G_CALLBACK(<fn>), <data>)` —
  emits one UI_EVENT_HANDLER EntryPoint per callback. Each callback
  function is a discrete user-event surface; the walker reasons about
  scenarios at the callback boundary.
- `gtk_application_new(...)` and `gtk_init(...)` boot calls — emit one
  BOOT_PATH EntryPoint per call site. These are the GTK toolkit
  initialisation points; the walker traces what runs before the main
  event loop is entered.
- `int main(int argc, char *argv[]) { ... gtk_init/gtk_application_new ... }` —
  emits one MAIN_FUNCTION EntryPoint per source file. The main() body
  is the deterministic launch path for a GTK app.

Regex-based heuristic (no AST for C; GLib macros expand at preprocess
time which we don't shell out for). Deterministic at every step:
files sorted, matches iterated in source order, output dedup'd and
sorted before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# g_signal_connect(emitter, "signal-name", G_CALLBACK(callback_fn), user_data)
# Variants tolerated:
#   - g_signal_connect_swapped, g_signal_connect_after, g_signal_connect_data
#   - whitespace and line breaks inside the argument list
# We capture (signal_name, callback_fn) and report one EntryPoint per call.
_SIGNAL_CONNECT_RE = re.compile(
    r"\bg_signal_connect"
    r"(?:_swapped|_after|_data)?"
    r"\s*\("
    r"\s*[A-Za-z_][A-Za-z0-9_\(\)\->.]*\s*,"
    r"\s*\"(?P<signal>[A-Za-z0-9_\-:]+)\"\s*,"
    r"\s*G_CALLBACK\s*\(\s*(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*\)",
    re.DOTALL,
)

# gtk_application_new("org.example.App", G_APPLICATION_FLAGS_NONE)
# gtk_init(&argc, &argv)
# Either is a boot indicator; we emit per-call BOOT_PATH entries.
_GTK_BOOT_RE = re.compile(
    r"\b(?P<fn>gtk_application_new|gtk_init|gtk_application_run)\s*\(",
)

# int main(...) { -- only in .c / .cc / .cpp files. We capture position
# and verify the file contains a gtk_init/gtk_application_new call so
# we don't emit MAIN_FUNCTION for non-GTK C entry points.
_MAIN_RE = re.compile(
    r"^\s*int\s+main\s*\("
    r"(?:\s*\)|[^)]*?)"
    r"\)\s*\{",
    re.MULTILINE,
)

# Rust: gtk::Application::builder() / Application::new(...) — Rust GTK
# bindings use a builder pattern. We treat each new-builder call as a
# BOOT_PATH entry.
_RUST_APP_NEW_RE = re.compile(
    r"\b(?:gtk::)?Application::(?:new|builder)\s*\(",
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "build",
        "_build",
        "dist",
        "out",
        "target",  # Rust build dir
        ".cache",
        "node_modules",
        "vendor",
        "__pycache__",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "examples_dev",
        "samples_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
    }
)


CONTENT_PREVIEW_BYTES = 131072  # 128KB — sufficient for a single GTK C source.


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES bytes, UTF-8 with replace."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number of `offset` within `text`."""
    return text.count("\n", 0, offset) + 1


def _is_skipped(path: Path, repo_root: Path) -> bool:
    """Skip-dir check against RELATIVE parts only.

    Absolute parts would mis-skip every fixture under tests/fixtures/.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_sources(repo_root: Path) -> list[Path]:
    """Sorted list of C / C++ / Rust source files, skip-dir filtered.

    GTK projects are usually pure C; the Rust gtk-rs binding produces
    .rs files. We scan both — disambiguation happens via the per-regex
    pattern (g_signal_connect for C, gtk::Application for Rust).
    """
    out: list[Path] = []
    for ext in ("*.c", "*.h", "*.cpp", "*.cxx", "*.cc", "*.hpp", "*.rs"):
        for p in repo_root.rglob(ext):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find GTK signal callbacks, boot calls, and main entries.

    `languages` is advisory — the detector already gated dispatch via
    the GTK fingerprint (gtk4/gtk3 in Cargo.toml or CMakeLists.txt,
    plus gtk_init / gtk_application_new in C sources).
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_sources(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) g_signal_connect callbacks → UI_EVENT_HANDLER per call.
        for m in _SIGNAL_CONNECT_RE.finditer(text):
            signal = m.group("signal")
            callback = m.group("fn")
            line = _line_of(text, m.start())
            # Symbol is the callback fn; the signal is metadata. Two
            # connects on the same line with the same callback would
            # be deduped; rare in practice.
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_EVENT_HANDLER,
                    file=rel,
                    line=line,
                    symbol=callback,
                    type_origin="desktop_gtk",
                    metadata={
                        "element": "signal_callback",
                        "signal": signal,
                        "framework": "gtk",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) gtk_init / gtk_application_new boot calls → BOOT_PATH per call.
        for m in _GTK_BOOT_RE.finditer(text):
            fn = m.group("fn")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=fn,
                    type_origin="desktop_gtk",
                    metadata={
                        "element": "boot_call",
                        "function": fn,
                        "framework": "gtk",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 3) Rust gtk-rs Application::new / Application::builder → BOOT_PATH.
        # Only emit when the file is .rs to avoid false-positives in C.
        if path.suffix == ".rs":
            for m in _RUST_APP_NEW_RE.finditer(text):
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.BOOT_PATH,
                        file=rel,
                        line=line,
                        symbol="Application::new",
                        type_origin="desktop_gtk",
                        metadata={
                            "element": "boot_call",
                            "function": "Application::new",
                            "framework": "gtk-rs",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

        # 4) main() in C source — only if file mentions GTK boot.
        if path.suffix in (".c", ".cpp", ".cc", ".cxx") and ("gtk_init" in text or "gtk_application_new" in text):
            for m in _MAIN_RE.finditer(text):
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.MAIN_FUNCTION,
                        file=rel,
                        line=line,
                        symbol="main",
                        type_origin="desktop_gtk",
                        metadata={
                            "element": "main",
                            "framework": "gtk",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by (file, line, symbol, kind) — same symbol may legitimately
    # appear as both a signal-callback registration and a boot call in
    # different files; keeping kind in the key distinguishes them.
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
