"""人間メモ Markdown と生の文字起こしから 2 セクション素材を生成する CLI スクリプト．

設計方針:

- 録音音声を起点とする新しい取り込み経路（フェーズ 7）の素材生成を担う．
  `transcribe-audio` で得た生の文字起こしと，人が手書きした人間メモ
  Markdown を 1 つの素材 Markdown へまとめる．
- 出力は `parse_enex.py` と同一の 2 セクション構成
  （人間メモ / 生の文字起こし）とし，下流の Subagent・スクリプトが
  既存フローのまま素材を扱えるようにする．
- 人間メモと音声・文字起こしは共通の basename（`YYYY-MM-DD-録音名`）で
  対応づける前提とする．`note_title` と `created` はメモのファイル名 stem から
  導出し，メモ自身のフロントマターがあれば優先して上書きする．
- フロントマターの `source` は `audio` 固定とする．
- 依存は `pyyaml` のみ（リポジトリ既定の依存）．人間メモのフロントマター解析に用いる．

使い方:

    python scripts/build_material.py --memo <memo.md> \\
        --transcription <transcript.txt> --output-dir <materials/raw>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml


SOURCE_NAME = "audio"
SECTION_HUMAN_MEMO = "## 🗒️ 人間メモ（音声添付の後に書かれたもの）"
SECTION_RAW_TRANSCRIPTION = "## 🗣️ 生の文字起こし"
STATE_TRANSCRIBED = "transcribed"
STATE_ABSENT = "absent"
_DATE_PREFIX_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-|$)")
_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass
class Material:
    note_title: str
    source: str
    created: str
    updated: str
    author: str | None
    tags: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    transcription_state: str = STATE_ABSENT
    memo_body: str = ""
    raw_transcription: str = ""


# ---------- public API ----------


def parse_memo(text: str) -> tuple[dict, str]:
    """人間メモ Markdown を (フロントマター辞書, 本文) へ分解する．

    フロントマターが無い場合は ({}, 本文全体) を返す．本文は前後の空白を除去する．
    `---` ブロックが存在するのに YAML として不正，またはマッピングでない場合は，
    ユーザーの記述ミスを黙って握りつぶさず `ValueError` を送出する．
    空のフロントマターは ({}, 本文) として正常に扱う．
    """
    match = _FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}, text.strip()

    raw_front, body = match.group(1), match.group(2)
    try:
        parsed = yaml.safe_load(raw_front)
    except yaml.YAMLError as exc:
        raise ValueError(f"人間メモのフロントマターが不正です: {exc}") from exc

    if parsed is not None and not isinstance(parsed, dict):
        raise ValueError(
            "人間メモのフロントマターはマッピングである必要があります: "
            f"{type(parsed).__name__} を検出しました"
        )

    front = parsed if isinstance(parsed, dict) else {}
    return front, body.strip()


def derive_created(stem: str) -> str:
    """ファイル名 stem の先頭 `YYYY-MM-DD` から ISO 日時を導出する．

    日付プレフィックスを持たない場合，または暦上存在しない日付
    （例 `2026-13-40`）の場合は空文字を返す．
    """
    match = _DATE_PREFIX_PATTERN.match(stem)
    if not match:
        return ""
    yyyy_mm_dd = match.group(1)
    try:
        date.fromisoformat(yyyy_mm_dd)
    except ValueError:
        return ""
    return f"{yyyy_mm_dd}T00:00:00Z"


def build_material(stem: str, memo_text: str, transcription_text: str) -> Material:
    """stem・人間メモ・生の文字起こしから `Material` を組み立てる．

    メタデータはメモのフロントマターを優先し，無ければ stem・既定値へフォールバックする．
    """
    front, memo_body = parse_memo(memo_text)
    transcription = transcription_text.strip()

    note_title = _str_or(front.get("note_title"), stem)
    created = _str_or(_coerce_iso(front.get("created")), derive_created(stem))
    updated = _str_or(_coerce_iso(front.get("updated")), created)
    author = _optional_str(front.get("author"))
    tags = _str_list(front.get("tags"))
    languages = _str_list(front.get("languages"))
    state = STATE_TRANSCRIBED if transcription else STATE_ABSENT

    return Material(
        note_title=note_title,
        source=SOURCE_NAME,
        created=created,
        updated=updated,
        author=author,
        tags=tags,
        languages=languages,
        transcription_state=state,
        memo_body=memo_body,
        raw_transcription=transcription,
    )


def material_to_markdown(material: Material) -> str:
    """`Material` をフロントマター付き 2 セクション Markdown へ整形する．"""
    parts: list[str] = [_yaml_frontmatter(material), ""]

    parts.append(SECTION_HUMAN_MEMO)
    parts.append("")
    if material.memo_body:
        parts.append(material.memo_body)
        parts.append("")

    parts.append(SECTION_RAW_TRANSCRIPTION)
    parts.append("")
    if material.raw_transcription:
        parts.append(material.raw_transcription)
        parts.append("")

    return "\n".join(parts)


def write_material(
    stem: str, memo_text: str, transcription_text: str, output_dir: Path
) -> Path:
    """素材 Markdown を `output_dir/<stem>.md` へ書き出す．

    再生成を想定し，既存ファイルは上書きする（idempotent）．
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    material = build_material(stem, memo_text, transcription_text)
    path = output_dir / f"{stem}.md"
    path.write_text(material_to_markdown(material), encoding="utf-8")
    return path


