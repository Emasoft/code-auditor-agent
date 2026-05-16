"""Unit tests for Step 12 — docstring quality."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import docstring_diff as dd


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- Docstring param mismatch ---------------------------------------------


def test_google_args_missing_param(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '''
def foo(a, b, c):
    """One-line summary.

    Args:
        a: first
        b: second
    """
    return a + b + c
'''.lstrip(),
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DOCSTRING_PARAM_MISSING" in codes


def test_google_args_complete_match(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '''
def foo(a, b, c):
    """Summary.

    Args:
        a: first
        b: second
        c: third
    """
    return a + b + c
'''.lstrip(),
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DOCSTRING_PARAM_MISSING" not in codes
    assert "DOCSTRING_PARAM_GHOST" not in codes


def test_google_args_ghost_param(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '''
def foo(a):
    """Summary.

    Args:
        a: first
        b: nonexistent
    """
    return a
'''.lstrip(),
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DOCSTRING_PARAM_GHOST" in codes


def test_sphinx_param_mismatch(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '''
def foo(a, b):
    """Summary.

    :param a: first
    """
    return a + b
'''.lstrip(),
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DOCSTRING_PARAM_MISSING" in codes


def test_numpy_params_complete(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '''
def foo(a, b):
    """Summary.

    Parameters
    ----------
    a : int
        First
    b : int
        Second
    """
    return a + b
'''.lstrip(),
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DOCSTRING_PARAM_MISSING" not in codes


def test_no_docstring_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def foo(a):\n    return a\n")
    result = dd.detect(tmp_path)
    mismatch = [f for f in result["findings"] if f["category"] == "docstring_param_mismatch"]
    assert not mismatch


def test_self_and_cls_not_required_in_docstring(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '''
class C:
    def method(self, a):
        """Summary.

        Args:
            a: first
        """
        return a
'''.lstrip(),
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DOCSTRING_PARAM_MISSING" not in codes


# ---- Trivial docstring -----------------------------------------------------


def test_trivial_module_docstring(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", '"""TODO"""\n')
    result = dd.detect(tmp_path)
    trivial = [f for f in result["findings"] if f["code"] == "TRIVIAL_DOCSTRING"]
    assert trivial


def test_trivial_function_docstring(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '"""Module docstring is long enough to be meaningful."""\n\n'
        "def foo():\n"
        '    """description here"""\n'
        "    return 1\n",
    )
    result = dd.detect(tmp_path)
    trivial = [f for f in result["findings"] if f["code"] == "TRIVIAL_DOCSTRING"]
    assert any("foo" in f["message"] for f in trivial)


def test_short_one_word_docstring_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '"""Module docstring is long enough."""\n\ndef foo():\n    """Helper"""\n    return 1\n',
    )
    result = dd.detect(tmp_path)
    trivial = [f for f in result["findings"] if f["code"] == "TRIVIAL_DOCSTRING"]
    assert any("foo" in f["message"] for f in trivial)


def test_substantial_docstring_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        '"""Substantial module docstring with multiple words."""\n\n'
        "def foo():\n"
        '    """Compute the result by applying the formula across all rows."""\n'
        "    return 1\n",
    )
    result = dd.detect(tmp_path)
    trivial = [f for f in result["findings"] if f["code"] == "TRIVIAL_DOCSTRING"]
    assert not trivial


# ---- Comment contradicts literal ------------------------------------------


def test_comment_contradicts_assignment(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "RETRIES = 3  # default is 5\n",
    )
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "COMMENT_CONTRADICTS_LITERAL" in codes


def test_comment_with_no_numbers_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "RETRIES = 3  # default value\n")
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "COMMENT_CONTRADICTS_LITERAL" not in codes


def test_comment_with_same_number_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "RETRIES = 3  # 3 means default\n")
    result = dd.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "COMMENT_CONTRADICTS_LITERAL" not in codes


# ---- Determinism + CLI ----------------------------------------------------


def test_invalid_python_silently_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "def x(:\n")
    result = dd.detect(tmp_path)
    assert result["total_findings"] == 0


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", 'def f(a):\n    """Args:\n        a: ok\n    """\n    return a\n')
    _write(tmp_path / "b.py", 'def g(b):\n    """summary"""\n    return b\n')
    r1 = dd.detect(tmp_path)
    r2 = dd.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", '"""ok"""\n')
    rc = dd.main(["docstring_diff", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
