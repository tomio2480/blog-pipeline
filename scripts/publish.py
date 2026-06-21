"""はてなブログ AtomPub API を使って Markdown ドラフトを下書き投稿・更新する CLI スクリプト．

設計方針:

- 標準ライブラリのみで実装する．サードパーティ依存ゼロ．
- `<app:draft>yes</app:draft>` をハードコードし，公開フラグは持たせない．
  公開判断ははてなブログの管理画面で人間が行う．
- frontmatter の `categories`（配列）を `<category term="...">` として送る．
  本文からの選定は個人化版リポジトリ側が担い，本スクリプトは送信機構のみを担う．
- 送信メソッドは frontmatter の `hatena_entry_id` を主キーとして自動判定する．
  `hatena_entry_id` あり → 既存下書きの更新 PUT（常に ID 指定）．
  `hatena_entry_id` なし → 新規 POST（成功時に entry ID をクォート付きで書き戻す）．
  `hatena_published: true` → 公開後ははてな側を真とするため自動送信を拒否する．
  タイトル一致は ID 未設定時の補助に留め，主たる照合には使わない．
- 新規 POST の前に，正規化タイトル（空白無視）一致の既存下書きがあれば抑止する．
  意図的に新規作成する場合は `--force-new` を付ける．
- 存在確認はメンバー `GET`（`/atom/entry/{id}` の 200／404）を正本とする．
  コレクションフィードは結果整合で取りこぼすため，破壊的判断の根拠にしない．
- 送信前に本文の Markdown 画像記法 `![alt](path "caption")` を処理する．
  ローカル相対パスはフォトライフへアップロードし f:id 記法へ，外部 URL は `<img>` へ，
  いずれも `<figure>` / `<figcaption>` で包む．alt は a11y 必須で欠落はエラーとする．
- 環境変数（HATENA_USERNAME / HATENA_BLOG_ID / HATENA_API_KEY）は
  `--env-file`（既定: `.env`）から読み込む．
  環境変数に既に設定済みの場合はそちらを優先する（os.environ 優先）．
- WSSE 認証（RFC 3339 CreatedDate，SHA-1 PasswordDigest）を使用する．

使い方:

    python scripts/publish.py drafts/2026-05-07-my-article.md
    python scripts/publish.py drafts/2026-05-07-my-article.md --env-file /path/to/.env
    python scripts/publish.py drafts/*.md --sync     # ID 回収のみ（送信しない）
    python scripts/publish.py drafts/*.md --verify   # ID の実在をメンバー GET で検証
    python scripts/publish.py drafts/new.md --force-new  # 重複抑止を無視して新規 POST
    python scripts/publish.py drafts/a.md --upload-map .upload_map.json  # 画像の再上げ抑止
    python scripts/publish.py --list-categories      # 既存カテゴリー term 一覧を出力

出力:

    下書きの作成・更新時，管理画面の URL を標準出力に書き出す．
    エラーは標準エラー出力に書き出し，exit code 1 で終了する．
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath


# YAML フロントマターのデリミタ
FRONTMATTER_DELIMITER = "---"

# 管理画面の下書き URL ベース
HATENA_BLOG_ADMIN_BASE = "https://blog.hatena.ne.jp/{username}/{blog_id}/edit?entry="

# Atom / AtomPub の名前空間
ATOM_NS = "http://www.w3.org/2005/Atom"
APP_NS = "http://www.w3.org/2007/app"

# hatena_published が真とみなす値
_TRUTHY = {"true", "yes", "1", "on"}

# はてなカテゴリーの推奨上限（これを超えると警告する）
CATEGORY_MAX = 10

# はてなフォトライフ AtomPub の投稿先（PostURI）
FOTOLIFE_POST_URL = "https://f.hatena.ne.jp/atom/post"

# フォトライフのエントリは Atom 0.3 名前空間を使う（ブログ API の Atom とは別）
FOTOLIFE_ATOM_NS = "http://purl.org/atom/ns#"

# フォルダ指定に使う Dublin Core 名前空間
DC_NS = "http://purl.org/dc/elements/1.1/"

# フォルダ未指定時の既定フォルダ名（ブログ用画像をまとめる）
FOTOLIFE_DEFAULT_FOLDER = "blog"

# 拡張子から content-type を引く対応表（マジックバイト判定の補助）
_IMAGE_EXT_CONTENT_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}

# 本文中の Markdown 画像記法 `![alt](target "caption")` を検出する正規表現．
# target は空白を含まない 1 トークン（相対パスまたは URL）．丸括弧を含む
# ファイル名（例: `image(1).png`）も拾えるよう貪欲一致とし，末尾の `)` は
# バックトラックで閉じ括弧へ割り当てる．
# caption は省略可で，直前に空白を挟み二重引用符または単一引用符で囲む．
_IMAGE_MD_PATTERN = re.compile(
    r"!\[(?P<alt>[^\]]*)\]"
    r"\(\s*(?P<target>[^\s]+)"
    r"(?:\s+\"(?P<caption_d>[^\"]*)\"|\s+'(?P<caption_s>[^']*)')?"
    r"\s*\)"
)


def build_collection_url(username: str, blog_id: str) -> str:
    """コレクション URI（新規 POST 先・一覧取得先）を組み立てる．"""
    return f"https://blog.hatena.ne.jp/{username}/{blog_id}/atom/entry"


def build_category_url(username: str, blog_id: str) -> str:
    """カテゴリ文書 URI（既存カテゴリー一覧の取得先）を組み立てる．"""
    return f"https://blog.hatena.ne.jp/{username}/{blog_id}/atom/category"


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


def _strip_matching_quotes(value: str) -> str:
    """前後が同種のクォート（`"` / `'`）で囲まれていれば 1 組だけ外す．"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def parse_inline_list(value: str) -> list[str]:
    """`[a, b, c]` 形式のインラインフロー配列を要素リストへ分解する．

    各要素は前後の空白とクォートを外す．空要素は捨てる．
    """
    inner = value[1:-1]
    items: list[str] = []
    for part in inner.split(","):
        item = _strip_matching_quotes(part.strip()).strip()
        if item:
            items.append(item)
    return items


