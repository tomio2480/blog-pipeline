"""はてなブログ AtomPub API を使って Markdown ドラフトを下書き投稿・更新する CLI スクリプト．

設計方針:

- 標準ライブラリのみで実装する．サードパーティ依存ゼロ．
- `<app:draft>yes</app:draft>` をハードコードし，公開フラグは持たせない．
  公開判断ははてなブログの管理画面で人間が行う．
- 送信メソッドは frontmatter で自動判定する．
  `hatena_entry_id` なし → 新規 POST（成功時に entry ID を frontmatter へ書き戻す）．
  `hatena_entry_id` あり → 既存下書きの更新 PUT．
  `hatena_published: true` → 公開後ははてな側を真とするため自動送信を拒否する．
- 環境変数（HATENA_USERNAME / HATENA_BLOG_ID / HATENA_API_KEY）は
  `--env-file`（既定: `.env`）から読み込む．
  環境変数に既に設定済みの場合はそちらを優先する（os.environ 優先）．
- WSSE 認証（RFC 3339 CreatedDate，SHA-1 PasswordDigest）を使用する．

使い方:

    python scripts/publish.py drafts/2026-05-07-my-article.md
    python scripts/publish.py drafts/2026-05-07-my-article.md --env-file /path/to/.env
    python scripts/publish.py drafts/*.md --sync   # ID 回収のみ（送信しない）

出力:

    下書きの作成・更新時，管理画面の URL を標準出力に書き出す．
    エラーは標準エラー出力に書き出し，exit code 1 で終了する．
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


# YAML フロントマターのデリミタ
FRONTMATTER_DELIMITER = "---"

# 管理画面の下書き URL ベース
HATENA_BLOG_ADMIN_BASE = "https://blog.hatena.ne.jp/{username}/{blog_id}/edit?entry="

# Atom / AtomPub の名前空間
ATOM_NS = "http://www.w3.org/2005/Atom"
APP_NS = "http://www.w3.org/2007/app"

# hatena_published が真とみなす値
_TRUTHY = {"true", "yes", "1", "on"}


def build_collection_url(username: str, blog_id: str) -> str:
    """コレクション URI（新規 POST 先・一覧取得先）を組み立てる．"""
    return f"https://blog.hatena.ne.jp/{username}/{blog_id}/atom/entry"


def build_member_url(username: str, blog_id: str, entry_id: str) -> str:
    """メンバー URI（既存エントリの更新 PUT 先）を組み立てる．"""
    return f"https://blog.hatena.ne.jp/{username}/{blog_id}/atom/entry/{entry_id}"


def load_env_file(path: Path) -> dict[str, str]:
    """シンプルな .env ファイルパーサー．

    - `KEY=VALUE` 形式の行を読む．
    - `#` 始まりの行はコメントとして無視する．
    - 値の前後のクォート（`"` / `'`）は除去する．
    - `export KEY=VALUE` 形式も受け付ける．
    """
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^export\s+", "", line)
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def get_env(key: str, env_file_vars: dict[str, str]) -> str:
    """環境変数を取得する．os.environ を env_file より優先する．"""
    value = os.environ.get(key)
    if value is None:
        value = env_file_vars.get(key, "")
    if not value:
        print(f"Error: {key} が設定されていません．", file=sys.stderr)
        sys.exit(1)
    return value


def build_wsse_header(username: str, api_key: str) -> str:
    """WSSE UsernameToken を生成する．

    PasswordDigest = Base64(SHA-1(Nonce + Created + APIKey))
    """
    nonce_raw = os.urandom(20)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # SHA-1 は WSSE 認証プロトコルの仕様で規定されているため変更不可．
    # パスワードの保存用途ではなく，ワンタイム認証トークン生成のみに使用する．
    digest_raw = hashlib.sha1(  # lgtm[py/weak-cryptographic-algorithm] noqa: S324
        nonce_raw + created.encode("utf-8") + api_key.encode("utf-8")
    ).digest()
    nonce_b64 = base64.b64encode(nonce_raw).decode("ascii")
    digest_b64 = base64.b64encode(digest_raw).decode("ascii")
    return (
        f'UsernameToken Username="{username}", '
        f'PasswordDigest="{digest_b64}", '
        f'Nonce="{nonce_b64}", '
        f'Created="{created}"'
    )


def parse_frontmatter(text: str, *, source: str = "") -> tuple[dict[str, str], str]:
    """YAML フロントマターをシンプルに解析する．

    Args:
        text: ファイル全体のテキスト
        source: 警告メッセージに付加するファイル名（省略可）

    Returns:
        (frontmatter_dict, body_text)
        フロントマターが存在しない場合は ({}, テキスト全体) を返す．
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != FRONTMATTER_DELIMITER:
        return {}, text

    fm_lines = []
    body_start = len(lines)
    found_end = False
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == FRONTMATTER_DELIMITER:
            body_start = i + 1
            found_end = True
            break
        fm_lines.append(line)

    if not found_end:
        prefix = f"{source}: " if source else ""
        print(
            f"Warning: {prefix}フロントマターの終端 `---` が見つかりません．ファイル全体を本文として扱います．",
            file=sys.stderr,
        )
        return {}, text

    fm_dict: dict[str, str] = {}
    for line in fm_lines:
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            key, _, value = line.partition(":")
            fm_dict[key.strip()] = value.strip().strip("\"'")

    body = "".join(lines[body_start:]).lstrip("\n")
    return fm_dict, body


