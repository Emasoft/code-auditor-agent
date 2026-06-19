"""Unit tests for Step 0 — domain detection pre-flight gate.

Each test builds a tiny fixture tree under a tmp_path, runs detection,
and asserts on language / domain / specialist_firing fields. The
fixtures are intentionally small (a few files each) — they exist to
prove rule wiring, not to benchmark scale.

A separate determinism test asserts byte-identical output across two
runs on the same fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prereview.detect_languages_and_domains import (
    _domain_file_globs_match,
    detect,
    main,
)


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _make_python_fastapi_with_alembic(root: Path) -> None:
    _write(root / "pyproject.toml", '[project]\nname="x"\ndependencies=["fastapi", "sqlalchemy", "alembic"]\n')
    _write(root / "alembic.ini", "[alembic]\nscript_location = migrations\n")
    _write(root / "migrations" / "env.py", "from alembic import context\n")
    _write(root / "migrations" / "versions" / "0001_init.py", "def upgrade(): pass\ndef downgrade(): pass\n")
    _write(
        root / "app" / "main.py",
        "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/health')\ndef health():\n    return {'ok': True}\n",
    )
    _write(root / "app" / "users.py", "from sqlalchemy import Column\n")
    _write(root / "tests" / "test_main.py", "def test_ok(): pass\n")


def _make_react_typescript_project(root: Path) -> None:
    _write(
        root / "package.json",
        '{"name":"web","dependencies":{"react":"^18","typescript":"^5"},"devDependencies":{"vite":"^5"}}\n',
    )
    _write(root / "tsconfig.json", '{"compilerOptions":{"strict":true}}\n')
    _write(root / "src" / "App.tsx", "export default function App() { return <div/>; }\n")
    _write(root / "src" / "main.tsx", "import React from 'react';\n")
    _write(root / "src" / "lib.ts", "export const x = 1;\n")


def _make_go_rest_with_docker(root: Path) -> None:
    _write(root / "go.mod", "module example.com/svc\nrequire github.com/gin-gonic/gin v1.9\n")
    _write(
        root / "main.go",
        'package main\nimport "github.com/gin-gonic/gin"\nfunc main(){ r := gin.Default(); r.Run() }\n',
    )
    _write(root / "Dockerfile", "FROM golang:1.22\n")
    _write(root / "docker-compose.yml", "version: '3'\n")


def _make_multi_tenant_python(root: Path) -> None:
    _write(root / "pyproject.toml", '[project]\nname="m"\ndependencies=["fastapi"]\n')
    for i in range(5):
        _write(
            root / "app" / f"feature_{i}.py",
            "def get_records(tenant_id: str):\n    return db.query(Item).filter_by(tenant_id=tenant_id).all()\n",
        )


def _make_mcp_python_server(root: Path) -> None:
    _write(root / "pyproject.toml", '[project]\nname="srv"\ndependencies=["mcp[cli]"]\n')
    _write(
        root / "server.py",
        'from mcp.server import Server\n\nserver = Server("demo")\n\n@server.tool()\ndef hello():\n    return "hi"\n',
    )


# ---- language detection ----------------------------------------------------


def test_python_fastapi_detected(tmp_path: Path) -> None:
    _make_python_fastapi_with_alembic(tmp_path)
    result = detect(tmp_path)
    assert result["languages"]["python"]["detected"] is True
    assert result["languages"]["javascript"]["detected"] is False
    assert result["languages"]["typescript"]["detected"] is False


def test_typescript_requires_tsconfig_or_volume(tmp_path: Path) -> None:
    """A single .ts file without tsconfig.json should NOT flip the TS flag.

    Otherwise vanilla JS projects that happen to have a .d.ts somewhere
    would be misclassified as TS. We require either tsconfig.json or
    enough .ts files to be unambiguous.
    """
    _write(tmp_path / "package.json", '{"name":"x"}\n')
    _write(tmp_path / "types.d.ts", "export {};\n")
    result = detect(tmp_path)
    assert result["languages"]["typescript"]["detected"] is False


def test_typescript_with_tsconfig_detected(tmp_path: Path) -> None:
    _make_react_typescript_project(tmp_path)
    result = detect(tmp_path)
    assert result["languages"]["typescript"]["detected"] is True
    assert result["languages"]["javascript"]["detected"] is False


def test_go_module_detected(tmp_path: Path) -> None:
    _make_go_rest_with_docker(tmp_path)
    result = detect(tmp_path)
    assert result["languages"]["go"]["detected"] is True


def test_no_language_when_empty_repo(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# empty\n", encoding="utf-8")
    result = detect(tmp_path)
    for lang in ("python", "javascript", "typescript", "go", "rust", "swift", "elixir", "solidity"):
        assert result["languages"][lang]["detected"] is False, f"{lang} falsely detected"


# ---- domain detection ------------------------------------------------------


def test_rest_api_detected_via_manifest(tmp_path: Path) -> None:
    _make_python_fastapi_with_alembic(tmp_path)
    result = detect(tmp_path)
    assert result["domains"]["rest_api"]["detected"] is True


def test_rest_api_detected_via_capitalized_manifest_dep(tmp_path: Path) -> None:
    """Case-insensitive manifest-substring match: a capitalized `Django` dep
    (the rule substring is lowercase `django`) must still flag the rest_api
    domain. Regression: a case-sensitive `in` silently missed it, so a Django
    project with no @app.route source was not detected at all.
    """
    _write(tmp_path / "requirements.txt", "Django==4.2\n")
    result = detect(tmp_path)
    assert result["domains"]["rest_api"]["detected"] is True


# ---- glob matcher: deep paths, bundle dirs, anchoring ----------------------


def test_glob_match_deep_path_glob(tmp_path: Path) -> None:
    """A `**/<dir>/**/*.ext` glob matches a deeply-nested file. Regression: the
    old substring test left a literal `*` in the needle and matched nothing."""
    f = tmp_path / "db" / "migrations" / "0001" / "init.sql"
    _write(f, "SELECT 1;\n")
    assert _domain_file_globs_match(tmp_path, [f], ("**/migrations/**/*.sql",))


def test_glob_match_bundle_directory(tmp_path: Path) -> None:
    """A directory-bundle glob (`**/*.xcodeproj`) matches via a file INSIDE the
    bundle — enumeration yields only the inner files, never the bundle dir."""
    f = tmp_path / "MyApp.xcodeproj" / "project.pbxproj"
    _write(f, "// pbxproj\n")
    assert _domain_file_globs_match(tmp_path, [f], ("**/*.xcodeproj",))


def test_glob_match_anchored_no_cross_boundary(tmp_path: Path) -> None:
    """`**/translations/**` must NOT match `auto_translations/` (the old
    unanchored substring test produced cross-directory-boundary false positives),
    but MUST still match a real `translations/` directory."""
    fp = tmp_path / "src" / "auto_translations" / "cache.json"
    _write(fp, "{}\n")
    assert _domain_file_globs_match(tmp_path, [fp], ("**/translations/**",)) == []
    real = tmp_path / "app" / "translations" / "en.json"
    _write(real, "{}\n")
    assert _domain_file_globs_match(tmp_path, [real], ("**/translations/**",))


def test_sql_migrations_detected_via_alembic(tmp_path: Path) -> None:
    _make_python_fastapi_with_alembic(tmp_path)
    result = detect(tmp_path)
    assert result["domains"]["sql_migrations"]["detected"] is True


def test_docker_detected(tmp_path: Path) -> None:
    _make_go_rest_with_docker(tmp_path)
    result = detect(tmp_path)
    assert result["domains"]["docker"]["detected"] is True


def test_frontend_detected_via_react(tmp_path: Path) -> None:
    _make_react_typescript_project(tmp_path)
    result = detect(tmp_path)
    assert result["domains"]["frontend"]["detected"] is True


def test_multi_tenant_requires_min_hits(tmp_path: Path) -> None:
    """≥3 distinct files mentioning a tenant marker → detected; below → not."""
    _write(tmp_path / "pyproject.toml", '[project]\nname="x"\ndependencies=[]\n')
    _write(tmp_path / "app" / "a.py", "tenant_id = 'x'\n")
    _write(tmp_path / "app" / "b.py", "tenant_id = 'y'\n")
    result_below = detect(tmp_path)
    assert result_below["domains"]["multi_tenant"]["detected"] is False
    _write(tmp_path / "app" / "c.py", "tenant_id = 'z'\n")
    _write(tmp_path / "app" / "d.py", "tenant_id = 'w'\n")
    result_above = detect(tmp_path)
    assert result_above["domains"]["multi_tenant"]["detected"] is True


def test_multi_tenant_fires_specialist(tmp_path: Path) -> None:
    _make_multi_tenant_python(tmp_path)
    result = detect(tmp_path)
    assert result["domains"]["multi_tenant"]["detected"] is True
    assert result["specialist_firing"]["multi_tenant_detector"] is True


def test_mcp_server_detected(tmp_path: Path) -> None:
    _make_mcp_python_server(tmp_path)
    result = detect(tmp_path)
    assert result["domains"]["mcp_server"]["detected"] is True
    assert result["specialist_firing"]["mcp_server_reviewer"] is True


def test_solidity_requires_language(tmp_path: Path) -> None:
    """solidity_contracts gates on the solidity language being detected too."""
    _write(tmp_path / "README.md", "Some .sol-flavoured docs but no contracts.\n")
    result = detect(tmp_path)
    assert result["domains"]["solidity_contracts"]["detected"] is False


def test_solidity_detected_when_contracts_present(tmp_path: Path) -> None:
    _write(tmp_path / "foundry.toml", "[profile.default]\nsrc = 'src'\n")
    for i in range(2):
        _write(tmp_path / "src" / f"C{i}.sol", "pragma solidity ^0.8.0;\ncontract X {}\n")
    result = detect(tmp_path)
    # Single-file thresholds — language only needs file-count >= 10 OR manifest;
    # foundry.toml IS a manifest, so solidity should fire.
    assert result["languages"]["solidity"]["detected"] is True
    assert result["domains"]["solidity_contracts"]["detected"] is True


# ---- specialist firing -----------------------------------------------------


def test_specialist_firing_keys_are_complete(tmp_path: Path) -> None:
    """Every specialist mentioned in the TRDD must appear in the JSON, even
    when not firing. Downstream agents check `specialist_firing[<name>]`
    by exact key; a missing key would crash them.
    """
    (tmp_path / "README.md").write_text("# empty\n", encoding="utf-8")
    result = detect(tmp_path)
    expected = {
        "multi_tenant_detector",
        "graphql_reviewer",
        "jwt_reviewer",
        "api_design_reviewer",
        "docker_reviewer",
        "prompt_injection_reviewer",
        "frontend_reviewer",
        "ios_reviewer",
        "elixir_reviewer",
        "solidity_reviewer",
        "mcp_server_reviewer",
        "i18n_reviewer",
        "l10n_reviewer",
        "monorepo_reviewer",
        "logging_reviewer",
    }
    assert set(result["specialist_firing"]) == expected
    # And every value is a bool.
    for v in result["specialist_firing"].values():
        assert isinstance(v, bool)


# ---- determinism -----------------------------------------------------------


def test_two_runs_byte_identical(tmp_path: Path) -> None:
    """Modulo the timestamp, two runs must produce byte-identical JSON.

    Determinism is the contract that lets downstream agents cache results
    and lets reviewers diff scans across PR revisions.
    """
    _make_python_fastapi_with_alembic(tmp_path)
    r1 = detect(tmp_path)
    r2 = detect(tmp_path)
    # Strip the only timestamp-bearing field before comparing.
    r1.pop("timestamp")
    r2.pop("timestamp")
    j1 = json.dumps(r1, indent=2, sort_keys=True)
    j2 = json.dumps(r2, indent=2, sort_keys=True)
    assert j1 == j2


# ---- CLI -------------------------------------------------------------------


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _make_python_fastapi_with_alembic(repo)
    rc = main(["detect_languages_and_domains", str(repo), str(out)])
    assert rc == 0
    files = list(out.iterdir())
    assert len(files) == 1
    assert files[0].name.endswith("-domains_detected.json")
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert "languages" in body
    assert "domains" in body
    assert "specialist_firing" in body


def test_main_rejects_bad_args(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["detect_languages_and_domains"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_main_rejects_nonexistent_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["detect_languages_and_domains", str(tmp_path / "missing"), str(tmp_path / "out")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "directory" in err.lower()