def parse_frontmatter(
    text: str, *, source: str = ""
) -> tuple[dict[str, str | list[str]], str]:
    """YAML フロントマターをシンプルに解析する．

    スカラー（`key: value`）に加え，配列も読む．配列は次の 2 形式に対応する．

    - インラインフロー: `categories: [PHP, コミュニティ]`
    - ブロック: `categories:` の直後に `  - PHP` のような要素行が続く形式

    配列値は `list[str]`，それ以外は `str` として返す．

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

    fm_dict: dict[str, str | list[str]] = {}
    n = len(fm_lines)
    i = 0
    while i < n:
        line = fm_lines[i]
        # コメント行（`#` 始まり）はコロンを含んでもキーにしない．
        if line.strip().startswith("#"):
            i += 1
            continue
        # キー行は行頭が空白・タブ・`-` でなく `:` を含む．
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                fm_dict[key] = parse_inline_list(value)
                i += 1
                continue
            if value == "":
                # ブロック形式の配列を先読みする（`  - item` 行の連続）．
                # 要素間の空行・コメント行は読み飛ばし，次のキー行で止める．
                items: list[str] = []
                j = i + 1
                while j < n:
                    nxt = fm_lines[j].strip()
                    if not nxt or nxt.startswith("#"):
                        j += 1
                        continue
                    if nxt.startswith("-"):
                        item = _strip_matching_quotes(nxt[1:].strip()).strip()
                        if item:
                            items.append(item)
                        j += 1
                    else:
                        break
                if items:
                    fm_dict[key] = items
                    i = j
                    continue
                fm_dict[key] = ""
                i += 1
                continue
            fm_dict[key] = _strip_matching_quotes(value)
        i += 1

    body = "".join(lines[body_start:]).lstrip("\n")
    return fm_dict, body


def normalize_categories(raw: str | list[str] | None) -> list[str]:
    """frontmatter の categories を送信前に正規化する．

    - `None` は空リストにする．
    - 文字列スカラーは 1 要素のリストへ寄せる（誤って文字単位に割れない）．
    - リスト・タプルの要素は `str()` 化する．それ以外のスカラーも 1 要素へ寄せて
      `str()` 化する（将来 YAML パーサーへ移行し数値スカラーが来ても落ちない防御）．
    - 各要素は前後空白を外し，空要素は捨てる．
    - 順序を保ったまま重複を除く．
    """
    if raw is None:
        items: list[str] = []
    elif isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = [str(raw)]

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        term = item.strip()
        if term and term not in seen:
            seen.add(term)
            result.append(term)
    return result


def build_atom_entry(
    title: str, body: str, categories: list[str] | None = None
) -> bytes:
    """AtomPub エントリ XML を生成する．

    `<app:draft>yes</app:draft>` は常にセットし，公開フラグは持たせない．
    `categories` を渡すと `<category term="...">` を順に出力する（空・None は出さない）．
    term は属性値のため `quote=True` でエスケープする．
    """
    title_esc = html.escape(title)
    body_esc = html.escape(body)
    category_xml = "".join(
        f'  <category term="{html.escape(term, quote=True)}" />\n'
        for term in (categories or [])
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<entry xmlns="http://www.w3.org/2005/Atom"\n'
        '       xmlns:app="http://www.w3.org/2007/app">\n'
        f"  <title>{title_esc}</title>\n"
        '  <content type="text/x-markdown">'
        f"{body_esc}"
        "</content>\n"
        f"{category_xml}"
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


def decide_publish_method(fm: dict[str, str | list[str]]) -> tuple[str, str | None]:
    """フロントマターから送信メソッドを判定する．

    - `hatena_published` が真 → 公開後ははてな側を真とするため自動送信を拒否（例外）．
    - `hatena_entry_id` あり → ("PUT", entry_id)（既存下書きの更新）．
    - それ以外 → ("POST", None)（新規作成）．
    """
    published: bool = str(fm.get("hatena_published", "")).strip().lower() in _TRUTHY
    if published:
        raise ValueError(
            "hatena_published が真のため自動送信を拒否します．"
            "公開後ははてなブログ側を真とし，publish.py からの更新は行いません．"
        )
    entry_id_raw = fm.get("hatena_entry_id")
    entry_id: str | None = entry_id_raw if isinstance(entry_id_raw, str) else None
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
    root: ET.Element = ET.fromstring(xml_bytes)
    results: list[dict] = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        id_el: ET.Element | None = entry.find(f"{{{ATOM_NS}}}id")
        title_el: ET.Element | None = entry.find(f"{{{ATOM_NS}}}title")
        draft_el: ET.Element | None = entry.find(
            f"{{{APP_NS}}}control/{{{APP_NS}}}draft"
        )
        id_text: str = id_el.text if id_el is not None and id_el.text else ""
        match: re.Match[str] | None = re.search(r"-(\d+)$", id_text)
        entry_id: str = match.group(1) if match else ""
        title: str = title_el.text if title_el is not None and title_el.text else ""
        draft: bool = (
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


def parse_category_document(xml_bytes: bytes) -> list[str]:
    """カテゴリ文書（`app:categories`）を解析し，既存カテゴリーの term 一覧を返す．

    はてなの `GET /atom/category` は `app:categories` を根に `atom:category`
    要素（`term` 属性）を並べる．`term` が空の要素は除く．

    入力は認証済みはてな AtomPub API（HTTPS）のレスポンスに限るため，
    `parse_collection_feed` と同じ信頼境界の扱いとし，`defusedxml` は導入しない．
    """
    root: ET.Element = ET.fromstring(xml_bytes)
    terms: list[str] = []
    for cat in root.findall(f"{{{ATOM_NS}}}category"):
        term = cat.get("term")
        if term:
            terms.append(term)
    return terms


def normalize_title(title: str) -> str:
    """タイトルを正規化する（空白類をすべて除去）．

    全角・半角の空白やタブの有無だけが異なるタイトルを同一視するために使う．
    文字そのものの違い（例：「学会誌」→「会誌」）は吸収しない．
    """
    return re.sub(r"\s+", "", title or "")


def build_title_index(entries: list[dict]) -> dict[str, list[str]]:
    """エントリ一覧から「正規化タイトル → entry_id のリスト」の索引を作る．

    同一の正規化タイトルが複数あれば，出現順で entry_id を集約する．
    """
    index: dict[str, list[str]] = {}
    for entry in entries:
        key = normalize_title(entry.get("title", ""))
        if not key:
            # 空タイトルは照合キーにしない（空文字列キーへの誤集約・誤一致を防ぐ）．
            continue
        entry_id = entry.get("entry_id") or ""
        if not entry_id:
            # entry_id が空のエントリは照合・書き戻しの対象にしない．
            continue
        index.setdefault(key, []).append(entry_id)
    return index


def find_title_matches(title: str, index: dict[str, list[str]]) -> list[str]:
    """正規化タイトルが一致する既存エントリの entry_id 一覧を返す（なければ空）．

    正規化後が空のタイトルは照合対象にせず，常に空リストを返す．
    """
    key = normalize_title(title)
    if not key:
        return []
    return index.get(key, [])


def should_suppress_new_post(
    title: str,
    index: dict[str, list[str]],
    *,
    force_new: bool,
) -> bool:
    """新規 POST を抑止すべきか判定する．

    正規化タイトル一致の既存エントリがあり，かつ `force_new` でないとき True．
    """
    if force_new:
        return False
    return bool(find_title_matches(title, index))


def upsert_frontmatter_field(
    text: str, key: str, value: str, *, quote: bool = False
) -> str:
    """フロントマターへ `key: value` を追記または置換する（本文は保つ）．

    `quote=True` のとき値をダブルクォートで囲む．`hatena_entry_id` のような
    19 桁の数値を YAML が浮動小数として精度を落とすのを防ぐ用途で使う．
    """
    lines = text.splitlines(keepends=True)
    rendered = f'"{value}"' if quote else value
    new_line = f"{key}: {rendered}\n"
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


def detect_image_content_type(data: bytes, *, filename: str | None = None) -> str:
    """画像バイト列から content-type を判定する．

    先頭のマジックバイトを優先し，判定できない場合は `filename` の拡張子で補う．
    どちらでも判定できなければ `ValueError` を送出する（未対応形式を早期に弾く）．

    対応形式は jpeg / png / gif とする．
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if filename:
        ext = Path(filename).suffix.lower()
        content_type = _IMAGE_EXT_CONTENT_TYPE.get(ext)
        if content_type:
            return content_type
    raise ValueError(
        f"未対応の画像形式です（jpeg / png / gif のみ対応）: filename={filename!r}"
    )


