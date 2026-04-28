# blog-pipeline

音声メモ起点のブログ執筆支援パイプラインのうち，仕組み部分を公開するためのリポジトリである．具体的には，文字起こし・素材取り込み・記事案生成・校閲・下書き投稿までの汎用スクリプトと， Claude Code の Skill ／ Subagent ひな形， textlint 設定の共有を目的とする．個人の文体プロファイルや原稿は別の Private リポジトリで管理し，本リポジトリには含めない．

## 📚 目次

- 🎯 リポジトリの位置づけ
- 🏛️ 全体像
- 📂 ディレクトリ構成
- 🛤️ 実装フェーズと現状
- 🔧 セットアップ
- 📜 ライセンス

## 🎯 リポジトリの位置づけ

本リポジトリは Public である．他の執筆者やエンジニアが同種の仕組みを構築する際の参考になる範囲のみを置く．

個人の文体や固有名詞辞書， Evernote の素材， 執筆中の原稿は Private リポジトリ側で扱う．これは個人情報と没ネタを Public に出さないための分離である．

## 🏛️ 全体像

人間が録音し，それ以降の工程は機械処理と Claude Code の Subagent ／ Skill で進める．完成稿は AtomPub で常に下書き投稿し，公開判断は人間がはてなブログ管理画面で行う．

詳細な設計と意思決定の経緯は，個人化リポジトリ側に置いた `system_design.md` に記述している．本リポジトリ側はその「再利用可能な部分」を提供する．

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

実装は 0 から 5 までの 6 フェーズで進める．現在はフェーズ 0 ，リポジトリ枠の作成段階にある．

表 2 フェーズと主な成果物

| フェーズ | 主な成果物 | 状態 |
|---|---|---|
| 0 | リポジトリ作成と初期構造 | 着手中 |
| 1 | 取り込みパイプライン（ `transcribe.py` ， `ingest_evernote.py` ） | 未着手 |
| 2 | 素材分析（ `note-summarizer` ， `propose-articles` ） | 未着手 |
| 3 | 執筆支援（ `article-drafter` ， `structure-note` ） | 未着手 |
| 4 | 校閲と公開（ textlint ， `draft-reviewer` ， `publish.py` ） | 未着手 |
| 5 | 辞書育成と CI 整備（ `build_dictionary.py` ） | 未着手 |

`.textlintrc.json` と `prh.yml` はフェーズ 4 で追加する予定であり，本フェーズには含まない．

## 🔧 セットアップ

各スクリプトはフェーズ 1 以降で実装する．現段階では空のディレクトリと .gitkeep のみが置かれている．

依存関係マネージャ（ `requirements.txt` 等）はスクリプト実装時に導入する．それまで Dependabot は GitHub Actions の ecosystem のみを対象とする．

## 📜 ライセンス

MIT License で公開する．詳細は [LICENSE](LICENSE) を参照すること．
