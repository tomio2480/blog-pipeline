"""build_material.py のテスト．

人間メモ Markdown と生の文字起こしテキストから 2 セクション素材を組み立てる
振る舞いを検証する．TDD の Red-Green-Refactor で実装する．
"""

from __future__ import annotations

from pathlib import Path

import pytest

from build_material import (
    Material,
    build_material,
    derive_created,
    main,
    material_to_markdown,
    parse_memo,
    write_material,
)


SECTION_HUMAN_MEMO = "## 🗒️ 人間メモ（音声添付の後に書かれたもの）"
SECTION_RAW_TRANSCRIPTION = "## 🗣️ 生の文字起こし"


# ---------- parse_memo ----------


def test_parse_memo_with_frontmatter_returns_dict_and_body() -> None:
    text = (
        "---\n"
        'tags: ["PHP", "登壇"]\n'
        "---\n"
        "\n"
        "fortee のリンクを貼った．\n"
    )
    front, body = parse_memo(text)
    assert front["tags"] == ["PHP", "登壇"]
    assert body == "fortee のリンクを貼った．"


def test_parse_memo_without_frontmatter_returns_empty_dict_and_full_body() -> None:
    text = "ただの手書きメモ．\n2 行目．\n"
    front, body = parse_memo(text)
    assert front == {}
    assert body == "ただの手書きメモ．\n2 行目．"


def test_parse_memo_frontmatter_only_has_empty_body() -> None:
    text = "---\ntags: []\n---\n"
    front, body = parse_memo(text)
    assert front["tags"] == []
    assert body == ""


def test_parse_memo_raises_on_malformed_frontmatter() -> None:
    # インデント不正で YAML パースに失敗する例．無言で本文扱いにせず明示エラーとする
    text = "---\ntags: [PHP\n  bad: : :\n---\n\n本文．"
    with pytest.raises(ValueError, match="フロントマターが不正"):
        parse_memo(text)


def test_parse_memo_raises_when_frontmatter_is_not_mapping() -> None:
    # フロントマターがスカラ（マッピングでない）の場合も明示エラーとする
    text = "---\nただの文字列\n---\n\n本文．"
    with pytest.raises(ValueError, match="マッピングである必要があります"):
        parse_memo(text)


# ---------- derive_created ----------


def test_derive_created_from_date_prefix() -> None:
    assert derive_created("2026-04-28-PHPカンファレンス香川の登壇") == "2026-04-28T00:00:00Z"


def test_derive_created_returns_empty_without_date_prefix() -> None:
    assert derive_created("録音メモ") == ""


def test_derive_created_returns_empty_for_invalid_calendar_date() -> None:
    # 正規表現は通るが暦上存在しない日付（13 月 40 日）は空文字へフォールバックする
    assert derive_created("2026-13-40-無効日付") == ""


# ---------- build_material: メタデータ解決 ----------


def test_build_material_inherits_tags_from_memo_frontmatter() -> None:
    memo = '---\ntags: ["PHP", "登壇"]\n---\n\n本文．'
    material = build_material("2026-04-28-登壇メモ", memo, "文字起こし本文．")
    assert material.tags == ["PHP", "登壇"]


def test_build_material_tags_empty_when_memo_has_no_frontmatter() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文のみ．", "文字起こし．")
    assert material.tags == []


def test_build_material_note_title_falls_back_to_stem() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "文字起こし．")
    assert material.note_title == "2026-04-28-登壇メモ"


def test_build_material_note_title_from_memo_frontmatter() -> None:
    memo = '---\nnote_title: "明示タイトル"\n---\n\n本文．'
    material = build_material("2026-04-28-登壇メモ", memo, "文字起こし．")
    assert material.note_title == "明示タイトル"


def test_build_material_created_from_stem_date_prefix() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "文字起こし．")
    assert material.created == "2026-04-28T00:00:00Z"


def test_build_material_created_from_memo_frontmatter_overrides_stem() -> None:
    memo = '---\ncreated: "2026-04-28T09:49:31Z"\n---\n\n本文．'
    material = build_material("2026-04-28-登壇メモ", memo, "文字起こし．")
    assert material.created == "2026-04-28T09:49:31Z"


def test_build_material_source_is_audio() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "文字起こし．")
    assert material.source == "audio"


def test_build_material_transcription_state_transcribed_when_present() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "文字起こし本文．")
    assert material.transcription_state == "transcribed"


