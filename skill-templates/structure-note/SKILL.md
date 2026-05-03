---
name: structure-note
description: 採用済み記事案または補正済み素材から本文ドラフトを生成するモード B のオーケストレーション Skill ひな形
---

# structure-note

`proposals/` 配下の採用済み記事案または `materials/corrected/` 配下の補正済み素材を入力に取る Skill である．`article-proposer`／`article-drafter` Subagent を順次起動し，`drafts/` 配下へ本文ドラフトを書き出す．設計書「第 2 段：記事案生成」のモード B（ノート構造化）に対応する．

本ファイルは Public リポジトリの **ひな形** である．利用者は個人化版を Private リポジトリの `.claude/skills/structure-note/SKILL.md` へコピーする．`style-profile.md` の参照パスや個別ドメインルールを差し込む前提とする．

## 役割

Skill はオーケストレーション役である．章立て生成は `article-proposer` Subagent に委譲する．本文ドラフト生成は `article-drafter` Subagent に委譲する．章立てのレビューは人間が行い，承認を得てから次工程へ進む．

## 入力

以下のいずれかを指定する．

- 採用済み記事案：`proposals/<採用名>.md`（`status: adopted`）
- 補正済み素材：`materials/corrected/<YYYY-MM-DD>-<note_title>.md`

複数素材から 1 記事を作る場合は採用済み記事案の `source_materials` フィールドで複数ファイルを束ねる．

## 出力

- 章立てファイル：`drafts/<YYYY-MM-DD>-<slug>-outline.md`
- 本文ドラフト：`drafts/<YYYY-MM-DD>-<slug>.md`

`slug` は仮タイトルから Windows 互換サニタイズを通した文字列とする．

## モード B の流れ

### 1. 入力の確認

入力ファイルを確認する．採用済み記事案の場合は `status: adopted` であることを確認する．補正済み素材を直接指定する場合は `materials/corrected/` 配下であることを確認する．いずれの条件も満たさない場合は人間に確認を求めて停止する．

### 2. 章立て生成

`article-proposer` Subagent を起動する．

```text
subagent_type: "article-proposer"
入力：[ファイルパス]
```

`article-proposer` が `drafts/<YYYY-MM-DD>-<slug>-outline.md` を書き出す．

### 3. 人間によるレビュー

**生成した章立てを人間に提示し，確認を得てから次工程に進む．** 章立てを修正したい場合は修正指示を受けて `article-proposer` を再起動するか，直接ファイルを編集する．承認を得たら次工程へ進む．

人間のレビューなしに `article-drafter` を起動しない．

### 4. 本文ドラフト生成

`article-drafter` Subagent を起動する．

```text
subagent_type: "article-drafter"
章立て：drafts/<YYYY-MM-DD>-<slug>-outline.md
素材：[元のファイルパス]
```

`article-drafter` が `drafts/<YYYY-MM-DD>-<slug>.md` を書き出す．

### 5. 完了通知

本文ドラフトが生成されたことをメイン会話に報告する．次の工程は textlint による機械校正と `draft-reviewer` Subagent による内容レビュー（フェーズ 4）である．

## やらないこと

- **自動承認は行わない** ．ステップ 3 の人間確認を省略しない
- `drafts/` への直接書き込みは Subagent の責務である．本 Skill はファイルを書かない
- 複数の記事を 1 回の呼び出しで並列生成しない（モード A の役割）
- 校閲・公開処理は行わない（フェーズ 4 の範囲）

## レート制限の扱い

`article-proposer` と `article-drafter` は順次起動するため，並列起動によるレート制限ヒットは発生しない．処理が詰まる場合は素材サイズを確認する．

## 利用者がカスタマイズする箇所

- `style-profile.md` の参照パスを `article-proposer`／`article-drafter` への呼び出し指示に差し込む
- 媒体差（はてなブログ向け／note 向け）を Subagent への指示に含める
- 章立てのレビューで人間に提示する確認ポイント

利用者カスタマイズは Private リポジトリ側の Skill ファイルに記載する．Public 側の本ひな形には個人色を含めない．
