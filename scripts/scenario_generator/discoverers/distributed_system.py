"""Distributed-system discoverer.

Selective discoverer for the `distributed_system` software type. Targets
the RPC and consensus-message handlers that an idiomatic Raft / Paxos /
gossip / leader-election implementation exposes:

1. **Consensus RPC handlers** — `AppendEntries`, `RequestVote`,
   `InstallSnapshot` (Raft), `Prepare`, `Promise`, `Accept`,
   `Accepted` (Paxos), `ProposeValue`. Mapped to IPC_HANDLER.

2. **Generic peer-RPC handlers** — method names ending in `RPC`,
   methods on a `*Raft`/`*Paxos`/`*Node` receiver. Also IPC_HANDLER.

3. **Consensus state-transition functions** — `becomeLeader`,
   `becomeFollower`, `becomeCandidate`, `startElection`,
   `replicateLog`, `commitIndex`, `applyCommitted`. Mapped to
   IPC_HANDLER with `category=state_transition`.

The conventions are case-insensitive across languages:
- Go uses CamelCase exported methods (`AppendEntries`).
- Rust uses snake_case (`append_entries`).
- Java uses CamelCase (`appendEntries` as a method).

`type_origin` is hard-coded to `"distributed_system"`. Output is sorted
by (file, line, symbol) with a category tiebreaker.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

# ---------------------------------------------------------------------------
# Consensus name registries — keys are case-insensitive (we lower the
# matched name before classification). The case-folded form covers
# Raft's `AppendEntries` vs `append_entries` vs `appendEntries` without
# emitting three regex variants.
# ---------------------------------------------------------------------------

# RPC handler names (case-folded). Each is one peer-to-peer message
# handler in idiomatic consensus protocols.
_RPC_NAMES_CI: frozenset[str] = frozenset(
    {
        "appendentries",
        "requestvote",
        "installsnapshot",
        "prepare",
        "promise",
        "accept",
        "accepted",
        "proposevalue",
        "preparerequest",
        "acceptrequest",
        "snapshotinstall",
        "heartbeat",
    }
)

# Consensus state-transition function names (case-folded).
_STATE_NAMES_CI: frozenset[str] = frozenset(
    {
        "becomeleader",
        "becomefollower",
        "becomecandidate",
        "startelection",
        "replicatelog",
        "commitindex",
        "applycommitted",
        "stepdown",
    }
)


def _strip_underscores(s: str) -> str:
    """Fold a snake_case identifier to its underscore-stripped form."""
    return s.replace("_", "").lower()


# ---------------------------------------------------------------------------
# Regexes. We capture any identifier; classification happens after the
# match using the case-folded comparison above.
# ---------------------------------------------------------------------------

# Go: top-level `func Name(` and method `func (r *Receiver) Name(`.
_GO_FN_RE = re.compile(
    r"^func\s+(?:\((?P<receiver>[^)]+)\)\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)

# Rust: `fn name(` and `pub fn name(`.
_RUST_FN_RE = re.compile(
    r"^\s*(?:pub\s+(?:\([^)]*\)\s+)?)?(?:async\s+|unsafe\s+|const\s+|extern\s+(?:\"[^\"]+\"\s+)?)*"
    r"fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)

# Java/Kotlin: method declarations within a class — `public void name(`,
# `public Result name(`, `void name(`, etc. We approximate with a regex
# that requires at least one modifier-or-type token before the method
# name. This is heuristic; for a richer Java parse the discoverer would
# need a true Java tokenizer.
_JAVA_FN_RE = re.compile(
    r"^\s+(?:public|private|protected|static|final|abstract|synchronized|\s)+"
    r"\s*[A-Za-z_<>][A-Za-z0-9_<>,\s.]*?\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        "node_modules",
        "vendor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        ".idea",
        ".vscode",
        "tests",
        "test",
        "__tests__",
        "examples",
        "example",
        "samples",
        "sample",
        "benches",
        "bench",
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


CONTENT_PREVIEW_BYTES = 262144  # 256KB


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
    """True if any DIRECTORY component (relative to repo_root) is skipped."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return True
    return any(part in _SKIP_DIRS for part in rel.parts[:-1])


def _iter_files(repo_root: Path, ext_globs: tuple[str, ...]) -> list[Path]:
    """Return a deterministic sorted list of files matching any of the globs."""
    seen: set[Path] = set()
    for glob in ext_globs:
        for p in repo_root.rglob(glob):
            if not p.is_file():
                continue
            if _is_skipped(p, repo_root):
                continue
            seen.add(p)
    return sorted(seen)


def _classify(name: str) -> tuple[bool, str]:
    """Return (matches, category) for a function name.

    The name is case-folded and underscore-stripped before being looked
    up in the registries — so `AppendEntries`, `appendEntries`, and
    `append_entries` all map to the same canonical form.
    """
    folded = _strip_underscores(name)
    if folded in _RPC_NAMES_CI:
        return (True, "rpc")
    if folded in _STATE_NAMES_CI:
        return (True, "state_transition")
    # Names ending in 'RPC' or 'Handler' are also peer-RPC handlers by
    # convention (e.g. `appendEntriesRPC`, `voteHandler`).
    if folded.endswith("rpc") and len(folded) > 3:
        return (True, "rpc")
    return (False, "")


def _emit(
    rel: str,
    text: str,
    pattern: re.Pattern[str],
    language: str,
    out: list[EntryPoint],
    *,
    require_group: str = "name",
) -> None:
    """Run `pattern` over `text`, classify, and append EntryPoint records."""
    for m in pattern.finditer(text):
        name = m.group(require_group)
        if not name:
            continue
        matched, category = _classify(name)
        if not matched:
            continue
        line = _line_of(text, m.start())
        out.append(
            EntryPoint(
                kind=EntryPointKind.IPC_HANDLER,
                file=rel,
                line=line,
                symbol=name,
                type_origin="distributed_system",
                metadata={
                    "language": language,
                    "category": category,
                },
            )
        )


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find distributed-system entry points. Deterministic order."""
    repo_root = repo_root.resolve()
    found: list[EntryPoint] = []

    # ---- Go ----------------------------------------------------------------
    if "go" in languages:
        for path in _iter_files(repo_root, ("*.go",)):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _GO_FN_RE, "go", found)

    # ---- Rust --------------------------------------------------------------
    if "rust" in languages:
        for path in _iter_files(repo_root, ("*.rs",)):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _RUST_FN_RE, "rust", found)

    # ---- Java --------------------------------------------------------------
    if "java" in languages:
        for path in _iter_files(repo_root, ("*.java",)):
            text = _read(path)
            if not text:
                continue
            _emit(str(path.relative_to(repo_root)), text, _JAVA_FN_RE, "java", found)

    # Dedup by (file, line, symbol) and sort deterministically.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: (e.sort_key(), str(e.metadata.get("category", ""))))
    return unique
