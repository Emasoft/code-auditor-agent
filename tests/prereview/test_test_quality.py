"""Unit tests for Step 13 — test-quality scanner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import test_quality as tq


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- Python: no assertion -------------------------------------------------


def test_no_assertion_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "def test_foo():\n    x = compute()\n    print(x)\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "NO_ASSERTION_TEST" in codes


def test_assert_statement_satisfies_check(tmp_path: Path) -> None:
    _write(tmp_path / "test_foo.py", "def test_foo():\n    assert 1 + 1 == 2\n")
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "NO_ASSERTION_TEST" not in codes


def test_patch_decorator_not_double_counted(tmp_path: Path) -> None:
    """A single @patch(...) decorator must yield ONE MOCK_REPLACES_SUT_HEURISTIC.

    Regression: ast.walk reached the decorator Call via both the FunctionDef
    branch and the standalone-Call branch of _patch_targets, so one decorator
    produced two identical findings; detect() now dedups on (file, line, code).
    """
    _write(
        tmp_path / "test_svc.py",
        "from unittest.mock import patch\n"
        "from app.svc import process\n"
        "@patch('app.svc.process')\n"
        "def test_process():\n"
        "    assert process() is None\n",
    )
    result = tq.detect(tmp_path)
    hits = [f for f in result["findings"] if f["code"] == "MOCK_REPLACES_SUT_HEURISTIC"]
    assert len(hits) == 1


def test_pytest_raises_satisfies_check(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "import pytest\ndef test_foo():\n    with pytest.raises(ValueError):\n        do_thing()\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "NO_ASSERTION_TEST" not in codes


def test_unittest_assert_satisfies_check(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "import unittest\nclass T(unittest.TestCase):\n    def test_foo(self):\n        self.assertEqual(1, 1)\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "NO_ASSERTION_TEST" not in codes


def test_mock_assert_called_satisfies_check(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "from unittest.mock import Mock\ndef test_foo():\n    m = Mock()\n    m()\n    m.assert_called_once()\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "NO_ASSERTION_TEST" not in codes


# ---- Python: assert true literal ------------------------------------------


def test_assert_true_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "test_foo.py", "def test_foo():\n    assert True\n")
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "ASSERT_TRUE_LITERAL" in codes


def test_assert_constant_int_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "test_foo.py", "def test_foo():\n    assert 1\n")
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "ASSERT_TRUE_LITERAL" in codes


def test_assert_same_operand_compare_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "test_foo.py", "def test_foo():\n    assert 'x' == 'x'\n")
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "ASSERT_TRUE_LITERAL" in codes


def test_asserttrue_true_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "import unittest\nclass T(unittest.TestCase):\n    def test_foo(self):\n        self.assertTrue(True)\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "ASSERT_TRUE_LITERAL" in codes


# ---- Python: mock-replaces-SUT -------------------------------------------


def test_mock_replaces_sut_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "from mymod.calculator import compute\n"
        "from unittest.mock import patch\n\n"
        '@patch("mymod.calculator.compute")\n'
        "def test_compute(mock_compute):\n"
        "    mock_compute.return_value = 42\n"
        "    assert compute(1) == 42\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MOCK_REPLACES_SUT_HEURISTIC" in codes


def test_mock_of_unrelated_function_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_foo.py",
        "from mymod.calculator import compute\n"
        "from unittest.mock import patch\n\n"
        '@patch("mymod.network.fetch")\n'
        "def test_compute(mock_fetch):\n"
        "    assert compute(1) == 42\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MOCK_REPLACES_SUT_HEURISTIC" not in codes


# ---- JS/TS regex checks ---------------------------------------------------


def test_js_expect_true_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.test.ts",
        "test('foo', () => {\n  expect(true).toBe(true);\n});\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_EXPECT_TRUE" in codes


def test_js_expect_truthy_literal_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.test.ts",
        'test("foo", () => {\n  expect(1).toBeTruthy();\n});\n',
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_EXPECT_TRUTHY" in codes


def test_js_real_assertion_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.test.ts",
        "test('foo', () => {\n  expect(compute(1)).toBe(42);\n});\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_EXPECT_TRUE" not in codes
    assert "JS_EXPECT_TRUTHY" not in codes


def test_js_test_without_expect_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.test.ts",
        "test('foo', () => {\n  const x = compute();\n  console.log(x);\n});\n",
    )
    result = tq.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_NO_ASSERTION" in codes


def test_non_test_file_python_not_scanned(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def foo():\n    print('x')\n")
    result = tq.detect(tmp_path)
    assert result["total_findings"] == 0


def test_non_test_file_js_not_scanned(tmp_path: Path) -> None:
    _write(tmp_path / "app.ts", "function foo() { expect(true).toBe(true); }\n")
    result = tq.detect(tmp_path)
    assert result["total_findings"] == 0


# ---- determinism + CLI ----------------------------------------------------


def test_invalid_python_silently_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "test_broken.py", "def test_x(:\n")
    result = tq.detect(tmp_path)
    assert result["total_findings"] == 0


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "test_a.py", "def test_a():\n    pass\n")
    _write(tmp_path / "test_b.py", "def test_b():\n    assert True\n")
    r1 = tq.detect(tmp_path)
    r2 = tq.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "test_foo.py", "def test_foo():\n    assert True\n")
    rc = tq.main(["test_quality", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
