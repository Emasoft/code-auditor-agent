"""Unit tests for Step 10 — complexity & dead-code scanner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import complexity as cx


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- length / params / branches / complexity / nesting ---------------------


def test_function_too_long_flagged(tmp_path: Path) -> None:
    body = "    x = 1\n" * 25  # 25 statements ⇒ ≥25 lines
    _write(tmp_path / "app.py", f"def long_fn():\n{body}    return x\n")
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "FN_TOO_LONG" in codes


def test_short_function_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def short_fn():\n    return 42\n")
    result = cx.detect(tmp_path)
    fn_too_long = [f for f in result["findings"] if f["code"] == "FN_TOO_LONG"]
    assert not fn_too_long


def test_too_many_params_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def too_many(a, b, c, d, e):\n    return a\n")
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "TOO_MANY_PARAMS" in codes


def test_kwargs_and_args_count_in_params(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def f(a, *args, **kwargs):\n    return a\n")
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    # 3 params (a, *args, **kwargs) — exactly at the limit (max 3), so not flagged.
    assert "TOO_MANY_PARAMS" not in codes


def test_too_many_branches_flagged(tmp_path: Path) -> None:
    # 6 if-statements ⇒ exceeds MAX_FN_BRANCHES (5).
    _write(
        tmp_path / "app.py",
        "def branchy(x):\n"
        "    if x == 1: return 1\n"
        "    if x == 2: return 2\n"
        "    if x == 3: return 3\n"
        "    if x == 4: return 4\n"
        "    if x == 5: return 5\n"
        "    if x == 6: return 6\n"
        "    return 0\n",
    )
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "TOO_MANY_BRANCHES" in codes
    # 6 branches + 1 base ⇒ complexity 7 — under MAX_FN_COMPLEXITY (10),
    # so HIGH_COMPLEXITY shouldn't fire here.
    assert "HIGH_COMPLEXITY" not in codes


def test_high_complexity_flagged(tmp_path: Path) -> None:
    # Build a function with 10 branches ⇒ complexity 11 ⇒ over MAX_FN_COMPLEXITY (10).
    body = "".join(f"    if x == {i}: return {i}\n" for i in range(11))
    _write(tmp_path / "app.py", f"def cmplx(x):\n{body}    return 0\n")
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "HIGH_COMPLEXITY" in codes


def test_deep_nesting_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def deep():\n"
        "    for a in [1]:\n"
        "        for b in [1]:\n"
        "            for c in [1]:\n"
        "                print(a, b, c)\n",
    )
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DEEP_NESTING" in codes


def test_two_levels_not_flagged_for_nesting(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def shallow():\n    for a in [1]:\n        for b in [1]:\n            print(a, b)\n",
    )
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DEEP_NESTING" not in codes


# ---- unused imports --------------------------------------------------------


def test_unused_import_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "import os\nimport sys\nprint(sys.argv)\n")
    result = cx.detect(tmp_path)
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_IMPORT"]
    assert any("os" in f["message"] for f in unused)


def test_aliased_used_import_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "import os as o\nprint(o.getcwd())\n")
    result = cx.detect(tmp_path)
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_IMPORT"]
    assert not unused


def test_from_import_unused_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "from os import path, sep\nprint(path.join('a'))\n",
    )
    result = cx.detect(tmp_path)
    unused = [f for f in result["findings"] if f["code"] == "UNUSED_IMPORT"]
    assert any("sep" in f["message"] for f in unused)
    assert not any("path" in f["message"] for f in unused)


def test_all_decl_keeps_name_used(tmp_path: Path) -> None:
    """If `__all__ = ['my_fn']` references `my_fn`, it's considered used."""
    _write(
        tmp_path / "app.py",
        "__all__ = ['my_fn']\n\ndef my_fn():\n    return 1\n",
    )
    result = cx.detect(tmp_path)
    orphans = [f for f in result["findings"] if f["code"] == "ORPHAN_MODULE_DEF"]
    assert not orphans


# ---- unreachable code ------------------------------------------------------


def test_unreachable_after_return_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def x():\n    return 1\n    print('never')\n",
    )
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "UNREACHABLE" in codes


def test_unreachable_after_raise_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def x():\n    raise ValueError\n    print('never')\n",
    )
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "UNREACHABLE" in codes


# ---- orphan module-level def -----------------------------------------------


def test_orphan_module_def_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def helper():\n    return 1\n\ndef main():\n    return 2\n")
    result = cx.detect(tmp_path)
    orphans = [f for f in result["findings"] if f["code"] == "ORPHAN_MODULE_DEF"]
    names = {f["message"].split("`")[1] for f in orphans}
    assert "helper" in names
    assert "main" in names


def test_private_def_not_flagged_as_orphan(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def _private():\n    return 1\n")
    result = cx.detect(tmp_path)
    orphans = [f for f in result["findings"] if f["code"] == "ORPHAN_MODULE_DEF"]
    assert not orphans


# ---- JS/TS fn-too-long approximate -----------------------------------------


def test_js_function_too_long_flagged(tmp_path: Path) -> None:
    body = "  x = 1;\n" * 30
    _write(tmp_path / "app.ts", f"function long() {{\n{body}}}\n")
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "FN_TOO_LONG_REGEX" in codes


def test_js_arrow_function_too_long_flagged(tmp_path: Path) -> None:
    body = "  x = 1;\n" * 30
    _write(tmp_path / "app.ts", f"const long = () => {{\n{body}}};\n")
    result = cx.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "FN_TOO_LONG_REGEX" in codes


# ---- determinism + CLI -----------------------------------------------------


def test_invalid_python_silently_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "def x(:\n")
    result = cx.detect(tmp_path)
    assert result["total_findings"] == 0


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "import os\n")
    _write(tmp_path / "b.py", "import sys\n")
    r1 = cx.detect(tmp_path)
    r2 = cx.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", "def x(): return 1\n")
    rc = cx.main(["complexity", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert "thresholds" in body
