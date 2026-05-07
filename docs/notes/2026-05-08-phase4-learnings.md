# フェーズ 4 実装・レビュー対応の知見

## 背景

PR #16 のレビュー対応（CodeQL アラート・Ruff・CodeRabbit 指摘）を通じて得た知見をまとめる．

## 判断・解決した問題

### `get_env` の `or` 演算子による空文字列フォールスルー

**What:** `os.environ.get(key) or env_file_vars.get(key, "")` は，環境変数が
空文字列 `""` に設定されている場合（ `os.environ.get` は `""` を返すが，
`""` は falsy）に env_file の値へフォールスルーしてしまう．

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

**What:** `# lgtm[py/weak-cryptographic-algorithm]` コメントは旧 LGTM.com 向けの
抑制構文であり，GHAS の CodeQL では効果がない．CodeQL アラートは GitHub の
Security タブから手動で Dismiss する必要がある．

**Why:** LGTM.com と GHAS は別インフラ．GHAS には Python 向けのインライン
抑制構文がない．

**How to apply:** GHAS で偽陽性アラートを抑制する場合は Security タブ →
Code scanning alerts → Dismiss（理由を記入）．PR のブロックが不要なら
アラートを Dismiss することで次回以降のスキャンで再報告されなくなる．

今回の WSSE SHA-1 使用については `# noqa: S324` で Ruff の警告は抑制できたが，
CodeQL は別途 Dismiss が必要だった（プロトコル仕様で変更不可の旨を記入した）．

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
