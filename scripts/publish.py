"""はてなブログ AtomPub API を使って Markdown ドラフトを下書き投稿する CLI スクリプト．

設計方針:

- 標準ライブラリのみで実装する．サードパーティ依存ゼロ．
- `<app:draft>yes</app:draft>` をハードコードし，公開フラグは持たせない．
  公開判断ははてなブログの管理画面で人間が行う．
- 環境変数（HATENA_USERNAME / HATENA_BLOG_ID / HATENA_API_KEY）は
  `--env-file`（既定: `.env`）から読み込む．
  環境変数に既に設定済みの場合はそちらを優先する（os.environ 優先）．
- WSSE 認証（RFC 3339 CreatedDate，SHA-1 PasswordDigest）を使用する．

使い方:

    python scripts/publish.py drafts/2026-05-07-my-article.md
    python scripts/publish.py drafts/2026-05-07-my-article.md --env-file /path/to/.env

出力:

    下書きが作成された場合，管理画面の URL を標準出力に書き出す．
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
from datetime import datetime, timezone
from pathlib import Path


# AtomPub エンドポイント（{username} と {blog_id} はランタイムで置換）
ATOM_PUB_ENDPOINT = "https://blog.hatena.ne.jp/{username}/{blog_id}/atom/entry"

# YAML フロントマターのデリミタ
FRONTMATTER_DELIMITER = "---"

# 管理画面の下書き URL ベース
HATENA_BLOG_ADMIN_BASE = "https://blog.hatena.ne.jp/{username}/{blog_id}/edit?entry="


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


def post_draft(
    draft_path: Path,
    username: str,
    blog_id: str,
    api_key: str,
) -> None:
    """ドラフトファイルを読み込み，AtomPub 経由で下書き投稿する．"""
    text = draft_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text, source=str(draft_path))

    title = fm.get("draft_of") or draft_path.stem
    if not title:
        title = draft_path.stem

    entry_xml = build_atom_entry(title, body)
    endpoint = ATOM_PUB_ENDPOINT.format(username=username, blog_id=blog_id)
    wsse = build_wsse_header(username, api_key)

    req = urllib.request.Request(
        endpoint,
        data=entry_xml,
        headers={
            "Content-Type": "application/atom+xml; charset=utf-8",
            "X-WSSE": wsse,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = resp.read()
            entry_id = extract_entry_id(response_body)
            if entry_id:
                admin_url = (
                    HATENA_BLOG_ADMIN_BASE.format(
                        username=username, blog_id=blog_id
                    )
                    + entry_id
                )
                print(f"下書き投稿完了: {admin_url}")
            else:
                print("下書き投稿完了（URL の取得に失敗しました）")
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Markdown ドラフトをはてなブログに下書き投稿する",
    )
    parser.add_argument(
        "draft_file",
        type=Path,
        help="投稿する Markdown ドラフトファイルのパス",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="環境変数ファイルのパス（既定: .env）",
    )
    args = parser.parse_args()

    if not args.draft_file.exists():
        print(f"Error: ファイルが見つかりません: {args.draft_file}", file=sys.stderr)
        sys.exit(1)

    env_vars = load_env_file(args.env_file)
    username = get_env("HATENA_USERNAME", env_vars)
    blog_id = get_env("HATENA_BLOG_ID", env_vars)
    api_key = get_env("HATENA_API_KEY", env_vars)

    post_draft(args.draft_file, username, blog_id, api_key)


if __name__ == "__main__":
    main()
