"""publish.py の純粋関数ユニットテスト．

純粋関数を主対象とする．`entry_exists` のみネットワークを伴うが，
`urllib.request.urlopen` をモックして単体テストする．
`publish_draft`・`sync_entry_ids`・`main` は統合テスト扱いとし，本ファイルでは扱わない．
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import publish
from publish import (
    build_atom_entry,
    build_collection_url,
    build_member_url,
    build_title_index,
    build_wsse_header,
    decide_publish_method,
    entry_exists,
    extract_entry_id,
    find_title_matches,
    get_env,
    load_env_file,
    normalize_title,
    parse_collection_feed,
    parse_frontmatter,
    should_suppress_new_post,
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


def test_upsert_frontmatter_field_quote_inserts_quoted() -> None:
    """quote=True で新規キーをダブルクォート付きで書き込む（YAML の精度落ち防止）．"""
    text = "---\ndraft_of: t\n---\nbody\n"
    out = upsert_frontmatter_field(text, "hatena_entry_id", "6801883189073", quote=True)
    assert 'hatena_entry_id: "6801883189073"' in out
    fm, _ = parse_frontmatter(out)
    assert fm["hatena_entry_id"] == "6801883189073"


def test_upsert_frontmatter_field_quote_replaces_unquoted() -> None:
    """既存のクォートなしキーを置換しても，書き戻しはクォート付きになる．"""
    text = "---\ndraft_of: t\nhatena_entry_id: 111\n---\nbody\n"
    out = upsert_frontmatter_field(text, "hatena_entry_id", "222", quote=True)
    assert 'hatena_entry_id: "222"' in out
    assert out.count("hatena_entry_id") == 1


def test_upsert_frontmatter_field_default_unquoted() -> None:
    """quote 省略時は従来どおりクォートなしで書き込む（後方互換）．"""
    text = "---\ndraft_of: t\n---\nbody\n"
    out = upsert_frontmatter_field(text, "k", "v")
    assert "k: v\n" in out


# ---------- normalize_title ----------


def test_normalize_title_removes_spaces() -> None:
    assert normalize_title("IPSJ 会誌 編集") == "IPSJ会誌編集"


def test_normalize_title_removes_fullwidth_space() -> None:
    assert normalize_title("記事　A") == "記事A"


def test_normalize_title_strips_edges_and_tabs() -> None:
    assert normalize_title("  a\tb\n") == "ab"


def test_normalize_title_empty() -> None:
    assert normalize_title("") == ""


# ---------- build_title_index / find_title_matches ----------


def test_build_title_index_groups_by_normalized_title() -> None:
    entries = [
        {"entry_id": "1", "title": "記事 A", "draft": True},
        {"entry_id": "2", "title": "記事A", "draft": True},
        {"entry_id": "3", "title": "別の記事", "draft": True},
    ]
    index = build_title_index(entries)
    assert index["記事A"] == ["1", "2"]
    assert index["別の記事"] == ["3"]


def test_find_title_matches_returns_candidate_ids() -> None:
    index = {"記事A": ["1", "2"]}
    assert find_title_matches("記事 A", index) == ["1", "2"]


def test_find_title_matches_empty_when_absent() -> None:
    assert find_title_matches("未知", {"記事A": ["1"]}) == []


# ---------- should_suppress_new_post ----------


def test_should_suppress_new_post_true_when_match_and_not_forced() -> None:
    index = {"記事A": ["1"]}
    assert should_suppress_new_post("記事 A", index, force_new=False) is True


def test_should_suppress_new_post_false_when_forced() -> None:
    index = {"記事A": ["1"]}
    assert should_suppress_new_post("記事 A", index, force_new=True) is False


def test_should_suppress_new_post_false_when_no_match() -> None:
    assert should_suppress_new_post("新題", {"記事A": ["1"]}, force_new=False) is False


# ---------- entry_exists（メンバー GET・ネットワークはモック） ----------


class _FakeResp:
    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return b""


def test_entry_exists_false_for_empty_id_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空・空白のみの entry_id はネットワークに出ず False を返す（誤検出防止）．"""

    def boom(req: object, timeout: int = 30) -> _FakeResp:
        raise AssertionError("urlopen は呼ばれてはならない")

    monkeypatch.setattr(publish.urllib.request, "urlopen", boom)
    assert entry_exists("u", "b", "k", "") is False
    assert entry_exists("u", "b", "k", "   ") is False


def test_entry_exists_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: int = 30) -> _FakeResp:
        return _FakeResp()

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)
    assert entry_exists("u", "b", "k", "123") is True


def test_entry_exists_false_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: int = 30) -> _FakeResp:
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, io.BytesIO(b""))

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)
    assert entry_exists("u", "b", "k", "123") is False


def test_entry_exists_raises_on_other_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: int = 30) -> _FakeResp:
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, io.BytesIO(b""))

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        entry_exists("u", "b", "k", "123")


# ---------- 空タイトルの誤一致ガード ----------


def test_build_title_index_skips_empty_title() -> None:
    entries = [{"entry_id": "1", "title": "  ", "draft": True}]
    assert build_title_index(entries) == {}


def test_build_title_index_skips_empty_entry_id() -> None:
    """entry_id が空のエントリは索引に載せない（空 ID の誤書き戻しを防ぐ）．"""
    entries = [
        {"entry_id": "", "title": "記事 A", "draft": True},
        {"entry_id": "2", "title": "記事 A", "draft": True},
    ]
    assert build_title_index(entries) == {"記事A": ["2"]}


def test_find_title_matches_empty_title_never_matches() -> None:
    assert find_title_matches("   ", {"記事A": ["1"]}) == []


def test_should_suppress_new_post_false_for_empty_title() -> None:
    assert should_suppress_new_post("  ", {"記事A": ["1"]}, force_new=False) is False


# ---------- publish_draft の POST 重複抑止（_send_entry をモック） ----------


def _draft_without_id(tmp_path: Path) -> Path:
    p = tmp_path / "2026-06-21-sample.md"
    p.write_text('---\ndraft_of: "記事 A"\n---\n本文\n', encoding="utf-8")
    return p


def test_publish_draft_suppresses_post_on_title_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正規化タイトル一致の既存エントリがあれば POST せず frontmatter も変えない．"""
    calls: list[str] = []

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        calls.append(method)
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    p = _draft_without_id(tmp_path)
    publish.publish_draft(
        p, "u", "b", "k", existing_index={"記事A": ["1"]}, force_new=False
    )
    assert calls == []
    assert "hatena_entry_id" not in p.read_text(encoding="utf-8")


def test_publish_draft_force_new_posts_despite_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """force_new=True なら一致があっても POST し，ID をクォート付きで書き戻す．"""
    calls: list[str] = []

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        calls.append(method)
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    p = _draft_without_id(tmp_path)
    publish.publish_draft(
        p, "u", "b", "k", existing_index={"記事A": ["1"]}, force_new=True
    )
    assert calls == ["POST"]
    assert 'hatena_entry_id: "999"' in p.read_text(encoding="utf-8")


def test_publish_draft_no_index_posts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """existing_index=None（既定）のときは抑止せず従来どおり POST する．"""
    calls: list[str] = []

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        calls.append(method)
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    p = _draft_without_id(tmp_path)
    publish.publish_draft(p, "u", "b", "k")
    assert calls == ["POST"]
