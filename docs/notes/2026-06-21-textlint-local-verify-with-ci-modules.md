# textlint をローカルで CI 同一バージョン検証する手順

## 背景

`blog-pipeline` は textlint 設定を中央テンプレ `tomio2480/github-workflows` から
継承する．設定ファイルはリポジトリに常設せず，composite action が実行時に
一時ディレクトリへ依存をインストールして lint する．このため手元に textlint 環境が
なく，`docs/notes` の残存エラー修正でローカル事前検証の方法が課題となった．

PR #50 でこの手順を確立したので記録する．

## 課題

### 1. `npx textlint` 単体では "No rules found" になる

設定（中央 `.textlintrc.json`）には `preset-ja-technical-writing` などの rule が
書かれている．それでも素の `npx textlint` は "No rules found" を返し，何も
検査しない．最新版を都度取得する `npx` 経路でも同様に失敗した．

根本原因は composite action の `action.yml` にコメントとして明記されている．
中央設定は `filters.comments: true` を持つ．
この指定により `textlint-filter-rule-comments` が必須依存となる．
これが未インストールだと，設定ローダーの `loadFilterRules` で
`ReferenceError` が起きる．`@textlint/config-loader` が `ok:false` を返して
fallback する．結果として `rules` セクションも含む全 rule が黙って破棄され，
"No rules found" として現れる．preset のバージョン差異でも同種の失敗が起きうる．

### 2. `filter-mode=added` は既存ファイルの残存エラーを見逃す

CI の reviewdog は `filter-mode=added` で動く．PR 差分の追加行だけを指摘する
仕様のため，差分外の既存ファイルに残るエラーはすり抜ける．PR #50 の対象は，
別 PR の CI を通過していた残存エラーであった．全体検査は別途必要になる．

## 解決

CI と同一バージョンの `node_modules` を使う．composite action は依存を
`action.yml` の `package.json` でピン留めする．clone 済みの中央リポジトリには，
インストール済みの `node_modules` が残っている．これを `NODE_PATH` 経由で
読ませれば，CI と同じ判定をローカルで再現できる．

表 1. ローカル検証で用いた主要パッケージのピン留めバージョン．

| パッケージ | バージョン |
|---|---|
| `textlint` | 15.6.0 |
| `textlint-rule-preset-ja-technical-writing` | 12.0.2 |
| `textlint-rule-preset-ja-spacing` | 2.4.3 |
| `textlint-rule-prh` | 6.1.0 |
| `textlint-filter-rule-comments` | 1.3.0 |

手順は次のとおり．`prh` の `rulePaths` は中央 `templates/prh.yml` の絶対パスへ
書き換えた設定を別途用意し，`--config` で渡す．

```bash
ACTION_DIR="<github-workflows>/.github/actions/markdown-lint"
NODE_PATH="${ACTION_DIR}/node_modules" \
  "${ACTION_DIR}/node_modules/.bin/textlint" \
  --config <prh パスを解決した .textlintrc.json> \
  <対象 .md ...>
```

## 二段構えの検証フロー

ローカルとクラウドを役割分担する．往復回数を抑えつつ最終確認の信頼性を保つ．

1. 中央テンプレの rule から修正方針を推測し，文意を保って直す．
2. CI 同一バージョンの textlint をローカル実行し，指摘 0 件まで詰める．
3. push して Draft PR を起票し，reviewdog の Markdown Lint で最終確認する．

PR #50 では推測どおりローカルで 0 件にでき，クラウドの Markdown Lint も
pass した．ローカルで詰め切ったため，クラウドの往復は 1 回で済んだ．

## 留意点

- 中央テンプレの依存が更新されると，手元の `node_modules` も `npm ci` で
  追随させる必要がある．バージョン乖離は判定差を生む．
- この手順は中央リポジトリを clone 済みであることに依存する．未取得なら
  対象バージョンを明示してインストールする環境を別に用意する．

## 参照

- [PR #50](https://github.com/tomio2480/blog-pipeline/pull/50)
- 中央テンプレ: [tomio2480/github-workflows](https://github.com/tomio2480/github-workflows)
- composite action: `.github/actions/markdown-lint/action.yml`
