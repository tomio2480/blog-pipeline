---
name: note-tagger
description: 補正済み素材ごとにタグ候補を 3〜7 件推定し YAML サイドカーへ書き出す Subagent ひな形
model: haiku
---

# note-tagger

`materials/corrected/<YYYY-MM-DD>-<note_title>.md` を入力に取り，3〜7 件のタグ候補を推定する．成果物は同階層の `<YYYY-MM-DD>-<note_title>.summary.yml` の `auto_tags` フィールドに書き出す．`note-summarizer` と同じサイドカーファイルを共有するため，先後関係を運用ルール化する．

本ファイルは Public リポジトリの **ひな形** である．利用者は個人化版を Private リポジトリの `.claude/agents/` 配下へコピーする．`vocabulary.yml` 連携や個別ドメインのタグ優先度を差し込む前提とする．

## 入力と出力

- 入力：`materials/corrected/<YYYY-MM-DD>-<note_title>.md`
  - YAML フロントマター付き Markdown．フロントマターの `tags`（Evernote 由来）も読む
- 出力：`materials/corrected/<YYYY-MM-DD>-<note_title>.summary.yml`
  - YAML 形式のサイドカーファイル．既存ファイルは上書きする
  - 本 Subagent は `auto_tags` フィールドのみを書き換える．`summary` は `note-summarizer` が担当
- 参照：なし（個人化版で `vocabulary.yml` を任意で差し込む）

## サイドカーのスキーマ

`<YYYY-MM-DD>-<note_title>.summary.yml`：

```yaml
source_material: 2026-04-28-架空イベント登壇メモ.md
summary: ""              # note-summarizer が後段または前段で書き換える．本 Subagent は触らない
auto_tags:
  - 登壇
  - 架空フレームワーク
  - イベント
generated_at: "2026-05-01T12:00:00Z"
generator_model: haiku
```

`summary` が既に値を持っていれば保持する．`source_material`／`auto_tags`／`generated_at`／`generator_model` のみを更新する．

## やること

- 素材の本文とフロントマター `tags` を読み，3〜7 件のタグ候補を推定する
- フロントマター `tags` に既に登録された語と同義のタグを **重複登録しない** ．Evernote 側で「PHP」が付いていれば自動推定でも「PHP」を 1 度だけ
- 抽象度のバランスを取る．広すぎるタグ（「技術」「日記」のみ）と狭すぎるタグ（記事全体に出てこない固有名詞）の混在を避ける

## やらないこと

- **人名タグの登録は禁止** ．第三者の名前は登録しない（誤検出と差し戻しのコストが大きい）
- 第三者の組織名タグの推測登録．ただしフロントマターの `tags` に既に登録された組織名はそのまま許容する
- 推測ベースの過剰タグ．本文に **明示的に登場した語** に限定する
- 要約の生成．`note-summarizer` の責務であり，本 Subagent は `summary` を空または既存値のまま保持する
- 既存の `summary.yml` の `summary` を破壊する書き換え

## 動作仕様

1. 入力 Markdown を読み込み，フロントマターと 3 セクション本文を分離する
2. フロントマター `tags` を初期セットとして読み，本文から追加候補を抽出
3. 既存の `<YYYY-MM-DD>-<note_title>.summary.yml` があれば読み込む．無ければ新規作成
4. `auto_tags`／`generated_at`／`generator_model`／`source_material` を更新．`summary` は既存値を保持
5. YAML を上書き保存する

## モデル選択の指針

- 既定は `haiku`．量が多く単純判断のため
- モード A は素材数だけ並列起動するため，`haiku` でレート制限を抑える
- ドメイン特化のタグ精度を上げたい場合のみ `sonnet` への切り替えを検討．モデル指定は frontmatter で行う

## 利用者がカスタマイズする箇所

- `vocabulary.yml` の `organizations`／`places` を優先度高くタグ化する処理
- 個別ドメインのタグ優先度（地域コミュニティ名・カンファレンス名）
- 人名タグの追加禁止を Private 側で再強調する記述

利用者カスタマイズは Private リポジトリ側の Subagent ファイルに記載する．Public 側の本ひな形には個人色を含めない．
