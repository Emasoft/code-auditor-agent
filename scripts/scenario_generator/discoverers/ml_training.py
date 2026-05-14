"""ML training-loop discoverer.

Finds the entry points of machine-learning training pipelines across
Python source. We treat *training loops* and *training entrypoints* as
the unit of work the walker reasons about — a single bad input or a
single OOM event can poison an entire run, so each loop becomes one
scenario seed.

A function is treated as an ML training entry point if EITHER:

1. Its body contains at least one of the canonical training-step calls:
   - ``model.fit(...)`` / ``estimator.fit(...)`` / ``trainer.fit(...)``
   - ``model.train(...)`` (PyTorch's mode-switch; common in custom loops)
   - ``optimizer.step(...)`` (canonical PyTorch step)
   - ``loss.backward(...)`` (canonical PyTorch backward pass)
   - ``trainer.train(...)`` (HuggingFace, PyTorch-Lightning)
2. OR the function is decorated with ``@hydra.main(...)`` — the Hydra
   library is the dominant config-driven entrypoint convention for
   ML scripts and almost always wraps a training callable.

Each match emits one ``EntryPoint`` with kind ``MAIN_FUNCTION``
(closest match in the universal taxonomy for "an executable training
loop"). The metadata field ``signal`` records which canonical token
triggered the match, so downstream consumers can distinguish "fit"-
style sklearn loops from low-level PyTorch loops.

Determinism: ``.py`` files are sorted; each function's signals are
sorted; the emitted list is sorted via ``sort_key()``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..types import EntryPoint, EntryPointKind

TYPE_ORIGIN = "ml_training"


# Canonical training-step call patterns. The key is the "signal name"
# stored in metadata.signal; the value is the (object-name, method)
# pair the AST walker looks for. ``object_name`` of ``None`` means
# match any attribute call ending with the given method.
_TRAINING_CALLS: tuple[tuple[str, str], ...] = (
    ("fit", "fit"),
    ("train", "train"),
    ("step", "step"),
    ("backward", "backward"),
)


_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        "tests",
        "test",
        "tests_dev",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
    }
)


CONTENT_PREVIEW_BYTES = 262144  # 256KB — ML training scripts can be sizable.


def _read(path: Path) -> str:
    """Read up to CONTENT_PREVIEW_BYTES of ``path``. Empty string on OSError."""
    try:
        return path.read_bytes()[:CONTENT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _parse(text: str) -> ast.Module | None:
    """Parse ``text`` into an AST module; return ``None`` on syntax error."""
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _first_docstring_line(node: ast.AST) -> str:
    """Return the first non-empty line of the symbol's docstring, or ''."""
    if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.Module):
        return ""
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    for ln in doc.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def _is_hydra_main(decorator: ast.AST) -> bool:
    """Return True iff ``decorator`` is ``@hydra.main`` / ``@hydra.main(...)``.

    Accepts both the call form (``@hydra.main(config_path=...)``) and
    the bare attribute form (``@hydra.main``). We don't try to be
    clever about aliased imports — Hydra is conventionally imported as
    ``hydra`` with no rename, so this matches the real-world spelling.
    """
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(func, ast.Attribute) and func.attr == "main":
        value = func.value
        if isinstance(value, ast.Name) and value.id == "hydra":
            return True
    return False


def _scan_function_for_training_signals(func: ast.AST) -> list[str]:
    """Return a sorted list of signals found inside ``func``.

    A signal is any of the canonical training-step methods (fit, train,
    step, backward) called as an *attribute call* — i.e. ``X.fit(...)``
    rather than ``fit(...)`` standalone. Bare-function calls would be
    ambiguous (``train`` could be any free function), so we require
    the attribute form.

    Returns a sorted, deduplicated list — required for deterministic
    metadata output.
    """
    signals: set[str] = set()
    target_methods = {method for _, method in _TRAINING_CALLS}
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Attribute):
            continue
        if callee.attr in target_methods:
            signals.add(callee.attr)
    return sorted(signals)


def _is_top_level_function(node: ast.AST) -> bool:
    """True iff ``node`` is a module-scope function definition."""
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)


def discover(repo_root: Path, languages: list[str]) -> list[EntryPoint]:
    """Find ML training entrypoints. Deterministic order."""
    if "python" not in languages:
        return []
    repo_root = repo_root.resolve()

    py_files: list[Path] = []
    for p in repo_root.rglob("*.py"):
        try:
            rel_parts = p.relative_to(repo_root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if p.is_file():
            py_files.append(p)
    py_files.sort()

    found: list[EntryPoint] = []

    for path in py_files:
        text = _read(path)
        if not text:
            continue
        # Cheap pre-filter: only files mentioning at least one ML-ish
        # signal get the AST parse cost. Hydra-decorated functions
        # always carry the literal ``hydra`` in the source.
        low = text.lower()
        if (
            "fit(" not in low
            and ".train(" not in low
            and ".step(" not in low
            and ".backward(" not in low
            and "hydra" not in low
        ):
            continue
        module = _parse(text)
        if module is None:
            continue
        rel = str(path.relative_to(repo_root))

        for stmt in module.body:
            if not _is_top_level_function(stmt):
                continue
            assert isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
            # Skip dunder/private names — same convention as the
            # library_python discoverer; private helpers like
            # ``_eval`` should not become scenario seeds.
            if stmt.name.startswith("_"):
                continue

            # Path A: training-call signal anywhere inside the body.
            signals = _scan_function_for_training_signals(stmt)
            # Path B: any @hydra.main decorator.
            hydra_decorated = any(_is_hydra_main(d) for d in stmt.decorator_list)

            if not signals and not hydra_decorated:
                continue

            # Build metadata in a stable shape.
            metadata: dict[str, object] = {
                "framework": "ml",
            }
            if signals:
                metadata["signals"] = tuple(signals)
            if hydra_decorated:
                metadata["entrypoint"] = "hydra.main"

            found.append(
                EntryPoint(
                    kind=EntryPointKind.MAIN_FUNCTION,
                    file=rel,
                    line=stmt.lineno,
                    symbol=stmt.name,
                    type_origin="ml_training",
                    metadata=metadata,
                    docstring=_first_docstring_line(stmt),
                    intended_behaviour_sources=(),
                )
            )

    # Dedup by (file, line, symbol). The AST scan can't legitimately
    # produce two records for the same name at the same line, but
    # the seen-set keeps the contract uniform with other discoverers.
    seen: set[tuple[str, int, str]] = set()
    unique: list[EntryPoint] = []
    for ep in found:
        key = (ep.file, ep.line, ep.symbol)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ep)
    unique.sort(key=lambda e: e.sort_key())
    return unique