# ---------- internal helpers ----------


def _coerce_iso(value: object) -> object:
    """YAML が date / datetime として解釈した値を ISO 文字列へ正規化する．

    str はそのまま返す．date / datetime は `isoformat()` で文字列化する．
    それ以外は元の値を返す．無クォートの日付フロントマターを `_str_or` が
    文字列として採用できるようにし，stem への黙示的フォールバックを防ぐ．
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _str_or(value: object, fallback: str) -> str:
    """value が非空の文字列ならそれを，さもなくば fallback を返す．"""
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _optional_str(value: object) -> str | None:
    """value が非空の文字列ならそれを，さもなくば None を返す．"""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _str_list(value: object) -> list[str]:
    """value がリストなら各要素を文字列化して返す．それ以外は空リスト．"""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _yaml_frontmatter(material: Material) -> str:
    lines: list[str] = ["---", f"source: {material.source}"]
    lines.append(f'note_title: "{_yaml_escape(material.note_title)}"')
    lines.append(f'created: "{_yaml_escape(material.created)}"')
    lines.append(f'updated: "{_yaml_escape(material.updated)}"')
    if material.author:
        lines.append(f'author: "{_yaml_escape(material.author)}"')
    else:
        lines.append("author: null")
    if material.tags:
        tags_str = ", ".join(f'"{_yaml_escape(t)}"' for t in material.tags)
        lines.append(f"tags: [{tags_str}]")
    else:
        lines.append("tags: []")
    lines.append("attachments: []")
    lines.append(f'transcription_state: "{material.transcription_state}"')
    if material.languages:
        langs_str = ", ".join(f'"{_yaml_escape(lang)}"' for lang in material.languages)
        lines.append(f"languages: [{langs_str}]")
    else:
        lines.append("languages: []")
    lines.append("---")
    return "\n".join(lines)


def _yaml_escape(s: str) -> str:
    """YAML double-quoted scalar として安全な形へエスケープする．

    json.dumps の double-quoted 文字列リテラルは YAML double-quoted scalar と
    互換のため，制御文字を含む文字列でもフロントマターが壊れない．
    """
    return json.dumps(s, ensure_ascii=False)[1:-1]


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="人間メモと生の文字起こしから 2 セクション素材 Markdown を生成する"
    )
    parser.add_argument("--memo", type=Path, required=True, help="人間メモ Markdown のパス")
    parser.add_argument(
        "--transcription", type=Path, required=True, help="生の文字起こしテキストのパス"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="出力先ディレクトリ（無ければ作成する）",
    )
    parser.add_argument(
        "--allow-mismatched-basename",
        action="store_true",
        help="人間メモと文字起こしの basename 不一致を許容する（既定では拒否）",
    )
    args = parser.parse_args(argv)

    for label, path in (("人間メモ", args.memo), ("文字起こし", args.transcription)):
        if not path.exists():
            print(f"{label}ファイルが見つかりません: {path}", file=sys.stderr)
            return 2
        if not path.is_file():
            print(f"{label}が通常ファイルではありません: {path}", file=sys.stderr)
            return 2

    if not args.allow_mismatched_basename and args.memo.stem != args.transcription.stem:
        print(
            "人間メモと文字起こしの basename が一致しません: "
            f"{args.memo.stem!r} / {args.transcription.stem!r}．"
            "別録音の取り違えを防ぐため拒否しました．"
            "意図的な場合は --allow-mismatched-basename を指定してください．",
            file=sys.stderr,
        )
        return 2

    stem = args.memo.stem
    memo_text = args.memo.read_text(encoding="utf-8")
    transcription_text = args.transcription.read_text(encoding="utf-8")
    written = write_material(stem, memo_text, transcription_text, args.output_dir)
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
