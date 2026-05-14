"""Qt desktop-app discoverer.

Finds entry points declared in Qt C++ desktop applications for the
`desktop_qt` software type:

- `class <Name> : public QMainWindow` (and QWidget, QDialog) — emits
  one UI_ROUTE EntryPoint per window/widget class. A QMainWindow is
  the top-level surface the user interacts with; the walker reasons
  about scenarios at the window-class boundary.
- `public slots:` declarations followed by member functions, and
  `Q_SLOT` marker macros — each declared slot is one UI_EVENT_HANDLER
  EntryPoint. Slots are the user-event surface (button clicks, menu
  selections); the walker traces input flow from slot invocation
  inward.
- `int main(int argc, char *argv[]) { ... QApplication ... }` —
  emits one MAIN_FUNCTION EntryPoint for the application entry. This
  is the deterministic launch path before the event loop spins up.

Regex-based heuristic (no AST for C++, no MOC parser — the public
surface we care about is small, well-defined, and stable across Qt5
and Qt6). Deterministic at every step: files sorted, matches iterated
in source order, output dedup'd and sorted before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Match `class Foo : public QMainWindow` (or QWidget, QDialog). The
# inheritance suffix is restricted to the small set of Qt window/widget
# base classes we recognise — avoids capturing unrelated subclasses
# that merely include "Window" or "Widget" in a parent class name.
_QT_WINDOW_RE = re.compile(
    r"^\s*class\s+(?:Q_DECL_EXPORT\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*final)?\s*:\s*public\s+"
    r"(?P<parent>QMainWindow|QWidget|QDialog|QFrame)\b",
    re.MULTILINE,
)

# Match a `public slots:` (or protected/private slots:) block header.
# Capture position so we can scan for the slot functions that follow
# up to the next access-specifier or closing brace.
_SLOTS_BLOCK_RE = re.compile(
    r"^\s*(?P<access>public|protected|private)\s+slots\s*:",
    re.MULTILINE,
)

# Within a slots block: match a function declaration. Captures the
# return type (often `void`) and the function name. We deliberately
# avoid trying to parse parameters — the walker uses the symbol name,
# not the signature.
_SLOT_FN_RE = re.compile(
    r"^\s*(?:virtual\s+)?(?:[A-Za-z_][A-Za-z0-9_<>:\s\*&]*?\s+)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:const\s*)?[;{]",
    re.MULTILINE,
)

# Match an access-specifier or class-end so we know where the slots
# block stops. Used to bound the per-block scan.
_SECTION_END_RE = re.compile(
    r"^\s*(?:public|protected|private)(?:\s+slots)?\s*:|^\s*\}\s*;",
    re.MULTILINE,
)

# Match `int main(int argc, char *argv[])` (and the `char **argv` and
# `char* argv[]` variants). We also accept the no-argument form
# `int main()` as a fallback for minimal Qt examples.
_MAIN_RE = re.compile(
    r"^\s*int\s+main\s*\("
    r"(?:\s*\)|[^)]*?)"
    r"\)\s*\{",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "build",
        "build-Desktop_Qt",
        "dist",
        "out",
        "release",
        "debug",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — sufficient for a single Qt source/header.


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

    Checking absolute parts would mis-skip every fixture under
    tests/fixtures/ since the test directory is in the absolute path.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_cpp_sources(repo_root: Path) -> list[Path]:
    """Sorted list of C++ source/header files, skip-dir filtered."""
    out: list[Path] = []
    for ext in ("*.cpp", "*.cc", "*.cxx", "*.h", "*.hpp", "*.hxx"):
        for p in repo_root.rglob(ext):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Qt UI classes, slots, and the main entry. Deterministic order.

    `languages` is advisory — the detector already gated dispatch via
    the Qt fingerprint (CMakeLists with `find_package(Qt6)` or `.pro`
    with `QT +=`). We run unconditionally on C++ source/header files.
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    for path in _iter_cpp_sources(repo_root):
        text = _read(path)
        if not text:
            continue
        # Quick gate — must mention Qt somewhere or skip the regexes
        # entirely. The substring check is cheap and avoids running the
        # heavier regexes on non-Qt C++ files that may share the tree.
        if "Q" not in text:
            continue
        rel = str(path.relative_to(repo_root))

        # 1) QMainWindow / QWidget / QDialog subclasses → UI_ROUTE.
        for m in _QT_WINDOW_RE.finditer(text):
            symbol = m.group("name")
            parent = m.group("parent")
            line = _line_of(text, m.start())
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="desktop_qt",
                    metadata={
                        "element": "window_class",
                        "parent_class": parent,
                        "framework": "qt",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        # 2) `public slots:` blocks → UI_EVENT_HANDLER per slot function.
        # Scan each block until the next access-specifier or class end.
        for block_match in _SLOTS_BLOCK_RE.finditer(text):
            access = block_match.group("access")
            block_start = block_match.end()
            # Find the end of this slots block: the next access-specifier
            # OR the class-end. Searching from block_start forward.
            end_match = _SECTION_END_RE.search(text, block_start)
            block_end = end_match.start() if end_match else len(text)
            slot_section = text[block_start:block_end]
            for slot_match in _SLOT_FN_RE.finditer(slot_section):
                slot_name = slot_match.group("name")
                abs_offset = block_start + slot_match.start()
                line = _line_of(text, abs_offset)
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_EVENT_HANDLER,
                        file=rel,
                        line=line,
                        symbol=slot_name,
                        type_origin="desktop_qt",
                        metadata={
                            "element": "slot",
                            "access": access,
                            "framework": "qt",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

        # 3) `int main(...)` → MAIN_FUNCTION (only in .cpp files; headers
        # don't define main).
        if path.suffix in (".cpp", ".cc", ".cxx"):
            for m in _MAIN_RE.finditer(text):
                line = _line_of(text, m.start())
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.MAIN_FUNCTION,
                        file=rel,
                        line=line,
                        symbol="main",
                        type_origin="desktop_qt",
                        metadata={
                            "element": "main",
                            "framework": "qt",
                        },
                        docstring="",
                        intended_behaviour_sources=(),
                    )
                )

    # Dedup by (file, line, symbol, kind) — a symbol may legitimately
    # appear as both a slot declaration in a header AND a definition in
    # the .cpp; keeping kind in the key lets distinct kinds coexist.
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
