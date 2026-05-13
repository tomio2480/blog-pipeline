#!/usr/bin/env python3
"""
build_dictionary.py

`vocabulary.yml` の既登録語をユーザー辞書に変換して janome に読み込み，
Markdown ファイルを形態素解析して未知語候補を抽出する．

出力: `vocabulary/candidates.yml`（毎回上書き）

使い方:
  python scripts/build_dictionary.py
  python scripts/build_dictionary.py --vocab vocabulary/vocabulary.yml
      --materials materials/raw --output vocabulary/candidates.yml

依存:
  pip install -e ".[dev]"  または  pip install janome pyyaml
"""

import argparse
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import yaml
from janome.tokenizer import Tokenizer

# --- マークアップ除去パターン ---

_RE_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_RE_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_RE_INLINE_CODE = re.compile(r"`[^`]+`")
_RE_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^\)]+\)")
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_RE_URL = re.compile(r"https?://\S+")
_RE_HEADER_MARK = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)
_RE_EMOJI = re.compile("[\U00010000-\U0010FFFF]", flags=re.UNICODE)

# --- 品詞フィルター ---

_EXCLUDE_SUB_POS = {
    "非自立",
    "接尾",
    "数",
    "接続詞的",
    "形容動詞語幹",
    "副詞可能",
}

_RE_HIRAGANA_ONLY = re.compile(r"^[ぁ-ゟ]+$")
_RE_NUM_OR_SYMBOL = re.compile(r"^[\d\W]+$")

# vocabulary.yml で処理対象とするカテゴリ名．新カテゴリ追加時はここへ追記する．
_VOCAB_CATEGORIES = ("places", "organizations", "technical_terms")


def extract_text(md_content: str) -> str:
    """Markdown からフロントマター・コード・URL を除いた本文テキストを返す．"""
    text = _RE_FRONTMATTER.sub("", md_content)
    text = _RE_CODE_BLOCK.sub(" ", text)
    text = _RE_INLINE_CODE.sub(" ", text)
    text = _RE_MD_IMAGE.sub(r"\1", text)
    text = _RE_MD_LINK.sub(r"\1", text)
    text = _RE_URL.sub(" ", text)
    text = _RE_HEADER_MARK.sub("", text)
    text = _RE_BLOCKQUOTE.sub("", text)
    text = _RE_EMOJI.sub(" ", text)
    return text


