"""publish.py の純粋関数ユニットテスト．

ネットワーク接続が不要な関数のみ対象とする．
`publish_draft`・`sync_entry_ids`・`main` は統合テスト扱いとし，本ファイルでは扱わない．
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from publish import (
    build_atom_entry,
    build_collection_url,
    build_member_url,
    build_wsse_header,
    decide_publish_method,
    extract_entry_id,
    get_env,
    load_env_file,
    parse_collection_feed,
    parse_frontmatter,
    upsert_frontmatter_field,
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


# ---------- build_collection_url / build_member_url ----------


def test_build_collection_url() -> None:
    url = build_collection_url("alice", "alice.hatenablog.com")
    assert url == "https://blog.hatena.ne.jp/alice/alice.hatenablog.com/atom/entry"


def test_build_member_url() -> None:
    url = build_member_url("alice", "alice.hatenablog.com", "12345678")
    assert url == "https://blog.hatena.ne.jp/alice/alice.hatenablog.com/atom/entry/12345678"


# ---------- decide_publish_method ----------


def test_decide_publish_method_post_when_no_entry_id() -> None:
    assert decide_publish_method({}) == ("POST", None)
    assert decide_publish_method({"draft_of": "t"}) == ("POST", None)


def test_decide_publish_method_put_when_entry_id_present() -> None:
    assert decide_publish_method({"hatena_entry_id": "999"}) == ("PUT", "999")


def test_decide_publish_method_refuses_when_published() -> None:
    """公開済み（hatena_published: true）の記事は自動送信を拒否する．"""
    with pytest.raises(ValueError):
        decide_publish_method({"hatena_entry_id": "999", "hatena_published": "true"})


def test_decide_publish_method_published_truthy_variants() -> None:
    for v in ("true", "True", "yes", "1"):
        with pytest.raises(ValueError):
            decide_publish_method({"hatena_entry_id": "999", "hatena_published": v})


def test_decide_publish_method_published_false_allows_put() -> None:
    assert decide_publish_method(
        {"hatena_entry_id": "999", "hatena_published": "false"}
    ) == ("PUT", "999")


# ---------- parse_collection_feed ----------


SAMPLE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:app="http://www.w3.org/2007/app">
  <title>Blog</title>
  <entry>
    <id>tag:blog.hatena.ne.jp,2013:blog-alice-12345-6801883189073</id>
    <title>\xe8\xa8\x98\xe4\xba\x8b A</title>
    <app:control><app:draft>yes</app:draft></app:control>
  </entry>
  <entry>
    <id>tag:blog.hatena.ne.jp,2013:blog-alice-12345-6801883189099</id>
    <title>\xe8\xa8\x98\xe4\xba\x8b B</title>
    <app:control><app:draft>no</app:draft></app:control>
  </entry>
</feed>
"""


def test_parse_collection_feed_basic() -> None:
    entries = parse_collection_feed(SAMPLE_FEED)
    assert len(entries) == 2
    assert entries[0] == {
        "entry_id": "6801883189073",
        "title": "記事 A",
        "draft": True,
    }
    assert entries[1] == {
        "entry_id": "6801883189099",
        "title": "記事 B",
        "draft": False,
    }


def test_parse_collection_feed_empty() -> None:
    feed = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    )
    assert parse_collection_feed(feed) == []


# ---------- upsert_frontmatter_field ----------


def test_upsert_frontmatter_field_inserts_new_key() -> None:
    text = "---\ndraft_of: t\nmedia: hatena\n---\nbody\n"
    out = upsert_frontmatter_field(text, "hatena_entry_id", "999")
    fm, body = parse_frontmatter(out)
    assert fm["hatena_entry_id"] == "999"
    assert fm["draft_of"] == "t"
    assert body == "body\n"


def test_upsert_frontmatter_field_replaces_existing_key() -> None:
    text = "---\ndraft_of: t\nhatena_entry_id: 111\n---\nbody\n"
    out = upsert_frontmatter_field(text, "hatena_entry_id", "222")
    fm, _ = parse_frontmatter(out)
    assert fm["hatena_entry_id"] == "222"
    assert out.count("hatena_entry_id") == 1


def test_upsert_frontmatter_field_preserves_body() -> None:
    text = "---\ndraft_of: t\n---\nline1\nline2\n"
    out = upsert_frontmatter_field(text, "k", "v")
    _, body = parse_frontmatter(out)
    assert body == "line1\nline2\n"
