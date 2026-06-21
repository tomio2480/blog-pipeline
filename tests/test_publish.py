"""publish.py の純粋関数ユニットテスト．

純粋関数を主対象とする．`entry_exists` のみネットワークを伴うが，
`urllib.request.urlopen` をモックして単体テストする．
`publish_draft`・`sync_entry_ids`・`main` は統合テスト扱いとし，本ファイルでは扱わない．
"""

from __future__ import annotations

import base64
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import publish
from publish import (
    build_atom_entry,
    build_category_url,
    build_collection_url,
    build_fotolife_entry,
    build_member_url,
    build_title_index,
    build_wsse_header,
    decide_publish_method,
    detect_image_content_type,
    entry_exists,
    extract_entry_id,
    extract_fotolife_syntax,
    fetch_categories,
    find_title_matches,
    get_env,
    is_external_image,
    list_categories,
    load_env_file,
    load_upload_map,
    normalize_categories,
    normalize_title,
    parse_category_document,
    parse_collection_feed,
    parse_frontmatter,
    render_image_figure,
    save_upload_map,
    should_suppress_new_post,
    transform_body_images,
    transform_hatena_body,
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


def test_entry_exists_false_for_non_digit_id_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """数字以外の entry_id はネットワークに出ず False を返す（不正 URL 組み立て防止）．

    はてなのエントリ ID は ASCII 数字のみで構成される．全角数字や記号混じりは
    パストラバーサルや不正 URL を招きうるため，送信前に拒否する．
    """

    def boom(req: object, timeout: int = 30) -> _FakeResp:
        raise AssertionError("urlopen は呼ばれてはならない")

    monkeypatch.setattr(publish.urllib.request, "urlopen", boom)
    assert entry_exists("u", "b", "k", "../../etc/passwd") is False
    assert entry_exists("u", "b", "k", "abc") is False
    assert entry_exists("u", "b", "k", "12a") is False
    assert entry_exists("u", "b", "k", "12 34") is False
    assert entry_exists("u", "b", "k", "１２３") is False


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


def test_publish_draft_post_updates_existing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST 成功時，同一バッチ内の後続抑止のため existing_index に新 ID を足す．"""

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    p = _draft_without_id(tmp_path)
    index: dict[str, list[str]] = {}
    publish.publish_draft(p, "u", "b", "k", existing_index=index, force_new=False)
    assert index == {"記事A": ["999"]}


def test_publish_draft_second_same_title_suppressed_in_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同名の新規ドラフトを同じ索引で続けて送ると，2 件目は重複 POST しない．"""
    calls: list[str] = []

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        calls.append(method)
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    p1 = tmp_path / "2026-06-21-a.md"
    p1.write_text('---\ndraft_of: "記事 A"\n---\n本文1\n', encoding="utf-8")
    p2 = tmp_path / "2026-06-21-b.md"
    p2.write_text('---\ndraft_of: "記事 A"\n---\n本文2\n', encoding="utf-8")
    index: dict[str, list[str]] = {}
    publish.publish_draft(p1, "u", "b", "k", existing_index=index, force_new=False)
    publish.publish_draft(p2, "u", "b", "k", existing_index=index, force_new=False)
    assert calls == ["POST"]
    assert "hatena_entry_id" not in p2.read_text(encoding="utf-8")


# ---------- verify_entries の戻り値（entry_exists をモック） ----------


def _draft_with_id(tmp_path: Path, entry_id: str) -> Path:
    p = tmp_path / f"2026-06-21-{entry_id or 'noid'}.md"
    fm = f'hatena_entry_id: "{entry_id}"\n' if entry_id else ""
    p.write_text(f"---\n{fm}---\n本文\n", encoding="utf-8")
    return p


def test_verify_entries_true_when_all_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全 ID が実在すれば True を返す．"""
    monkeypatch.setattr(publish, "entry_exists", lambda u, b, k, i: True)
    p = _draft_with_id(tmp_path, "123")
    assert publish.verify_entries([p], "u", "b", "k") is True


def test_verify_entries_false_on_missing_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """404（欠落）が 1 件でもあれば False を返す．"""
    monkeypatch.setattr(publish, "entry_exists", lambda u, b, k, i: False)
    p = _draft_with_id(tmp_path, "123")
    assert publish.verify_entries([p], "u", "b", "k") is False


def test_verify_entries_missing_id_is_not_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """hatena_entry_id 未設定は未送信・未回収の通常状態で，失敗に数えない．"""

    def boom(u: str, b: str, k: str, i: str) -> bool:
        raise AssertionError("ID なしで entry_exists を呼んではならない")

    monkeypatch.setattr(publish, "entry_exists", boom)
    p = _draft_with_id(tmp_path, "")
    assert publish.verify_entries([p], "u", "b", "k") is True


def test_verify_entries_false_on_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HTTP エラーは検証不能として False を返す（中断はしない）．"""

    def boom(u: str, b: str, k: str, i: str) -> bool:
        raise urllib.error.HTTPError("url", 500, "Server Error", {}, io.BytesIO(b""))

    monkeypatch.setattr(publish, "entry_exists", boom)
    p = _draft_with_id(tmp_path, "123")
    assert publish.verify_entries([p], "u", "b", "k") is False


# ---------- parse_frontmatter（categories 配列） ----------


def test_parse_frontmatter_inline_list() -> None:
    """`categories: [PHP, コミュニティ]` をリストとして読む．"""
    text = "---\ndraft_of: t\ncategories: [PHP, コミュニティ]\n---\nbody\n"
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "コミュニティ"]
    assert fm["draft_of"] == "t"


