"""録音音声から生の文字起こしテキストを得る CLI スクリプト．

設計方針:

- 録音音声を起点とする新しい取り込み経路（フェーズ 7）の文字起こし工程を担う．
  `ffmpeg` で 16kHz モノラル WAV へ変換し，`whisper.cpp` の `large-v3` で
  文字起こしする．生成テキストは `.scratch/` など Git 管理外の場所へ出力し，
  後段の `build_material.py` が人間メモと束ねて素材 Markdown を生成する．
- `whisper.cpp` のバイナリとモデルは環境依存のため，パスは環境変数
  `WHISPER_CLI_PATH`／`WHISPER_MODEL_PATH` で受け取る．未設定なら fail fast する．
  無言の代替動作を避ける（`code-quality` の silent fallback 回避）．
- ループ対策として `-mc 0`（直前文脈の持ち越し無効化）を標準化する．
  STT パイロット（2026-06-12）で 72 分録音のループ消失を確認した判断である．
- 固有名詞の正答率を上げるため，`vocabulary.yml` の canonical 語を
  `--prompt`（初期プロンプト）へ注入する．
- 依存は `pyyaml` のみ（リポジトリ既定の依存）．`ffmpeg` は PATH 上を前提とする．

使い方:

    set WHISPER_CLI_PATH=C:\\path\\to\\whisper-cli.exe
    set WHISPER_MODEL_PATH=C:\\path\\to\\ggml-large-v3.bin
    python scripts/transcribe_audio.py --audio <materials/audio/録音.m4a> \\
        --vocabulary <vocabulary.yml> --output-dir <.scratch/transcription>
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml


# canonical 語を抽出する辞書カテゴリ（出現順を保つ）
VOCABULARY_CATEGORIES = ("places", "organizations", "technical_terms")
PROMPT_SEPARATOR = "、"
ENV_WHISPER_CLI = "WHISPER_CLI_PATH"
ENV_WHISPER_MODEL = "WHISPER_MODEL_PATH"
DEFAULT_LANGUAGE = "ja"


# ---------- prompt ----------


def load_prompt_words(vocabulary_path: Path) -> str:
    """`vocabulary.yml` の canonical 語を連結した初期プロンプト文字列を返す．

    `places`／`organizations`／`technical_terms` の各 canonical を出現順に集め，
    重複を除いて区切り文字で連結する．エントリが無ければ空文字列を返す．
    """
    if not vocabulary_path.exists():
        raise ValueError(f"辞書ファイルが見つかりません: {vocabulary_path}")

    try:
        data = yaml.safe_load(vocabulary_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"辞書ファイルの読み込みまたは解析に失敗しました: {vocabulary_path}: {exc}"
        ) from exc
    if data is None:
        return ""
    if not isinstance(data, Mapping):
        raise ValueError(
            f"辞書のトップレベルはマッピングである必要があります: {vocabulary_path}"
        )

    words: list[str] = []
    seen: set[str] = set()
    for category in VOCABULARY_CATEGORIES:
        entries = data.get(category)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            canonical = entry.get("canonical")
            if not isinstance(canonical, str):
                continue
            canonical = canonical.strip()
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            words.append(canonical)

    return PROMPT_SEPARATOR.join(words)


# ---------- command builders ----------


def build_ffmpeg_command(input_path: Path, wav_path: Path) -> list[str]:
    """音声を 16kHz モノラルの PCM WAV へ変換する `ffmpeg` コマンドを組み立てる．"""
    return [
        "ffmpeg",
        "-i",
        str(input_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(wav_path),
    ]


def build_whisper_command(
    whisper_cli: Path,
    whisper_model: Path,
    wav_path: Path,
    output_stem: Path,
    *,
    prompt: str,
    language: str,
) -> list[str]:
    """`whisper.cpp` 実行コマンドを組み立てる．

    `-mc 0` を標準化し，`-otxt` でテキストを `output_stem`.txt へ出力する．
    `prompt` が非空のときのみ `--prompt` を付与する．
    """
    cmd = [
        str(whisper_cli),
        "-m",
        str(whisper_model),
        "-f",
        str(wav_path),
        "-l",
        language,
        "-mc",
        "0",
        "-otxt",
        "-of",
        str(output_stem),
    ]
    if prompt:
        cmd += ["--prompt", prompt]
    return cmd


# ---------- env ----------


def load_env_file(path: Path) -> dict[str, str]:
    """シンプルな `.env` ファイルパーサー（`publish.py` と同じ規約）．

    - `KEY=VALUE` 形式の行を読む．`#` 始まりの行は無視する．
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


