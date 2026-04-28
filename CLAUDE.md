# CLAUDE.md

本ファイルは `blog-pipeline` リポジトリでの Claude Code の常設指示である．本リポジトリは Public な OSS であり，再利用可能な汎用部分のみを集約する．個人情報・固有名詞辞書・原稿は **絶対に** コミットしない．

## 📚 目次

- 🎯 本リポジトリの位置づけ
- 🚦 行動原則
- 🤖 担当の切り分け
- 🛠️ 開発の進め方
- 📑 参照ドキュメント

## 🎯 本リポジトリの位置づけ

音声メモを起点としたブログ執筆支援システムのうち，他者にも再利用可能な汎用部分を OSS として公開する．具体的には以下を提供する．

- 取り込み・解析・投稿の汎用スクリプト（ENEX パース，AtomPub 投稿等）
- Claude Code の Subagent ／ Skill のひな形
- textlint と prh の標準設定（中央テンプレートを起点としたカスタマイズ可能）

利用者は本リポジトリをフォークまたは clone のうえ，個人化版（文体プロファイル・固有名詞辞書・原稿）を別の Private リポジトリで持つ運用を想定する．

設計の全体像と意思決定の経緯は [ARCHITECTURE.md](ARCHITECTURE.md) に記す．本ファイルは行動原則のみを扱う．

## 🚦 行動原則

`github-dev` Skill の方針を踏襲する．以下を絶対に守る．

- `git push` は明示的な指示があるまで行わない
- Pull Request は必ず Draft で作成する
- GitHub Actions の権限設定は最小権限を原則とする
- リポジトリには個人情報・実名・固有名詞辞書・原稿・録音データを **絶対に** 含めない
- API キー・トークンはコミットしない
- `publish.py` には公開フラグを持たせない（常に下書き）
- 中央 workflow ・テンプレート（`tomio2480/github-workflows`）を変更する場合は別 PR で扱う

利用者側の Private リポジトリは README やコミットメッセージで具体名を出さず，「個人化版」「Private リポジトリ」といった汎用呼称で参照する．

## 🤖 担当の切り分け

[ARCHITECTURE.md](ARCHITECTURE.md) の「Subagent と Skill の設計」を踏襲する．要点は以下のとおり．

- 機械的処理（ENEX パース，形態素解析，textlint）はスクリプト
- 量の多い単純判断（要約，タグ推定）は Haiku Subagent
- 章立て・本文ドラフト・内容レビューは Sonnet Subagent
- 文脈横断のクラスタリング・全体方針調整・最終確認はメイン会話の Opus 本体

モデル指定は本ファイルおよび各 Subagent ひな形ファイル（`agent-templates/*.md`）で行い，世代交代に追随できる構造を保つ．

## 🛠️ 開発の進め方

### 着手前

- 関連 Issue を確認し，何を作ろうとしているか明確にする
- フェーズ単位で区切り，1 PR で複数フェーズを完走させない
- 機能追加には対応するテストを先に書く（TDD，`code-quality` Skill 参照）

### 実装中

- コミットは端的なメッセージで小刻みに
- ライブラリ追加時は公式情報を確認し最新安定版を採用
- README やドキュメントとの整合を崩さない

### push 直前

- セルフコードレビューを必ず実施（`github-dev` Skill 参照）
- デバッグ残骸・コメントアウト・個人情報混入の有無を確認
- TDD 順序（テストが先）を満たしているか確認

### PR 作成時

- 必ず Draft で作成
- 関連 Issue を Closes 等で参照
- 変更が利用者影響を持つ場合は README ・ ARCHITECTURE.md の更新も同 PR に含める

## 📑 参照ドキュメント

- [ARCHITECTURE.md](ARCHITECTURE.md) ：全体設計とパイプラインの説明
- [README.md](README.md) ：リポジトリ概要と利用方法
- [LICENSE](LICENSE) ：MIT License

`~/.claude/skills/` 配下の `github-dev`，`code-quality`，`docs-quality` も状況に応じて参照すること．