def load_vocabulary(vocab_path: Path) -> tuple[list[str], set[str]]:
    """vocabulary.yml を読み込み，ユーザー辞書行リストと既知語セットを返す．

    ユーザー辞書の形式（janome simpledic）: surface,品詞,読み
    カンマを含むエントリは simpledic の区切り文字と衝突するため辞書行から除外する．
    """
    with open(vocab_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        data = {}

    known: set[str] = set()
    udic_lines: list[str] = []

    for category in _VOCAB_CATEGORIES:
        for entry in data.get(category, []):
            if not isinstance(entry, dict) or "canonical" not in entry:
                continue
            canonical: str = entry["canonical"]
            known.add(canonical)
            if "," not in canonical:
                udic_lines.append(f"{canonical},名詞,{canonical}")

            for alias in entry.get("aliases", []):
                known.add(alias)
                if "," not in alias:
                    udic_lines.append(f"{alias},名詞,{alias}")

    return udic_lines, known


def is_candidate(surface: str, pos_str: str, known: set[str]) -> bool:
    """未知語候補として取り出す条件を判定する．"""
    if surface in known:
        return False
    if len(surface) <= 1:
        return False
    if _RE_HIRAGANA_ONLY.match(surface):
        return False
    if _RE_NUM_OR_SYMBOL.match(surface):
        return False

    parts = pos_str.split(",")
    main_pos = parts[0]
    # parts[1] が存在しない場合（未知語・記号）は sub_pos を空文字とし除外しない
    sub_pos = parts[1] if len(parts) > 1 else ""

    if main_pos != "名詞":
        return False
    if sub_pos in _EXCLUDE_SUB_POS:
        return False

    return True


_CANDIDATES_HEADER = """\
# 固有名詞候補 candidates.yml
#
# `build_dictionary.py` が生成した未知語候補．
# 人間がレビューし，採用語を `vocabulary.yml` へ追記すること．
# このファイルは毎回上書きされる．git commit は不要．

"""


def write_candidates(candidates: dict[str, dict], output_path: Path) -> None:
    """候補語を出現頻度降順で YAML として書き出す．"""
    sorted_items = sorted(
        candidates.items(),
        key=lambda x: (-x[1]["count"], x[0]),
    )

    data = {
        "candidates": [
            {
                "surface": surface,
                "count": info["count"],
                "sources": sorted(info["files"]),
            }
            for surface, info in sorted_items
        ]
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    output_path.write_text(_CANDIDATES_HEADER + yaml_body, encoding="utf-8")


def _build_tokenizer(udic_lines: list[str]) -> Tokenizer:
    """ユーザー辞書を一時ファイルに書き出して Tokenizer を構築する．"""
    if not udic_lines:
        return Tokenizer()

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".csv",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write("\n".join(udic_lines))
        tmp_path = tmp.name

    try:
        return Tokenizer(udic=tmp_path, udic_type="simpledic", udic_enc="utf8")
    finally:
        os.unlink(tmp_path)


def _analyze(
    materials_dir: Path,
    tokenizer: Tokenizer,
    known: set[str],
) -> dict[str, dict]:
    """materials_dir 内の .md ファイルを解析して候補語を収集する．"""
    candidates: dict[str, dict] = defaultdict(lambda: {"count": 0, "files": set()})

    md_files = sorted(
        f for f in materials_dir.rglob("*.md") if f.name != "README.md"
    )
    if not md_files:
        print(f"  警告: {materials_dir} に .md ファイルが見つかりません", file=sys.stderr)
        return candidates

    for md_file in md_files:
        rel_path = md_file.relative_to(materials_dir).as_posix()
        print(f"  解析中: {rel_path}")
        try:
            content = md_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(
                f"  警告: {rel_path} の文字コード解読に失敗しました．スキップします．",
                file=sys.stderr,
            )
            continue
        text = extract_text(content)

        for token in tokenizer.tokenize(text):
            surface = token.surface
            pos_str = token.part_of_speech
            if is_candidate(surface, pos_str, known):
                candidates[surface]["count"] += 1
                candidates[surface]["files"].add(rel_path)

    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "vocabulary.yml をユーザー辞書として読み込み，"
            "Markdown ファイルの未知語候補を抽出する．"
        )
    )
    parser.add_argument(
        "--vocab",
        default="vocabulary/vocabulary.yml",
        help="vocabulary.yml のパス（既定: vocabulary/vocabulary.yml）",
    )
    parser.add_argument(
        "--materials",
        default="materials/raw",
        help="素材ディレクトリのパス（既定: materials/raw）",
    )
    parser.add_argument(
        "--output",
        default="vocabulary/candidates.yml",
        help="候補ファイルの出力先（既定: vocabulary/candidates.yml）",
    )
    args = parser.parse_args()

    vocab_path = Path(args.vocab)
    materials_dir = Path(args.materials)
    output_path = Path(args.output)

    if not vocab_path.exists():
        print(f"エラー: vocabulary ファイルが見つかりません: {vocab_path}", file=sys.stderr)
        sys.exit(1)
    if not materials_dir.exists():
        print(f"エラー: materials ディレクトリが見つかりません: {materials_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"vocabulary 読み込み: {vocab_path}")
    udic_lines, known = load_vocabulary(vocab_path)
    print(f"  既知語数: {len(known)} / ユーザー辞書エントリ数: {len(udic_lines)}")

    print("Tokenizer 構築中（ユーザー辞書あり）...")
    tokenizer = _build_tokenizer(udic_lines)

    print(f"素材解析: {materials_dir}")
    candidates = _analyze(materials_dir, tokenizer, known)
    print(f"  候補語数: {len(candidates)}")

    write_candidates(candidates, output_path)
    print(f"出力完了: {output_path}")
    print()
    print("次のステップ: candidates.yml をレビューして vocabulary.yml へ採用語を追記してください．")


if __name__ == "__main__":
    main()
