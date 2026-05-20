# blog-pipeline

音声メモ起点のブログ執筆支援パイプラインのうち，仕組み部分を OSS として公開するリポジトリである．素材取り込み・記事案生成・校閲・下書き投稿の汎用スクリプト，Claude Code の Skill／Subagent ひな形，textlint 設定を提供する．個人の文体プロファイル・固有名詞辞書・原稿は別の Private リポジトリで管理し，本リポジトリには含めない．

## 📚 目次

- 🎯 リポジトリの位置づけ
- 🏛️ 全体像
- 📂 ディレクトリ構成
- 🛤️ 実装フェーズと現状
- 🔧 セットアップ
- 🗓 運用手順
- 🤝 開発に参加する
- 📜 ライセンス

## 🎯 リポジトリの位置づけ

本リポジトリは Public である．他の執筆者やエンジニアが同種の仕組みを構築する際の参考になる範囲のみを置く．

個人の文体・固有名詞辞書・Evernote 素材・執筆中の原稿は Private 側で扱う．これは個人情報と没ネタを Public に出さないための分離である．

## 🏛️ 全体像

人間が Evernote で録音と内蔵文字起こしを済ませ，ENEX としてエクスポートしたものを起点とする．以降の工程はスクリプトと Claude Code の Subagent／Skill で進める．完成稿は AtomPub で常に下書き投稿し，公開判断は人間がはてなブログ管理画面で行う．

設計の詳細・パイプラインの図・意思決定の経緯は [ARCHITECTURE.md](ARCHITECTURE.md) を参照のこと．本 README ではリポジトリ利用に必要な範囲のみを扱う．

## 📂 ディレクトリ構成

表 1 ディレクトリの役割．

| パス | 役割 |
|---|---|
| `scripts/` | 取り込み・解析・投稿の汎用スクリプト |
| `skill-templates/` | Claude Code Skill のひな形 |
| `agent-templates/` | Claude Code Subagent のひな形 |
| `examples/` | サンプル設定とサンプル入出力 |
| `.github/` | GitHub Actions と Dependabot 設定 |

## 🛤️ 実装フェーズと現状

実装は 0 から 5 までの 6 フェーズで進める．フェーズ 0〜3 はクローズ済みである．各フェーズの進捗は GitHub Issue（`phase-N` ラベル）で追跡する．

表 2 フェーズと主な成果物．

| フェーズ | 主な成果物 | 状態 |
|---|---|---|
| 0 | リポジトリ作成と初期構造，CLAUDE.md，ARCHITECTURE.md | 完了 |
| 1 | `parse_enex.py`，`agent-templates/transcript-corrector.md` | 完了 |
| 2 | `note-summarizer`，`note-tagger`，`list_materials.py`，`propose-articles` | 完了 |
| 3 | `article-proposer`，`article-drafter`，`structure-note`，`writing-style` ひな形 | 完了 |
| 4 | lint 設定ファイル群，`draft-reviewer`，`review-draft`，`publish.py` | 完了 |
| 5 | `build_dictionary.py`，月次運用ドキュメント，CI・Skill チューニング | 完了 |