def build_atom_entry(title: str, body: str) -> bytes:
    """AtomPub エントリ XML を生成する．

    `<app:draft>yes</app:draft>` は常にセットし，公開フラグは持たせない．
    """
    title_esc = html.escape(title)
    body_esc = html.escape(body)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<entry xmlns="http://www.w3.org/2005/Atom"\n'
        '       xmlns:app="http://www.w3.org/2007/app">\n'
        f"  <title>{title_esc}</title>\n"
        '  <content type="text/x-markdown">'
        f"{body_esc}"
        "</content>\n"
        "  <app:control>\n"
        "    <app:draft>yes</app:draft>\n"
        "  </app:control>\n"
        "</entry>\n"
    )
    return xml.encode("utf-8")


def extract_entry_id(response_body: bytes) -> str:
    """AtomPub レスポンスの <id> 要素からエントリ ID（末尾の数字列）を抽出する．

    はてなブログの <id> は `tag:blog.hatena.ne.jp,...-{numeric_id}` 形式のため，
    ハイフン直後の数字列を取り出す．複数の <id> があれば最初のものを使用する．
    """
    match = re.search(rb"<id>[^<]+-(\d+)</id>", response_body)
    if match:
        return match.group(1).decode("ascii")
    return ""


def decide_publish_method(fm: dict[str, str]) -> tuple[str, str | None]:
    """フロントマターから送信メソッドを判定する．

    - `hatena_published` が真 → 公開後ははてな側を真とするため自動送信を拒否（例外）．
    - `hatena_entry_id` あり → ("PUT", entry_id)（既存下書きの更新）．
    - それ以外 → ("POST", None)（新規作成）．
    """
    published = str(fm.get("hatena_published", "")).strip().lower() in _TRUTHY
    if published:
        raise ValueError(
            "hatena_published が真のため自動送信を拒否します．"
            "公開後ははてなブログ側を真とし，publish.py からの更新は行いません．"
        )
    entry_id = fm.get("hatena_entry_id") or None
    if entry_id:
        return ("PUT", entry_id)
    return ("POST", None)


def parse_collection_feed(xml_bytes: bytes) -> list[dict]:
    """AtomPub コレクションフィードを解析し，エントリ一覧を返す．

    各要素は `{"entry_id": str, "title": str, "draft": bool}`．
    `entry_id` は `<id>` 末尾のハイフン直後の数字列．

    入力は認証済みはてな AtomPub API（HTTPS）のレスポンスに限るため，
    信頼境界の内側として扱う．`publish.py` は標準ライブラリのみ・
    サードパーティ依存ゼロを設計原則とするため `defusedxml` は導入しない．
    expat は外部エンティティ・外部 DTD を解決しないため XXE は対象外である．
    """
    root = ET.fromstring(xml_bytes)
    results: list[dict] = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        id_el = entry.find(f"{{{ATOM_NS}}}id")
        title_el = entry.find(f"{{{ATOM_NS}}}title")
        draft_el = entry.find(f"{{{APP_NS}}}control/{{{APP_NS}}}draft")
        id_text = id_el.text if id_el is not None and id_el.text else ""
        match = re.search(r"-(\d+)$", id_text)
        entry_id = match.group(1) if match else ""
        title = title_el.text if title_el is not None and title_el.text else ""
        draft = (
            draft_el is not None
            and (draft_el.text or "").strip().lower() == "yes"
        )
        results.append({"entry_id": entry_id, "title": title, "draft": draft})
    return results


def parse_feed_next_link(xml_bytes: bytes) -> str | None:
    """フィードの `<link rel="next" href="...">` を返す（なければ None）．"""
    root = ET.fromstring(xml_bytes)
    for link in root.findall(f"{{{ATOM_NS}}}link"):
        if link.get("rel") == "next":
            return link.get("href")
    return None


def upsert_frontmatter_field(text: str, key: str, value: str) -> str:
    """フロントマターへ `key: value` を追記または置換する（本文は保つ）．"""
    lines = text.splitlines(keepends=True)
    new_line = f"{key}: {value}\n"
    if not lines or lines[0].rstrip() != FRONTMATTER_DELIMITER:
        return f"---\n{new_line}---\n\n{text}"

    close = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == FRONTMATTER_DELIMITER:
            close = i
            break
    if close is None:
        return text

    for j in range(1, close):
        line = lines[j]
        if ":" in line and not line.startswith((" ", "-")):
            existing_key = line.partition(":")[0].strip()
            if existing_key == key:
                lines[j] = new_line
                return "".join(lines)

    lines.insert(close, new_line)
    return "".join(lines)


