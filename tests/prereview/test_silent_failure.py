"""Unit tests for Step 8 — silent-failure hunter."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import silent_failure as sf


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- Python AST checks -----------------------------------------------------


def test_bare_except_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "try:\n    do_thing()\nexcept:\n    pass\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SILENT_BARE" in codes
    assert "SILENT_EMPTY" in codes  # also flagged for the empty body


def test_broad_except_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "try:\n    do_thing()\nexcept Exception:\n    raise\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "BROAD_CATCH" in codes


def test_empty_body_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "try:\n    parse()\nexcept ValueError:\n    pass\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SILENT_EMPTY" in codes


def test_log_only_handler_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "import logging\nlogger = logging.getLogger(__name__)\n"
        "try:\n    parse()\nexcept ValueError as e:\n    logger.error('parse failed: %s', e)\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SILENT_LOG_ONLY" in codes


def test_print_only_handler_flagged(tmp_path: Path) -> None:
    """A handler whose only body is `print(...)` must flag SILENT_LOG_ONLY.

    The matcher runs against the dotted callee name ("print"), so the print
    shape must end at a word boundary, not a literal "(" (regression: the
    documented print case of SILENT_LOG_ONLY was silently broken).
    """
    _write(
        tmp_path / "app.py",
        "try:\n    parse()\nexcept ValueError:\n    print('parse failed')\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SILENT_LOG_ONLY" in codes


def test_log_then_raise_not_flagged_as_log_only(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "import logging\nlogger = logging.getLogger(__name__)\n"
        "try:\n    parse()\nexcept ValueError as e:\n    logger.error('parse failed')\n    raise\n",
    )
    result = sf.detect(tmp_path)
    log_only = [f for f in result["findings"] if f["code"] == "SILENT_LOG_ONLY"]
    assert not log_only


def test_todo_in_handler_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "try:\n    parse()\nexcept ValueError:\n    # TODO: handle this properly\n    pass\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "TODO_IN_HANDLER" in codes


def test_specific_except_with_proper_handling_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "try:\n    parse()\nexcept ValueError as e:\n    raise CustomError() from e\n",
    )
    result = sf.detect(tmp_path)
    # No SILENT_* / BROAD_* findings should appear.
    bad_codes = {"SILENT_BARE", "SILENT_EMPTY", "SILENT_LOG_ONLY", "BROAD_CATCH", "TODO_IN_HANDLER"}
    actual_codes = {f["code"] for f in result["findings"]}
    assert not (bad_codes & actual_codes)


def test_invalid_python_skipped_silently(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "def x(:\n  pass\n")
    result = sf.detect(tmp_path)
    # Should not crash; no findings either.
    assert result["total_findings"] == 0


# ---- JS/TS regex checks ----------------------------------------------------


def test_js_empty_catch_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "try {\n  parse();\n} catch (e) {\n}\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "CATCH_EMPTY" in codes


def test_js_console_only_catch_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "try {\n  parse();\n} catch (e) {\n  console.error('parse failed', e);\n}\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "CATCH_CONSOLE_ONLY" in codes


def test_js_throw_in_catch_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "try {\n  parse();\n} catch (e) {\n  console.error('parse failed');\n  throw e;\n}\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "CATCH_CONSOLE_ONLY" not in codes


def test_optional_chain_over_fallible_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "const data = response?.json();\nconst t = response?.text();\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "OPTIONAL_CHAIN_FALLIBLE" in codes


def test_optional_chain_over_safe_method_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "const n = user?.name;\nconst c = obj?.children;\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "OPTIONAL_CHAIN_FALLIBLE" not in codes


# ---- mock-in-prod fallback -------------------------------------------------


def test_mock_fallback_detected_node_env(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.js",
        "if (process.env.NODE_ENV !== 'production') {\n  api = mockApi;\n}\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MOCK_FALLBACK" in codes


def test_mock_fallback_detected_python(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "import os\nif os.environ.get('ENV') != 'production':\n    api = fake_api()\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MOCK_FALLBACK" in codes


def test_no_mock_in_window_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.js",
        "if (process.env.NODE_ENV !== 'production') {\n  console.log('debug');\n}\n",
    )
    result = sf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MOCK_FALLBACK" not in codes


# ---- determinism + CLI -----------------------------------------------------


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "try:\n  x()\nexcept:\n  pass\n")
    _write(tmp_path / "b.py", "try:\n  y()\nexcept Exception:\n  raise\n")
    r1 = sf.detect(tmp_path)
    r2 = sf.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", "try:\n  x()\nexcept:\n  pass\n")
    rc = sf.main(["silent_failure", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert any(f["code"] == "SILENT_BARE" for f in body["findings"])
