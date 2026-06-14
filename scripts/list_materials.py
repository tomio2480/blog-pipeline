"""materials/corrected/ 配下の素材 Markdown を列挙して情報を出力する CLI スクリプト．

設計方針:

- 標準ライブラリのみで実装する．サードパーティ依存ゼロ．
- YAML フロントマターは限定パーサで処理する（ネスト無し，コメント無視）．
- .summary.yml が存在する場合は summary / auto_tags をマージする．
- README.md および *.summary.yml は対象から除外する．
- フロントマター不正のファイルはスキップし，stderr に warning を出す．
- .summary.yml 欠損は warning のみ（非ゼロ終了しない）．

使い方:

    python scripts/list_materials.py <materials_dir> [--format json|table]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------- YAML 限定パーサ ----------


_JSON_DECODER = json.JSONDecoder()


def _dequote_list_element(item_val: str) -> str:
    """リスト要素のクォートを除去する．

    - ダブルクォート始まりは JSON 文字列として解析し ``\\"`` や ``\\n`` 等のエスケープを処理する．
      JSON として不正な場合，または閉じクォート後に余分なデータが残る場合は，
      両端クォートのスライスにフォールバックする（値の切り捨てを防ぐ）．
    - シングルクォートはエスケープ処理せず両端のクォートのみ除去する．
    - クォートなしはそのまま返す．
    """
    if item_val.startswith('"'):
        try:
            value, end = _JSON_DECODER.raw_decode(item_val)
            # 閉じクォート以降に余分なデータが無いときだけ採用する．
            # ``"foo"bar`` のような不正要素を 'foo' へ丸めないため．
            if item_val[end:].strip() == "":
                return value
        except json.JSONDecodeError:
            pass
        # フォールバック：両端ダブルクォートなら単純スライス
        if item_val.endswith('"') and len(item_val) >= 2:
            return item_val[1:-1]
        return item_val
    if item_val.startswith("'") and item_val.endswith("'") and len(item_val) >= 2:
        return item_val[1:-1]
    return item_val


def _split_inline_array(inner: str) -> list[str]:
    """インライン配列の中身をクォート状態を考慮して要素分割する．

    クォート外のカンマだけを要素境界とする．ダブルクォート内は ``\\`` を
    直後 1 文字のエスケープとして扱い ``\\"`` で閉じない．シングルクォート内は
    エスケープ処理せず次の ``'`` までを 1 要素とみなす．クォートの除去と
    エスケープ解釈は後段の :func:`_dequote_list_element` に委ねるため，
    各要素はクォート文字を含んだまま返す．
    """
    elements: list[str] = []
    current: list[str] = []
    in_double: bool = False
    in_single: bool = False
    escaped: bool = False
    for ch in inner:
        if escaped:
            current.append(ch)
            escaped = False
        elif in_double:
            current.append(ch)
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
        elif in_single:
            current.append(ch)
            if ch == "'":
                in_single = False
        elif ch == '"':
            current.append(ch)
            in_double = True
        elif ch == "'":
            current.append(ch)
            in_single = True
        elif ch == ",":
            elements.append("".join(current))
            current = []
        else:
            current.append(ch)
    elements.append("".join(current))
    return elements


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """ネスト無し・コメント無視の限定 YAML パーサ．

    対応形式:
    - ``key: "value"`` または ``key: value``（クォート有無両対応）
    - ``key:`` の次行から ``  - item`` のリスト
    - 空行・コメント行（# 始まり）は無視
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # コメント・空行スキップ
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # key: value または key:
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*:(.*)', line)
        if not m:
            i += 1
            continue

        key = m.group(1)
        raw_val = m.group(2).strip()

        # コメント除去（ # 以降）
        # ただしクォート内の # は除去しない
        if raw_val.startswith('"') or raw_val.startswith("'"):
            quote_char = raw_val[0]
            value = None
            if quote_char == '"':
                # ダブルクォート：JSON 文字列として解析し \" や \n 等を処理する
                try:
                    value, _ = _JSON_DECODER.raw_decode(raw_val)
                except json.JSONDecodeError:
                    pass

            if value is None:
                # シングルクォートまたは解析失敗時：エスケープなしで終了クォートを探す
                end_idx = raw_val.find(quote_char, 1)
                value = raw_val[1:end_idx] if end_idx != -1 else raw_val[1:]
            result[key] = value
            i += 1
        elif raw_val.startswith("["):
            # インライン配列表記: ["tagA", "tagB"] または [a, b]
            inner = raw_val.strip("[]")
            items_inline: list[str] = []
            for item_raw in _split_inline_array(inner):
                item_raw = item_raw.strip()
                if not item_raw:
                    continue
                item_val = _dequote_list_element(item_raw)
                if item_val:
                    items_inline.append(item_val)
            result[key] = items_inline
            i += 1
        elif raw_val == "" or raw_val.startswith("#"):
            # 値が空 → 次行以降にリストがあるか確認
            items: list[str] = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped or next_stripped.startswith("#"):
                    i += 1
                    continue
                list_m = re.match(r'^\s+- (.*)', next_line)
                if list_m:
                    items.append(_dequote_list_element(list_m.group(1).strip()))
                    i += 1
                else:
                    break
            result[key] = items
        else:
            # クォートなし値：コメント除去
            val_no_comment = re.sub(r'\s+#.*$', '', raw_val).strip()
            result[key] = val_no_comment
            i += 1

    return result


