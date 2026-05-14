"""iOS mobile-app discoverer.

Finds entry points declared in iOS-native source for the `mobile_ios`
software type:

- `@UIApplicationMain` / `@main` annotations on a Swift class — emits
  one BOOT_PATH EntryPoint per file that declares the app entry. This
  is the application's lifecycle root, called by UIKit at launch.
- `class <Name>: UIViewController` (and subclass-of-UIViewController
  variants) — emits one UI_ROUTE EntryPoint per ViewController.
  A ViewController owns a screen and handles its lifecycle events; the
  `element: "view_controller"` metadata field distinguishes a screen
  from a URL-scheme deep link, both of which carry kind UI_ROUTE.
- `CFBundleURLSchemes` arrays in Info.plist — each `<string>` inside
  an array under that key is one custom URL scheme, emitted as a
  UI_ROUTE EntryPoint with metadata `{scheme}`. Deep-link entry
  points the walker can reason about.

Regex-based heuristic (no AST for Swift, no full PLIST parser — the
shape we care about is small and well-defined). Deterministic at every
step: files sorted, matches iterated in source order, output dedup'd
and sorted before return.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# `@main` or `@UIApplicationMain` on its own line, immediately followed
# by a `class <Name>` declaration (possibly on the next line). We
# capture the class name as the symbol.
_APP_MAIN_RE = re.compile(
    r"^\s*@(?:main|UIApplicationMain)\b\s*\n"
    r"\s*(?:final\s+)?class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)

# `class <Name>: UIViewController` — also matches subclasses of
# UIViewController like `UITableViewController`, `UICollectionViewController`,
# `UISplitViewController` (the inheritance suffix is matched against a
# small alternation, not arbitrary text, to avoid pulling in unrelated
# classes that merely include `View` in their parent name).
_VIEWCONTROLLER_RE = re.compile(
    r"^\s*(?:final\s+|public\s+|open\s+|internal\s+)?class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*:\s*(?P<parent>UI(?:View|TableView|CollectionView|SplitView|NavigationView|PageView)Controller)",
    re.MULTILINE,
)

# Match a `<key>CFBundleURLSchemes</key>` followed by an `<array>` block,
# and capture all `<string>X</string>` entries inside the array. DOTALL
# is required so newlines inside the array are matched.
_URL_SCHEMES_BLOCK_RE = re.compile(
    r"<key>\s*CFBundleURLSchemes\s*</key>\s*<array>(?P<body>.*?)</array>",
    re.DOTALL,
)
_PLIST_STRING_RE = re.compile(r"<string>(?P<value>[^<]+)</string>")


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".build",
        ".swiftpm",
        ".idea",
        ".vscode",
        "build",
        "DerivedData",
        "dist",
        "out",
        "Pods",
        "Carthage",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — Swift source files rarely exceed this


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
    """Skip-dir check against RELATIVE parts.

    Identical reasoning to other discoverers — absolute parts would
    mis-skip every fixture under tests/fixtures/. Only what's inside
    `repo_root` is consulted.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_swift_files(repo_root: Path) -> list[Path]:
    """Sorted list of .swift files, skip-dir filtered."""
    out: list[Path] = []
    for p in repo_root.rglob("*.swift"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        out.append(p)
    out.sort()
    return out


def _iter_plists(repo_root: Path) -> list[Path]:
    """Sorted list of Info.plist files (the standard manifest name)."""
    out: list[Path] = []
    for p in repo_root.rglob("Info.plist"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        out.append(p)
    out.sort()
    return out


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find iOS entry points from Swift sources and Info.plist files.

    `languages` is advisory — the detector already gated dispatch via
    the iOS fingerprint, and Swift mixing with Objective-C is the
    norm. Running unconditionally on .swift + Info.plist matches.
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # 1) Swift sources: @main / @UIApplicationMain + UIViewController subclasses.
    for path in _iter_swift_files(repo_root):
        text = _read(path)
        if not text:
            continue
        rel = str(path.relative_to(repo_root))

        for m in _APP_MAIN_RE.finditer(text):
            line = _line_of(text, m.start())
            symbol = m.group("name")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.BOOT_PATH,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="mobile_ios",
                    metadata={
                        "element": "app_main",
                        "language": "swift",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

        for m in _VIEWCONTROLLER_RE.finditer(text):
            line = _line_of(text, m.start())
            symbol = m.group("name")
            parent = m.group("parent")
            found.append(
                EntryPoint(
                    kind=EntryPointKind.UI_ROUTE,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="mobile_ios",
                    metadata={
                        "element": "view_controller",
                        "parent_class": parent,
                        "language": "swift",
                    },
                    docstring="",
                    intended_behaviour_sources=(),
                )
            )

    # 2) Info.plist files: CFBundleURLSchemes arrays.
    for plist in _iter_plists(repo_root):
        text = _read(plist)
        if not text:
            continue
        rel = str(plist.relative_to(repo_root))

        for block_match in _URL_SCHEMES_BLOCK_RE.finditer(text):
            body = block_match.group("body")
            block_start = block_match.start()
            for scheme_match in _PLIST_STRING_RE.finditer(body):
                scheme = scheme_match.group("value").strip()
                if not scheme:
                    continue
                # Locate the line of the scheme string within the full
                # plist, not just within the block, so the EntryPoint
                # points to the actual offset.
                absolute_offset = block_start + scheme_match.start()
                line = _line_of(text, absolute_offset)
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_ROUTE,
                        file=rel,
                        line=line,
                        symbol=scheme,
                        type_origin="mobile_ios",
                        metadata={
                            "element": "url_scheme",
                            "scheme": scheme,
                        },
                        docstring="",
                        intended_behaviour_sources=(rel,),
                    )
                )

    # Dedup by (file, line, symbol, kind) and sort.
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
