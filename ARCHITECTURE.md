# Architecture

本ドキュメントは `blog-pipeline` の全体設計を記す．音声メモを起点としたブログ執筆支援システムにおける，再利用可能な汎用部分の役割と構造を定義する．個人化された素材・原稿・固有名詞辞書は別の Private リポジトリで扱う前提とする．

## 📚 目次

- 🎯 目的
- 🏛️ 全体パイプライン
- 📂 リポジトリ構成と提供物
- 🤖 Subagent と Skill の設計
- 🛤️ 段階的実装フェーズ
- 🔐 取り扱い方針
- 📖 用語集

## 🎯 目的

執筆者が音声メモを録音してから， はてなブログへ下書き投稿するまでの一連の流れを Claude Code の Subagent と Skill で支援する．本リポジトリはこの流れの中で OSS として再利用できる部分を提供する．

達成したいゴールは以下のとおり．

- 録音から下書き投稿までを少ない手数で進められること
- 文体や固有名詞の癖を保ったまま生成できること
- 機械校正と内容レビューの両方が走ること
- 公開判断は人間が必ず行うこと
- 既存契約以外の追加課金を発生させないこと

非ゴールは以下のとおり．

- 自動公開機能は実装しない
- 多人数執筆や共同編集は対象外
- Evernote 以外のソース（Notion ・ Obsidian 等）からの取り込みは対象外
- 商用展開は想定しない

## 🏛️ 全体パイプライン

執筆者（人間）は録音と Evernote から ENEX を取り出すまでの橋渡し， および公開判断を担当する．それ以外の工程はスクリプトと Claude Code の Subagent ・ Skill で処理する．

図 1 全体構成（左が入力， 右が出力）

```
[人間 録音 + Evernote 添付]
    ↓
[Evernote 内蔵文字起こし + Evernote AI 構造化]
    ↓
[人間 ENEX エクスポート]
    ↓
[parse_enex.py]  ENML → Markdown，メタ情報抽出
    ↓
[materials/raw/*.md]
    ↓
[Claude Code Opus（手動トリガー）]
    ├── [transcript-corrector Subagent]  固有名詞辞書で校正
    ├── [Haiku Subagent]                 要約・タグ付け（並列）
    ├── [Sonnet Subagent]                記事案・本文ドラフト
    └── [Opus 本体]                       全体方針・最終レビュー
    ↓
[materials/corrected/*.md]
    ↓
[textlint + prh]  機械校正
    ↓
[Markdown ドラフト]
    ↓
[はてなブログ AtomPub]  常に下書きとして投稿
    ↓
[人間 公開判断]
```

文字起こしは Evernote 内蔵の機能と Evernote AI の構造化結果を利用する．素材は ENEX エクスポートで人間がリポジトリに橋渡しする．これにより whisper.cpp や Evernote API への依存を排し， 利用者の準備コストを最小化する．

## 📂 リポジトリ構成と提供物

```
blog-pipeline/
├─ scripts/
│  ├─ parse_enex.py           ENEX → Markdown（フロントマター付き）
│  ├─ list_materials.py       素材一覧の取得
│  ├─ build_dictionary.py     形態素解析で固有名詞辞書を更新
│  └─ publish.py              AtomPub 投稿（常に下書き）
├─ skill-templates/
│  ├─ writing-style/          文体プロファイルを参照する Skill ひな形
│  ├─ propose-articles/       テーマ横断の記事案生成 Skill ひな形
│  ├─ structure-note/         ノート構造化 Skill ひな形
│  └─ review-draft/           レビュー Skill ひな形
├─ agent-templates/
│  ├─ transcript-corrector.md  Sonnet または Haiku Subagent
│  ├─ note-summarizer.md       Haiku Subagent
│  ├─ note-tagger.md           Haiku Subagent
│  ├─ article-proposer.md      Sonnet Subagent
│  ├─ article-drafter.md       Sonnet Subagent
│  └─ draft-reviewer.md        Sonnet または Opus Subagent
├─ examples/                  サンプル設定とサンプル入出力
├─ .textlintrc.json           textlint 設定（Phase 4 で追加予定）
├─ prh.yml                    prh 辞書（Phase 4 で追加予定）
├─ .markdownlint-cli2.yaml    markdownlint 設定（Phase 4 で追加予定）
├─ LICENSE                    MIT
└─ README.md
```

## 🤖 Subagent と Skill の設計

判断軸は 3 つある．

- 出力が決定論的か（同じ入力で同じ出力になるか）
- 文脈理解が必要か（前後関係や暗黙知を読む必要があるか）
- 人間との対話が前提か

表 1 工程別の担当．

