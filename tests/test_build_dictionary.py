"""tests/test_build_dictionary.py

build_dictionary.py の各関数に対するユニットテスト．
テストは janome の Tokenizer を実際にインスタンス化して実行する（モック不使用）．
"""

from pathlib import Path

import pytest
import yaml

from janome.tokenizer import Tokenizer

from build_dictionary import (
    _analyze,
    _build_tokenizer,
    extract_text,
    is_candidate,
    load_vocabulary,
    write_candidates,
)


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_removes_frontmatter(self):
        md = "---\ntitle: test\n---\n本文です．"
        assert "title" not in extract_text(md)
        assert "本文です" in extract_text(md)

    def test_passthrough_without_frontmatter(self):
        md = "フロントマターなし．"
        assert extract_text(md) == md

    def test_replaces_fenced_code_block_with_space(self):
        md = "前\n```\ncode here\n```\n後"
        result = extract_text(md)
        assert "code here" not in result
        assert "前" in result
        assert "後" in result

    def test_replaces_inline_code_with_space(self):
        md = "これは `foo()` の例です．"
        result = extract_text(md)
        assert "foo()" not in result
        assert "例" in result

    def test_removes_url_outside_link(self):
        md = "詳細は https://example.com を参照．"
        result = extract_text(md)
        assert "https://example.com" not in result

    def test_keeps_link_text_removes_url(self):
        md = "[サンプルページ](https://example.com/sample) を参照．"
        result = extract_text(md)
        assert "サンプルページ" in result
        assert "https://example.com" not in result

    def test_removes_header_marks(self):
        md = "## 見出し\n本文"
        result = extract_text(md)
        assert "##" not in result
        assert "見出し" in result

    def test_empty_string(self):
        assert extract_text("") == ""


# ---------------------------------------------------------------------------
# load_vocabulary
# ---------------------------------------------------------------------------


