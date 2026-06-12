# Phase 5 `build_dictionary.py` 実装レビュー対応の知見

## 背景

PR #21 で `build_dictionary.py` を TDD で実装し，Gemini Code Assist のレビューに
対応した際に得た知見をまとめる．

## 学びと知見

### 1. YAML の `null` 値は `dict.get(key, [])` でガードできない

YAML でカテゴリキーが存在するが値を省略した場合，`yaml.safe_load` はそのキーの
値を `None` として返す．

```yaml
# このような vocabulary.yml
places:
organizations:
technical_terms:
```

この場合 `data.get("places", [])` は `None` を返すため，`for entry in None` で
`TypeError` が発生する．`dict.get(key, [])` はキー自体が存在しないときの
デフォルト値であり，キーが存在して値が `None` のケースは対象外である．

**対処**: `(data.get(key) or [])` を使い，`None` を空リストに落とす．
同じ理由で `entry.get("aliases", [])` も `(entry.get("aliases") or [])` と
する必要がある．

```python
# NG
for entry in data.get(category, []):

# OK
for entry in (data.get(category) or []):
```

**再発防止**: YAML を読み込んで辞書をイテレートする処理では，
キーが存在して値が `null` になる可能性を常に考慮する．

### 2. Windows 環境で `subprocess.run` の stdout が `cp932` で読まれる

`gh api` を Python の `subprocess.run` 経由で呼び出し，stdout を text モードで読む場合を考える．
Windows ではデフォルトエンコーディングが `cp932` になる．
GitHub API レスポンスは UTF-8 の JSON（日本語含む）のため
`UnicodeDecodeError` が発生する．

この例外を「API 呼び出し失敗」と誤判定すると，実際には投稿済みのコメントを
再投稿してしまい，二重投稿になる．

**対処**: `bin/reply-review.ps1`（Windows）または `bin/reply-review.sh`（bash）
を使う．これらは `gh api --input <tempfile>` 方式で呼び出しており，
エンコーディング問題を回避している．
Python から直接 `subprocess` で `gh api` を組み立てない．

**再発防止**: `tomio2480/settings#76` を起票した．
CLAUDE.md または `github-dev` Skill にスクリプト使用を必須化する方針を記録した．

### 3. `load_vocabulary` のエラーハンドリングはファイル読み込み層で行う

`vocabulary.yml` の読み込みで発生しうる例外は以下の 3 種類である．

- `yaml.YAMLError`: YAML 構文エラー
- `OSError`: パーミッションエラーなどの I/O エラー
- `UnicodeDecodeError`: ファイルエンコーディングが UTF-8 でない場合

いずれもスクリプト全体の続行が不可能なため，`sys.exit(1)` で終了する設計が
適切である．`main()` 側で `vocab_path.exists()` チェックを行っていても，
パーミッションエラーは防げないため，ファイル読み込み層での捕捉が必要になる．

```python
try:
    with open(vocab_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
    print(f"エラー: {vocab_path} の処理に失敗しました: {e}", file=sys.stderr)
    sys.exit(1)
```

## 参照

- [PR #21](https://github.com/tomio2480/blog-pipeline/pull/21)
- Gemini レビューコメント: 3235190157，3235269429，3235269436
- 二重投稿の根本原因と対策: [tomio2480/settings#76](https://github.com/tomio2480/settings/issues/76)
