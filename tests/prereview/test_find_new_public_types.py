"""Unit tests for Step 16 gate — find new public types in a diff."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.prereview import find_new_public_types as fnt


def _write_diff(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_python_class_addition_detected(tmp_path: Path) -> None:
    diff = "+++ b/app/models.py\n@@ -0,0 +1,3 @@\n+class User:\n+    pass\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 1
    t = result["types"][0]
    assert t["name"] == "User"
    assert t["kind"] == "class"
    assert t["language"] == "python"
    assert t["file"] == "app/models.py"
    assert t["line"] == 1


def test_python_dataclass_decorator_promotes_kind(tmp_path: Path) -> None:
    diff = "+++ b/app/order.py\n@@ -0,0 +1,3 @@\n+@dataclass\n+class Order:\n+    id: int\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    types = result["types"]
    assert len(types) == 1
    assert types[0]["kind"] == "dataclass"
    assert types[0]["name"] == "Order"


def test_python_enum_detected(tmp_path: Path) -> None:
    diff = (
        "+++ b/app/status.py\n@@ -0,0 +1,4 @@\n+from enum import Enum\n+class OrderStatus(Enum):\n+    OPEN = 'open'\n"
    )
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    types = result["types"]
    # `class OrderStatus(Enum):` matches the enum pattern (more specific) AND
    # the generic class pattern. The matcher returns whichever fires first;
    # because enum is in the list it should fire first if ordering is right.
    enum_types = [t for t in types if t["kind"] == "enum"]
    assert enum_types
    assert enum_types[0]["name"] == "OrderStatus"


def test_nested_class_not_reported(tmp_path: Path) -> None:
    """A class nested inside another class is NOT a new public top-level type.

    Regression: lstrip() erased the indentation that distinguishes a nested
    decl, so Inner was reported alongside the module-level Outer.
    """
    diff = (
        "+++ b/app/models.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+class Outer:\n"
        "+    class Inner:\n"
        "+        pass\n"
    )
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    names = {t["name"] for t in result["types"]}
    assert "Outer" in names
    assert "Inner" not in names


def test_python_typeddict_detected(tmp_path: Path) -> None:
    diff = (
        "+++ b/app/dto.py\n@@ -0,0 +1,4 @@\n+from typing import TypedDict\n+class UserDTO(TypedDict):\n+    id: int\n"
    )
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    typeddict_types = [t for t in result["types"] if t["kind"] == "typeddict"]
    assert typeddict_types


def test_python_private_class_not_detected(tmp_path: Path) -> None:
    diff = "+++ b/app/internal.py\n@@ -0,0 +1,2 @@\n+class _Internal:\n+    pass\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 0


def test_typescript_interface_detected(tmp_path: Path) -> None:
    diff = "+++ b/src/types.ts\n@@ -0,0 +1,3 @@\n+export interface User {\n+  id: string;\n+}\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 1
    assert result["types"][0]["kind"] == "interface"
    assert result["types"][0]["name"] == "User"
    assert result["types"][0]["language"] == "typescript"


def test_typescript_type_alias_detected(tmp_path: Path) -> None:
    diff = "+++ b/src/types.ts\n@@ -0,0 +1 @@\n+export type UserId = string;\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    types = result["types"]
    assert types and types[0]["kind"] == "type"
    assert types[0]["name"] == "UserId"


def test_typescript_non_exported_not_detected(tmp_path: Path) -> None:
    diff = "+++ b/src/internal.ts\n@@ -0,0 +1,3 @@\n+interface Hidden {\n+  x: number;\n+}\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 0


def test_go_exported_struct_detected(tmp_path: Path) -> None:
    diff = "+++ b/pkg/user/user.go\n@@ -0,0 +1,3 @@\n+type User struct {\n+    ID int\n+}\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 1
    assert result["types"][0]["language"] == "go"
    assert result["types"][0]["kind"] == "struct"


def test_go_lowercase_not_detected(tmp_path: Path) -> None:
    diff = "+++ b/pkg/user/user.go\n@@ -0,0 +1 @@\n+type user struct{}\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 0


def test_rust_pub_struct_detected(tmp_path: Path) -> None:
    diff = "+++ b/src/lib.rs\n@@ -0,0 +1 @@\n+pub struct Config { pub url: String }\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 1
    assert result["types"][0]["language"] == "rust"


def test_rust_non_pub_struct_not_detected(tmp_path: Path) -> None:
    diff = "+++ b/src/lib.rs\n@@ -0,0 +1 @@\n+struct InternalConfig {}\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 0


def test_diff_with_context_lines_tracks_line_numbers(tmp_path: Path) -> None:
    """The post-image line cursor must advance through context AND addition
    lines but NOT deletion lines.
    """
    diff = "+++ b/app/models.py\n@@ -1,3 +1,6 @@\n # existing module\n import os\n+class NewType:\n+    pass\n \n+\n"
    _write_diff(tmp_path / "pr.patch", diff)
    result = fnt.detect(tmp_path / "pr.patch")
    assert result["total"] == 1
    # New post-image: line 1 (` # existing module`), 2 (`import os`), 3
    # (`+class NewType:`). So the class is at line 3.
    assert result["types"][0]["line"] == 3


def test_findings_deterministically_sorted(tmp_path: Path) -> None:
    diff = "+++ b/z.py\n@@ -0,0 +1 @@\n+class Zebra:\n+    pass\n+++ b/a.py\n@@ -0,0 +1 @@\n+class Apple:\n+    pass\n"
    _write_diff(tmp_path / "pr.patch", diff)
    r1 = fnt.detect(tmp_path / "pr.patch")
    r2 = fnt.detect(tmp_path / "pr.patch")
    r1.pop("timestamp")
    r2.pop("timestamp")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
    # And the order is by file alphabetically.
    files = [t["file"] for t in r1["types"]]
    assert files == sorted(files)


def test_main_emits_file(tmp_path: Path) -> None:
    diff_file = tmp_path / "pr.patch"
    out = tmp_path / "out"
    diff_file.write_text(
        "+++ b/app/x.py\n@@ -0,0 +1 @@\n+class X:\n    pass\n",
        encoding="utf-8",
    )
    rc = fnt.main(["find_new_public_types", str(diff_file), str(out)])
    assert rc == 0
    body = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
    assert body["schema_version"] == 1
    assert "types" in body


def test_main_rejects_missing_diff_file(tmp_path: Path, capsys) -> None:
    rc = fnt.main(["find_new_public_types", str(tmp_path / "missing.patch"), str(tmp_path / "out")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()