# ---------- フロントマターパーサ ----------


def _extract_frontmatter(text: str) -> tuple[dict[str, Any], bool]:
    """Markdown テキストから YAML フロントマターを抽出してパースする．

    戻り値: (parsed_dict, success)
    - success=False のとき parsed_dict は空辞書
    """
    if not text.startswith("---"):
        return {}, False

    # 最初の --- の直後から次の --- を探す
    first_end = text.find("\n", 0)
    if first_end == -1:
        return {}, False

    rest = text[first_end + 1:]
    # 終了 --- を探す
    close_m = re.search(r'^---\s*$', rest, flags=re.MULTILINE)
    if not close_m:
        return {}, False

    yaml_block = rest[:close_m.start()]
    try:
        parsed = _parse_simple_yaml(yaml_block)
    except (ValueError, TypeError):
        return {}, False

    return parsed, True


# ---------- .summary.yml パーサ ----------


def _load_summary_yaml(path: Path) -> dict[str, Any]:
    """summary.yml を読み込む．失敗時は警告を出して空辞書を返す．"""
    try:
        text = path.read_text(encoding="utf-8")
        return _parse_simple_yaml(text)
    except (OSError, UnicodeDecodeError) as e:
        _warn(f"{path.name} を読み込めませんでした: {e}")
        return {}


# ---------- 内部ユーティリティ ----------


def _warn(message: str) -> None:
    """warning メッセージを stderr へ出力する．"""
    print(f"Warning: {message}", file=sys.stderr)


# ---------- コア関数 ----------


def list_materials(materials_dir: Path) -> list[dict[str, Any]]:
    """materials_dir 配下の Markdown を列挙し，フロントマターと summary をマージして返す．

    - README.md と *.summary.yml は除外する
    - フロントマター不正のファイルはスキップし，stderr に warning を出す
    - .summary.yml 欠損は warning のみ（非ゼロ終了しない）
    """
    results: list[dict[str, Any]] = []

    md_files = sorted(materials_dir.glob("*.md"))
    # README.md と *.summary.yml を除外（.summary.yml は .md で終わらないが念のため）
    target_files = [
        p for p in md_files
        if p.name != "README.md" and not p.name.endswith(".summary.yml")
    ]

    for md_path in target_files:
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _warn(f"{md_path.name} を読み込めませんでした: {e}")
            continue

        frontmatter, success = _extract_frontmatter(text)
        if not success:
            _warn(f"{md_path.name} のフロントマターが不正です．スキップします．")
            continue

        # .summary.yml のマージ
        summary_path = md_path.parent / f"{md_path.stem}.summary.yml"
        if summary_path.exists():
            summary_data = _load_summary_yaml(summary_path)
            if summary_data.get("summary"):
                frontmatter["summary"] = summary_data["summary"]
            else:
                frontmatter.setdefault("summary", "")
            if summary_data.get("auto_tags"):
                frontmatter["auto_tags"] = summary_data["auto_tags"]
            else:
                frontmatter.setdefault("auto_tags", [])
        else:
            _warn(
                f"{md_path.stem}.summary.yml が見つかりません．"
                "summary と auto_tags は空で設定します．"
            )
            frontmatter.setdefault("summary", "")
            frontmatter.setdefault("auto_tags", [])

        results.append(frontmatter)

    return results


# ---------- フォーマッタ ----------


def format_json(items: list[dict[str, Any]]) -> str:
    """リストを JSON 文字列へ変換する．"""
    return json.dumps(items, ensure_ascii=False, indent=2)


def format_table(items: list[dict[str, Any]]) -> str:
    """リストを簡易表形式へ変換する．

    列: note_title / tags / summary（先頭 30 字）
    """
    header = f"{'note_title':<40} {'tags':<30} {'summary':<30}"
    separator = "-" * (40 + 1 + 30 + 1 + 30)
    lines = [header, separator]

    for item in items:
        note_title = str(item.get("note_title", ""))[:40]
        tags_raw = item.get("tags", [])
        if isinstance(tags_raw, list):
            tags_str = ", ".join(str(t) for t in tags_raw)
        else:
            tags_str = str(tags_raw)
        tags_str = tags_str[:30]
        summary_raw = str(item.get("summary", ""))
        summary_short = summary_raw[:30]

        lines.append(f"{note_title:<40} {tags_str:<30} {summary_short:<30}")

    return "\n".join(lines)


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="materials ディレクトリ内の素材 Markdown を列挙する"
    )
    parser.add_argument(
        "materials_dir",
        type=Path,
        help="素材ディレクトリのパス（materials/corrected/ を想定）",
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="出力形式（default: json）",
    )
    args = parser.parse_args(argv)

    if not args.materials_dir.is_dir():
        print(
            f"存在しないかディレクトリではありません: {args.materials_dir}",
            file=sys.stderr,
        )
        return 2

    items = list_materials(args.materials_dir)

    if args.format == "json":
        print(format_json(items))
    else:
        print(format_table(items))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
