"""Unit tests for Step 15 — database / migration scanner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import database as db


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- migrations -----------------------------------------------------------


def test_empty_downgrade_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "migrations" / "versions" / "0001_init.py",
        "def upgrade():\n    op.create_table('x')\n\ndef downgrade():\n    pass\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "EMPTY_DOWNGRADE" in codes


def test_real_downgrade_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "migrations" / "versions" / "0001_init.py",
        "def upgrade():\n    op.create_table('x')\n\ndef downgrade():\n    op.drop_table('x')\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "EMPTY_DOWNGRADE" not in codes
    assert "MISSING_DOWNGRADE" not in codes


def test_async_empty_downgrade_flagged(tmp_path: Path) -> None:
    """async def downgrade() with an empty body must flag EMPTY_DOWNGRADE.

    Regression: ast.AsyncFunctionDef is not a subclass of ast.FunctionDef, so
    async Alembic migrations were silently invisible to the scanner.
    """
    _write(
        tmp_path / "migrations" / "versions" / "0001_init.py",
        "async def upgrade():\n    await op.create_table('x')\n\n"
        "async def downgrade():\n    pass\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "EMPTY_DOWNGRADE" in codes


def test_async_real_downgrade_not_flagged(tmp_path: Path) -> None:
    """An async migration with a real downgrade body must NOT be flagged."""
    _write(
        tmp_path / "migrations" / "versions" / "0001_init.py",
        "async def upgrade():\n    await op.create_table('x')\n\n"
        "async def downgrade():\n    await op.drop_table('x')\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "EMPTY_DOWNGRADE" not in codes
    assert "MISSING_DOWNGRADE" not in codes


def test_missing_downgrade_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "migrations" / "versions" / "0001_init.py",
        "def upgrade():\n    op.create_table('x')\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "MISSING_DOWNGRADE" in codes


def test_migration_outside_migrations_dir_not_scanned(tmp_path: Path) -> None:
    _write(
        tmp_path / "app" / "noddyfile.py",
        "def upgrade():\n    pass\n\ndef downgrade():\n    pass\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "EMPTY_DOWNGRADE" not in codes
    assert "MISSING_DOWNGRADE" not in codes


# ---- SQL injection via f-string -------------------------------------------


def test_fstring_execute_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        'def get(user_id):\n    return cursor.execute(f"select * from u where id = {user_id}")\n',
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SQL_INJECTION_FSTRING" in codes


def test_parameterised_execute_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def get(user_id):\n    return cursor.execute('select * from u where id = ?', (user_id,))\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SQL_INJECTION_FSTRING" not in codes


def test_percent_format_execute_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        'def get(user_id):\n    return cursor.execute("select * from u where id = %s" % user_id)\n',
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SQL_INJECTION_FSTRING" in codes


def test_str_format_execute_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        'def get(user_id):\n    return cursor.execute("select * from u where id = {}".format(user_id))\n',
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SQL_INJECTION_FSTRING" in codes


def test_fstring_without_interpolation_not_flagged(tmp_path: Path) -> None:
    """A plain f-string (no `{x}` slots) is just a regular string."""
    _write(
        tmp_path / "app.py",
        'def get():\n    return cursor.execute(f"select * from u")\n',
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "SQL_INJECTION_FSTRING" not in codes


# ---- Generic SQL scan -----------------------------------------------------


def test_alter_table_in_random_sql_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "fix.sql", "ALTER TABLE users ADD COLUMN x INT;\n")
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "ALTER_TABLE_OUTSIDE_MIGRATION" in codes


def test_alter_table_in_migration_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "migrations" / "001_add_col.sql",
        "ALTER TABLE users ADD COLUMN x INT;\n",
    )
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "ALTER_TABLE_OUTSIDE_MIGRATION" not in codes


def test_drop_table_outside_migration_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "wipe.sql", "DROP TABLE temp_data;\n")
    result = db.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DROP_TABLE_OUTSIDE_MIGRATION" in codes


# ---- determinism + CLI ----------------------------------------------------


def test_invalid_python_silently_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "migrations" / "versions" / "broken.py", "def x(:\n")
    result = db.detect(tmp_path)
    assert result["total_findings"] == 0


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(
        tmp_path / "migrations" / "versions" / "001.py",
        "def upgrade():\n    pass\n\ndef downgrade():\n    pass\n",
    )
    _write(
        tmp_path / "app.py",
        'cursor.execute(f"select * where id = {x}")\n',
    )
    r1 = db.detect(tmp_path)
    r2 = db.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "migrations" / "versions" / "001.py", "def upgrade(): pass\n")
    rc = db.main(["database", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
