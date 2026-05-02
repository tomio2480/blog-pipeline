"""list_materials.py のテスト．TDD（Red-Green-Refactor）で実装する．

必須テストケース 4 種 + 追加テスト 4 種の計 8 テストを含む．
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from list_materials import (
    _extract_frontmatter,
    format_json,
    format_table,
    list_materials,
    main,
)


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


# ---------- B-2: UnicodeDecodeError 対応テスト ----------


def test_invalid_utf8_file_is_skipped_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """不正な UTF-8 バイト列を含む .md ファイルはスキップされ warning が出る（B-2）．
    同ディレクトリの正常ファイルは影響を受けない．
    """
    # 不正な UTF-8 バイト列（0xFF 0xFE はシーケンスとして不正）を書き込む
    invalid_path = tmp_path / "broken.md"
    invalid_path.write_bytes(b"---\nnote_title: test\n---\n\xff\xfe invalid utf8")

    # 正常なファイルも置く
    _write_md(tmp_path, "valid.md", MINIMAL_FRONTMATTER_2)

    result = list_materials(tmp_path)

    # 正常ファイルは返る
    assert len(result) == 1
    assert result[0]["note_title"] == "別のノート"

    # stderr に warning が出る
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "Warning" in captured.err


# ---------- B-3: サイドカー空値の一貫性テスト ----------


def test_sidecar_empty_values_preserve_existing_frontmatter(
    tmp_path: Path,
) -> None:
    """サイドカーに summary: "" と auto_tags: [] が入っているとき，
    frontmatter の既存 summary / tags が保持される（B-3）．
    """
    frontmatter_with_summary = """\
---
source: evernote
note_title: "サマリー付きノート"
created: "2026-04-28T09:49:31Z"
updated: "2026-04-28T10:11:33Z"
author: "alice"
tags:
  - 既存タグA
  - 既存タグB
summary: "既存のサマリーテキスト"
---

本文
"""
    # サイドカーに空値を入れる（note-tagger が未実行の想定）
    empty_sidecar = """\
summary: ""
auto_tags:
"""
    _write_md(tmp_path, "note.md", frontmatter_with_summary)
    _write_summary(tmp_path, "note", empty_sidecar)

    result = list_materials(tmp_path)

    assert len(result) == 1
    item = result[0]
    # 空値のサイドカーで frontmatter の既存 summary が上書きされないこと
    assert item["summary"] == "既存のサマリーテキスト"
    # 空値のサイドカーで frontmatter の既存 tags が保持されること
    assert item["tags"] == ["既存タグA", "既存タグB"]
    # サイドカーの auto_tags が空のとき auto_tags は空配列にフォールバックすること
    assert item["auto_tags"] == []


# ---------- B-4: format_table truncate テスト ----------


def test_format_table_truncates_long_note_title(tmp_path: Path) -> None:
    """note_title が 50 字のとき，table 出力のデータ行が 40 字＋スペース＋tags 30 字以内＋スペース＋summary という幅に収まる（B-4）．"""
    long_title_frontmatter = """\
---
source: evernote
note_title: "12345678901234567890123456789012345678901234567890"
created: "2026-04-28T09:49:31Z"
updated: "2026-04-28T10:11:33Z"
author: "alice"
tags: ["tagA"]
---