def test_parse_frontmatter_inline_list_single() -> None:
    text = "---\ncategories: [PHP]\n---\nbody\n"
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP"]


def test_parse_frontmatter_inline_list_quoted_items() -> None:
    """引用符付きの要素はクォートを外して読む．"""
    text = '---\ncategories: ["PHP", \'地域 コミュニティ\']\n---\nbody\n'
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "地域 コミュニティ"]


def test_parse_frontmatter_inline_list_empty() -> None:
    text = "---\ncategories: []\n---\nbody\n"
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == []


def test_parse_frontmatter_inline_list_drops_empty_items() -> None:
    text = "---\ncategories: [PHP, , コミュニティ]\n---\nbody\n"
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "コミュニティ"]


def test_parse_frontmatter_block_list() -> None:
    """ブロック形式（`- item`）も配列として読む．"""
    text = (
        "---\n"
        "draft_of: t\n"
        "categories:\n"
        "  - PHP\n"
        "  - コミュニティ\n"
        "---\n"
        "body\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "コミュニティ"]
    assert fm["draft_of"] == "t"
    assert body == "body\n"


def test_parse_frontmatter_block_list_stops_at_next_key() -> None:
    """ブロック配列の直後に別キーが来ても取り違えない．"""
    text = (
        "---\n"
        "categories:\n"
        "  - PHP\n"
        "  - コミュニティ\n"
        "media: hatena\n"
        "---\n"
        "body\n"
    )
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "コミュニティ"]
    assert fm["media"] == "hatena"


def test_parse_frontmatter_block_list_skips_blank_lines() -> None:
    """ブロック配列の要素間に空行があっても以降の要素を取りこぼさない．"""
    text = (
        "---\n"
        "categories:\n"
        "  - PHP\n"
        "\n"
        "  - コミュニティ\n"
        "media: hatena\n"
        "---\n"
        "body\n"
    )
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "コミュニティ"]
    assert fm["media"] == "hatena"


def test_parse_frontmatter_block_list_skips_comment_lines() -> None:
    """ブロック配列の要素間にコメント行（`#`）があっても取りこぼさない．"""
    text = (
        "---\n"
        "categories:\n"
        "  - PHP\n"
        "  # 補足コメント\n"
        "  - コミュニティ\n"
        "---\n"
        "body\n"
    )
    fm, _ = parse_frontmatter(text)
    assert fm["categories"] == ["PHP", "コミュニティ"]


def test_parse_frontmatter_skips_root_comment_with_colon() -> None:
    """ルートのコロンを含むコメント行をキーとして誤解析しない．"""
    text = "---\n# これはコメント: コロン入り\ndraft_of: t\n---\nbody\n"
    fm, _ = parse_frontmatter(text)
    assert fm == {"draft_of": "t"}


def test_parse_frontmatter_scalar_still_string() -> None:
    """配列でないキーは従来どおり文字列のまま（後方互換）．"""
    text = "---\ndraft_of: t\nmedia: hatena\n---\nbody\n"
    fm, _ = parse_frontmatter(text)
    assert fm["draft_of"] == "t"
    assert isinstance(fm["draft_of"], str)


# ---------- normalize_categories ----------


def test_normalize_categories_none() -> None:
    assert normalize_categories(None) == []


def test_normalize_categories_list_passthrough() -> None:
    assert normalize_categories(["PHP", "コミュニティ"]) == ["PHP", "コミュニティ"]


def test_normalize_categories_strips_and_drops_empty() -> None:
    assert normalize_categories([" PHP ", "", "  ", "地域"]) == ["PHP", "地域"]


def test_normalize_categories_dedup_preserves_order() -> None:
    assert normalize_categories(["PHP", "地域", "PHP"]) == ["PHP", "地域"]


def test_normalize_categories_string_scalar() -> None:
    """文字列スカラーは 1 要素のリストへ寄せる（誤って文字単位に割れない）．"""
    assert normalize_categories("PHP") == ["PHP"]


def test_normalize_categories_empty_string() -> None:
    assert normalize_categories("") == []


def test_normalize_categories_coerces_non_string_elements() -> None:
    """非文字列の要素（数値など）も str 化して受ける（将来の YAML 移行対策）．"""
    assert normalize_categories([2026, "PHP"]) == ["2026", "PHP"]


def test_normalize_categories_non_string_scalar() -> None:
    """非文字列スカラーも 1 要素へ寄せて str 化する（list(int) の TypeError を防ぐ）．"""
    assert normalize_categories(2026) == ["2026"]


