"""Linux userspace driver discoverer.

Finds entry points exposed by a *userspace* Linux driver. The
canonical members of this category are:

- libusb-based USB device drivers (no kernel module, talks to
  `/dev/bus/usb/*` via the libusb API).
- CUSE (character userspace) and FUSE filesystem drivers that
  install device nodes from userspace.
- V4L2 userspace clients that drive `/dev/video*` via ioctl()
  callbacks.
- HID-raw and spidev clients that open `/dev/hidraw*` /
  `/dev/spidev*` and dispatch ioctl()s.

The walker reasons about these as *userspace processes that talk
to the kernel via syscalls*, so the natural entry points are:

1. The driver's `main()` / dispatcher loop — emitted as a
   ``MAIN_FUNCTION`` so the walker traces it as the boot path.
2. Each ``ioctl(fd, REQUEST, ...)`` call site — emitted as an
   ``IOCTL_HANDLER`` so the walker reasons about kernel-side
   handling of those requests.
3. libusb / CUSE / V4L2 lifecycle callbacks (``libusb_init``,
   ``cuse_lowlevel_main``, V4L2 ``vidioc_*`` callbacks) — emitted
   as ``EVENT_LISTENER`` so the walker treats them as event
   handlers driven by the kernel-to-userspace boundary.

Skip-dir check uses ``p.relative_to(repo_root).parts`` (NOT
``p.parts``) so a fixture living under ``tests/fixtures/...`` is
not mis-skipped by the absolute-path check.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

CONTENT_PREVIEW_BYTES = 131072  # 128 KB — enough for any realistic single-file driver.

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
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "tests_dev",
    }
)

# Top-level `main()` / `int main(int argc, char **argv)` declarations.
# We deliberately do NOT match `_main`, `app_main`, or `qemu_main` —
# only the C-standard `main`.
_MAIN_RE = re.compile(
    r"^\s*(?:int|void)\s+main\s*\(",
    re.MULTILINE,
)

# ioctl() call sites. The first argument is the file descriptor; the
# second is the request code (constant or macro). We capture the request
# token so the walker can reason about the request space.
_IOCTL_RE = re.compile(
    r"\bioctl\s*\(\s*(?P<fd>[^,]+),\s*(?P<request>[A-Za-z_][A-Za-z0-9_]*)\s*[,)]",
)

# Userspace-driver lifecycle / event-handler entry-point patterns. Each
# pattern below is a (regex, callback_kind, framework) triple. The match
# group ``sym`` (when present) is the callback symbol; otherwise the
# matched literal is the symbol.
#
# libusb: ``libusb_init`` + ``libusb_set_pollfd_notifiers(ctx, added_cb,
# removed_cb, ...)`` and ``libusb_hotplug_register_callback(..., cb, ...)``.
# CUSE:   ``cuse_lowlevel_main(...)``.
# V4L2:   ``static const struct v4l2_ioctl_ops <var> = { .vidioc_X = fn };``
#         and ``vidioc_*`` callback definitions.
_LIFECYCLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?P<sym>libusb_init)\s*\("), "libusb"),
    (re.compile(r"\b(?P<sym>libusb_open_device_with_vid_pid)\s*\("), "libusb"),
    (re.compile(r"\b(?P<sym>libusb_hotplug_register_callback)\s*\("), "libusb"),
    (re.compile(r"\b(?P<sym>cuse_lowlevel_main)\s*\("), "cuse"),
    (re.compile(r"\b(?P<sym>fuse_main)\s*\("), "fuse"),
    (re.compile(r"^\s*static\s+\w+\s+(?P<sym>vidioc_\w+)\s*\(", re.MULTILINE), "v4l2"),
)


def _line_of(text: str, offset: int) -> int:
    """1-indexed line number for a byte offset."""
    return text.count("\n", 0, offset) + 1


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of `path`.

    Decodes with ``errors="replace"`` so binary fixtures survive without
    blowing up the parse. Comments are NOT stripped here — the regexes
    are precise enough that an ``ioctl(`` inside a `//` comment is rare
    and harmless; stripping would shift line numbers off the original
    file, which the walker uses for navigation.
    """
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _docstring_near(text: str, line: int) -> str:
    """Best-effort doc/comment near `line`. Looks at the 5 lines before.

    C-style ``/* ... */`` and ``//`` comments are concatenated; the first
    blank line stops the scan. Used to populate the ``docstring`` field
    on each EntryPoint so the walker has intended-behaviour context
    without going back to the source.
    """
    lines = text.splitlines()
    end = max(0, line - 1)
    start = max(0, end - 5)
    out: list[str] = []
    for ln in lines[start:end]:
        s = ln.strip()
        if not s:
            if out:
                # blank line breaks the block — keep what we collected.
                continue
            continue
        if s.startswith(("//", "/*", "*")) or s.endswith("*/"):
            out.append(s.lstrip("/*").rstrip("*/").strip())
            continue
        # non-comment line — stop walking back.
        break
    return " ".join(out).strip()


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find userspace-driver entry points. Deterministic order.

    Sort key: ``(file, line, symbol)`` then by metadata key to break ties
    when two callbacks register at the same source line (rare but
    possible with macros).
    """
    if "c" not in languages:
        return []
    repo_root = repo_root.resolve()

    # Step 1: collect candidate .c files, sorted, with skip-dirs honoured
    # against the REPO-RELATIVE parts (NOT the absolute path).
    sources: list[Path] = []
    for p in repo_root.rglob("*.c"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if p.is_file():
            sources.append(p)
    sources.sort()
    if not sources:
        return []

    entries: list[EntryPoint] = []
    seen: set[tuple[str, int, str, str]] = set()

    for path in sources:
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        # main() — MAIN_FUNCTION
        for m in _MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            key = (rel, line, "main", "main")
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=line,
                    symbol="main",
                    type_origin="driver_linux_userspace",
                    metadata={"role": "main", "via": "main_decl"},
                    docstring=_docstring_near(text, line),
                )
            )

        # ioctl() call sites — IOCTL_HANDLER
        for m in _IOCTL_RE.finditer(text):
            request = m.group("request").strip()
            line = _line_of(text, m.start())
            # Deduplicate by (file, line, request) — multiple ioctl calls
            # on the same line are rare; if they happen we keep the first.
            symbol = f"ioctl:{request}"
            key = (rel, line, symbol, "ioctl")
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                EntryPoint(
                    kind=EntryPointKind.IOCTL_HANDLER,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="driver_linux_userspace",
                    metadata={
                        "request": request,
                        "fd_expr": m.group("fd").strip(),
                        "via": "ioctl_call",
                    },
                    docstring=_docstring_near(text, line),
                )
            )

        # Lifecycle / framework callbacks — EVENT_LISTENER
        for pattern, framework in _LIFECYCLE_PATTERNS:
            for m in pattern.finditer(text):
                sym = m.group("sym")
                line = _line_of(text, m.start())
                key = (rel, line, sym, framework)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    EntryPoint(
                        kind=EntryPointKind.EVENT_LISTENER,
                        file=rel,
                        line=line,
                        symbol=sym,
                        type_origin="driver_linux_userspace",
                        metadata={"framework": framework, "via": "lifecycle_pattern"},
                        docstring=_docstring_near(text, line),
                    )
                )

    # Deterministic sort: (file, line, symbol) is enough because the
    # dedup set already removed exact ties.
    entries.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("via", ""))))
    return entries
