# フェーズ 4 実装・レビュー対応の知見

## 背景

PR #16 のレビュー対応（CodeQL アラート・Ruff・CodeRabbit 指摘）を通じて得た知見をまとめる．

## 判断・解決した問題

### `get_env` の `or` 演算子による空文字列フォールスルー

**What:** `os.environ.get(key) or env_file_vars.get(key, "")` は空文字列でフォールスルーする．
環境変数が `""` のとき，`os.environ.get` は `""` を返す．
`""` は falsy なため，`or` は env_file の値へフォールスルーしてしまう．

**Why:** Python の `or` 演算子は falsy 値（`""`, `0`, `None` 等）をすべて
「未設定」と同じように扱うため，意図しない動作になる．

**How to apply:** 環境変数の有無を判断するときは `or` でなく明示的な `None` チェックを使う．

```python
# NG
value = os.environ.get(key) or env_file_vars.get(key, "")

# OK
value = os.environ.get(key)
if value is None:
    value = env_file_vars.get(key, "")
```

### GitHub Advanced Security（GHAS）での CodeQL アラート抑制

**What:** `# lgtm[rule-id]` は旧 LGTM.com 向け構文であり，GHAS の CodeQL では無効である．
GHAS のインライン抑制には `# codeql[rule-id]` 形式を使う．

**Why:** LGTM.com と GHAS は別インフラのため，旧構文が効果を持たない．

**How to apply:** GHAS で偽陽性アラートを抑制するには `# codeql[rule-id]` コメントをコード行に追加する．
Security タブ → Code scanning alerts → Dismiss は，インライン修正が難しい場合の代替である．

今回の WSSE SHA-1 使用について，`# noqa: S324` で Ruff の警告は抑制できた．
CodeQL は Security タブから Dismiss した（プロトコル仕様上，変更不可のため）．

### `urllib.request.urlopen` のデフォルトタイムアウト

**What:** `urllib.request.urlopen(req)` はデフォルトタイムアウトが `None`（無制限）．
外部 API が応答しない場合にプロセスが無期限にハングする．

**How to apply:** 外部 API への `urlopen` 呼び出しには常に `timeout=` を指定する．
はてなブログ AtomPub 向けには `timeout=30` を採用した．

## 代替案と棄却理由

- `get_env` の `or` 演算子を残して空文字列の場合は `""` を有効値として扱う案
  → 環境変数を空文字列に設定しても即 exit すべき仕様のため棄却．
- urlopen timeout を環境変数から取得する案
  → 設定項目が増える割に利点が薄く YAGNI．固定値 30 秒で十分と判断．

## 参照

- PR #16: <https://github.com/tomio2480/blog-pipeline/pull/16>
- `scripts/publish.py` の `get_env` 関数（修正後）
- `tests/test_publish.py` の `test_get_env_empty_os_environ_does_not_fall_through`
