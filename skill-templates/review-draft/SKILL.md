---
name: review-draft
description: ブログ記事ドラフトの校閲フローをオーケストレーションする Skill．textlint による機械校正と draft-reviewer Subagent による内容レビューを順次実行する
---

# review-draft

ブログ記事ドラフトの校閲フローをオーケストレーションする Skill である．
`structure-note` Skill が生成した `drafts/<YYYY-MM-DD>-<slug>.md` を入力に取る．
機械校正（textlint）と LLM によるコンテンツレビューを順次実行し，結果を人間に提示する．

## 役割

Skill はオーケストレーション役である．

- 機械校正は textlint コマンドの実行結果を読み取る
- 内容レビューは `draft-reviewer` Subagent に委譲する
- 結果の統合と人間への提示はメイン会話が行う

## 入力

- レビュー対象ドラフト：`drafts/<YYYY-MM-DD>-<slug>.md`

## 出力

- textlint の指摘一覧（コマンド出力のまま）
- `draft-reviewer` Subagent のレビュー結果

## フロー

### 1. 入力の確認

`drafts/` 配下の対象ドラフトファイルが存在することを確認する．
ファイルが存在しない場合は人間に確認を求める．

### 2. 機械校正（textlint）

```bash
npx textlint <対象ファイルパス>
```

- textlint の出力を人間に提示する．
- 指摘がゼロの場合でも「指摘なし」と明示して次工程へ進む．
- 指摘がある場合は，**人間が修正を済ませてから** 本 Skill を再度呼び出す．
  Skill 自身はファイルを書き換えない．

### 3. 内容レビュー

`draft-reviewer` Subagent を起動してレビュー結果を受け取る．

### 4. 結果の提示

textlint の結果と `draft-reviewer` の結果を並べて人間に提示する．

## やらないこと

- ドラフトの自動修正は行わない
- 機械校正の指摘を無視して内容レビューに進まない
- `publish.py` の呼び出しは行わない（投稿判断は人間が行う）