# ---------- build_atom_entry（categories） ----------


def test_build_atom_entry_no_categories_by_default() -> None:
    """categories 省略時は <category> を出さない（後方互換）．"""
    data = build_atom_entry("title", "body")
    assert b"<category" not in data


def test_build_atom_entry_empty_categories() -> None:
    data = build_atom_entry("title", "body", [])
    assert b"<category" not in data


def test_build_atom_entry_single_category() -> None:
    data = build_atom_entry("title", "body", ["PHP"])
    assert b'<category term="PHP"' in data


def test_build_atom_entry_multiple_categories_in_order() -> None:
    data = build_atom_entry("title", "body", ["PHP", "コミュニティ"])
    text = data.decode("utf-8")
    assert '<category term="PHP"' in text
    assert '<category term="コミュニティ"' in text
    assert text.index('term="PHP"') < text.index('term="コミュニティ"')


def test_build_atom_entry_escapes_category_term() -> None:
    """term 属性の特殊文字をエスケープする（属性インジェクション防止）．"""
    data = build_atom_entry("title", "body", ['a"b', "c&d", "e<f>"])
    text = data.decode("utf-8")
    assert 'term="a"b"' not in text
    assert "&quot;" in text
    assert "&amp;" in text
    assert "&lt;" in text and "&gt;" in text


def test_build_atom_entry_categories_still_draft() -> None:
    data = build_atom_entry("title", "body", ["PHP"])
    assert b"<app:draft>yes</app:draft>" in data


# ---------- build_category_url ----------


def test_build_category_url() -> None:
    url = build_category_url("alice", "alice.hatenablog.com")
    assert url == "https://blog.hatena.ne.jp/alice/alice.hatenablog.com/atom/category"


# ---------- parse_category_document ----------


SAMPLE_CATEGORY_DOC = b"""<?xml version="1.0" encoding="utf-8"?>
<app:categories xmlns:app="http://www.w3.org/2007/app"
                xmlns:atom="http://www.w3.org/2005/Atom"
                fixed="no">
  <atom:category term="Perl" />
  <atom:category term="\xe3\x82\xb3\xe3\x83\x9f\xe3\x83\xa5\xe3\x83\x8b\xe3\x83\x86\xe3\x82\xa3" />
</app:categories>
"""


def test_parse_category_document_basic() -> None:
    terms = parse_category_document(SAMPLE_CATEGORY_DOC)
    assert terms == ["Perl", "コミュニティ"]


def test_parse_category_document_empty() -> None:
    doc = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<app:categories xmlns:app="http://www.w3.org/2007/app" '
        b'xmlns:atom="http://www.w3.org/2005/Atom" fixed="no"></app:categories>'
    )
    assert parse_category_document(doc) == []


def test_parse_category_document_skips_blank_term() -> None:
    doc = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<app:categories xmlns:app="http://www.w3.org/2007/app" '
        b'xmlns:atom="http://www.w3.org/2005/Atom">'
        b'<atom:category term="" />'
        b'<atom:category term="PHP" />'
        b"</app:categories>"
    )
    assert parse_category_document(doc) == ["PHP"]


# ---------- fetch_categories（ネットワークはモック） ----------


class _FakeCategoryResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeCategoryResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_fetch_categories_parses_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: int = 30) -> _FakeCategoryResp:
        return _FakeCategoryResp(SAMPLE_CATEGORY_DOC)

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)
    assert fetch_categories("u", "b", "k") == ["Perl", "コミュニティ"]


# ---------- publish_draft（categories 送信・上限警告） ----------


def test_publish_draft_sends_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """frontmatter の categories が <category term> として送信 XML に載る．"""
    sent: dict[str, bytes] = {}

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        sent["xml"] = xml
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    p = tmp_path / "2026-06-21-cat.md"
    p.write_text(
        '---\ndraft_of: "記事 A"\ncategories: [PHP, コミュニティ]\n---\n本文\n',
        encoding="utf-8",
    )
    publish.publish_draft(p, "u", "b", "k")
    xml_text = sent["xml"].decode("utf-8")
    assert '<category term="PHP"' in xml_text
    assert '<category term="コミュニティ"' in xml_text


def test_publish_draft_warns_when_over_max_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """categories が上限 10 件を超えると警告する（送信は妨げない）．"""

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        return b"<id>tag:...-999</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    cats = ", ".join(f"c{i}" for i in range(11))
    p = tmp_path / "2026-06-21-many.md"
    p.write_text(
        f'---\ndraft_of: "記事 A"\ncategories: [{cats}]\n---\n本文\n',
        encoding="utf-8",
    )
    publish.publish_draft(p, "u", "b", "k")
    captured = capsys.readouterr()
    assert "10" in captured.err


# ---------- list_categories（標準出力・ネットワークはモック） ----------


def test_list_categories_prints_terms_one_per_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """既存カテゴリーの term を 1 行 1 件で標準出力へ出す．"""

    def fake_urlopen(req: object, timeout: int = 30) -> _FakeCategoryResp:
        return _FakeCategoryResp(SAMPLE_CATEGORY_DOC)

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)
    list_categories("u", "b", "k")
    captured = capsys.readouterr()
    assert captured.out == "Perl\nコミュニティ\n"


