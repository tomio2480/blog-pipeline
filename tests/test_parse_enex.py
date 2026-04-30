"""parse_enex.py のテスト．happy path は fixture を使用し，エッジケースは
inline ENEX 文字列を一時ファイルへ書き出して検証する．"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from parse_enex import (
    Note,
    enml_to_markdown,
    extract_transcription,
    note_to_markdown,
    parse_enex,
    sanitize_filename,
    write_notes,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _write_enex(tmp_path: Path, body: str, name: str = "edge.enex") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------- Happy path: tests/fixtures/sample.enex ----------


@pytest.fixture
def happy_note() -> Note:
    notes = list(parse_enex(FIXTURES / "sample.enex"))
    assert len(notes) == 1
    return notes[0]


def test_happy_frontmatter_fields(happy_note: Note) -> None:
    assert happy_note.title == "架空イベント登壇メモ"
    assert happy_note.created == "2026-04-28T09:49:31Z"
    assert happy_note.updated == "2026-04-28T10:11:33Z"
    assert happy_note.author == "alice"
    assert happy_note.tags == ["架空タグA", "架空タグB"]
    assert happy_note.transcription_state == "transcribed"
    assert happy_note.languages == ["ja"]
    assert happy_note.attachments == [
        {"hash": "abc1234567890abcdef1234567890abcd", "type": "audio/mp4"}
    ]


def test_happy_transcription_extracted(happy_note: Note) -> None:
    assert "こんにちは" in happy_note.raw_transcription
    assert "架空のイベントで話します" in happy_note.raw_transcription


def test_happy_markdown_three_sections_order(happy_note: Note) -> None:
    md = note_to_markdown(happy_note)
    h1 = md.find("## 🗒️ 人間メモ")
    h2 = md.find("## 🤖 Evernote AI 構造化情報")
    h3 = md.find("## 🗣️ 生の文字起こし")
    assert 0 < h1 < h2 < h3


def test_happy_markdown_no_base64(happy_note: Note) -> None:
    md = note_to_markdown(happy_note)
    assert "AAECAwQFBgcICQoL" not in md
    assert "<data" not in md


def test_happy_markdown_frontmatter_yaml_shape(happy_note: Note) -> None:
    md = note_to_markdown(happy_note)
    assert md.startswith("---\n")
    fm_end = md.index("\n---\n", 4)
    fm = md[: fm_end + 5]
    assert 'source: evernote' in fm
    assert 'note_title: "架空イベント登壇メモ"' in fm
    assert 'created: "2026-04-28T09:49:31Z"' in fm
    assert 'transcription_state: "transcribed"' in fm
    assert 'languages: ["ja"]' in fm
    assert "- hash: \"abc1234567890abcdef1234567890abcd\"" in fm
    assert "type: \"audio/mp4\"" in fm


def test_happy_markdown_human_memo_links(happy_note: Note) -> None:
    md = note_to_markdown(happy_note)
    memo_start = md.index("## 🗒️ 人間メモ")
    ai_start = md.index("## 🤖 Evernote AI 構造化情報")
    memo = md[memo_start:ai_start]
    assert "[イベントページ](https://example.com/event)" in memo
    assert "[過去資料](https://example.com/slides)" in memo


def test_happy_markdown_ai_structured(happy_note: Note) -> None:
    md = note_to_markdown(happy_note)
    ai_start = md.index("## 🤖 Evernote AI 構造化情報")
    transcription_start = md.index("## 🗣️ 生の文字起こし")
    ai = md[ai_start:transcription_start]
    assert "# 登壇のテーマ" in ai
    assert "## 導入" in ai
    assert "## 本論" in ai
    assert "### 細かい話" in ai
    assert "- 項目その一" in ai
    assert "- 項目その二" in ai
    assert "[参考資料](https://example.com/ref)" in ai
    assert "> 引用したいテキスト" in ai


def test_happy_markdown_bold_no_outer_space_with_japanese_neighbor(happy_note: Note) -> None:
    md = note_to_markdown(happy_note)
    assert "**架空のフレームワーク**" in md
    assert " **架空のフレームワーク** " not in md


# ---------- enml_to_markdown ユニット ----------


def test_enml_headings_levels() -> None:
    enml = "<div><h1>A</h1><h2>B</h2><h3>C</h3></div>"
    out = enml_to_markdown(enml)
    assert "# A" in out
    assert "## B" in out
    assert "### C" in out


def test_enml_link_to_markdown() -> None:
    enml = '<p><a href="https://example.com/x">リンク</a></p>'
    assert "[リンク](https://example.com/x)" in enml_to_markdown(enml)


def test_enml_bold_no_space_with_japanese_neighbor() -> None:
    enml = "<p>前後<b>強調</b>あり</p>"
    out = enml_to_markdown(enml)
    assert "前後**強調**あり" in out


def test_enml_bold_at_line_edges_keeps_outer_space() -> None:
    enml = "<p><b>head</b></p><p>also <b>tail</b></p>"
    out = enml_to_markdown(enml)
    assert " **head** " in out
    assert " **tail** " in out


def test_enml_bullet_list() -> None:
    enml = "<ul><li>one</li><li>two</li></ul>"
    out = enml_to_markdown(enml)
    assert "- one" in out
    assert "- two" in out


def test_enml_blockquote() -> None:
    enml = "<blockquote>引用</blockquote>"
    assert "> 引用" in enml_to_markdown(enml)


def test_enml_entity_decoding() -> None:
    enml = "<p>A&nbsp;B&amp;C&lt;D</p>"
    out = enml_to_markdown(enml)
    assert "A" in out
    assert "B&C<D" in out


# ---------- extract_transcription ユニット ----------


def test_extract_transcription_segments_joined() -> None:
    style = (
        '--en-transcription:{"version":1,"languages":["ja"],'
        '"transcription_state":"transcribed",'
        '"segments":[{"text":"foo"},{"text":"bar"}]};'
    )
    text, state, langs = extract_transcription(style)
    assert "foo" in text
    assert "bar" in text
    assert state == "transcribed"
    assert langs == ["ja"]


def test_extract_transcription_absent_when_no_segments() -> None:
    style = '--en-transcription:{"version":1,"transcription_state":"absent"};'
    text, state, langs = extract_transcription(style)
    assert text == ""
    assert state == "absent"
    assert langs == []


def test_extract_transcription_returns_absent_for_empty_style() -> None:
    text, state, langs = extract_transcription("")
    assert text == ""
    assert state == "absent"
    assert langs == []


def test_extract_transcription_handles_brace_inside_string() -> None:
    style = (
        '--en-transcription:{"version":1,"languages":["ja"],'
        '"transcription_state":"transcribed",'
        '"segments":[{"text":"foo}bar"},{"text":"baz"}]};'
    )
    text, state, langs = extract_transcription(style)
    assert "foo}bar" in text
    assert "baz" in text
    assert state == "transcribed"
    assert langs == ["ja"]


def test_enml_nested_emphasis_preserved() -> None:
    enml = "<p>before<b>bold <i>italic</i></b>after</p>"
    out = enml_to_markdown(enml)
    assert "*italic*" in out
    assert "**bold" in out


def test_enml_bold_no_double_space_when_text_already_has_space() -> None:
    enml = "<p>foo <b>bar</b> baz</p>"
    out = enml_to_markdown(enml)
    assert "  **" not in out
    assert "**  " not in out
    assert "foo **bar** baz" in out


def test_enml_numeric_entity_does_not_break_parser() -> None:
    enml = "<p>A&#38;B&#60;C&#62;D</p>"
    out = enml_to_markdown(enml)
    assert "A&B<C>D" in out


def test_enml_bold_no_space_before_full_width_punctuation() -> None:
    enml = "<p>これは<b>強調</b>，あとに続く．</p>"
    out = enml_to_markdown(enml)
    assert "**強調**，" in out
    assert "** ，" not in out


def test_enml_bold_no_space_inside_full_width_brackets() -> None:
    enml = "<p>（<b>強調</b>）</p>"
    out = enml_to_markdown(enml)
    assert "（**強調**）" in out


def test_namespaced_enex_note_fields_extracted(tmp_path: Path) -> None:
    enex = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<en-export xmlns="http://xml.evernote.com/pub/evernote-export.xsd" '
        'application="Evernote" version="10.0">'
        "<note>"
        "<title>名前空間付き</title>"
        "<content><![CDATA[<en-note><h1>章</h1><p>本文．</p></en-note>]]></content>"
        "<created>20260428T094931Z</created>"
        "<updated>20260428T094931Z</updated>"
        "<tag>tagX</tag>"
        "<note-attributes><author>alice</author></note-attributes>"
        "</note>"
        "</en-export>"
    )
    path = _write_enex(tmp_path, enex, "namespaced.enex")
    notes = list(parse_enex(path))
    assert len(notes) == 1
    note = notes[0]
    assert note.title == "名前空間付き"
    assert note.tags == ["tagX"]
    assert note.author == "alice"
    assert note.created == "2026-04-28T09:49:31Z"


def test_namespaced_enml_list_items_rendered() -> None:
    enml = (
        '<ul xmlns="http://xml.evernote.com/pub/enml2.dtd">'
        "<li>alpha</li><li>beta</li></ul>"
    )
    out = enml_to_markdown(enml)
    assert "- alpha" in out
    assert "- beta" in out


def test_enml_hr_renders_as_thematic_break() -> None:
    enml = "<div><p>前段</p><hr/><p>後段</p></div>"
    out = enml_to_markdown(enml)
    assert "---" in out


def test_enml_empty_bold_does_not_emit_markup() -> None:
    enml = "<p>foo<b></b>bar</p>"
    out = enml_to_markdown(enml)
    assert "**" not in out
    assert "foobar" in out


def test_enml_inline_code_renders_as_backticks() -> None:
    enml = "<p>see <code>parse_enex</code> for detail</p>"
    out = enml_to_markdown(enml)
    assert "`parse_enex`" in out


def test_enml_bold_no_space_before_half_width_punctuation() -> None:
    enml = "<p>see <b>foo</b>, then <b>bar</b>!</p>"
    out = enml_to_markdown(enml)
    assert "**foo**," in out
    assert "**bar**!" in out


def test_enml_nested_list_rendered_with_indentation() -> None:
    enml = "<ul><li>top<ul><li>child1</li><li>child2</li></ul></li><li>top2</li></ul>"
    out = enml_to_markdown(enml)
    assert "- top" in out
    assert "  - child1" in out
    assert "  - child2" in out
    assert "- top2" in out


def test_enml_blockquote_multiline_each_prefixed() -> None:
    enml = "<blockquote>line1<br/>line2</blockquote>"
    out = enml_to_markdown(enml)
    assert "> line1" in out
    assert "> line2" in out


def test_enml_link_text_escapes_brackets() -> None:
    enml = '<p><a href="https://example.com/x">[label]</a></p>'
    out = enml_to_markdown(enml)
    assert "[\\[label\\]](https://example.com/x)" in out


def test_enml_inline_code_with_backtick_uses_double_backticks() -> None:
    enml = "<p><code>has `tick`</code></p>"
    out = enml_to_markdown(enml)
    assert "`` has `tick` ``" in out


def test_enml_br_outputs_two_space_newline() -> None:
    enml = "<p>foo<br/>bar</p>"
    out = enml_to_markdown(enml)
    assert "foo  \nbar" in out


# ---------- sanitize_filename ----------


def test_sanitize_filename_basic() -> None:
    name = sanitize_filename("ノートのタイトル", "2026-04-28T09:49:31Z")
    assert name.startswith("2026-04-28-")
    assert name.endswith(".md")
    assert "ノートのタイトル" in name


def test_sanitize_filename_replaces_unsafe_chars() -> None:
    name = sanitize_filename('a/b\\c:d*e?f"g<h>i|j', "2026-04-28T00:00:00Z")
    assert "/" not in name
    assert "\\" not in name
    assert ":" not in name
    assert "*" not in name
    assert "?" not in name
    assert '"' not in name
    assert "<" not in name
    assert ">" not in name
    assert "|" not in name


def test_sanitize_filename_collapses_consecutive_hyphens() -> None:
    name = sanitize_filename("a / b / c", "2026-04-28T00:00:00Z")
    assert "--" not in name.removesuffix(".md")


def test_sanitize_filename_strips_trailing_dot_and_space() -> None:
    name = sanitize_filename("title.   ", "2026-04-28T00:00:00Z")
    stem = name.removesuffix(".md")
    assert not stem.endswith(".")
    assert not stem.endswith(" ")


def test_sanitize_filename_avoids_windows_reserved_names() -> None:
    for reserved in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
        name = sanitize_filename(reserved, "2026-04-28T00:00:00Z")
        stem_after_date = name.removesuffix(".md").removeprefix("2026-04-28-")
        assert stem_after_date.upper() != reserved


def test_sanitize_filename_truncates_to_max_length() -> None:
    long_title = "あ" * 200
    name = sanitize_filename(long_title, "2026-04-28T00:00:00Z")
    stem = name.removesuffix(".md")
    assert len(stem) <= 80


def test_sanitize_filename_nfc_normalized() -> None:
    import unicodedata

    nfd = unicodedata.normalize("NFD", "ガ")
    name = sanitize_filename(nfd, "2026-04-28T00:00:00Z")
    stem = name.removesuffix(".md")
    assert unicodedata.is_normalized("NFC", stem)


# ---------- write_notes：衝突回避 ----------


def test_write_notes_collision_suffix(tmp_path: Path) -> None:
    enex = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<en-export application="Evernote" version="10.0">'
        + _make_minimal_note("同じタイトル", "20260428T094931Z")
        + _make_minimal_note("同じタイトル", "20260428T094931Z")
        + "</en-export>"
    )
    enex_path = _write_enex(tmp_path, enex, "collision.enex")
    out_dir = tmp_path / "out"
    written = write_notes(parse_enex(enex_path), out_dir)
    assert len(written) == 2
    names = sorted(p.name for p in written)
    assert names[0] != names[1]
    for p in written:
        assert p.exists()


# ---------- エッジケース ----------


def _make_minimal_note(
    title: str,
    created: str = "20260428T094931Z",
    body: str = "<en-note></en-note>",
    *,
    tags: list[str] | None = None,
    with_resource: bool = False,
) -> str:
    tags_xml = "".join(f"<tag>{t}</tag>" for t in (tags or []))
    resource_xml = ""
    if with_resource:
        resource_xml = (
            "<resource>"
            "<data encoding=\"base64\">AAECAwQF</data>"
            "<mime>audio/mp4</mime>"
            "</resource>"
        )
    return (
        "<note>"
        f"<title>{title}</title>"
        f"<content><![CDATA[{body}]]></content>"
        f"<created>{created}</created>"
        f"<updated>{created}</updated>"
        f"{tags_xml}"
        "<note-attributes><author>alice</author></note-attributes>"
        f"{resource_xml}"
        "</note>"
    )


def _wrap_export(notes_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<en-export application="Evernote" version="10.0">'
        + notes_xml
        + "</en-export>"
    )


def test_no_transcription_yields_absent_state(tmp_path: Path) -> None:
    body = "<en-note><h1>記事</h1><p>本文．</p></en-note>"
    enex = _wrap_export(_make_minimal_note("文字起こし無し", body=body))
    path = _write_enex(tmp_path, enex)
    note = next(parse_enex(path))
    assert note.transcription_state == "absent"
    assert note.raw_transcription == ""
    assert note.attachments == []


def test_no_h1_yields_empty_ai_section(tmp_path: Path) -> None:
    body = (
        '<en-note>'
        '<en-media style="--en-transcription:{&quot;segments&quot;:[{&quot;text&quot;:&quot;a&quot;}],&quot;transcription_state&quot;:&quot;transcribed&quot;,&quot;languages&quot;:[&quot;ja&quot;]};" hash="hhh" type="audio/mp4"/>'
        '<div>memo only</div>'
        '</en-note>'
    )
    enex = _wrap_export(_make_minimal_note("見出し無し", body=body))
    path = _write_enex(tmp_path, enex)
    note = next(parse_enex(path))
    md = note_to_markdown(note)
    ai_start = md.index("## 🤖 Evernote AI 構造化情報")
    transcription_start = md.index("## 🗣️ 生の文字起こし")
    ai = md[ai_start:transcription_start].strip()
    body_only = ai.removeprefix("## 🤖 Evernote AI 構造化情報").strip()
    assert body_only in {"", "（構造化情報なし）"}


def test_multiple_en_media_collected(tmp_path: Path) -> None:
    body = (
        '<en-note>'
        '<en-media style="--en-transcription:{&quot;segments&quot;:[{&quot;text&quot;:&quot;A&quot;}],&quot;transcription_state&quot;:&quot;transcribed&quot;};" hash="h1" type="audio/mp4"/>'
        '<en-media style="--en-transcription:{&quot;segments&quot;:[{&quot;text&quot;:&quot;B&quot;}],&quot;transcription_state&quot;:&quot;transcribed&quot;};" hash="h2" type="audio/mp4"/>'
        '<h1>章</h1>'
        '</en-note>'
    )
    enex = _wrap_export(_make_minimal_note("複数添付", body=body))
    path = _write_enex(tmp_path, enex)
    note = next(parse_enex(path))
    hashes = {a["hash"] for a in note.attachments}
    assert hashes == {"h1", "h2"}
    assert "A" in note.raw_transcription
    assert "B" in note.raw_transcription


def test_zero_attachments_yields_empty_list(tmp_path: Path) -> None:
    body = "<en-note><h1>章</h1><p>本文．</p></en-note>"
    enex = _wrap_export(_make_minimal_note("添付なし", body=body))
    path = _write_enex(tmp_path, enex)
    note = next(parse_enex(path))
    assert note.attachments == []
    md = note_to_markdown(note)
    assert "attachments: []" in md


def test_resource_base64_not_in_output(tmp_path: Path) -> None:
    body = "<en-note><h1>章</h1></en-note>"
    enex = _wrap_export(
        _make_minimal_note("base64 除外", body=body, with_resource=True)
    )
    path = _write_enex(tmp_path, enex)
    note = next(parse_enex(path))
    md = note_to_markdown(note)
    assert "AAECAwQF" not in md
    assert "AAECAwQF" not in note.human_memo_enml
    assert "AAECAwQF" not in note.ai_structured_enml


def test_iso_datetime_format(tmp_path: Path) -> None:
    body = "<en-note><h1>章</h1></en-note>"
    enex = _wrap_export(
        _make_minimal_note("時刻形式", created="20260101T000000Z", body=body)
    )
    path = _write_enex(tmp_path, enex)
    note = next(parse_enex(path))
    assert note.created == "2026-01-01T00:00:00Z"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", note.created)
