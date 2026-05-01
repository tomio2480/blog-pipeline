---
name: propose-articles
description: 補正済み素材から並列要約とタグ推定を経て，テーマ横断の記事案候補を生成するモード A のオーケストレーション Skill ひな形
---

# propose-articles

`materials/corrected/` 配下の素材群を入力に取る Skill である．テーマ横断の記事案候補を `proposals/candidates/` 配下へ書き出す．設計書「第 2 段：記事案生成」のモード A に対応する．

本ファイルは Public リポジトリの **ひな形** である．利用者は個人化版を Private リポジトリの `.claude/skills/propose-articles/SKILL.md` へコピーする．固有名詞辞書連携や Issue テンプレートを差し込む前提とする．

## 役割

Skill はオーケストレーション役である．個別の要約とタグ推定は `note-summarizer` ／ `note-tagger` Subagent に委譲する．戻った要約一覧はメイン会話の Opus がクラスタリングする．素材数が増えた場合のレート制限ハンドリングも本 Skill 内で扱う．

## 入力

- `materials/corrected/` 配下の `<YYYY-MM-DD>-<note_title>.md`（補正済み素材）
- 同階層の `<YYYY-MM-DD>-<note_title>.summary.yml`（要約・タグのサイドカー．存在しない場合は本 Skill 内で生成）

## 出力

- `proposals/candidates/<YYYY-MM-DD>-<候補名>.md`
- 各候補ファイルは以下のフロントマター付き Markdown とする

```yaml
---
proposed_at: "2026-05-01"
status: candidate
source_materials:
  - 2026-04-28-架空イベント登壇メモ.md
  - 2026-04-29-別の素材.md
themes:
  - テーマ A
  - テーマ B
---

# 仮タイトル

200〜400 字程度の概要．素材から導かれる記事の方向性を示す．
```

`status: candidate` は採用前の候補を示す．人間が採用を判断したのち，Issue として起票し，採用後に `proposals/<採用名>.md` へ昇格する．昇格時は `status: adopted` に書き換える．

## モード A の流れ

### 1. 素材一覧の取得

`scripts/list_materials.py` を実行する．補正済み素材の frontmatter と既存の `.summary.yml` をマージした JSON が取得できる．

```bash
python scripts/list_materials.py materials/corrected/ --format json
```

返ってきた JSON は以下の構造である．

- `note_title`：元ノートのタイトル
- `tags`：Evernote 由来のタグ
- `created`：元ノートの作成日時
- `summary`：既存の要約（無い場合は空文字列）
- `auto_tags`：既存の自動推定タグ（無い場合は空配列）

### 2. 要約・タグ推定の補完

`summary` または `auto_tags` が欠損している素材を抽出する．欠損がある場合は `note-summarizer` ／ `note-tagger` Subagent を **並列で起動** する．並列度の既定は 5 件以下．

並列実行は次の順で行う．

1. 欠損リストを抽出する
2. `note-summarizer` を欠損数の上限 5 件分まで並列起動．戻った結果で `<file>.summary.yml` の `summary` を更新
3. `note-tagger` も同様に並列起動．`auto_tags` を更新
4. 残りがあれば次のバッチを起動

### 3. クラスタリング

要約一覧をメイン会話の Opus が読み，テーマ横断のクラスタを抽出する．クラスタリングは Subagent には委譲しない．文脈横断の判断と全体方針調整はメインの Opus 本体が担う．

クラスタの目安．

- 1 クラスタにつき 2〜5 件の素材
- 全体で 2〜5 クラスタ
- 1 件の素材だけで成立するクラスタは原則作らない（モード B の対象．フェーズ 3 で扱う）

### 4. 候補ファイルの書き出し

クラスタごとに `proposals/candidates/<YYYY-MM-DD>-<候補名>.md` を書き出す．候補名はクラスタの主題から決め，ファイル名は Windows 互換のサニタイズを通す．

候補ファイルの本文は次の構造とする．

- 仮タイトル（h1）
- 200〜400 字程度の概要
- 「想定する読者」「主要なトピック」「補足情報」のサブ見出しを必要に応じて追加

## レート制限の扱い

Subagent はメイン契約のレート制限を消費する．並列度を上げるとレート制限ヒットのリスクがある．

- 既定の並列度：**5 件以下**
- レート制限ヒット時：**順次実行へ縮退** する．具体的には並列度を 1 に下げて再実行
- 30 件を超える素材を扱う場合：5 件ずつのバッチで順次起動．バッチ間に短い間隔を空ける

並列度はカスタマイズ可能な値として個人化版で上書きできる．

## やらないこと

- **GitHub Issue の自動起票は行わない** ．`gh issue create` の実行は人間判断とする
- 採用案の `proposals/` 直下への昇格は人間操作とする．Skill は `proposals/candidates/` までを担当する
- 既存の `.summary.yml` の上書き．要約・タグが既に存在する素材は再生成しない（冪等性確保）
- クラスタリング結果の自動公開．クラスタ結果はメイン会話に返し，候補ファイルとして `proposals/candidates/` に保存するに留める

## Issue 起票の手順（人間が実施）

候補が出た後の手順は次の通り．

1. `proposals/candidates/<候補名>.md` を人間がレビューする
2. 採用したい候補について `gh issue create` で Issue を起票する．タイトルは仮タイトルを流用する
3. Issue 上で詳細を詰める
4. 採用が決まったら候補ファイルを `proposals/<採用名>.md` へ移動し，`status: adopted` に書き換える
5. 採用されなかった候補は `proposals/candidates/` に残し，後の参照素材とする

Public 側は本 Skill のひな形として手順までを記述する．Issue テンプレートやコマンド例は個人化版（Private）で具体化する．

## 利用者がカスタマイズする箇所

- `vocabulary.yml` 連携．固有名詞辞書を踏まえてクラスタリング判断を行う
- Issue テンプレートの参照．`gh issue create --template=...` で記事案用テンプレートを使う
- 並列度の調整．素材数や個人契約のレート制限に合わせて変える
- 候補名の命名規則．日本語タイトルか英数字スラッグかなど

利用者カスタマイズは Private リポジトリ側の Skill ファイルに記載する．Public 側の本ひな形には個人色を含めない．
