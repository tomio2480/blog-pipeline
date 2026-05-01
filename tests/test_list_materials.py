"""list_materials.py のテスト．TDD（Red-Green-Refactor）で実装する．

必須テストケース 4 種 + 追加テスト 4 種の計 8 テストを含む．
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from list_materials import list_materials, format_json, format_table, main


MINIMAL_FRONTMATTER = """\
---
source: evernote
note_title: "テストノート"
created: "2026-04-28T09:49:31Z"
updated: "2026-04-28T10:11:33Z"
author: "alice"
tags: ["tagA", "tagB"]
---

本文
"""

MINIMAL_FRONTMATTER_2 = """\
---
source: evernote
note_title: "別のノート"
created: "2026-04-29T09:49:31Z"
updated: "2026-04-29T10:11:33Z"
author: "bob"
tags: ["tagC"]
---

別の本文
"""

INVALID_FRONTMATTER = """\
note_title: "フロントマター区切りなし"
created: "2026-04-29T09:49:31Z"

本文（フロントマター開始 --- が無いため不正と判定される）
"""

SUMMARY_YAML = """\
summary: "これはサマリーです"
auto_tags:
  - タグ1
  - タグ2
"""


def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _write_summary(tmp_path: Path, stem: str, content: str) -> Path:
    path = tmp_path / f"{stem}.summary.yml"
    path.write_text(content, encoding="utf-8")
    return path


# ---------- 必須テストケース ----------


def test_list_empty_directory_returns_empty_array(tmp_path: Path) -> None:
    """素材 0 件のディレクトリ → 空配列を返す．"""
    result = list_materials(tmp_path)
    assert result == []


def test_list_materials_without_summary_yields_frontmatter_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """.summary.yml 無し → frontmatter フィールドのみ返す．
    summary は空文字列，auto_tags は空配列．stderr に warning が出る．
    """
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER)

    result = list_materials(tmp_path)

    assert len(result) == 1
    item = result[0]
    assert item["note_title"] == "テストノート"
    assert item["summary"] == ""
    assert item["auto_tags"] == []

    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "Warning" in captured.err


def test_list_materials_merges_summary_yaml(tmp_path: Path) -> None:
    """素材 + .summary.yml 揃い → 両者マージ．summary と auto_tags が含まれる．"""
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER)
    _write_summary(tmp_path, "note", SUMMARY_YAML)

    result = list_materials(tmp_path)

    assert len(result) == 1
    item = result[0]
    assert item["summary"] == "これはサマリーです"
    assert item["auto_tags"] == ["タグ1", "タグ2"]


def test_list_invalid_frontmatter_skipped_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """frontmatter 不正の素材 → スキップ + stderr に warning．他のファイルは正常に返す．"""
    _write_md(tmp_path, "invalid.md", INVALID_FRONTMATTER)
    _write_md(tmp_path, "valid.md", MINIMAL_FRONTMATTER_2)

    result = list_materials(tmp_path)

    assert len(result) == 1
    assert result[0]["note_title"] == "別のノート"

    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "Warning" in captured.err


# ---------- 追加テストケース ----------


def test_format_json_output_is_valid_json(tmp_path: Path) -> None:
    """--format json の出力が json.loads できる．"""
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER)
    _write_summary(tmp_path, "note", SUMMARY_YAML)

    result = list_materials(tmp_path)
    output = format_json(result)

    parsed = json.loads(output)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


def test_format_table_output_has_header(tmp_path: Path) -> None:
    """--format table の出力にヘッダー行がある．"""
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER)
    _write_summary(tmp_path, "note", SUMMARY_YAML)

    result = list_materials(tmp_path)
    output = format_table(result)

    lines = output.splitlines()
    assert len(lines) >= 1
    header = lines[0]
    assert "note_title" in header
    assert "tags" in header
    assert "summary" in header


def test_missing_directory_returns_exit_code_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """存在しないディレクトリで return 2．"""
    non_existent = tmp_path / "does_not_exist"

    exit_code = main(["--format", "json", str(non_existent)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err != ""


def test_readme_md_is_excluded(tmp_path: Path) -> None:
    """README.md は結果から除外される．"""
    _write_md(tmp_path, "README.md", MINIMAL_FRONTMATTER)
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER_2)

    result = list_materials(tmp_path)

    assert len(result) == 1
    assert result[0]["note_title"] == "別のノート"