本文
"""
    _write_md(tmp_path, "note.md", long_title_frontmatter)
    _write_summary(tmp_path, "note", SUMMARY_YAML)

    result = list_materials(tmp_path)
    output = format_table(result)

    lines = output.splitlines()
    # ヘッダー行・セパレーター行を除いた最初のデータ行を確認
    data_line = lines[2]
    # note_title 列（先頭 40 字幅）の後ろはスペース区切りであること
    # つまり data_line[40] はスペースでなければならない（41 字目が切り詰め後の境界）
    assert data_line[40] == " ", (
        f"41 字目がスペースでない（note_title が切り詰められていない）: {data_line!r}"
    )


# ---------- 新規 5 件（レビュー指摘反映）----------


def test_load_summary_yaml_invalid_yaml_returns_empty_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """_load_summary_yaml が OSError / UnicodeDecodeError のとき空辞書を返し warning を出す．"""
    from list_materials import _load_summary_yaml

    invalid_path = tmp_path / "broken.summary.yml"
    invalid_path.write_bytes(b"\xff\xfe broken utf8 content")

    result = _load_summary_yaml(invalid_path)

    assert result == {}
    captured = capsys.readouterr()
    assert "Warning" in captured.err or "warning" in captured.err.lower()


def test_format_table_header_has_summary_column_padding(tmp_path: Path) -> None:
    """format_table ヘッダー行の幅が note_title(40)+1+tags(30)+1+summary(30)=102 文字に揃う．"""
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER)
    _write_summary(tmp_path, "note", SUMMARY_YAML)

    result = list_materials(tmp_path)
    output = format_table(result)

    header = output.splitlines()[0]
    assert len(header) == 102, (
        f"ヘッダー長が 102 でない: {len(header)!r}, header={header!r}"
    )


def test_format_table_data_row_summary_padding(tmp_path: Path) -> None:
    """summary が 10 字以下の短い場合でも，データ行の summary 列が :<30 でパディングされる．"""
    short_summary_sidecar = """\
summary: "短い"
auto_tags:
  - x
"""
    _write_md(tmp_path, "note.md", MINIMAL_FRONTMATTER)
    _write_summary(tmp_path, "note", short_summary_sidecar)

    result = list_materials(tmp_path)
    output = format_table(result)

    data_line = output.splitlines()[2]
    # note_title(40) + space(1) + tags(30) + space(1) = 72 文字目から summary 開始
    # summary 列も :<30 でパディングされると全体が 102 文字になる
    assert len(data_line) == 102, (
        f"データ行長が 102 でない: {len(data_line)!r}, line={data_line!r}"
    )


def test_inline_yaml_list_in_frontmatter_parses_as_list(tmp_path: Path) -> None:
    """tags: ["a","b"] のインライン配列表記がリストとしてパースされる．"""
    from list_materials import _parse_simple_yaml

    yaml_text = 'tags: ["tagA", "tagB"]'
    result = _parse_simple_yaml(yaml_text)

    assert result["tags"] == ["tagA", "tagB"], (
        f"インライン配列がリストにならなかった: {result['tags']!r}"
    )


def test_main_returns_2_when_path_is_file_not_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """通常ファイルを引数に渡したとき exit code 2 + エラーメッセージを返す．"""
    file_path = tmp_path / "not_a_dir.md"
    file_path.write_text("content", encoding="utf-8")

    exit_code = main([str(file_path)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.err != ""


def test_extract_frontmatter_returns_false_when_parser_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """_parse_simple_yaml が ValueError を投げたとき，
    _extract_frontmatter は (空辞書, False) を返す．
    warning は呼び出し側 list_materials が出すため本関数からは出さない．
    """
    def _raise_value_error(_text: str) -> dict[str, object]:
        raise ValueError("simulated parse error")

    monkeypatch.setattr("list_materials._parse_simple_yaml", _raise_value_error)

    text = "---\nfoo: bar\n---\n\n本文\n"
    parsed, ok = _extract_frontmatter(text)

    assert parsed == {}
    assert ok is False

    captured = capsys.readouterr()
    assert captured.err == ""


def test_extract_frontmatter_does_not_swallow_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """終了系例外（KeyboardInterrupt）は捕捉せず伝播する．
    except (ValueError, TypeError) に絞った効果を確認．
    """
    def _raise_keyboard_interrupt(_text: str) -> dict[str, object]:
        raise KeyboardInterrupt("simulated interrupt")

    monkeypatch.setattr("list_materials._parse_simple_yaml", _raise_keyboard_interrupt)

    text = "---\nfoo: bar\n---\n\n本文\n"
    with pytest.raises(KeyboardInterrupt):
        _extract_frontmatter(text)