def _send_entry(
    url: str,
    entry_xml: bytes,
    username: str,
    api_key: str,
    method: str,
) -> bytes:
    """AtomPub へエントリ XML を送信する（POST / PUT 共通）．"""
    req = urllib.request.Request(
        url,
        data=entry_xml,
        headers={
            "Content-Type": "application/atom+xml; charset=utf-8",
            "X-WSSE": build_wsse_header(username, api_key),
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def publish_draft(
    draft_path: Path,
    username: str,
    blog_id: str,
    api_key: str,
) -> None:
    """ドラフトを読み込み，frontmatter に応じて新規 POST か更新 PUT で送る．"""
    text = draft_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text, source=str(draft_path))

    title = fm.get("draft_of") or draft_path.stem
    if not title:
        title = draft_path.stem

    try:
        method, entry_id = decide_publish_method(fm)
    except ValueError as exc:
        print(f"Skip: {draft_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    entry_xml = build_atom_entry(title, body)
    if method == "PUT":
        url = build_member_url(username, blog_id, entry_id)  # type: ignore[arg-type]
    else:
        url = build_collection_url(username, blog_id)

    try:
        response_body = _send_entry(url, entry_xml, username, api_key, method)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(
            f"Error: HTTP {exc.code} {exc.reason}\n{body_text}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Error: {exc.reason}", file=sys.stderr)
        sys.exit(1)

    if method == "POST":
        new_id = extract_entry_id(response_body)
        if new_id:
            updated = upsert_frontmatter_field(text, "hatena_entry_id", new_id)
            draft_path.write_text(updated, encoding="utf-8")
        entry_id = new_id

    if entry_id:
        admin_url = (
            HATENA_BLOG_ADMIN_BASE.format(username=username, blog_id=blog_id)
            + entry_id
        )
        verb = "更新" if method == "PUT" else "下書き投稿"
        print(f"{verb}完了: {admin_url}")
    else:
        print("送信完了（entry ID の取得に失敗しました）")


def fetch_all_entries(
    username: str,
    blog_id: str,
    api_key: str,
    *,
    max_pages: int = 20,
) -> list[dict]:
    """コレクションフィードを rel=next で辿り，全エントリ一覧を返す．"""
    url: str | None = build_collection_url(username, blog_id)
    entries: list[dict] = []
    pages = 0
    while url and pages < max_pages:
        req = urllib.request.Request(
            url,
            headers={"X-WSSE": build_wsse_header(username, api_key)},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_bytes = resp.read()
        entries.extend(parse_collection_feed(xml_bytes))
        url = parse_feed_next_link(xml_bytes)
        pages += 1
    return entries


def sync_entry_ids(
    draft_paths: list[Path],
    username: str,
    blog_id: str,
    api_key: str,
) -> None:
    """はてな側の一覧と突合し，title 一致で hatena_entry_id を frontmatter へ書く．"""
    try:
        entries = fetch_all_entries(username, blog_id, api_key)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {exc.code} {exc.reason}\n{body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Error: {exc.reason}", file=sys.stderr)
        sys.exit(1)

    by_title: dict[str, str] = {}
    for entry in entries:
        # 同名が複数あれば最初の 1 件を採用する（重複は警告）．
        title = entry["title"]
        if title in by_title and by_title[title] != entry["entry_id"]:
            print(f"Warning: 同名タイトルが複数あります: {title}", file=sys.stderr)
            continue
        by_title.setdefault(title, entry["entry_id"])

    for path in draft_paths:
        text = path.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(text, source=str(path))
        if fm.get("hatena_entry_id"):
            print(f"Skip（ID 設定済み）: {path}")
            continue
        title = fm.get("draft_of") or path.stem
        entry_id = by_title.get(title)
        if not entry_id:
            print(f"未一致（はてな側に該当なし）: {path}", file=sys.stderr)
            continue
        updated = upsert_frontmatter_field(text, "hatena_entry_id", entry_id)
        path.write_text(updated, encoding="utf-8")
        print(f"ID 記録: {path} -> {entry_id}")


def _load_credentials(env_file: Path) -> tuple[str, str, str]:
    env_vars = load_env_file(env_file)
    username = get_env("HATENA_USERNAME", env_vars)
    blog_id = get_env("HATENA_BLOG_ID", env_vars)
    api_key = get_env("HATENA_API_KEY", env_vars)
    return username, blog_id, api_key


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Markdown ドラフトをはてなブログに下書き投稿・更新する",
    )
    parser.add_argument(
        "draft_file",
        type=Path,
        nargs="+",
        help="対象の Markdown ドラフトファイル（複数可）",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="環境変数ファイルのパス（既定: .env）",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="送信せず，はてな側の一覧と title 照合で hatena_entry_id を frontmatter へ記録する",
    )
    args = parser.parse_args()

    missing = [p for p in args.draft_file if not p.exists()]
    if missing:
        for p in missing:
            print(f"Error: ファイルが見つかりません: {p}", file=sys.stderr)
        sys.exit(1)

    username, blog_id, api_key = _load_credentials(args.env_file)

    if args.sync:
        sync_entry_ids(args.draft_file, username, blog_id, api_key)
        return

    for path in args.draft_file:
        publish_draft(path, username, blog_id, api_key)


if __name__ == "__main__":
    main()