`.textlintrc.json`・`prh.yml`・`.markdownlint-cli2.yaml` はフェーズ 4 で追加する．それまでは中央テンプレート（[tomio2480/github-workflows](https://github.com/tomio2480/github-workflows)）の標準設定が CI で適用される．

## 🔧 セットアップ

スクリプト本体は `scripts/` 配下にある．
`parse_enex.py`・`list_materials.py`・`publish.py` は標準ライブラリのみで実装している．
`prompt-maker/generate_prompts.py` も同様である．
`build_dictionary.py` は形態素解析のため `janome` と `pyyaml` を使用する．
テストは `pytest` を使う．

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

### `generate_prompts.py` の使い方

Evernote AI に投入する構造化プロンプトを 3 段階分生成する．

```bash
python scripts/prompt-maker/generate_prompts.py "2026-05-21-セッション名"
```

セッション識別子を渡すと，同名のディレクトリへ 3 ファイルが生成される．

```
2026-05-21-セッション名/
├── 01_structure.md     # 文字起こし構造化プロンプト
├── 02_links.md         # リンク整理・提案プロンプト
└── 03_proper_nouns.md  # 固有名詞校閲プロンプト
```

生成したファイルを順に Evernote AI のチャットへ貼り付ける．
各段階は別チャットで実行することを推奨する（Evernote AI のチャット長制限を回避するため）．

詳細は `scripts/prompt-maker/README.md` を参照すること．

### `parse_enex.py` の使い方

ENEX ファイルを Markdown へ変換する．

```bash
python scripts/parse_enex.py path/to/export.enex --output-dir materials/raw
```

出力は 1 ノート 1 ファイルで，フロントマター付き Markdown となる．3 セクション構成（🗒️ 人間メモ／🤖 Evernote AI 構造化情報／🗣️ 生の文字起こし）．ENEX 内の音声 base64 データは出力に含めない．

### `build_dictionary.py` の使い方

`vocabulary/vocabulary.yml` を参照しながら Markdown ファイルを形態素解析し，未知語候補を抽出する．

```bash
# デフォルトのパスで実行（vocabulary/ と materials/raw/ が対象）
python scripts/build_dictionary.py

# パスを明示して実行
python scripts/build_dictionary.py \
  --vocab path/to/vocabulary.yml \
  --materials path/to/materials \
  --output path/to/candidates.yml
```

出力先（デフォルト: `vocabulary/candidates.yml`）は毎回上書きされる．git 管理は不要．
候補のレビューと `vocabulary.yml` への追記方法は `🗓 運用手順` の「月次辞書更新」節を参照のこと．

月次辞書更新では `materials/raw/` でなく `materials/corrected/` の使用を推奨する．
明示する場合は `--materials materials/corrected` を指定すること．

サンプルの `vocabulary.yml` は `examples/vocabulary.yml` を参照すること．

### `list_materials.py` の使い方

補正済み素材の一覧と要約・タグを JSON または Table 形式で取得する．

```bash
python scripts/list_materials.py materials/corrected/ --format json
python scripts/list_materials.py materials/corrected/ --format table
```

`propose-articles` Skill はこのコマンドで素材一覧を取得する．

### `publish.py` の使い方

ドラフトをはてなブログへ下書き投稿する．以下の環境変数を `.env` ファイルに設定すること．

| 変数名 | 説明 |
|---|---|
| `HATENA_USERNAME` | はてなユーザー名 |
| `HATENA_BLOG_ID` | ブログ ID（例：`yourname.hatenablog.com`） |
| `HATENA_API_KEY` | はてなブログ AtomPub API キー |

```bash
python scripts/publish.py drafts/2026-05-07-my-article.md
python scripts/publish.py drafts/2026-05-07-my-article.md --env-file /path/to/.env
```

常に下書きとして投稿する．公開判断ははてなブログ管理画面で人間が行う．

### テスト

```bash
pytest -v
```

合成 fixture（`tests/fixtures/sample.enex`）に基づくユニットテストが回る．Public リポジトリの fixture は個人情報を一切含まない合成データのみ．

### CI

CI は中央 composite action を呼び出す形で Markdown lint（`markdownlint`・`textlint`・`prh`）を回す．設定を上書きしたい場合は，リポジトリルートに `.markdownlint-cli2.yaml`・`.textlintrc.json`・`prh.yml` を置く．これらが中央設定より優先される（per-repo override）．Python テストの CI 化はフェーズ 5 で扱う．

## 🗓 運用手順

月次の辞書更新と，モデルの定期的なメンテナンス手順をまとめる．
Private リポジトリでは `materials/` や `docs/notes/` 等の個人データを `.gitignore` で除外すること．

### 月次辞書更新

月初め（毎月 1 日前後）に手動で実施する．

#### 実行手順

1. `python scripts/build_dictionary.py` を実行して `vocabulary/candidates.yml` を生成する．
2. `candidates.yml` を確認し，採用候補語を選別する（採用基準は後述）．
3. 採用語を `vocabulary/vocabulary.yml` の適切なカテゴリへ追記する．
   - `canonical` に正式表記，`aliases` に表記ゆれ，`note` に補足を記入する．
4. 変更を commit し，Draft PR として起票する．

#### 採用基準

以下の条件を満たす語を採用候補とする．

- **固有名詞**：製品名・サービス名・組織名・イベント名
- **技術用語**：プログラミング言語・ライブラリ・ツール名・概念語
- **出現頻度**：同一の表記が 2 件以上のソースに出現するものを優先する．4 件以上は積極採用の目安とする．
- **誤認識リスク**：`transcript-corrector` が誤変換しやすい語は 1 件でも採用を検討する．

以下は採用しない．

- 一般的な日本語名詞（「情報」「改善」「構成」など）
- 文脈なしには固有名詞か判断できない語
- `vocabulary.yml` に登録済みの語

#### 実施記録

採用・不採用の判断と理由を `docs/notes/YYYY-MM-dict-update.md` に記録する．更新不要な月は「更新不要と判断」の一行でよい．

### Subagent モデルの世代交代

Claude のモデルは定期的に世代が更新される．新世代が安定したら Subagent の指定モデルを変更する．

Private リポジトリの `.claude/agents/` 配下に配置した各 Subagent 定義ファイルの
`model:` フィールドを更新する．`agent-templates/*.md` がひな形である．
最新のモデル名は [Anthropic Models overview](https://docs.claude.com/en/docs/about-claude/models/overview) を参照する．

### 文体プロファイルの劣化検知

文体は時間とともに変化する．古いプロファイルに引きずられると出力品質が低下するため，
年 1 回程度を目安に `style-profile.md` を見直す．
更新は執筆者の明示指示で起動する（自動更新は採用しない）．

## 🤝 開発に参加する

Issue や Pull Request は歓迎する．以下の方針に従ってほしい．

- Pull Request は Draft で作成し，レビューが整った段階で Ready for Review に切り替える
- テストは実装と同じ PR で追加する（TDD）
- 個人情報・実名・固有名詞辞書・原稿・録音データは絶対にコミットしない
- 中央 workflow・テンプレートへの変更は別 PR で扱う

詳細な行動規範は [CLAUDE.md](CLAUDE.md)，設計の根拠は [ARCHITECTURE.md](ARCHITECTURE.md) を参照のこと．

## 📜 ライセンス

MIT License で公開する．詳細は [LICENSE](LICENSE) を参照すること．