def test_list_categories_empty_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """カテゴリーが無ければ標準出力は空とする．"""
    empty_doc = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<app:categories xmlns:app="http://www.w3.org/2007/app" '
        b'xmlns:atom="http://www.w3.org/2005/Atom" fixed="no"></app:categories>'
    )

    def fake_urlopen(req: object, timeout: int = 30) -> _FakeCategoryResp:
        return _FakeCategoryResp(empty_doc)

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake_urlopen)
    list_categories("u", "b", "k")
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------- detect_image_content_type ----------

_JPEG_MAGIC = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
_GIF_MAGIC = b"GIF89a\x01\x00\x01\x00"


def test_detect_image_content_type_jpeg_by_magic() -> None:
    assert detect_image_content_type(_JPEG_MAGIC) == "image/jpeg"


def test_detect_image_content_type_png_by_magic() -> None:
    assert detect_image_content_type(_PNG_MAGIC) == "image/png"


def test_detect_image_content_type_gif_by_magic() -> None:
    assert detect_image_content_type(b"GIF87a\x00\x00") == "image/gif"
    assert detect_image_content_type(_GIF_MAGIC) == "image/gif"


def test_detect_image_content_type_extension_fallback() -> None:
    """マジックバイトで判定できなくても拡張子から判定する（大文字も許容）．"""
    assert (
        detect_image_content_type(b"\x00\x01\x02\x03", filename="photo.JPG")
        == "image/jpeg"
    )
    assert (
        detect_image_content_type(b"\x00\x01\x02\x03", filename="photo.PNG")
        == "image/png"
    )
    assert (
        detect_image_content_type(b"\x00\x01\x02\x03", filename="photo.GIF")
        == "image/gif"
    )


def test_detect_image_content_type_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        detect_image_content_type(b"\x00\x01\x02\x03", filename="data.txt")
    with pytest.raises(ValueError):
        detect_image_content_type(b"\x00\x01\x02\x03")


# ---------- build_fotolife_entry ----------


def test_build_fotolife_entry_includes_base64_content() -> None:
    xml = build_fotolife_entry(b"hello", "image/png", "タイトル").decode("utf-8")
    assert 'xmlns="http://purl.org/atom/ns#"' in xml
    assert "<title>タイトル</title>" in xml
    assert '<content mode="base64" type="image/png">' in xml
    assert base64.b64encode(b"hello").decode("ascii") in xml


def test_build_fotolife_entry_sets_folder_via_dc_subject() -> None:
    xml = build_fotolife_entry(b"x", "image/jpeg", "t", folder="blog").decode("utf-8")
    assert (
        '<dc:subject xmlns:dc="http://purl.org/dc/elements/1.1/">blog</dc:subject>'
        in xml
    )


def test_build_fotolife_entry_omits_subject_when_folder_empty() -> None:
    xml = build_fotolife_entry(b"x", "image/jpeg", "t", folder="").decode("utf-8")
    assert "dc:subject" not in xml


def test_build_fotolife_entry_escapes_title() -> None:
    xml = build_fotolife_entry(b"x", "image/png", "a & <b>").decode("utf-8")
    assert "a &amp; &lt;b&gt;" in xml


# ---------- extract_fotolife_syntax ----------


def test_extract_fotolife_syntax_returns_fid() -> None:
    resp = (
        b'<entry xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">'
        b"<hatena:syntax>f:id:naoya:20060101120000:image</hatena:syntax></entry>"
    )
    assert extract_fotolife_syntax(resp) == "f:id:naoya:20060101120000:image"


def test_extract_fotolife_syntax_empty_when_absent() -> None:
    assert extract_fotolife_syntax(b"<entry></entry>") == ""


def test_extract_fotolife_syntax_handles_other_prefix() -> None:
    """名前空間接頭辞が変わっても要素のローカル名で取り出せる．"""
    resp = (
        b'<entry xmlns:h="http://www.hatena.ne.jp/info/xmlns#">'
        b"<h:syntax>f:id:u:1:image</h:syntax></entry>"
    )
    assert extract_fotolife_syntax(resp) == "f:id:u:1:image"


def test_extract_fotolife_syntax_empty_on_malformed_xml() -> None:
    """整形式でない XML は空文字を返す（呼び出し側がアップロード失敗を判定する）．"""
    assert extract_fotolife_syntax(b"<entry><hatena:syntax>broken") == ""


# ---------- load_upload_map / save_upload_map ----------


def test_load_upload_map_missing_returns_empty(tmp_path: Path) -> None:
    assert load_upload_map(tmp_path / "nope.json") == {}


def test_save_then_load_upload_map_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "uploads.json"
    save_upload_map(p, {"abc": "f:id:u:1:image"})
    assert load_upload_map(p) == {"abc": "f:id:u:1:image"}