def build_fotolife_entry(
    image_data: bytes,
    content_type: str,
    title: str,
    folder: str = FOTOLIFE_DEFAULT_FOLDER,
) -> bytes:
    """フォトライフ AtomPub の投稿用エントリ XML を生成する．

    画像は Base64 化して `<content mode="base64" type="image/...">` で載せる．
    `folder` を渡すと `<dc:subject>` でフォルダを指定する（空文字なら省略）．
    フォトライフのエントリは Atom 0.3 名前空間（`FOTOLIFE_ATOM_NS`）を使う．
    """
    title_esc = html.escape(title)
    content_type_esc = html.escape(content_type, quote=True)
    b64 = base64.b64encode(image_data).decode("ascii")
    subject_xml = ""
    if folder:
        folder_esc = html.escape(folder)
        subject_xml = (
            f'  <dc:subject xmlns:dc="{DC_NS}">{folder_esc}</dc:subject>\n'
        )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<entry xmlns="{FOTOLIFE_ATOM_NS}">\n'
        f"  <title>{title_esc}</title>\n"
        f'  <content mode="base64" type="{content_type_esc}">{b64}</content>\n'
        f"{subject_xml}"
        "</entry>\n"
    )
    return xml.encode("utf-8")


def extract_fotolife_syntax(response_body: bytes) -> str:
    """フォトライフの投稿レスポンスから `hatena:syntax` の f:id 記法を取り出す．

    レスポンスは `<hatena:syntax>f:id:USER:XXXX:image</hatena:syntax>` を含む．
    名前空間接頭辞の変更や属性・改行に影響されないよう，`{*}syntax` の
    ワイルドカード名前空間でローカル名照合する．見つからない・整形式でない場合は
    空文字を返す（呼び出し側でアップロード失敗を判定する）．

    入力は認証済みはてな AtomPub API（HTTPS）のレスポンスに限るため信頼境界の
    内側として扱う．stdlib の expat は外部エンティティ・DTD を解決しないため
    XXE は対象外である（`parse_collection_feed` と同方針）．
    """
    try:
        root = ET.fromstring(response_body)
    except ET.ParseError:
        return ""
    syntax_text = root.findtext(".//{*}syntax")
    if syntax_text:
        return syntax_text.strip()
    return ""