def resolve_whisper_paths(env: Mapping[str, str]) -> tuple[Path, Path]:
    """環境変数から `whisper.cpp` バイナリとモデルのパスを解決する．

    未設定または空白なら `ValueError` を送出する（fail fast）．
    """
    cli = env.get(ENV_WHISPER_CLI, "").strip()
    if not cli:
        raise ValueError(
            f"環境変数 {ENV_WHISPER_CLI} が未設定です．whisper-cli の絶対パスを設定してください．"
        )
    model = env.get(ENV_WHISPER_MODEL, "").strip()
    if not model:
        raise ValueError(
            f"環境変数 {ENV_WHISPER_MODEL} が未設定です．ggml モデルの絶対パスを設定してください．"
        )
    return Path(cli), Path(model)


# ---------- orchestration ----------


def transcribe(
    *,
    audio_path: Path,
    vocabulary_path: Path,
    output_dir: Path,
    whisper_cli: Path,
    whisper_model: Path,
    language: str = DEFAULT_LANGUAGE,
) -> Path:
    """音声を WAV へ変換し `whisper.cpp` で文字起こしして txt パスを返す．"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = audio_path.stem
    wav_path = output_dir / f"{stem}.wav"
    output_stem = output_dir / stem

    # 辞書の読み込みは高コストな変換の前に行い，不正なら fail fast する．
    prompt = load_prompt_words(vocabulary_path)

    ffmpeg_cmd = build_ffmpeg_command(audio_path, wav_path)
    try:
        ffmpeg_result = subprocess.run(ffmpeg_cmd)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg が見つかりません．PATH 上に ffmpeg が存在することを確認してください．"
        ) from exc
    if ffmpeg_result.returncode != 0:
        raise RuntimeError(f"ffmpeg による WAV 変換に失敗しました: {audio_path}")

    whisper_cmd = build_whisper_command(
        whisper_cli,
        whisper_model,
        wav_path,
        output_stem,
        prompt=prompt,
        language=language,
    )
    if subprocess.run(whisper_cmd).returncode != 0:
        raise RuntimeError(f"whisper.cpp による文字起こしに失敗しました: {audio_path}")

    return output_dir / f"{stem}.txt"


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="録音音声を whisper.cpp で文字起こしし，生テキストを出力する"
    )
    parser.add_argument("--audio", type=Path, required=True, help="入力音声ファイルのパス")
    parser.add_argument(
        "--vocabulary",
        type=Path,
        required=True,
        help="canonical 語を --prompt へ注入する vocabulary.yml のパス",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="生テキストと中間 WAV の出力先（無ければ作成する．Git 管理外を想定）",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=f"文字起こし言語（既定: {DEFAULT_LANGUAGE}）",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="WHISPER_CLI_PATH／WHISPER_MODEL_PATH を読む .env のパス（既定: .env）",
    )
    args = parser.parse_args(argv)

    if not args.audio.exists() or not args.audio.is_file():
        print(f"音声ファイルが見つかりません: {args.audio}", file=sys.stderr)
        return 2
    if not args.vocabulary.exists() or not args.vocabulary.is_file():
        print(f"辞書ファイルが見つかりません: {args.vocabulary}", file=sys.stderr)
        return 2

    # os.environ を .env より優先する（publish.py と同じ規約）．
    env_file_vars = load_env_file(args.env_file)
    merged_env = {**env_file_vars, **os.environ}
    try:
        whisper_cli, whisper_model = resolve_whisper_paths(merged_env)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for label, path in (("whisper-cli", whisper_cli), ("モデル", whisper_model)):
        if not path.exists():
            print(f"{label}が見つかりません: {path}", file=sys.stderr)
            return 2

    try:
        written = transcribe(
            audio_path=args.audio,
            vocabulary_path=args.vocabulary,
            output_dir=args.output_dir,
            whisper_cli=whisper_cli,
            whisper_model=whisper_model,
            language=args.language,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