def test_build_material_transcription_state_absent_when_empty() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "   \n")
    assert material.transcription_state == "absent"


def test_build_material_languages_inherited_from_memo_frontmatter() -> None:
    memo = '---\nlanguages: ["ja"]\n---\n\n本文．'
    material = build_material("2026-04-28-登壇メモ", memo, "文字起こし．")
    assert material.languages == ["ja"]


def test_build_material_languages_empty_by_default() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "文字起こし．")
    assert material.languages == []


def test_build_material_author_null_by_default() -> None:
    material = build_material("2026-04-28-登壇メモ", "本文．", "文字起こし．")
    assert material.author is None


def test_build_material_author_from_memo_frontmatter() -> None:
    memo = '---\nauthor: "Example Author"\n---\n\n本文．'
    material = build_material("2026-04-28-登壇メモ", memo, "文字起こし．")
    assert material.author == "Example Author"


def test_build_material_keeps_memo_body_verbatim() -> None:
    memo = "---\ntags: []\n---\n\n**強調** を含む手書きメモ．"
    material = build_material("2026-04-28-登壇メモ", memo, "文字起こし．")
    assert material.memo_body == "**強調** を含む手書きメモ．"


# ---------- material_to_markdown ----------


@pytest.fixture
def sample_markdown() -> str:
    memo = '---\ntags: ["PHP"]\nauthor: "Example Author"\n---\n\nfortee のリンク．'
    material = build_material("2026-04-28-登壇メモ", memo, "こんにちは．登壇しました．")
    return material_to_markdown(material)


def test_markdown_has_frontmatter_source(sample_markdown: str) -> None:
    assert "source: audio" in sample_markdown


def test_markdown_has_both_sections_in_order(sample_markdown: str) -> None:
    memo_idx = sample_markdown.index(SECTION_HUMAN_MEMO)
    trans_idx = sample_markdown.index(SECTION_RAW_TRANSCRIPTION)
    assert memo_idx < trans_idx


def test_markdown_contains_memo_body_and_transcription(sample_markdown: str) -> None:
    assert "fortee のリンク．" in sample_markdown
    assert "こんにちは．登壇しました．" in sample_markdown


def test_markdown_frontmatter_tags_inline(sample_markdown: str) -> None:
    assert 'tags: ["PHP"]' in sample_markdown


def test_markdown_frontmatter_note_title_quoted(sample_markdown: str) -> None:
    assert 'note_title: "2026-04-28-登壇メモ"' in sample_markdown


def test_markdown_starts_with_frontmatter_delimiter(sample_markdown: str) -> None:
    assert sample_markdown.startswith("---\n")


# ---------- write_material ----------


def test_write_material_writes_stem_filename(tmp_path: Path) -> None:
    path = write_material(
        "2026-04-28-登壇メモ", "本文．", "文字起こし．", tmp_path
    )
    assert path == tmp_path / "2026-04-28-登壇メモ.md"
    assert path.exists()


def test_write_material_content_matches_builder(tmp_path: Path) -> None:
    stem, memo, trans = "2026-04-28-登壇メモ", "本文．", "文字起こし．"
    path = write_material(stem, memo, trans, tmp_path)
    expected = material_to_markdown(build_material(stem, memo, trans))
    assert path.read_text(encoding="utf-8") == expected


def test_write_material_overwrites_existing(tmp_path: Path) -> None:
    stem = "2026-04-28-登壇メモ"
    first = write_material(stem, "初回本文．", "初回文字起こし．", tmp_path)
    second = write_material(stem, "再生成本文．", "再生成文字起こし．", tmp_path)
    assert first == second
    content = second.read_text(encoding="utf-8")
    assert "再生成本文．" in content
    assert "初回本文．" not in content


# ---------- CLI (main) ----------


def test_main_returns_2_when_memo_is_a_directory(tmp_path: Path) -> None:
    # ディレクトリを --memo に渡しても read_text のクラッシュではなく終了コード 2 を返す
    memo_dir = tmp_path / "memo_dir"
    memo_dir.mkdir()
    transcription = tmp_path / "transcription.txt"
    transcription.write_text("文字起こし．", encoding="utf-8")

    exit_code = main([
        "--memo", str(memo_dir),
        "--transcription", str(transcription),
        "--output-dir", str(tmp_path / "out"),
    ])

    assert exit_code == 2
