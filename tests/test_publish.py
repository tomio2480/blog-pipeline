"""publish.py の純粋関数ユニットテスト．

ネットワーク接続が不要な関数のみ対象とする．
`post_draft` と `main` は統合テスト扱いとし，本ファイルでは扱わない．
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from publish import (
    build_atom_entry,
    build_wsse_header,
    extract_entry_id,
    get_env,
    load_env_file,
    parse_frontmatter,
)


# ---------- load_env_file ----------


def test_load_env_file_basic(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("KEY=value\n", encoding="utf-8")
    assert load_env_file(f) == {"KEY": "value"}


def test_load_env_file_comment_and_blank(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("# comment\n\nKEY=value\n", encoding="utf-8")
    assert load_env_file(f) == {"KEY": "value"}


def test_load_env_file_export_prefix(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("export KEY=value\n", encoding="utf-8")
    assert load_env_file(f) == {"KEY": "value"}


def test_load_env_file_double_quoted_value(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text('KEY="hello world"\n', encoding="utf-8")
    assert load_env_file(f) == {"KEY": "hello world"}


def test_load_env_file_single_quoted_value(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("KEY='hello world'\n", encoding="utf-8")
    assert load_env_file(f) == {"KEY": "hello world"}


def test_load_env_file_asymmetric_quote_not_stripped(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("KEY='value\"\n", encoding="utf-8")
    assert load_env_file(f) == {"KEY": "'value\""}


def test_load_env_file_missing_file(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "no_such.env") == {}


def test_load_env_file_value_with_equals(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("KEY=a=b=c\n", encoding="utf-8")
    assert load_env_file(f) == {"KEY": "a=b=c"}


# ---------- get_env ----------


def test_get_env_from_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HATENA_USERNAME", "testuser")
    assert get_env("HATENA_USERNAME", {}) == "testuser"


def test_get_env_from_env_file_when_os_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HATENA_USERNAME", raising=False)
    assert get_env("HATENA_USERNAME", {"HATENA_USERNAME": "fileuser"}) == "fileuser"


def test_get_env_os_environ_takes_priority_over_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HATENA_USERNAME", "envuser")
    assert get_env("HATENA_USERNAME", {"HATENA_USERNAME": "fileuser"}) == "envuser"


def test_get_env_empty_os_environ_does_not_fall_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """os.environ の値が空文字列のときは env_file へフォールスルーせず sys.exit すべき．"""
    monkeypatch.setenv("HATENA_USERNAME", "")
    with pytest.raises(SystemExit):
        get_env("HATENA_USERNAME", {"HATENA_USERNAME": "fileuser"})


def test_get_env_exits_when_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HATENA_USERNAME", raising=False)
    with pytest.raises(SystemExit):
        get_env("HATENA_USERNAME", {})


# ---------- parse_frontmatter ----------


def test_parse_frontmatter_basic() -> None:
    text = "---\ntitle: hello\n---\nbody text\n"
    fm, body = parse_frontmatter(text)
    assert fm == {"title": "hello"}
    assert body == "body text\n"


def test_parse_frontmatter_no_delimiter() -> None:
    text = "plain body without frontmatter\n"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_source_in_warning(capsys: pytest.CaptureFixture) -> None:
    text = "---\ntitle: hello\n"
    fm, body = parse_frontmatter(text, source="test.md")
    assert fm == {}
    assert body == text
    captured = capsys.readouterr()
    assert "test.md" in captured.err


def test_parse_frontmatter_strips_quotes() -> None:
    text = '---\ndraft_of: "My Article"\n---\nbody\n'
    fm, _ = parse_frontmatter(text)
    assert fm["draft_of"] == "My Article"


def test_parse_frontmatter_media_field() -> None:
    text = "---\ndraft_of: test\nmedia: hatena\n---\nbody\n"
    fm, body = parse_frontmatter(text)
    assert fm["media"] == "hatena"
    assert body == "body\n"


def test_parse_frontmatter_empty_body() -> None:
    text = "---\ntitle: t\n---\n"
    fm, body = parse_frontmatter(text)
    assert fm == {"title": "t"}
    assert body == ""


# ---------- extract_entry_id ----------


def test_extract_entry_id_basic() -> None:
    body = b"<id>tag:blog.hatena.ne.jp,2013:blog-user-12345678</id>"
    assert extract_entry_id(body) == "12345678"


def test_extract_entry_id_fallback_empty() -> None:
    assert extract_entry_id(b"<response><status>ok</status></response>") == ""


def test_extract_entry_id_uses_first_match() -> None:
    body = b"<id>tag:...-111</id><id>tag:...-222</id>"
    assert extract_entry_id(body) == "111"


# ---------- build_atom_entry ----------


def test_build_atom_entry_contains_title() -> None:
    data = build_atom_entry("My Title", "body text")
    assert b"<title>My Title</title>" in data


def test_build_atom_entry_always_draft() -> None:
    data = build_atom_entry("title", "body")
    assert b"<app:draft>yes</app:draft>" in data


def test_build_atom_entry_escapes_title() -> None:
    data = build_atom_entry("<script>alert(1)</script>", "body")
    assert b"<script>" not in data
    assert b"&lt;script&gt;" in data


def test_build_atom_entry_escapes_body() -> None:
    data = build_atom_entry("title", "<b>bold</b>")
    assert b"<b>" not in data
    assert b"&lt;b&gt;" in data


def test_build_atom_entry_is_utf8() -> None:
    data = build_atom_entry("タイトル", "本文")
    assert isinstance(data, bytes)
    data.decode("utf-8")  # should not raise


# ---------- build_wsse_header ----------


def test_build_wsse_header_structure() -> None:
    header = build_wsse_header("user", "apikey")
    assert 'Username="user"' in header
    assert "PasswordDigest=" in header
    assert "Nonce=" in header
    assert "Created=" in header


def test_build_wsse_header_nonce_is_random() -> None:
    h1 = build_wsse_header("user", "apikey")
    h2 = build_wsse_header("user", "apikey")
    assert h1 != h2