| 工程 | 担当 | モデル | 理由 |
|---|---|---|---|
| 音声録音と Evernote 添付 | 人間 | - | 既存習慣に載せる |
| 文字起こしと構造化 | Evernote 内蔵 + Evernote AI | - | サードパーティサービスに委譲 |
| ENEX エクスポート | 人間 | - | API 申請を回避するための橋渡し |
| ENML → Markdown 変換 | スクリプト（`parse_enex.py`）| - | 決定論的 |
| 文字起こし校正（固有名詞補正）| Subagent | Sonnet または Haiku | 辞書照合と文脈判断のミックス |
| 形態素解析・辞書構築 | スクリプト | - | 決定論的 |
| ノート要約（200 字）| Subagent | Haiku | 量が多く単純判断 |
| タグ推定 | Subagent | Haiku | 量が多く単純判断 |
| 記事案クラスタリング | Skill 内 | Sonnet または Opus | 文脈横断と判断 |
| 章立て | Subagent | Sonnet | 整合性判断が必要 |
| 本文ドラフト作成 | Subagent | Sonnet | 文体判断が必要 |
| textlint | スクリプト | - | 決定論的 |
| 内容レビュー | Subagent | Sonnet または Opus | 論旨判断が必要 |
| 全体方針調整 | Opus 本体 | Opus | 設計判断 |
| 投稿前の最終確認 | Opus 本体 | Opus | 人間との対話前提 |

Skill はオーケストレーション役， Subagent は個別タスクの実行役とする．たとえば `propose-articles` Skill のなかでは次の流れを書く．利用者の素材ディレクトリ配下のファイルを `note-summarizer` Subagent に並列で渡し， 戻った要約をメイン会話の Opus がクラスタリングする．

## 🛤️ 段階的実装フェーズ

実装は 0 から 5 までの 6 フェーズで進める．本リポジトリで提供する成果物の範囲を以下に示す．

| フェーズ | 提供する成果物 | 状態 |
|---|---|---|
| 0 | リポジトリ作成と初期構造，CLAUDE.md ， ARCHITECTURE.md ， md-lint workflow ， Dependabot | 着手中 |
| 1 | `parse_enex.py` ， `agent-templates/transcript-corrector.md` ， `materials/raw/` `materials/corrected/` の運用ガイド | 未着手 |
| 2 | `agent-templates/note-summarizer.md` ， `agent-templates/note-tagger.md` ， `list_materials.py` ， `skill-templates/propose-articles/` | 未着手 |
| 3 | `agent-templates/article-proposer.md` ， `agent-templates/article-drafter.md` ， `skill-templates/structure-note/` ， `skill-templates/writing-style/` のひな形 | 未着手 |
| 4 | `.textlintrc.json` ， `prh.yml` ， `.markdownlint-cli2.yaml` の汎用設定， `agent-templates/draft-reviewer.md` ， `skill-templates/review-draft/` ， `publish.py` | 未着手 |
| 5 | `build_dictionary.py` ， 月次運用のドキュメント， CI ・ Skill チューニング | 未着手 |

各フェーズは GitHub Issue（`phase-N` ラベル）で管理する．フェーズ間で依存があれば Issue 本文に明記する．

## 🔐 取り扱い方針

本リポジトリは Public であるため， 以下を絶対に守る．

- 個人情報・実名・固有名詞辞書・原稿・録音データを含めない
- API キー・トークンを含めない
- 利用者の Private リポジトリの存在を具体名で書かない（「個人化版」 や「Private リポジトリ」 など汎用呼称を使う）
- `publish.py` には公開フラグを持たせず ， AtomPub の draft 指定をハードコードする
- 中央 workflow（`tomio2480/github-workflows`）への変更は別 PR で扱う

## 📖 用語集

表 2 主要な用語．

| 用語 | 説明 |
|---|---|
| ENEX | Evernote の公式エクスポート形式．XML ベースで， ENML 本文と添付，タグを内包する |
| ENML | Evernote 独自のノート記法．XML ベース |
| Evernote AI | Evernote 内蔵の AI 機能．文字起こしと構造化（要点抽出，補足情報の URL 付与等）を提供 |
| AtomPub | はてなブログ公式の投稿用 API．WSSE 認証 |
| Subagent | Claude Code が提供する，独立コンテキストで動く別エージェント |
| Skill | Claude Code が提供する，特定タスク用の常設指示と実装 |
| Opus | Claude のフラッグシップモデル．本システムでは司令塔 |
| Sonnet | Claude の中位モデル．本文ドラフトとレビューを担当 |
| Haiku | Claude の軽量モデル．要約とタグ付けを担当 |
| textlint | JavaScript 製の校正ツール．日本語ルール群が豊富 |
| prh | Proofreading Helper．用語ゆれを統一する textlint プラグイン |
| WSSE 認証 | XML を用いた認証方式．はてなブログ AtomPub で使用 |