def load_upload_map(path: Path) -> dict[str, str]:
    """アップロード記録（内容ハッシュ → f:id 記法）を読み込む．

    ファイルが無い・空のときは空辞書を返す．JSON の最上位が辞書でない場合は
    記録が壊れているとみなし `ValueError` を送出する（黙って握りつぶさない）．
    """
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"アップロード記録の JSON 解析に失敗しました: {path}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"アップロード記録の形式が不正です（最上位は辞書である必要があります）: {path}"
        )
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError(
            f"アップロード記録の形式が不正です（キーと値は文字列である必要があります）: {path}"
        )
    return data


def save_upload_map(path: Path, mapping: dict[str, str]) -> None:
    """アップロード記録を JSON で書き出す（キー順に整列し差分を安定させる）．

    親ディレクトリが無い場合は作成してから書き込む（`FileNotFoundError` を防ぐ）．
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def upload_image(
    image_path: Path,
    username: str,
    api_key: str,
    *,
    folder: str = FOTOLIFE_DEFAULT_FOLDER,
    map_path: Path | None = None,
) -> str:
    """画像をフォトライフへアップロードし，f:id 記法を返す．

    `map_path` を渡すと内容ハッシュ（SHA-256）で既存記録を照合し，同一内容の
    画像は再アップロードせず記録済みの f:id 記法を返す．新規アップロード時は
    記録を更新する．応答から f:id 記法を取得できない場合は `ValueError` とする．
    """
    data = image_path.read_bytes()
    content_key = hashlib.sha256(data).hexdigest()
    upload_map = load_upload_map(map_path) if map_path is not None else {}
    cached = upload_map.get(content_key)
    if cached:
        return cached

    content_type = detect_image_content_type(data, filename=image_path.name)
    entry_xml = build_fotolife_entry(data, content_type, image_path.stem, folder)
    response_body = _send_entry(
        FOTOLIFE_POST_URL, entry_xml, username, api_key, "POST"
    )
    syntax = extract_fotolife_syntax(response_body)
    if not syntax:
        raise ValueError(
            f"アップロード応答から f:id 記法を取得できませんでした: {image_path}"
        )
    if map_path is not None:
        upload_map[content_key] = syntax
        save_upload_map(map_path, upload_map)
    return syntax


def is_external_image(target: str) -> bool:
    """画像の参照先が外部 URL かどうかを判定する（http / https のみ外部とみなす）．

    外部 URL はアップロード対象外とし，本文からそのまま `<img>` で参照する．
    スキームは大文字小文字を区別しないため，小文字化して判定する．
    """
    return target.lower().startswith(("http://", "https://"))


def render_image_figure(
    *,
    alt: str,
    caption: str | None = None,
    fid: str | None = None,
    src: str | None = None,
) -> str:
    """画像 1 件分の `<figure>` ブロックを生成する．

    `fid`（フォトライフの f:id 記法）か `src`（外部 URL）のどちらか一方を渡す．
    `fid` のときは `[f:id:...:image:alt=...]`，`src` のときは `<img>` を出力する．
    `caption` があれば `<figcaption>` を付ける．caption が無くても `<figure>` で包む．

    alt はアクセシビリティ上の必須項目とし，空・空白のみは `ValueError`．
    f:id 記法の alt オプションはコロン（:）と閉じ括弧（]）を区切りに使うため，
    これらを含む alt は記法を壊す．早期に `ValueError` で弾き，壊れた投稿を防ぐ．
    """
    if not alt or not alt.strip():
        raise ValueError("画像の alt（代替テキスト）が空です．alt は必須です．")
    if (fid is None) == (src is None):
        raise ValueError(
            "render_image_figure には fid と src のどちらか一方のみ指定してください．"
        )

    lines = ["<figure>"]
    if fid is not None:
        if "]" in alt or ":" in alt:
            raise ValueError(
                "f:id 記法の alt にコロン（:）と閉じ括弧（]）は使えません: "
                f"{alt!r}"
            )
        lines.append(f"[{fid}:alt={alt}]")
    elif src is not None:
        src_esc = html.escape(src, quote=True)
        alt_esc = html.escape(alt, quote=True)
        lines.append(f'<img src="{src_esc}" alt="{alt_esc}">')
    if caption:
        lines.append(f"<figcaption>{html.escape(caption)}</figcaption>")
    lines.append("</figure>")
    return "\n".join(lines)


def transform_body_images(
    body: str,
    *,
    base_dir: Path,
    upload_fn: Callable[[Path], str],
) -> str:
    """本文の Markdown 画像記法を `<figure>` へ置換する（本文確定前処理）．

    ローカル相対パスの画像は `base_dir` 起点で解決し，`upload_fn` でフォトライフへ
    アップロードして f:id 記法へ置換する．外部 URL 画像はアップロードせず `<img>` で
    そのまま参照する．caption（Markdown のタイトル文字列）は `<figcaption>` にする．

    alt は a11y 必須とし，欠落時は `ValueError`．ローカル画像はアップロード前に
    alt を検証し，無駄な通信を避ける．
    """

    def replace(match: re.Match[str]) -> str:
        alt = match.group("alt")
        target = match.group("target")
        if not alt or not alt.strip():
            raise ValueError(
                f"画像の alt（代替テキスト）が空です．alt は必須です: {target}"
            )
        caption = match.group("caption_d") or match.group("caption_s")
        if is_external_image(target):
            return render_image_figure(alt=alt, caption=caption, src=target)
        # ローカル画像はリポジトリ内の相対パス参照を規約とする．
        # パーセントエンコード（`%20` や日本語の `%E5%9B%B3` 等）を先にデコードする．
        # デコード後に検証することで，`%2e%2e%2f` のようなエンコードされた親参照も弾く．
        decoded = urllib.parse.unquote(target)
        # 絶対パスと親ディレクトリ参照は base_dir の外を指しうるため明確なエラーで弾く．
        # POSIX 区切りと Windows 区切りの双方で解釈し，実行 OS に依存せず判定する
        # （Windows の `Path("/x").is_absolute()` は False になるため）．
        # `win.drive` も弾く．`C:assets/x.png` のドライブ相対パスは is_absolute が
        # False だが，`base_dir / それ` で base_dir が無視され任意のドライブを指しうる．
        posix, win = PurePosixPath(decoded), PureWindowsPath(decoded)
        if posix.is_absolute() or win.is_absolute() or win.drive:
            raise ValueError(
                f"画像は相対パスで指定してください（絶対パス・ドライブ指定は不可）: {target}"
            )
        if ".." in posix.parts or ".." in win.parts:
            raise ValueError(
                f"画像パスに親ディレクトリ参照（..）は使えません: {target}"
            )
        # Windows 区切り（`\`）を `/` へ正規化し，非 Windows 環境でも参照できる
        # ようにする．Markdown は `/` 区切りが通例だが，著者が `\` を書いても拾う．
        normalized = PureWindowsPath(decoded).as_posix()
        fid = upload_fn(base_dir / normalized)
        return render_image_figure(alt=alt, caption=caption, fid=fid)

    return _IMAGE_MD_PATTERN.sub(replace, body)


def entry_exists(
    username: str,
    blog_id: str,
    api_key: str,
    entry_id: str,
) -> bool:
    """メンバー URI を `GET` し，エントリの実在を確認する（存在確認の正本）．

    HTTP 200 → True，404 → False．それ以外の `HTTPError` は再送出する．
    コレクションフィードは結果整合で取りこぼしがあるため，削除・再投稿などの
    破壊的判断はこのメンバー `GET` を根拠にする．

    `entry_id` が空・空白のみの場合はメンバー URI が作れず，コレクション URI への
    `GET`（フィード）に化けて 200 を誤って返すため，先に False を返す．
    はてなのエントリ ID は ASCII 数字のみで構成される．全角数字や記号混じりは
    不正な URL 組み立てを招きうるため，送信前に拒否する（不要な通信も避ける）．
    """
    if not entry_id or not (entry_id.isascii() and entry_id.isdigit()):
        return False
    url = build_member_url(username, blog_id, entry_id)
    req = urllib.request.Request(
        url,
        headers={"X-WSSE": build_wsse_header(username, api_key)},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def publish_draft(
    draft_path: Path,
    username: str,
    blog_id: str,
    api_key: str,
    *,
    existing_index: dict[str, list[str]] | None = None,
    force_new: bool = False,
    upload_map_path: Path | None = None,
) -> None:
    """ドラフトを読み込み，frontmatter に応じて新規 POST か更新 PUT で送る．

    `existing_index` に正規化タイトル索引を渡すと，新規 POST 前に重複候補を照合し
    抑止する．`None` のとき（既定）は抑止せず従来どおり送信する．`force_new=True`
    は索引があっても抑止しない．
    """
    text = draft_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text, source=str(draft_path))

    title = fm.get("draft_of") or draft_path.stem
    if not title:
        title = draft_path.stem

    try:
        method, entry_id = decide_publish_method(fm)
    except ValueError as exc:
        print(f"Skip: {draft_path}: {exc}", file=sys.stderr)
        return

    # 新規 POST の前に，正規化タイトル一致の既存下書きがあれば抑止する．
    # フィードは結果整合のため取りこぼしがありうるが，ここは破壊的でない
    # 警告・抑止であり，誤検知（取りこぼしによる未警告）でも従来動作に戻るだけ．
    if (
        method == "POST"
        and existing_index is not None
        and should_suppress_new_post(title, existing_index, force_new=force_new)
    ):
        matches = find_title_matches(title, existing_index)
        print(
            f"Skip（重複の恐れ）: {draft_path}: "
            f"同名（空白無視）の既存エントリがあります: {', '.join(matches)}．"
            "更新する場合は frontmatter に hatena_entry_id を設定するか "
            "`--sync` で回収してください．意図的な新規作成は `--force-new` を付けます．",
            file=sys.stderr,
        )
        return

    categories = normalize_categories(fm.get("categories"))
    if len(categories) > CATEGORY_MAX:
        print(
            f"Warning: {draft_path}: categories が {len(categories)} 件で上限 "
            f"{CATEGORY_MAX} 件を超えています．はてな側で一部が無視される可能性が"
            "あります．frontmatter を見直してください．",
            file=sys.stderr,
        )

    # 本文確定前処理: 本文中の Markdown 画像をフォトライフへ上げ figure へ置換する．
    # 送信が確定したドラフトに対してのみ実行し，抑止・スキップ時の無駄な通信を避ける．
    # バッチ処理でどのドラフトが原因か特定できるよう，失敗はパス付きで再送出する．
    try:
        body = transform_body_images(
            body,
            base_dir=draft_path.parent,
            upload_fn=lambda image_path: upload_image(
                image_path, username, api_key, map_path=upload_map_path
            ),
        )
    except urllib.error.HTTPError as exc:
        # フォトライフの応答ボディには失敗理由（認証・容量など）が入るため拾う．
        body_text = exc.read().decode("utf-8", errors="replace")
        raise ValueError(
            f"{draft_path}: 画像のアップロードに失敗しました"
            f"（HTTP {exc.code}）: {body_text}"
        ) from exc
    except (ValueError, OSError) as exc:
        raise ValueError(f"{draft_path}: 画像の処理に失敗しました: {exc}") from exc

    entry_xml = build_atom_entry(title, body, categories)
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
            updated = upsert_frontmatter_field(
                text, "hatena_entry_id", new_id, quote=True
            )
            draft_path.write_text(updated, encoding="utf-8")
            # 同一バッチ内に同名の新規ドラフトが続く場合の重複 POST を防ぐため，
            # 送信した ID を索引へ反映し，後続の照合で抑止できるようにする．
            if existing_index is not None:
                key = normalize_title(title)
                if key:
                    existing_index.setdefault(key, []).append(new_id)
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


def fetch_categories(
    username: str,
    blog_id: str,
    api_key: str,
) -> list[str]:
    """カテゴリ文書 URI を `GET` し，既存カテゴリーの term 一覧を返す．

    本文からのカテゴリー選定（blog-private 側）が，既存カテゴリーを優先する
    ための入力に使う．取得は 1 リクエストで，ページングはしない．
    """
    url = build_category_url(username, blog_id)
    req = urllib.request.Request(
        url,
        headers={"X-WSSE": build_wsse_header(username, api_key)},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_bytes = resp.read()
    return parse_category_document(xml_bytes)


def list_categories(
    username: str,
    blog_id: str,
    api_key: str,
) -> None:
    """既存カテゴリーの term 一覧を 1 行 1 件で標準出力へ出す．

    本文からのカテゴリー選定（blog-private 側オーケストレーション）が，
    既存カテゴリーを優先する入力として読み取るための窓口とする．
    """
    for term in fetch_categories(username, blog_id, api_key):
        print(term)


def sync_entry_ids(
    draft_paths: list[Path],
    username: str,
    blog_id: str,
    api_key: str,
) -> None:
    """はてな側の一覧と突合し，正規化タイトル一致で hatena_entry_id を frontmatter へ書く．

    同名（空白無視）が複数あるときは取り違えを避けて自動記録しない（警告のみ）．
    """
    try:
        entries = fetch_all_entries(username, blog_id, api_key)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {exc.code} {exc.reason}\n{body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Error: {exc.reason}", file=sys.stderr)
        sys.exit(1)

    index = build_title_index(entries)

    for path in draft_paths:
        text = path.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(text, source=str(path))
        if fm.get("hatena_entry_id"):
            print(f"Skip（ID 設定済み）: {path}")
            continue
        title = fm.get("draft_of") or path.stem
        matches = find_title_matches(title, index)
        if not matches:
            print(f"未一致（はてな側に該当なし）: {path}", file=sys.stderr)
            continue
        if len(matches) > 1:
            # 同名（空白無視）が複数のときは取り違えを避け，自動記録しない．
            print(
                f"Warning: 同名（空白無視）が複数あり一意に定まりません: "
                f"{path}: {', '.join(matches)}",
                file=sys.stderr,
            )
            continue
        entry_id = matches[0]
        updated = upsert_frontmatter_field(
            text, "hatena_entry_id", entry_id, quote=True
        )
        path.write_text(updated, encoding="utf-8")
        print(f"ID 記録: {path} -> {entry_id}")


def verify_entries(
    draft_paths: list[Path],
    username: str,
    blog_id: str,
    api_key: str,
) -> bool:
    """各ドラフトの `hatena_entry_id` をメンバー `GET` し，実在を検証する．

    コレクションフィードは結果整合で取りこぼすため，存在確認はメンバー `GET`
    （200／404）を正本とする．送信や frontmatter の変更は行わない（読み取りのみ）．
    診断目的のため，1 件のエラーで中断せず各ドラフトを最後まで検証する．

    検証に失敗した項目（404 の欠落・HTTP／URL エラー）が 1 件でもあれば `False`，
    すべて健全なら `True` を返す．呼び出し元はこの戻り値で終了コードを決められる．
    `hatena_entry_id` 未設定は未送信・未回収の通常状態とみなし，失敗に数えない．
    """
    ok: bool = True
    for path in draft_paths:
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
        entry_id = fm.get("hatena_entry_id")
        if not entry_id:
            print(f"ID なし（未送信または未回収）: {path}")
            continue
        try:
            exists = entry_exists(username, blog_id, api_key, entry_id)
        except urllib.error.HTTPError as exc:
            print(
                f"Error: HTTP {exc.code} {exc.reason}: {path} (id={entry_id})",
                file=sys.stderr,
            )
            ok = False
            continue
        except urllib.error.URLError as exc:
            print(f"Error: {exc.reason}: {path} (id={entry_id})", file=sys.stderr)
            ok = False
            continue
        if exists:
            print(f"OK（実在）: {path} -> {entry_id}")
        else:
            print(
                f"欠落（404・ID が無効）: {path} (id={entry_id})．"
                "ID の付け間違いか，はてな側で削除された可能性があります．",
                file=sys.stderr,
            )
            ok = False
    return ok


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
        nargs="*",
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
        help="送信せず，はてな側の一覧と正規化タイトル照合で hatena_entry_id を frontmatter へ記録する",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="送信せず，各ドラフトの hatena_entry_id をメンバー GET（200／404）で検証する",
    )
    parser.add_argument(
        "--force-new",
        action="store_true",
        help="正規化タイトル一致の既存下書きがあっても抑止せず，新規 POST を強行する",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="送信せず，はてな側の既存カテゴリー term 一覧を 1 行 1 件で標準出力へ出す",
    )
    parser.add_argument(
        "--upload-map",
        type=Path,
        default=None,
        help="画像アップロード記録（内容ハッシュ → f:id）の JSON パス．"
        "指定すると同一画像の再アップロードを抑止する（既定: 記録しない）",
    )
    args = parser.parse_args()

    selected_modes = [
        name
        for name, on in (
            ("--sync", args.sync),
            ("--verify", args.verify),
            ("--list-categories", args.list_categories),
        )
        if on
    ]
    if len(selected_modes) > 1:
        print(
            f"Error: {' と '.join(selected_modes)} は同時に指定できません．",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.env_file != Path(".env") and not args.env_file.is_file():
        print(
            f"Error: 指定された環境変数ファイルが見つかりません: {args.env_file}",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.list_categories:
        if args.draft_file:
            print(
                "Error: --list-categories はドラフトファイルを取りません．",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        if not args.draft_file:
            print(
                "Error: 対象のドラフトファイルを 1 つ以上指定してください．",
                file=sys.stderr,
            )
            sys.exit(2)
        missing = [p for p in args.draft_file if not p.is_file()]
        if missing:
            for p in missing:
                print(f"Error: ファイルが見つかりません: {p}", file=sys.stderr)
            sys.exit(1)

    username, blog_id, api_key = _load_credentials(args.env_file)

    try:
        if args.list_categories:
            list_categories(username, blog_id, api_key)
            return

        if args.sync:
            sync_entry_ids(args.draft_file, username, blog_id, api_key)
            return

        if args.verify:
            if not verify_entries(args.draft_file, username, blog_id, api_key):
                sys.exit(1)
            return

        # 新規 POST 予定（hatena_entry_id 未設定）のドラフトがある場合のみ，
        # 重複抑止のため一覧を 1 度だけ取得して正規化タイトル索引を作る．
        existing_index: dict[str, list[str]] | None = None
        if not args.force_new:
            needs_index: bool = False
            for path in args.draft_file:
                fm, _ = parse_frontmatter(
                    path.read_text(encoding="utf-8"), source=str(path)
                )
                if not fm.get("hatena_entry_id"):
                    needs_index = True
                    break
            if needs_index:
                existing_index = build_title_index(
                    fetch_all_entries(username, blog_id, api_key)
                )

        for path in args.draft_file:
            publish_draft(
                path,
                username,
                blog_id,
                api_key,
                existing_index=existing_index,
                force_new=args.force_new,
                upload_map_path=args.upload_map,
            )
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {exc.code} {exc.reason}\n{body_text}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Error: {exc.reason}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
