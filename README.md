# blog-pipeline

音声メモ起点のブログ執筆支援パイプラインのうち，仕組み部分を OSS として公開するリポジトリである．素材取り込み・記事案生成・校閲・下書き投稿の汎用スクリプト，Claude Code の Skill／Subagent ひな形，textlint 設定を提供する．個人の文体プロファイル・固有名詞辞書・原稿は別の Private リポジトリで管理し，本リポジトリには含めない．

## 📚 目次

- 🎯 リポジトリの位置づけ
- 🗂️ 個人化版リポジトリの推奨構造
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

## 🗂️ 個人化版リポジトリの推奨構造

本リポジトリは仕組み（スクリプト・テンプレート・ひな形）を提供し，生成物・素材・原稿などのデータは個人化版（Private）リポジトリへ寄せる．両者を兄弟ディレクトリとして並べ，CLI は個人化版の作業ディレクトリから相対的に呼び出す運用とする．本書ではこの運用を D2 と呼ぶ．

この分離により，`session_id` にイベント名や人名などの固有名詞が含まれても，生成物が Public リポジトリへ混入する事故を防ぐ．防御線として本リポジトリの `.gitignore` は，先頭が 4 桁数字のトップレベルディレクトリを除外する．

個人化版の推奨構造を図 1 に示す．

```
個人化版/
├─ prompts/        prompt-maker の出力（非推奨．設計経緯の参照用）
├─ materials/      build_material.py の生成物（raw/）と校正後（corrected/）
├─ drafts/         article-drafter の出力
├─ vocabulary/     固有名詞辞書
├─ style-profile/  文体プロファイル
└─ .claude/
   ├─ agents/      本リポジトリからコピーしたサブエージェント
   └─ skills/      本リポジトリからコピーしたスキル
```

図 1 個人化版リポジトリの推奨ディレクトリ構造．仕組みを本リポジトリから参照しつつデータを個人化版側へ集約する．

具体的な呼び出し方法は [ARCHITECTURE.md](ARCHITECTURE.md) の「個人化版リポジトリとの分離運用」を参照のこと．

## 🏛️ 全体像

人間が録音した音声を起点とする．音声は `whisper.cpp` で文字起こしする．これと人が手書きした人間メモを `build_material.py` が素材へまとめる．以降の工程はスクリプトと Claude Code の Subagent／Skill で進める．完成稿は AtomPub で常に下書き投稿し，公開判断は人間がはてなブログ管理画面で行う．

旧来の Evernote／ENEX 経路は非推奨とする．`parse_enex.py` は既存素材の変換用に残置する．

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

実装は 0 から 7 までの 8 フェーズで進める．全フェーズがクローズ済みである．各フェーズの進捗は GitHub Issue（`phase-N` ラベル）で追跡する．

表 2 フェーズと主な成果物．

| フェーズ | 主な成果物 | 状態 |
|---|---|---|
| 0 | リポジトリ作成と初期構造，CLAUDE.md，ARCHITECTURE.md | 完了 |
| 1 | `parse_enex.py`，`agent-templates/transcript-corrector.md` | 完了 |
| 2 | `note-summarizer`，`note-tagger`，`list_materials.py`，`propose-articles` | 完了 |
| 3 | `article-proposer`，`article-drafter`，`structure-note`，`writing-style` ひな形 | 完了 |
| 4 | lint 設定ファイル群，`draft-reviewer`，`review-draft`，`publish.py` | 完了 |
| 5 | `build_dictionary.py`，月次運用ドキュメント，CI・Skill チューニング | 完了 |
| 6 | `parse_enex.py` の 2 セクション化，`prompt-maker/` の非推奨化（Evernote AI 連携廃止），STT パイロット | 完了 |
| 7 | `transcribe_audio.py`，`build_material.py`，`parse_enex.py` の非推奨化（Evernote 廃止・音声直接取り込み経路） | 完了 |

