# Phase 5 ドキュメント整備 PR レビュー対応の知見

## 背景

PR #19（`docs(phase5): 運用手順を README に追記し vocabulary.yml サンプルを追加する`）の
レビュー対応で得た知見をまとめる．

## 判断と知見

### 1. `**text**` と全角コロン `：` の組み合わせ

CLAUDE.md は「`**` の終了直後に半角スペースを挟む」と規定している．
しかし `prh` の「全角コロン前後にスペースを入れない」ルールと衝突する場合がある．

`- **固有名詞** ：製品名` と書くと textlint が `prh` ルールでエラーを報告した．
正しい形式は `- **固有名詞**：製品名`（スペースなし）である．

**判断** ：CI で直接検出される `prh` ルールを優先する．全角コロン・句読点・全角記号は
「句読点や全角記号は例外」という spacing 規律が適用されるため，`**` の直後にスペースは不要．

### 2. textlint の sentence-length は Markdown の折り返しを無視する

段落内で改行しても，textlint は `．` で区切るまでを 1 文として計測する．

追加した文を見やすさのために 2 行に折り返したが，textlint は 98 字 1 文と判定して
`sentence-length` エラーを報告した．折り返し前後の合計文字数を意識すること．

**再発防止** ：段落内で行をまたぐ文は，合計文字数が 80 字以内か確認してから書く．

### 3. `gh api --field body=` でバッククォートが剥がれる

bash の `--field body="..."` の文字列内にバッククォート `` ` `` を含めると，
bash がコマンド置換（`` `cmd` ``）として解釈し，内容が欠落する．

**解決策** ：Python スクリプトで `{"body": "..."}` の JSON ファイルを生成し，
`gh api ... --input <file>` で渡す．これにより特殊文字のエスケープ問題を回避できる．

```python
import json
body = "...バッククォートを含む文字列..."
with open("reply.json", "w", encoding="utf-8") as f:
    json.dump({"body": body}, f, ensure_ascii=False)
```

```bash
gh api repos/<owner>/<repo>/pulls/comments/<id>/replies \
  --method POST --input reply.json
```

## 代替案と棄却理由

- **`printf '%s'` でのエスケープ** ：バッククォートを `\`` でエスケープしても
  bash の挙動が安定しないため採用しなかった．
- **`gh pr comment` コマンド** ：PR 全体への一般コメントにしか対応しておらず，
  inline review comment の個別 Reply には使えない．

## 参照

- PR #19: https://github.com/tomio2480/blog-pipeline/pull/19
- textlint sentence-length エラー: reviewdog comment #3233877062
- prh エラー: reviewdog comment #3233792107〜3233792121
