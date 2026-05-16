"""Unit tests for Step 7 — multi-tenant data-isolation scanner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import multi_tenant as mt


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- query predicates ------------------------------------------------------


def test_sqlalchemy_filter_by_user_id_without_tenant_id_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def list_items(user_id):\n    return db.query(Item).filter_by(user_id=user_id).all()\n",
    )
    result = mt.detect(tmp_path)
    queries = [f for f in result["findings"] if f["category"] == "query_missing_tenant"]
    assert len(queries) >= 1
    assert queries[0]["code"] == "SQLALCHEMY_FILTER_BY"


def test_sqlalchemy_with_tenant_id_in_same_line_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "def list_items(user_id, tenant_id):\n"
        "    return db.query(Item).filter_by(user_id=user_id, tenant_id=tenant_id).all()\n",
    )
    result = mt.detect(tmp_path)
    queries = [f for f in result["findings"] if f["category"] == "query_missing_tenant"]
    assert not queries


def test_sqlalchemy_with_tenant_in_nearby_line_not_flagged(tmp_path: Path) -> None:
    """`tenant_id` mentioned within the ±2 line window is enough."""
    _write(
        tmp_path / "app.py",
        "def list_items(user_id, tenant_id):\n"
        "    q = db.query(Item)\n"
        "    q = q.filter_by(user_id=user_id)\n"
        "    q = q.filter(Item.tenant_id == tenant_id)\n"
        "    return q.all()\n",
    )
    result = mt.detect(tmp_path)
    queries = [f for f in result["findings"] if f["category"] == "query_missing_tenant"]
    assert not queries


def test_django_filter_user_without_tenant_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "items = Item.objects.filter(user=request.user)\n",
    )
    result = mt.detect(tmp_path)
    queries = [f for f in result["findings"] if f["category"] == "query_missing_tenant"]
    assert len(queries) == 1
    assert queries[0]["code"] == "DJANGO_FILTER"


def test_prisma_where_user_id_without_tenant_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "users.ts",
        "const u = await prisma.user.findMany({ where: { userId: id } });\n",
    )
    result = mt.detect(tmp_path)
    queries = [f for f in result["findings"] if f["category"] == "query_missing_tenant"]
    assert len(queries) == 1
    assert queries[0]["code"] == "PRISMA_WHERE"


def test_raw_sql_where_user_id_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "queries.sql",
        "SELECT * FROM items WHERE user_id = 1;\n",
    )
    result = mt.detect(tmp_path)
    queries = [f for f in result["findings"] if f["category"] == "query_missing_tenant"]
    assert any(q["code"] == "RAW_SQL_WHERE_USER" for q in queries)


# ---- cache keys ------------------------------------------------------------


def test_cache_get_without_tenant_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "cache.py",
        "def get_user_session(uid):\n    return cache.get(f'sess:{uid}')\n",
    )
    result = mt.detect(tmp_path)
    cache = [f for f in result["findings"] if f["category"] == "cache_key_missing_tenant"]
    assert len(cache) == 1
    assert cache[0]["code"] == "CACHE_KEY_NO_TENANT"


def test_cache_get_with_tenant_in_key_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "cache.py",
        "def get_user_session(uid, tenant_id):\n    return cache.get(f'sess:{tenant_id}:{uid}')\n",
    )
    result = mt.detect(tmp_path)
    cache = [f for f in result["findings"] if f["category"] == "cache_key_missing_tenant"]
    assert not cache


def test_redis_get_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "store.py", 'val = redis.get(f"user:{u}:state")\n')
    result = mt.detect(tmp_path)
    cache = [f for f in result["findings"] if f["category"] == "cache_key_missing_tenant"]
    assert len(cache) == 1


# ---- module-level state ----------------------------------------------------


def test_module_level_empty_dict_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "state.py",
        "CACHE: dict = {}\nSESSIONS = []\n",
    )
    result = mt.detect(tmp_path)
    state = [f for f in result["findings"] if f["category"] == "module_level_mutable_state"]
    names = {f["message"].split("'")[1] for f in state}
    assert "CACHE" in names
    assert "SESSIONS" in names


def test_module_level_inside_function_not_flagged(tmp_path: Path) -> None:
    """Mutable state inside a function body is per-call, not per-process."""
    _write(
        tmp_path / "fn.py",
        "def handle():\n    cache: dict = {}\n    return cache\n",
    )
    result = mt.detect(tmp_path)
    state = [f for f in result["findings"] if f["category"] == "module_level_mutable_state"]
    assert not state


def test_module_level_non_empty_dict_not_flagged(tmp_path: Path) -> None:
    """Config-like dicts are intentionally const and not the bug target.

    Only the "empty container, MUST be filled at runtime" form is the
    cross-tenant accumulator pattern.
    """
    _write(
        tmp_path / "config.py",
        "DEFAULTS: dict = {'timeout': 30, 'retries': 3}\n",
    )
    result = mt.detect(tmp_path)
    state = [f for f in result["findings"] if f["category"] == "module_level_mutable_state"]
    assert not state


# ---- function signatures ---------------------------------------------------


def test_function_signature_user_id_without_tenant_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "fn.py",
        "def get_user_record(user_id: str):\n    pass\n",
    )
    result = mt.detect(tmp_path)
    sigs = [f for f in result["findings"] if f["category"] == "function_takes_user_not_tenant"]
    assert len(sigs) == 1


def test_function_signature_with_tenant_id_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "fn.py",
        "def get_user_record(user_id: str, tenant_id: str):\n    pass\n",
    )
    result = mt.detect(tmp_path)
    sigs = [f for f in result["findings"] if f["category"] == "function_takes_user_not_tenant"]
    assert not sigs


def test_function_signature_tenant_id_within_body_not_flagged(tmp_path: Path) -> None:
    """If `tenant_id` shows up in the function body within 8 lines, accept."""
    _write(
        tmp_path / "fn.py",
        "def get_user_record(user_id: str, tenant: object):\n"
        "    tenant_id = tenant.id\n"
        "    return db.query().filter_by(user_id=user_id, tenant_id=tenant_id).first()\n",
    )
    result = mt.detect(tmp_path)
    sigs = [f for f in result["findings"] if f["category"] == "function_takes_user_not_tenant"]
    assert not sigs


# ---- gating + CLI ----------------------------------------------------------


def test_domains_gate_off_when_multi_tenant_absent(tmp_path: Path) -> None:
    _write(tmp_path / "domains.json", json.dumps({"domains": {"multi_tenant": {"detected": False}}}))
    _write(tmp_path / "app.py", "items = db.query(I).filter_by(user_id=1).all()\n")
    result = mt.detect(
        tmp_path,
        domains={"multi_tenant": {"detected": False}},
    )
    assert result["gated_off_multi_tenant_not_detected"] is True
    assert result["total_findings"] == 0


def test_domains_gate_on_when_multi_tenant_detected(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "items = db.query(I).filter_by(user_id=1).all()\n")
    result = mt.detect(
        tmp_path,
        domains={"multi_tenant": {"detected": True}},
    )
    assert result["gated_off_multi_tenant_not_detected"] is False
    assert result["total_findings"] >= 1


def test_findings_are_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x = db.query(I).filter_by(user_id=1).all()\n")
    _write(tmp_path / "b.py", "y = cache.get(f'k:{u}')\n")
    r1 = mt.detect(tmp_path)
    r2 = mt.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", "x = db.query(I).filter_by(user_id=1).all()\n")
    rc = mt.main(["multi_tenant", str(repo), str(out)])
    assert rc == 0
    files = list(out.iterdir())
    assert len(files) == 1


def test_main_with_domains_from_gates_correctly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", "x = db.query(I).filter_by(user_id=1).all()\n")
    domains_path = tmp_path / "domains.json"
    domains_path.write_text(
        json.dumps({"domains": {"multi_tenant": {"detected": False, "evidence": []}}}),
        encoding="utf-8",
    )
    rc = mt.main(["multi_tenant", str(repo), str(out), "--domains-from", str(domains_path)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["gated_off_multi_tenant_not_detected"] is True
    assert body["total_findings"] == 0
