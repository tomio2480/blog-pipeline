"""Evernote AI 文字起こし整理プロンプトを生成する CLI．

`templates/` ディレクトリ配下のマークダウンテンプレートに，
セッション識別子を埋め込んで，3 段階分のプロンプトを出力する．

Usage:
    python generate_prompts.py "2026-05-01-他人のルールに乗る"
    python generate_prompts.py "foo" --output-dir ./out
    python generate_prompts.py "foo" --templates-dir ./my_templates
    python generate_prompts.py "foo" --source-suffix "文字起こし"
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_SOURCE_SUFFIX = "元ノート"
SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_TEMPLATES_DIR = SCRIPT_DIR / "templates"

STAGE_KEYS = ("01_structure", "02_links", "03_proper_nouns")

PLACEHOLDER_SESSION_ID = "{session_id}"
PLACEHOLDER_SOURCE_NOTE = "{source_note}"


def build_source_note_title(
    session_id: str, suffix: str = DEFAULT_SOURCE_SUFFIX
) -> str:
    """元ノートのフルタイトルを組み立てる．

    Args:
        session_id: セッション識別子．
        suffix: タイトル末尾の文字列．デフォルトは「元ノート」．

    Returns:
        `[session_id] suffix` 形式のタイトル文字列．
    """
    return f"[{session_id}] {suffix}"


def build_prompt(
    template: str, session_id: str, suffix: str = DEFAULT_SOURCE_SUFFIX
) -> str:
    """テンプレート内のプレースホルダを埋めてプロンプトを生成する．

    `str.replace` を使うため，`{session_id}` `{source_note}` 以外の
    波括弧（コードブロック等）はそのまま保持される．

    Args:
        template: `{session_id}` および `{source_note}` を含むテンプレート．
        session_id: セッション識別子．
        suffix: 元ノートタイトルの末尾文字列．

    Returns:
        プレースホルダ置換後のプロンプト文字列．
    """
    source_note = build_source_note_title(session_id, suffix)
    return template.replace(PLACEHOLDER_SESSION_ID, session_id).replace(
        PLACEHOLDER_SOURCE_NOTE, source_note
    )


def load_template(stage_key: str, templates_dir: Path) -> str:
    """指定されたディレクトリから段階に対応するテンプレートを読み込む．

    Args:
        stage_key: 段階キー（拡張子なし，例：`01_structure`）．
        templates_dir: テンプレートが置かれたディレクトリ．

    Returns:
        テンプレートファイルの内容．

    Raises:
        FileNotFoundError: テンプレートファイルが存在しない場合．
    """
    path = templates_dir / f"{stage_key}.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"テンプレートが見つかりません：{path}"
        )
    return path.read_text(encoding="utf-8")


def generate_all_prompts(
    session_id: str,
    output_dir: Path,
    templates_dir: Path = DEFAULT_TEMPLATES_DIR,
    source_suffix: str = DEFAULT_SOURCE_SUFFIX,
) -> list[Path]:
    """3 段階分のプロンプトを生成し，ファイルへ書き出す．

    Args:
        session_id: セッション識別子．
        output_dir: 出力先ディレクトリ．存在しなければ作成する．
        templates_dir: テンプレートディレクトリ．
        source_suffix: 元ノートタイトルの末尾文字列．

    Returns:
        生成したファイルのパス一覧（STAGE_KEYS 順）．

    Raises:
        FileNotFoundError: いずれかのテンプレートが見つからない場合．
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for stage_key in STAGE_KEYS:
        template = load_template(stage_key, templates_dir)
        content = build_prompt(template, session_id, source_suffix)
        path = output_dir / f"{stage_key}.md"
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evernote AI 文字起こし整理プロンプトを生成する．",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            '  python generate_prompts.py "2026-05-01-他人のルールに乗る"\n'
            '  python generate_prompts.py "foo" --output-dir ./out\n'
            '  python generate_prompts.py "foo" --templates-dir ./my_templates\n'
            '  python generate_prompts.py "foo" --source-suffix "文字起こし"\n'
        ),
    )
    parser.add_argument(
        "session_id",
        help="セッション識別子．元ノートの角括弧内に入れた文字列．",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力先ディレクトリ（デフォルト：./{session_id}/）",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=DEFAULT_TEMPLATES_DIR,
        help=f"テンプレートディレクトリ（デフォルト：{DEFAULT_TEMPLATES_DIR}）",
    )
    parser.add_argument(
        "--source-suffix",
        default=DEFAULT_SOURCE_SUFFIX,
        help=f"元ノートタイトルの末尾文字列（デフォルト：{DEFAULT_SOURCE_SUFFIX}）",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir: Path = (
        args.output_dir if args.output_dir is not None else Path(args.session_id)
    )
    paths = generate_all_prompts(
        session_id=args.session_id,
        output_dir=output_dir,
        templates_dir=args.templates_dir,
        source_suffix=args.source_suffix,
    )
    print(f"セッション識別子：{args.session_id}")
    print(f"テンプレート：{args.templates_dir.resolve()}")
    print(f"出力先：{output_dir.resolve()}")
    print("生成ファイル：")
    for path in paths:
        print(f"  - {path.name}")


if __name__ == "__main__":
    main()
