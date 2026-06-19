"""Unit tests for Step 9 — concurrency hazards scanner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import concurrency as cc


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---- Python: detached create_task / ensure_future --------------------------


def test_detached_create_task_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "import asyncio\nasync def main():\n    asyncio.create_task(do_work())\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DETACHED_CREATE_TASK" in codes


def test_create_task_with_reference_not_flagged_for_detached(tmp_path: Path) -> None:
    """`task = asyncio.create_task(...)` is not a bare-statement Call — pass."""
    _write(
        tmp_path / "app.py",
        "import asyncio\nasync def main():\n    task = asyncio.create_task(do_work())\n    await task\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DETACHED_CREATE_TASK" not in codes


def test_ensure_future_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "import asyncio\nasync def main():\n    asyncio.ensure_future(do_work())\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "DETACHED_CREATE_TASK" in codes


def test_run_in_executor_no_await_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.py",
        "import asyncio\n"
        "async def main():\n"
        "    loop = asyncio.get_event_loop()\n"
        "    loop.run_in_executor(None, blocking)\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "LOOP_RUN_IN_EXECUTOR_NO_AWAIT" in codes


# ---- comment/string-blindness + path containment --------------------------


def test_load_pr_files_confines_to_repo_root(tmp_path: Path) -> None:
    """_load_pr_files must drop listing entries that resolve OUTSIDE repo_root
    (a `../secret.txt` traversal) — an out-of-tree read otherwise."""
    repo = tmp_path / "repo"
    _write(repo / "app.py", "x = 1\n")
    _write(tmp_path / "secret.txt", "OUTSIDE\n")  # sibling of repo, not inside it
    listing = tmp_path / "pr.txt"
    _write(listing, "app.py\n../secret.txt\n")
    files = cc._load_pr_files(repo, listing)
    assert files is not None
    names = {p.name for p in files}
    assert "app.py" in names
    assert "secret.txt" not in names


def test_go_channel_send_after_close_real_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.go",
        "package main\nfunc f(ch chan int) {\n    close(ch)\n    ch <- 1\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "CHANNEL_SEND_AFTER_CLOSE" in codes


def test_go_channel_send_after_close_comment_not_flagged(tmp_path: Path) -> None:
    """A `ch <- x` inside a // comment must NOT fire CHANNEL_SEND_AFTER_CLOSE
    (the only error-severity rule) — comments are blanked before matching."""
    _write(
        tmp_path / "main.go",
        "package main\nfunc f(ch chan int) {\n    close(ch)\n"
        "    // ch <- 1 handled elsewhere\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "CHANNEL_SEND_AFTER_CLOSE" not in codes


def test_promise_no_catch_real_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.js",
        "function f() {\n    Promise.all([a, b]);\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "PROMISE_NO_CATCH" in codes


def test_promise_no_catch_comment_not_flagged(tmp_path: Path) -> None:
    """A `Promise.all(` inside a // comment must NOT fire PROMISE_NO_CATCH."""
    _write(
        tmp_path / "app.js",
        "function f() {\n    // Promise.all([a, b]) is done elsewhere\n    doStuff();\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "PROMISE_NO_CATCH" not in codes


def test_invalid_python_silently_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "def x(:\n")
    result = cc.detect(tmp_path)
    assert result["total_findings"] == 0


# ---- JS/TS: floating promises / no-catch -----------------------------------


def test_floating_promise_call_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "function main() {\n  fetch('https://example.com');\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "FLOATING_PROMISE" in codes


def test_awaited_promise_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "async function main() {\n  await fetch('https://example.com');\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "FLOATING_PROMISE" not in codes


def test_promise_all_without_catch_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "const r = Promise.all([fa(), fb()]);\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "PROMISE_NO_CATCH" in codes


def test_promise_all_with_catch_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "const r = Promise.all([fa(), fb()]).catch(console.error);\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "PROMISE_NO_CATCH" not in codes


def test_promise_all_in_try_block_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "async function main() {\n"
        "  try {\n"
        "    const r = await Promise.all([fa(), fb()]);\n"
        "  } catch (e) { console.error(e); }\n"
        "}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "PROMISE_NO_CATCH" not in codes


# ---- Go: goroutine + send-after-close --------------------------------------


def test_goroutine_without_sync_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.go",
        "func main() {\n    go doWork()\n    return\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "GOROUTINE_NO_SYNC" in codes


def test_goroutine_with_waitgroup_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.go",
        "func main() {\n"
        "    var wg sync.WaitGroup\n"
        "    wg.Add(1)\n"
        "    go func() { defer wg.Done(); doWork() }()\n"
        "    wg.Wait()\n"
        "}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "GOROUTINE_NO_SYNC" not in codes


def test_channel_send_after_close_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.go",
        "func main() {\n    ch := make(chan int, 1)\n    close(ch)\n    ch <- 42\n}\n",
    )
    result = cc.detect(tmp_path)
    codes = {f["code"] for f in result["findings"]}
    assert "CHANNEL_SEND_AFTER_CLOSE" in codes


# ---- determinism + CLI -----------------------------------------------------


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "import asyncio\nasync def m():\n    asyncio.create_task(work())\n")
    _write(tmp_path / "b.ts", "fetch('x');\n")
    r1 = cc.detect(tmp_path)
    r2 = cc.detect(tmp_path)
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_main_emits_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    _write(repo / "app.py", "import asyncio\nasync def m():\n    asyncio.create_task(work())\n")
    rc = cc.main(["concurrency", str(repo), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert any(f["code"] == "DETACHED_CREATE_TASK" for f in body["findings"])