class TestLoadVocabulary:
    def _write_vocab(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "vocabulary.yml"
        p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        return p

    def test_returns_known_set_and_udic_lines(self, tmp_path):
        data = {
            "places": [
                {"canonical": "東京", "aliases": ["東京都", "とうきょう"]}
            ],
            "organizations": [],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)

        assert "東京" in known
        assert "東京都" in known
        assert "とうきょう" in known
        assert len(udic_lines) == 3  # canonical + 2 aliases

    def test_entry_without_aliases(self, tmp_path):
        data = {
            "places": [{"canonical": "大阪"}],
            "organizations": [],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)

        assert "大阪" in known
        assert len(udic_lines) == 1

    def test_canonical_with_comma_excluded_from_udic(self, tmp_path):
        data = {
            "places": [],
            "organizations": [{"canonical": "A,B Corp", "aliases": []}],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)

        assert "A,B Corp" in known
        assert all("A,B Corp" not in line for line in udic_lines)

    def test_alias_with_comma_excluded_from_udic(self, tmp_path):
        data = {
            "places": [],
            "organizations": [
                {"canonical": "FooBar", "aliases": ["Foo,Bar"]}
            ],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)

        assert "Foo,Bar" in known
        assert all("Foo,Bar" not in line for line in udic_lines)

    def test_empty_yaml_returns_empty(self, tmp_path):
        p = tmp_path / "vocabulary.yml"
        p.write_text("", encoding="utf-8")
        udic_lines, known = load_vocabulary(p)

        assert udic_lines == []
        assert known == set()

    def test_all_categories_loaded(self, tmp_path):
        data = {
            "places": [{"canonical": "東京", "aliases": []}],
            "organizations": [{"canonical": "PyCon JP", "aliases": []}],
            "technical_terms": [{"canonical": "GitHub Actions", "aliases": []}],
        }
        path = self._write_vocab(tmp_path, data)
        _, known = load_vocabulary(path)

        assert "東京" in known
        assert "PyCon JP" in known
        assert "GitHub Actions" in known


# ---------------------------------------------------------------------------
# is_candidate
# ---------------------------------------------------------------------------


class TestIsCandidate:
    def test_known_word_is_not_candidate(self):
        assert not is_candidate("GitHub", "名詞", {"GitHub"})

    def test_single_char_is_not_candidate(self):
        assert not is_candidate("A", "名詞", set())

    def test_hiragana_only_is_not_candidate(self):
        assert not is_candidate("あいう", "名詞", set())

    def test_digits_only_is_not_candidate(self):
        assert not is_candidate("123", "名詞", set())

    def test_symbol_only_is_not_candidate(self):
        assert not is_candidate("!!", "名詞", set())

    def test_non_noun_is_not_candidate(self):
        assert not is_candidate("走る", "動詞,自立,*,*,五段・ラ行,基本形", set())

    def test_suffix_noun_is_not_candidate(self):
        assert not is_candidate("さ", "名詞,接尾,特殊,*,*,*", set())

    def test_dependent_noun_is_not_candidate(self):
        assert not is_candidate("こと", "名詞,非自立,一般,*,*,*", set())

    def test_numeric_noun_is_not_candidate(self):
        assert not is_candidate("三", "名詞,数,*,*,*,*", set())

    def test_unknown_proper_noun_is_candidate(self):
        assert is_candidate("PyCon", "名詞,固有名詞,一般,*,*,*", set())

    def test_katakana_common_noun_is_candidate(self):
        assert is_candidate("コミュニティ", "名詞,一般,*,*,*,*", set())

    def test_ascii_term_is_candidate(self):
        assert is_candidate("OSS", "名詞,一般,*,*,*,*", set())

    def test_kanji_noun_not_in_known_is_candidate(self):
        assert is_candidate("東京", "名詞,固有名詞,地域,一般,*,*", set())


# ---------------------------------------------------------------------------
# write_candidates
# ---------------------------------------------------------------------------


class TestWriteCandidates:
    def test_creates_valid_yaml(self, tmp_path):
        output = tmp_path / "candidates.yml"
        candidates = {
            "AI": {"count": 3, "files": {"note1.md", "note2.md"}},
        }
        write_candidates(candidates, output)

        content = output.read_text(encoding="utf-8")
        assert "candidates:" in content
        assert "AI" in content
        assert "count: 3" in content

    def test_sorted_by_frequency_descending(self, tmp_path):
        output = tmp_path / "candidates.yml"
        candidates = {
            "少ない": {"count": 1, "files": {"a.md"}},
            "多い": {"count": 5, "files": {"a.md"}},
        }
        write_candidates(candidates, output)

        content = output.read_text(encoding="utf-8")
        assert content.index("多い") < content.index("少ない")

    def test_creates_parent_directory(self, tmp_path):
        output = tmp_path / "subdir" / "candidates.yml"
        candidates = {"AI": {"count": 1, "files": {"a.md"}}}
        write_candidates(candidates, output)

        assert output.exists()

    def test_surface_with_colon_is_valid_yaml(self, tmp_path):
        output = tmp_path / "candidates.yml"
        candidates = {"foo: bar": {"count": 1, "files": {"a.md"}}}
        write_candidates(candidates, output)

        content = output.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        surfaces = [e["surface"] for e in parsed["candidates"]]
        assert "foo: bar" in surfaces

    def test_surface_with_hash_is_valid_yaml(self, tmp_path):
        output = tmp_path / "candidates.yml"
        candidates = {"foo#bar": {"count": 1, "files": {"a.md"}}}
        write_candidates(candidates, output)

        content = output.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        surfaces = [e["surface"] for e in parsed["candidates"]]
        assert "foo#bar" in surfaces


# ---------------------------------------------------------------------------
# load_vocabulary — 防衛的チェック
# ---------------------------------------------------------------------------


class TestLoadVocabularyDefensive:
    def _write_vocab(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "vocabulary.yml"
        p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        return p

    def test_non_dict_entry_is_skipped(self, tmp_path):
        data = {
            "places": ["文字列エントリ（辞書でない）"],
            "organizations": [],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)
        assert udic_lines == []
        assert known == set()

    def test_entry_missing_canonical_is_skipped(self, tmp_path):
        data = {
            "places": [{"aliases": ["別表記"]}],
            "organizations": [],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)
        assert udic_lines == []
        assert known == set()

    def test_valid_entry_alongside_invalid_is_loaded(self, tmp_path):
        data = {
            "places": [
                "不正エントリ",
                {"canonical": "東京", "aliases": []},
            ],
            "organizations": [],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        _, known = load_vocabulary(path)
        assert "東京" in known

    def test_list_yaml_returns_empty(self, tmp_path):
        p = tmp_path / "vocabulary.yml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")
        udic_lines, known = load_vocabulary(p)
        assert udic_lines == []
        assert known == set()

    def test_invalid_yaml_exits(self, tmp_path):
        p = tmp_path / "vocabulary.yml"
        p.write_text("key: :\n  invalid: [unclosed", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            load_vocabulary(p)
        assert exc.value.code == 1

    def test_permission_error_exits(self, tmp_path, monkeypatch):
        p = tmp_path / "vocabulary.yml"
        p.write_text("", encoding="utf-8")
        monkeypatch.setattr("builtins.open", lambda *a, **kw: (_ for _ in ()).throw(OSError("Permission denied")))
        with pytest.raises(SystemExit) as exc:
            load_vocabulary(p)
        assert exc.value.code == 1

    def test_category_null_value_treated_as_empty(self, tmp_path):
        p = tmp_path / "vocabulary.yml"
        p.write_text("places:\norganizations:\ntechnical_terms:\n", encoding="utf-8")
        udic_lines, known = load_vocabulary(p)
        assert udic_lines == []
        assert known == set()

    def test_aliases_null_value_treated_as_empty(self, tmp_path):
        data = {
            "places": [{"canonical": "東京", "aliases": None}],
            "organizations": [],
            "technical_terms": [],
        }
        path = self._write_vocab(tmp_path, data)
        udic_lines, known = load_vocabulary(path)
        assert "東京" in known
        assert len(udic_lines) == 1


# ---------------------------------------------------------------------------
# _build_tokenizer
# ---------------------------------------------------------------------------


class TestBuildTokenizer:
    def test_empty_udic_returns_plain_tokenizer(self):
        result = _build_tokenizer([])
        assert isinstance(result, Tokenizer)

    def test_non_empty_udic_returns_tokenizer(self):
        result = _build_tokenizer(["GitHub,名詞,ギットハブ"])
        assert isinstance(result, Tokenizer)


# ---------------------------------------------------------------------------
# _analyze — 再帰探索
# ---------------------------------------------------------------------------


class TestAnalyzeRecursive:
    def test_analyzes_files_in_subdirectory(self, tmp_path):
        subdir = tmp_path / "2026"
        subdir.mkdir()
        md = subdir / "note.md"
        md.write_text("Python に参加した．", encoding="utf-8")

        tokenizer = _build_tokenizer([])
        candidates = _analyze(tmp_path, tokenizer, set())
        assert "2026/note.md" in {
            fname
            for info in candidates.values()
            for fname in info["files"]
        }

    def test_readme_in_subdirectory_is_excluded(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        readme = subdir / "README.md"
        readme.write_text("README の中身．", encoding="utf-8")
        note = subdir / "note.md"
        note.write_text("Python に参加した．", encoding="utf-8")

        tokenizer = _build_tokenizer([])
        candidates = _analyze(tmp_path, tokenizer, set())
        all_files = {fname for info in candidates.values() for fname in info["files"]}
        assert any("note.md" in fname for fname in all_files), "通常ファイルが解析対象に含まれていない"
        assert all("README.md" not in fname for fname in all_files)

    def test_same_filename_in_different_subdirs_tracked_separately(self, tmp_path):
        subdir_a = tmp_path / "2025"
        subdir_b = tmp_path / "2026"
        subdir_a.mkdir()
        subdir_b.mkdir()
        (subdir_a / "note.md").write_text("Python に参加した．", encoding="utf-8")
        (subdir_b / "note.md").write_text("Python に参加した．", encoding="utf-8")

        tokenizer = _build_tokenizer([])
        candidates = _analyze(tmp_path, tokenizer, set())
        all_files = {fname for info in candidates.values() for fname in info["files"]}
        assert "2025/note.md" in all_files
        assert "2026/note.md" in all_files
