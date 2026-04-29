# blog-pipeline

音声メモ起点のブログ執筆支援パイプラインのうち，仕組み部分を OSS として公開するリポジトリである．素材取り込み・記事案生成・校閲・下書き投稿までの汎用スクリプトと，Claude Code の Skill ／ Subagent ひな形，textlint 設定の共有を目的とする．個人の文体プロファイル・固有名詞辞書・原稿は別の Private リポジトリで管理し，本リポジトリには含めない．

## 📚 目次

- 🎯 リポジトリの位置づけ
- 🏛️ 全体像
- 📂 ディレクトリ構成
- 🛤️ 実装フェーズと現状
- 🔧 セットアップ
- 🤝 開発に参加する
- 📜 ライセンス

## 🎯 リポジトリの位置づけ

本リポジトリは Public である．他の執筆者やエンジニアが同種の仕組みを構築する際の参考になる範囲のみを置く．

個人の文体・固有名詞辞書・ Evernote 素材・執筆中の原稿は Private 側で扱う．これは個人情報と没ネタを Public に出さないための分離である．

## 🏛️ 全体像

人間が Evernote で録音と内蔵文字起こしを済ませ，ENEX としてエクスポートしたものを起点とする．以降の工程はスクリプトと Claude Code の Subagent ／ Skill で進める．完成稿は AtomPub で常に下書き投稿し，公開判断は人間がはてなブログ管理画面で行う．

設計の詳細・パイプラインの図・意思決定の経緯は [ARCHITECTURE.md](ARCHITECTURE.md) を参照のこと．本 README ではリポジトリ利用に必要な範囲のみを扱う．

## 📂 ディレクトリ構成

表 1 ディレクトリの役割

| パス | 役割 |
|---|---|
| `scripts/` | 取り込み・解析・投稿の汎用スクリプト |
| `skill-templates/` | Claude Code Skill のひな形 |
| `agent-templates/` | Claude Code Subagent のひな形 |
| `examples/` | サンプル設定とサンプル入出力 |
| `.github/` | GitHub Actions と Dependabot 設定 |

## 🛤️ 実装フェーズと現状

実装は 0 から 5 までの 6 フェーズで進める．フェーズ 0 はクローズ済みで，現在はフェーズ 1（取り込み補助スクリプトと文字起こし校正）に着手している．各フェーズの進捗は GitHub Issue（`phase-N` ラベル）で追跡する．

表 2 フェーズと主な成果物

| フェーズ | 主な成果物 | 状態 |
|---|---|---|
| 0 | リポジトリ作成と初期構造，CLAUDE.md，ARCHITECTURE.md | 完了 |
| 1 | `parse_enex.py`，`agent-templates/transcript-corrector.md` | 実装中 |
| 2 | `note-summarizer`，`note-tagger`，`list_materials.py`，`propose-articles` | 未着手 |
| 3 | `article-proposer`，`article-drafter`，`structure-note`，`writing-style` ひな形 | 未着手 |
| 4 | `.textlintrc.json`，`prh.yml`，`.markdownlint-cli2.yaml`，`draft-reviewer`，`review-draft`，`publish.py` | 未着手 |
| 5 | `build_dictionary.py`，月次運用ドキュメント，CI ・ Skill チューニング | 未着手 |

`.textlintrc.json` ・ `prh.yml` ・ `.markdownlint-cli2.yaml` はフェーズ 4 で追加する．それまでは中央テンプレート（[tomio2480/github-workflows](https://github.com/tomio2480/github-workflows)）の標準設定が CI で適用される．

## 🔧 セットアップ

スクリプト本体は `scripts/` 配下にある．依存はサードパーティ非依存（標準ライブラリのみ）で実装するが，テストは `pytest` を使う．

### Python 環境

Python 3.11 以上が必要．以下のいずれかでテスト用依存を導入する．

```bash
# venv を使う場合
python -m venv .venv
source .venv/bin/activate          # Windows は .venv/Scripts/activate
pip install -e ".[dev]"

# pytest だけが必要であれば
pip install pytest
```

### `parse_enex.py` の使い方

ENEX ファイルを Markdown へ変換する．

```bash
python scripts/parse_enex.py path/to/export.enex --output-dir materials/raw
```

出力は 1 ノート 1 ファイルで，フロントマター付き Markdown となる．3 セクション構成（ 🗒️ 人間メモ ／ 🤖 Evernote AI 構造化情報 ／ 🗣️ 生の文字起こし）．ENEX 内の音声 base64 データは出力に含めない．

### テスト

```bash
pytest -v
```

合成 fixture（`tests/fixtures/sample.enex`）に基づくユニットテストが回る．Public リポジトリの fixture は個人情報を一切含まない合成データのみ．

### CI

CI は中央 composite action を呼び出す形で Markdown lint（`markdownlint` ・ `textlint` ・ `prh`）を回す．設定を上書きしたい場合は，リポジトリルートに `.markdownlint-cli2.yaml` ・ `.textlintrc.json` ・ `prh.yml` を置く．これらが中央設定より優先される（per-repo override）．Python テストの CI 化はフェーズ 5 で扱う．

## 🤝 開発に参加する

Issue や Pull Request は歓迎する．以下の方針に従ってほしい．

- Pull Request は Draft で作成し，レビューが整った段階で Ready for Review に切り替える
- テストは実装と同じ PR で追加する（TDD）
- 個人情報・実名・固有名詞辞書・原稿・録音データは絶対にコミットしない
- 中央 workflow ・テンプレートへの変更は別 PR で扱う

詳細な行動規範は [CLAUDE.md](CLAUDE.md)，設計の根拠は [ARCHITECTURE.md](ARCHITECTURE.md) を参照のこと．

## 📜 ライセンス

MIT License で公開する．詳細は [LICENSE](LICENSE) を参照すること．
