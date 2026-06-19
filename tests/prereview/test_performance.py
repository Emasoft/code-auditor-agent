"""Unit tests for Step 14 — performance scanner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import performance as pf


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- Python: N+1 ----------------------------------------------------------


def test_n_plus_one_in_for_loop_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def handler(ids):\n    for uid in ids:\n        user = db.query(User).filter(id=uid).first()\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "N_PLUS_ONE_LOOP" in codes


def test_query_outside_loop_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def handler(ids):\n    users = db.query(User).filter(id__in=ids).all()\n")
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "N_PLUS_ONE_LOOP" not in codes


def test_open_read_not_double_counted(tmp_path: Path) -> None:
    """open(...).read() must yield ONE LARGE_FILE_FULL_READ, not two.

    Regression: the check matched both the outer .read() Attribute and the inner
    open() Name at the same line; detect() now dedups on (file, line, code).
    """
    _write(tmp_path / "app.py", "def f():\n    data = open('data.csv').read()\n    return data\n")
    result = pf.detect(tmp_path)
    hits = [f for f in result["findings"] if f["code"] == "LARGE_FILE_FULL_READ"]
    assert len(hits) == 1


def test_load_pr_files_confines_to_repo_root(tmp_path: Path) -> None:
    """_load_pr_files drops listing entries that resolve OUTSIDE repo_root — the
    shared path-containment guard applied across the prereview family (the same
    fix verified in concurrency; representative check that it holds in a sibling).
    """
    repo = tmp_path / "repo"
    _write(repo / "app.py", "x = 1\n")
    _write(tmp_path / "secret.txt", "OUTSIDE\n")
    listing = tmp_path / "pr.txt"
    _write(listing, "app.py\n../secret.txt\n")
    files = pf._load_pr_files(repo, listing)
    assert files is not None
    names = {p.name for p in files}
    assert "app.py" in names
    assert "secret.txt" not in names


# ---- Python: recursive-no-memo --------------------------------------------


def test_recursive_no_memo_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def fib(n):\n    if n < 2: return n\n    return fib(n-1) + fib(n-2)\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "RECURSIVE_NO_MEMO" in codes


def test_recursive_with_lru_cache_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "from functools import lru_cache\n"
        "@lru_cache\n"
        "def fib(n):\n    if n < 2: return n\n    return fib(n-1) + fib(n-2)\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "RECURSIVE_NO_MEMO" not in codes


def test_non_recursive_function_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "def add(a, b):\n    return a + b\n")
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "RECURSIVE_NO_MEMO" not in codes


# ---- Python: large-file read ----------------------------------------------


def test_large_file_read_flagged_by_extension(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "data = open('events.log').read()\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "LARGE_FILE_FULL_READ" in codes


def test_large_file_read_flagged_by_hint_name(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "from pathlib import Path\nbig_dataset = Path('large_input.txt').read_text()\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "LARGE_FILE_FULL_READ" in codes


def test_normal_read_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "data = open('config.toml').read()\n")
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "LARGE_FILE_FULL_READ" not in codes


# ---- JS / TS --------------------------------------------------------------


def test_js_n_plus_one_in_foreach_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "ids.forEach((id) => {\n  const u = db.findOne({ id });\n});\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_N_PLUS_ONE_LOOP" in codes


def test_js_n_plus_one_in_for_loop_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "for (const id of ids) {\n  const u = db.query('select ...');\n}\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_N_PLUS_ONE_LOOP" in codes


def test_js_read_sync_large_file_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "import fs from 'fs';\nconst data = fs.readFileSync('events.log');\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_LARGE_FILE_SYNC_READ" in codes


def test_js_read_sync_normal_file_flags_sync_warning(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "import fs from 'fs';\nconst data = fs.readFileSync('config.json');\n",
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "JS_SYNC_FILE_READ" in codes
    assert "JS_LARGE_FILE_SYNC_READ" not in codes


# ---- Go -------------------------------------------------------------------


def test_go_db_in_loop_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.go",
        'func handle(ids []int) {\n  for _, id := range ids {\n    db.QueryContext(ctx, "select ...")\n  }\n}\n',
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "GO_DB_IN_LOOP" in codes


def test_go_db_outside_loop_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.go",
        'func handle(ids []int) {\n  db.QueryContext(ctx, "select ...")\n}\n',
    )
    result = pf.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "GO_DB_IN_LOOP" not in codes


# ---- determinism + CLI ----------------------------------------------------


def test_invalid_python_silently_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "def x(:\n")
    result = pf.detect(tmp_path)
    assert result["total_findings"] == 0


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "def fib(n):\n    return fib(n-1)\n")
    _write(tmp_path / "b.py", "for x in [1]:\n    db.query()\n")
    r1 = pf.detect(tmp_path)
    r2 = pf.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", "def fib(n):\n    return fib(n-1)\n")
    rc = pf.main(["performance", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
