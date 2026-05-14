"""Android mobile-app discoverer.

Finds entry points declared in `AndroidManifest.xml` files across the
repository — the canonical surface area for the `mobile_android`
software type.

Three element families are recognised:

- `<activity android:name="...">` — emits one EntryPoint per activity.
  Kind: UI_ROUTE (an Activity is the screen the user lands on for the
  intent it was registered against). When the activity also carries a
  `<intent-filter>` whose `<data android:scheme="...">` identifies a
  custom URL scheme, a second UI_ROUTE EntryPoint is emitted for the
  deep-link target (metadata `{element: "deep_link"}` distinguishes
  the two). The walker reads `scheme`+`host` from metadata when
  constructing the stimulus.
- `<service android:name="...">` — emits one EntryPoint per service.
  Kind: IPC_HANDLER (services are bound or started via Binder IPC).
- `<receiver android:name="...">` — emits one EntryPoint per receiver.
  Kind: EVENT_LISTENER. Receivers fire on broadcast intents (boot
  completed, network change, etc.).

The discoverer ONLY parses manifest XML — it does NOT chase the matching
`.kt` / `.java` class files. The walker resolves those when it needs
the body for a scenario; the goal here is to enumerate the surface
area, not to inline the bodies.

Heuristic XML parsing (no `xml.etree` dependency on this fast path —
regex is enough for the well-defined manifest shape). Deterministic
output: files are sorted, matches within a file are iterated in source
order, and the final list is dedup'd + sorted by (file, line, symbol,
kind).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# Matches `<activity ... android:name="..."`, `<service ... android:name="..."`,
# or `<receiver ... android:name="..."`. The attribute may be on the same
# line or wrapped onto a continuation line, so we use DOTALL but limit the
# greedy span with a lazy `.*?` and require the closing `>` (self-closing
# or with a body) within the same element opening.
_ELEMENT_RE = re.compile(
    r"<(?P<element>activity|service|receiver)\b"
    r"(?P<attrs>[^>]*?)"
    r"(?P<close>/>|>)",
    re.DOTALL,
)
_NAME_ATTR_RE = re.compile(r'android:name\s*=\s*"(?P<name>[^"]+)"')
# `<data android:scheme="..."` plus optional `android:host="..."`. We only
# care about custom schemes; `http`/`https` deep-links require app links
# verification and are a separate concern.
_DATA_RE = re.compile(
    r'<data\b[^>]*?android:scheme\s*=\s*"(?P<scheme>[^"]+)"'
    r'(?:[^>]*?android:host\s*=\s*"(?P<host>[^"]+)")?',
    re.DOTALL,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".gradle",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "out",
        "bin",
        "obj",
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


CONTENT_PREVIEW_BYTES = 131072  # 128KB — manifests are tiny in practice


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

    Same reason as every other discoverer: a fixture living under
    `tests/fixtures/...` would mis-skip if we checked absolute path
    parts. Only inspect what's inside `repo_root`.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts)


def _iter_manifests(repo_root: Path) -> list[Path]:
    """Sorted list of AndroidManifest.xml files."""
    out: list[Path] = []
    for p in repo_root.rglob("AndroidManifest.xml"):
        if not p.is_file():
            continue
        if _is_skipped(p, repo_root):
            continue
        out.append(p)
    out.sort()
    return out


def _shorten_name(raw: str) -> str:
    """Strip leading `.` (relative-to-package shorthand) but keep the rest.

    `.MainActivity` → `MainActivity`. `com.example.MainActivity` is
    kept verbatim. The bare leaf is what the walker uses as a symbol.
    """
    if raw.startswith("."):
        return raw[1:]
    return raw


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find Android entry points declared in AndroidManifest.xml files.

    `languages` is advisory — we run whenever at least one
    AndroidManifest.xml exists. The detector already gated the
    dispatch; this discoverer trusts that contract.
    """
    del languages

    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    manifests = _iter_manifests(repo_root)
    if not manifests:
        return []

    for manifest_path in manifests:
        text = _read(manifest_path)
        if not text:
            continue
        rel = str(manifest_path.relative_to(repo_root))

        for elem_match in _ELEMENT_RE.finditer(text):
            element = elem_match.group("element")
            attrs = elem_match.group("attrs")
            name_match = _NAME_ATTR_RE.search(attrs)
            if name_match is None:
                continue
            raw_name = name_match.group("name")
            symbol = _shorten_name(raw_name)
            line = _line_of(text, elem_match.start())

            # Map element type → EntryPointKind. Activities and deep
            # links both become UI_ROUTE; the `element` field in
            # metadata distinguishes them at the walker level. Services
            # are Binder-IPC entry points; receivers are broadcast
            # event listeners.
            if element == "activity":
                kind = EntryPointKind.UI_ROUTE
            elif element == "service":
                kind = EntryPointKind.IPC_HANDLER
            else:  # receiver
                kind = EntryPointKind.EVENT_LISTENER

            metadata: dict[str, object] = {
                "element": element,
                "android_name": raw_name,
            }
            # `android:exported` is a security-relevant flag; surface it
            # when present so the walker can reason about whether the
            # entry is reachable from another app.
            exported_match = re.search(r'android:exported\s*=\s*"(?P<v>true|false)"', attrs)
            if exported_match is not None:
                metadata["exported"] = exported_match.group("v") == "true"

            found.append(
                EntryPoint(
                    kind=kind,
                    file=rel,
                    line=line,
                    symbol=symbol,
                    type_origin="mobile_android",
                    metadata=metadata,
                    docstring="",
                    intended_behaviour_sources=(rel,),
                )
            )

            # If the element body extends past the self-closing form,
            # also scan it for deep-link <data> elements. We bound the
            # search to the next `</activity|service|receiver>` close
            # tag so deep-links from one activity don't bleed into the
            # next.
            if elem_match.group("close") == "/>":
                continue
            close_tag = f"</{element}>"
            close_idx = text.find(close_tag, elem_match.end())
            body_end = close_idx if close_idx != -1 else len(text)
            body = text[elem_match.end() : body_end]
            for data_match in _DATA_RE.finditer(body):
                scheme = data_match.group("scheme")
                if scheme.lower() in {"http", "https"}:
                    # App-link verification covers these elsewhere; skip
                    # to avoid noising the per-scheme entry-point list.
                    continue
                host = data_match.group("host") or ""
                deeplink_line = _line_of(text, elem_match.end() + data_match.start())
                deeplink_symbol = f"{symbol}#{scheme}"
                found.append(
                    EntryPoint(
                        kind=EntryPointKind.UI_ROUTE,
                        file=rel,
                        line=deeplink_line,
                        symbol=deeplink_symbol,
                        type_origin="mobile_android",
                        metadata={
                            "element": "deep_link",
                            "scheme": scheme,
                            "host": host,
                            "host_activity": symbol,
                        },
                        docstring="",
                        intended_behaviour_sources=(rel,),
                    )
                )

    # Dedup by (file, line, symbol, kind) + sort.
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