def test_save_upload_map_creates_parent_dirs(tmp_path: Path) -> None:
    """親ディレクトリが無くても作成して書き込む（FileNotFoundError を防ぐ）．"""
    p = tmp_path / "nested" / "dir" / "uploads.json"
    save_upload_map(p, {"abc": "f:id:u:1:image"})
    assert load_upload_map(p) == {"abc": "f:id:u:1:image"}


def test_load_upload_map_wraps_corrupt_json_with_path(tmp_path: Path) -> None:
    """壊れた JSON は ValueError とし，メッセージにパスを含める（識別容易化）．"""
    p = tmp_path / "uploads.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_upload_map(p)
    assert str(p) in str(exc.value)


def test_load_upload_map_empty_file_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "uploads.json"
    p.write_text("", encoding="utf-8")
    assert load_upload_map(p) == {}


def test_load_upload_map_rejects_non_dict(tmp_path: Path) -> None:
    p = tmp_path / "uploads.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_upload_map(p)


def test_load_upload_map_rejects_non_str_value(tmp_path: Path) -> None:
    """値が文字列でない記録は破損とみなして弾く（型の暗黙伝播を防ぐ）．"""
    p = tmp_path / "uploads.json"
    p.write_text('{"abc": 123}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_upload_map(p)


# ---------- upload_image（ネットワークはモック） ----------

_FOTOLIFE_RESP = (
    b'<entry xmlns="http://purl.org/atom/ns#" '
    b'xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">'
    b"<hatena:syntax>f:id:testuser:20260621120000:image</hatena:syntax>"
    b"</entry>"
)
_PNG_IMAGE = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRbody"


def test_upload_image_posts_and_returns_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    img = tmp_path / "pic.png"
    img.write_bytes(_PNG_IMAGE)
    calls: list[tuple[str, str]] = []

    def fake_send(
        url: str, entry_xml: bytes, username: str, api_key: str, method: str
    ) -> bytes:
        calls.append((url, method))
        return _FOTOLIFE_RESP

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    syntax = publish.upload_image(img, "testuser", "key")
    assert syntax == "f:id:testuser:20260621120000:image"
    assert calls == [("https://f.hatena.ne.jp/atom/post", "POST")]


def test_upload_image_skips_when_already_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一内容の画像は記録を参照して再アップロードしない．"""
    img = tmp_path / "pic.png"
    img.write_bytes(_PNG_IMAGE)
    map_path = tmp_path / "uploads.json"

    monkeypatch.setattr(
        publish, "_send_entry", lambda *a, **k: _FOTOLIFE_RESP
    )
    first = publish.upload_image(img, "testuser", "key", map_path=map_path)

    def boom(*a: object, **k: object) -> bytes:
        raise AssertionError("二重アップロードしてはならない")

    monkeypatch.setattr(publish, "_send_entry", boom)
    second = publish.upload_image(img, "testuser", "key", map_path=map_path)
    assert first == second == "f:id:testuser:20260621120000:image"


def test_upload_image_raises_when_no_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    img = tmp_path / "pic.png"
    img.write_bytes(_PNG_IMAGE)
    monkeypatch.setattr(publish, "_send_entry", lambda *a, **k: b"<entry></entry>")
    with pytest.raises(ValueError):
        publish.upload_image(img, "testuser", "key")


# ---------- is_external_image ----------


def test_is_external_image_true_for_http_and_https() -> None:
    assert is_external_image("http://example.com/a.png") is True
    assert is_external_image("https://example.com/a.png") is True


def test_is_external_image_false_for_relative_path() -> None:
    assert is_external_image("assets/a.png") is False
    assert is_external_image("./a.png") is False
    assert is_external_image("/abs/a.png") is False


def test_is_external_image_case_insensitive_scheme() -> None:
    assert is_external_image("HTTPS://example.com/a.png") is True
    assert is_external_image("Http://example.com/a.png") is True


# ---------- render_image_figure ----------


def test_render_image_figure_fid_with_caption() -> None:
    html_out = render_image_figure(
        alt="代替テキスト",
        caption="図の説明",
        fid="f:id:u:20260621120000:image",
    )
    assert html_out == (
        "<figure>\n"
        "[f:id:u:20260621120000:image:alt=代替テキスト]\n"
        "<figcaption>図の説明</figcaption>\n"
        "</figure>"
    )


def test_render_image_figure_fid_without_caption_still_wraps_figure() -> None:
    html_out = render_image_figure(alt="代替", fid="f:id:u:1:image")
    assert html_out == (
        "<figure>\n[f:id:u:1:image:alt=代替]\n</figure>"
    )


def test_render_image_figure_external_uses_img_and_escapes() -> None:
    html_out = render_image_figure(
        alt="A & B",
        caption="<b>注</b>",
        src="https://example.com/a.png?x=1&y=2",
    )
    assert html_out == (
        "<figure>\n"
        '<img src="https://example.com/a.png?x=1&amp;y=2" alt="A &amp; B">\n'
        "<figcaption>&lt;b&gt;注&lt;/b&gt;</figcaption>\n"
        "</figure>"
    )


def test_render_image_figure_empty_alt_raises() -> None:
    with pytest.raises(ValueError):
        render_image_figure(alt="", fid="f:id:u:1:image")
    with pytest.raises(ValueError):
        render_image_figure(alt="   ", src="https://example.com/a.png")


def test_render_image_figure_requires_exactly_one_of_fid_src() -> None:
    with pytest.raises(ValueError):
        render_image_figure(alt="x")
    with pytest.raises(ValueError):
        render_image_figure(alt="x", fid="f:id:u:1:image", src="https://e/a.png")


def test_render_image_figure_fid_alt_with_breaking_chars_raises() -> None:
    with pytest.raises(ValueError):
        render_image_figure(alt="a:b", fid="f:id:u:1:image")
    with pytest.raises(ValueError):
        render_image_figure(alt="a]b", fid="f:id:u:1:image")


# ---------- transform_body_images ----------


def test_transform_body_images_local_uploads_and_replaces(tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_upload(path: Path) -> str:
        calls.append(path)
        return "f:id:u:111:image"

    body = '前文\n\n![代替](assets/a.png "説明")\n\n後文\n'
    out = transform_body_images(body, base_dir=tmp_path, upload_fn=fake_upload)
    assert calls == [tmp_path / "assets/a.png"]
    assert "<figure>\n[f:id:u:111:image:alt=代替]\n<figcaption>説明</figcaption>\n</figure>" in out
    assert "前文" in out and "後文" in out
    assert "![代替]" not in out


def test_transform_body_images_local_without_caption(tmp_path: Path) -> None:
    out = transform_body_images(
        "![代替](a.png)\n", base_dir=tmp_path, upload_fn=lambda p: "f:id:u:1:image"
    )
    assert out == "<figure>\n[f:id:u:1:image:alt=代替]\n</figure>\n"


def test_transform_body_images_external_not_uploaded(tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_upload(path: Path) -> str:
        calls.append(path)
        return "f:id:u:1:image"

    body = '![外部](https://example.com/a.png "外部説明")\n'
    out = transform_body_images(body, base_dir=tmp_path, upload_fn=fake_upload)
    assert calls == []
    assert '<img src="https://example.com/a.png" alt="外部">' in out
    assert "<figcaption>外部説明</figcaption>" in out


def test_transform_body_images_multiple_mixed(tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_upload(path: Path) -> str:
        calls.append(path)
        return f"f:id:u:{len(calls)}:image"

    body = (
        "![一](local1.png)\n"
        "![二](https://example.com/x.png)\n"
        '![三](sub/local2.png "三の説明")\n'
    )
    out = transform_body_images(body, base_dir=tmp_path, upload_fn=fake_upload)
    assert calls == [tmp_path / "local1.png", tmp_path / "sub/local2.png"]
    assert "[f:id:u:1:image:alt=一]" in out
    assert '<img src="https://example.com/x.png" alt="二">' in out
    assert "[f:id:u:2:image:alt=三]" in out
    assert "<figcaption>三の説明</figcaption>" in out


def test_transform_body_images_missing_alt_raises_before_upload(
    tmp_path: Path,
) -> None:
    def boom(path: Path) -> str:
        raise AssertionError("alt 欠落時はアップロードしてはならない")

    with pytest.raises(ValueError):
        transform_body_images("![](a.png)\n", base_dir=tmp_path, upload_fn=boom)


def test_transform_body_images_handles_parens_in_path(tmp_path: Path) -> None:
    """丸括弧を含むファイル名（例: image(1).png）も拾えて置換する．"""
    calls: list[Path] = []

    def fake_upload(path: Path) -> str:
        calls.append(path)
        return "f:id:u:1:image"

    out = transform_body_images(
        "![代替](assets/image(1).png)\n", base_dir=tmp_path, upload_fn=fake_upload
    )
    assert calls == [tmp_path / "assets/image(1).png"]
    assert out == "<figure>\n[f:id:u:1:image:alt=代替]\n</figure>\n"


def test_transform_body_images_normalizes_backslash_path(tmp_path: Path) -> None:
    """Windows 区切り（\\）のパスは / へ正規化してアップロードする．"""
    calls: list[Path] = []

    def fake_upload(path: Path) -> str:
        calls.append(path)
        return "f:id:u:1:image"

    out = transform_body_images(
        "![代替](assets\\sub\\a.png)\n", base_dir=tmp_path, upload_fn=fake_upload
    )
    assert calls == [tmp_path / "assets" / "sub" / "a.png"]
    assert out == "<figure>\n[f:id:u:1:image:alt=代替]\n</figure>\n"


def test_transform_body_images_decodes_percent_encoded_path(tmp_path: Path) -> None:
    """パーセントエンコードされたパス（%20 や日本語）はデコードして上げる．"""
    calls: list[Path] = []

    def fake_upload(path: Path) -> str:
        calls.append(path)
        return "f:id:u:1:image"

    out = transform_body_images(
        "![代替](assets/sub/%E5%9B%B3%201.png)\n",
        base_dir=tmp_path,
        upload_fn=fake_upload,
    )
    assert calls == [tmp_path / "assets" / "sub" / "図 1.png"]
    assert out == "<figure>\n[f:id:u:1:image:alt=代替]\n</figure>\n"


def test_transform_body_images_rejects_percent_encoded_traversal(
    tmp_path: Path,
) -> None:
    """エンコードされた親参照（%2e%2e%2f）もデコード後に弾く．"""
    def boom(path: Path) -> str:
        raise AssertionError("エンコードされた親参照を上げてはならない")

    with pytest.raises(ValueError):
        transform_body_images(
            "![代替](%2e%2e%2fsecret/a.png)\n", base_dir=tmp_path, upload_fn=boom
        )


def test_transform_body_images_rejects_absolute_path(tmp_path: Path) -> None:
    def boom(path: Path) -> str:
        raise AssertionError("絶対パスはアップロードしてはならない")

    with pytest.raises(ValueError):
        transform_body_images(
            "![代替](/etc/passwd.png)\n", base_dir=tmp_path, upload_fn=boom
        )


def test_transform_body_images_rejects_drive_relative_path(tmp_path: Path) -> None:
    """Windows のドライブ相対パス（C:assets/...）も弾く．"""
    def boom(path: Path) -> str:
        raise AssertionError("ドライブ相対パスはアップロードしてはならない")

    with pytest.raises(ValueError):
        transform_body_images(
            "![代替](C:assets/a.png)\n", base_dir=tmp_path, upload_fn=boom
        )


def test_transform_body_images_rejects_parent_traversal(tmp_path: Path) -> None:
    def boom(path: Path) -> str:
        raise AssertionError("親ディレクトリ参照はアップロードしてはならない")

    with pytest.raises(ValueError):
        transform_body_images(
            "![代替](../secret/a.png)\n", base_dir=tmp_path, upload_fn=boom
        )


def test_transform_body_images_no_images_unchanged(tmp_path: Path) -> None:
    body = "画像のない本文です．\n\n通常の段落．\n"
    out = transform_body_images(
        body, base_dir=tmp_path, upload_fn=lambda p: "f:id:u:1:image"
    )
    assert out == body


# ---------- publish_draft の画像処理統合（_send_entry をモック） ----------


def test_publish_draft_embeds_local_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本文の Markdown 画像が POST 前にアップロード＋figure 置換される．"""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    draft = tmp_path / "2026-06-21-img.md"
    draft.write_text(
        '---\ndraft_of: "画像記事"\n---\n![代替](a.png "説明")\n',
        encoding="utf-8",
    )

    sent: dict[str, bytes] = {}

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        if url == publish.FOTOLIFE_POST_URL:
            return (
                b'<entry xmlns:hatena="http://www.hatena.ne.jp/info/xmlns#">'
                b"<hatena:syntax>f:id:u:999:image</hatena:syntax></entry>"
            )
        sent["body"] = xml
        return b"<id>tag:...-555</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    publish.publish_draft(draft, "u", "b", "k")

    body_xml = sent["body"].decode("utf-8")
    assert "f:id:u:999:image:alt=代替" in body_xml
    assert "figcaption" in body_xml
    assert 'hatena_entry_id: "555"' in draft.read_text(encoding="utf-8")


def test_publish_draft_image_error_includes_draft_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """画像処理の失敗は，どのドラフトが原因かパス付きで再送出される．"""
    draft = tmp_path / "2026-06-21-bad.md"
    draft.write_text(
        '---\ndraft_of: "画像記事"\n---\n![](a.png)\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        publish, "_send_entry", lambda *a, **k: b"<id>tag:...-1</id>"
    )
    with pytest.raises(ValueError) as excinfo:
        publish.publish_draft(draft, "u", "b", "k")
    assert str(draft) in str(excinfo.value)


def test_publish_draft_image_upload_http_error_includes_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """画像アップロードの HTTPError は応答ボディと HTTP コードを含めて再送出される．"""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    draft = tmp_path / "2026-06-21-img.md"
    draft.write_text(
        '---\ndraft_of: "画像記事"\n---\n![代替](a.png)\n', encoding="utf-8"
    )

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        raise urllib.error.HTTPError(
            url, 401, "Unauthorized", {}, io.BytesIO(b"<error>auth failed</error>")
        )

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    with pytest.raises(ValueError) as excinfo:
        publish.publish_draft(draft, "u", "b", "k")
    msg = str(excinfo.value)
    assert str(draft) in msg
    assert "401" in msg
    assert "auth failed" in msg


# ---------- transform_hatena_body ----------


def test_transform_hatena_body_joins_wrapped_prose() -> None:
    """段落内の改行を取り除き 1 行へ結合し，末尾へ半角スペース 2 つを付ける．"""
    body = "あいう，\nえお．\n"
    assert transform_hatena_body(body) == "あいう，えお．  \n"


def test_transform_hatena_body_inserts_spacer_between_paragraphs() -> None:
    """連続する段落の間へ区切り行（全角スペース + 半角スペース 2 つ）を挟む．"""
    body = "だん一の文．\n\nだん二の文．\n"
    assert (
        transform_hatena_body(body)
        == "だん一の文．  \n　  \nだん二の文．  \n"
    )


def test_transform_hatena_body_keeps_heading_on_own_line() -> None:
    """見出しは結合せず，前後を空行で区切ってそのまま残す．"""
    body = "## 見出し\n\n本文です．\n"
    assert transform_hatena_body(body) == "## 見出し\n\n本文です．  \n"


def test_transform_hatena_body_passes_through_ordered_list() -> None:
    """番号付き箇条書きは結合・カード化せずそのまま残す．"""
    body = "1. 一\n2. 二\n"
    assert transform_hatena_body(body) == "1. 一\n2. 二\n"


def test_transform_hatena_body_embeds_standalone_markdown_link() -> None:
    """単独行の Markdown リンクは URL を残して埋め込み記法へ変換する．"""
    body = (
        "[techbookfest.org/x]"
        "(https://techbookfest.org/product/abc?productVariantID=xyz)\n"
    )
    assert transform_hatena_body(body) == (
        "[https://techbookfest.org/product/abc?productVariantID=xyz"
        ":embed:cite]\n"
    )


def test_transform_hatena_body_embeds_bare_url() -> None:
    """単独行の裸 URL も埋め込み記法（cite 付き）へ変換する．"""
    body = "https://www.youtube.com/watch?v=fft1OojZyLs\n"
    assert transform_hatena_body(body) == (
        "[https://www.youtube.com/watch?v=fft1OojZyLs:embed:cite]\n"
    )


def test_transform_hatena_body_keeps_inline_link_in_prose() -> None:
    """文中のインラインリンクは埋め込み化せず，段落結合のみ行う．"""
    body = "[IPSJ](https://www.ipsj.or.jp/)（情報処理学会）の任期が，\n終わりました．\n"
    assert transform_hatena_body(body) == (
        "[IPSJ](https://www.ipsj.or.jp/)（情報処理学会）の任期が，"
        "終わりました．  \n"
    )


def test_transform_hatena_body_passes_through_image_markdown() -> None:
    """画像記法はカード化・結合せず残し，画像処理（後段）へ委ねる．"""
    body = '![代替テキスト](img/a.png "図1")\n'
    assert transform_hatena_body(body) == body


def test_transform_hatena_body_prose_link_prose_structure() -> None:
    """段落・単独リンク・段落の並びで，リンク前後は空行で区切る．"""
    body = "前段の文．\n\n[a](https://e/x)\n\n後段の文．\n"
    assert transform_hatena_body(body) == (
        "前段の文．  \n\n[https://e/x:embed:cite]\n\n後段の文．  \n"
    )


def test_transform_hatena_body_keeps_code_fence_verbatim() -> None:
    """コードフェンス内は結合せず，空行を含めてそのまま残す．"""
    body = "```\na = 1\n\nb = 2\n```\n"
    assert transform_hatena_body(body) == body


def test_transform_hatena_body_empty() -> None:
    """空本文はそのまま返す．"""
    assert transform_hatena_body("") == ""


def test_publish_draft_applies_hatena_body_transform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """送信本文へはてな整形（段落結合・単独リンクの埋め込み化）が適用される．"""
    draft = tmp_path / "2026-06-21-fmt.md"
    draft.write_text(
        '---\ndraft_of: "整形記事"\nhatena_entry_id: "777"\n---\n'
        "前段の文，\nつづき．\n\n"
        "[note.com/x](https://note.com/tomio2480/n/abc)\n",
        encoding="utf-8",
    )

    sent: dict[str, bytes] = {}

    def fake_send(url, xml, username, api_key, method):  # noqa: ANN001
        sent["body"] = xml
        return b"<id>tag:...-777</id>"

    monkeypatch.setattr(publish, "_send_entry", fake_send)
    publish.publish_draft(draft, "u", "b", "k")

    body_xml = sent["body"].decode("utf-8")
    # 段落内の改行が結合され，末尾へ半角スペース 2 つが付く．
    assert "前段の文，つづき．  " in body_xml
    # 単独行リンクが埋め込み記法へ変換される．
    assert "[https://note.com/tomio2480/n/abc:embed:cite]" in body_xml


# ---------- preview_drafts ----------


def test_preview_drafts_writes_utf8_bytes(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture
) -> None:
    """プレビューは UTF-8 バイト列で出力する（コンソールの cp932 に依存しない）．"""
    draft = tmp_path / "2026-06-21-emdash.md"
    # em ダッシュ（U+2014）は cp932 で表現できず，print 経由だと環境により落ちる．
    draft.write_text(
        '---\ndraft_of: "ダッシュ記事"\n---\n本文 — つづき．\n\n'
        "[t](https://example.com/x)\n",
        encoding="utf-8",
    )
    publish.preview_drafts([draft])
    out = capsysbinary.readouterr().out.decode("utf-8")
    assert "本文 — つづき．  " in out
    assert "[https://example.com/x:embed:cite]" in out