`.textlintrc.json`・`prh.yml`・`.markdownlint-cli2.yaml` はフェーズ 4 で追加する．それまでは中央テンプレート（[tomio2480/github-workflows](https://github.com/tomio2480/github-workflows)）の標準設定が CI で適用される．

## 🔧 セットアップ

スクリプト本体は `scripts/` 配下にある．
`parse_enex.py`・`list_materials.py`・`publish.py` は標準ライブラリのみで実装している．
`prompt-maker/generate_prompts.py` も同様である．
`build_dictionary.py` は形態素解析のため `janome` と `pyyaml` を使用する．
`build_material.py` は人間メモのフロントマター解析のため `pyyaml` を使用する．
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

### `generate_prompts.py` の使い方（非推奨）

> **非推奨．** 2026-06-12 の設計見直しで Evernote AI 構造化を廃止したため，
> 本スクリプトは使用しない．詳細は `scripts/prompt-maker/README.md` を参照すること．

Evernote AI に投入する構造化プロンプトを 3 段階分生成する CLI である．
スクリプトとテンプレートは設計経緯の参照のため残置する．

### `parse_enex.py` の使い方

> **非推奨．** Evernote の利用停止（2026-06-13）に伴い ENEX 取り込みは廃止した．
> 新規素材は `build_material.py` で生成する．本スクリプトは既存 ENEX 素材の変換用に残置する．

ENEX ファイルを Markdown へ変換する．

```bash
python scripts/parse_enex.py path/to/export.enex --output-dir materials/raw
```

出力は 1 ノート 1 ファイルで，フロントマター付き Markdown となる．
原則 2 セクション構成（🗒️ 人間メモ／🗣️ 生の文字起こし）で出力する．
`<h1>` を含む旧ノートは互換として
🤖 Evernote AI 構造化情報セクションを人間メモと生の文字起こしの間に追加出力する（3 セクション構成）．
ENEX 内の音声 base64 データは出力に含めない．

### `transcribe_audio.py` の使い方

録音音声を `whisper.cpp` で文字起こしし，生の文字起こしテキストを出力する．
フェーズ 7 で新設した音声直接取り込み経路の文字起こし工程を担う．
`ffmpeg` で 16kHz モノラル WAV へ変換した上で `whisper.cpp` の `large-v3` を実行する．

`whisper.cpp` のバイナリとモデルは環境依存のため，パスを環境変数で渡す．
未設定なら明示エラーで停止する．

```bash
export WHISPER_CLI_PATH=/path/to/whisper-cli
export WHISPER_MODEL_PATH=/path/to/ggml-large-v3.bin
python scripts/transcribe_audio.py \
  --audio path/to/2026-04-28-録音名.m4a \
  --vocabulary path/to/vocabulary.yml \
  --output-dir .scratch/transcription
```

ループ対策として `-mc 0`（直前文脈の持ち越し無効化）を標準化する．
`vocabulary.yml` の canonical 語を `--prompt`（初期プロンプト）へ注入し，固有名詞の正答率を補助する．
ただし初期プロンプトは soft hint であり，誤認識の残りは後段の `transcript-corrector` で補正する前提とする．
入力音声と中間 WAV，生の文字起こしは再生成できるため `.scratch/` 配下など Git 管理外へ出力する．
`ffmpeg` は PATH 上にある前提とする．

### `build_material.py` の使い方

録音音声から得た生の文字起こしと，人が手書きした人間メモ Markdown を 1 つの素材へまとめる．
フェーズ 7 で新設した音声直接取り込み経路の素材生成を担う．

```bash
python scripts/build_material.py \
  --memo path/to/2026-04-28-録音名.md \
  --transcription path/to/transcript.txt \
  --output-dir materials/raw
```

出力は `parse_enex.py` と同一の 2 セクション構成（🗒️ 人間メモ／🗣️ 生の文字起こし）となる．
`note_title` と `created` は人間メモのファイル名 stem から導出する．
人間メモがフロントマターを持つ場合は `tags` 等を引き継ぐ．
フロントマターの `source` は `audio` で固定する．

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

常に下書きとして投稿する（`<app:draft>yes</app:draft>` をハードコード）．公開判断ははてなブログ管理画面で人間が行う．

複数ファイルをまとめて送れる．送信メソッドは frontmatter の `hatena_entry_id` を主キーに自動判定する．

- `hatena_entry_id` あり：既存下書きの更新 `PUT`（常に ID 指定）．未公開の下書きを再送する用途．
- `hatena_entry_id` なし：新規 `POST`．成功時に entry ID をクォート付きで frontmatter へ書き戻す．
- `hatena_published: true`：公開後ははてな側を真とするため，自動送信を拒否する（安全ガード）．

新規 `POST` の前に，正規化タイトル（空白無視）一致の既存下書きがあれば抑止する．タイトル変更による重複作成を防ぐためであり，意図的な新規作成は `--force-new` を付ける．

frontmatter の `categories` を読み，はてなのカテゴリーとして `<category term="...">` で送る．記述は配列とする．インラインフロー（`categories: [PHP, コミュニティ]`）とブロック形式（`- PHP` の各行）に対応する．空・未指定なら付けない．重複は順序を保って除く．推奨上限は 10 件で，超えると警告する（送信自体は妨げない）．`PUT` 更新でも毎回送り，はてな側を上書きする．本文からの選定は個人化版リポジトリ側の役割とし，本スクリプトは送信機構のみを担う．

`--sync` は送信せず，はてな側のエントリ一覧を取得して正規化タイトル一致で `hatena_entry_id` を frontmatter へ記録する．送信済みだが ID 未記録の下書きを更新可能にするための回収に使う．同名（空白無視）が複数あれば取り違えを避けて記録しない．

```bash
python scripts/publish.py drafts/*.md --sync
```

`--verify` は送信せず，各ドラフトの `hatena_entry_id` をメンバー `GET`（200／404）で検証する．コレクションフィードは結果整合で取りこぼすため，存在確認はメンバー `GET`（`/atom/entry/{id}`）を正本とする．

```bash
python scripts/publish.py drafts/*.md --verify
```

欠落（404）や通信エラーが 1 件でもあれば終了コード 1 で終わるため，CI で検証失敗を検知できる．`hatena_entry_id` 未設定は未送信・未回収の通常状態とみなし，失敗には数えない．

`--list-categories` は送信せず，はてな側の既存カテゴリー term 一覧を 1 行 1 件で標準出力へ出す．本文からのカテゴリー選定（個人化版リポジトリ側のオーケストレーション）が，既存カテゴリーを優先する入力として読み取る窓口である．ドラフトファイルは取らない．他のモード指定（`--sync`／`--verify`）とは併用できない．

```bash
python scripts/publish.py --list-categories
```

#### 本文への画像設置

送信前に本文の標準 Markdown 画像記法 `![alt](path "caption")` を処理する．ローカル相対パスの画像はフォトライフへ上げて f:id 記法へ置換する．外部 URL（`https://...`）の画像は上げずに `<img>` でそのまま参照する．いずれも `<figure>` / `<figcaption>` で包む．`alt` は必須とし，欠落はエラーとする．

オーサリング規約は次のとおり．

- 本文に `![alt](相対パス "caption")` を書く．`caption` は省略可とし，省略時は `<figcaption>` を付けない．
- 画像ファイルはリポジトリ内（例：`assets/`）へ置き，本文からは相対パスで参照する．相対パスはドラフトファイルの位置を起点に解決する．
- 既に Web 上にある画像は外部 URL でそのまま参照し，アップロード対象外とする．
- f:id 記法の `alt` はコロン（`:`）と閉じ括弧（`]`）を区切りに使うため，これらを `alt` に含めるとエラーとする．

`--upload-map` に JSON パスを渡すと，画像内容のハッシュをキーに記録し，同一画像の再アップロードを抑止する（既定では記録しない）．

```bash
python scripts/publish.py drafts/2026-05-07-my-article.md --upload-map .upload_map.json
```

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
