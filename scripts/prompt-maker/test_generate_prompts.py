"""generate_prompts モジュールのテスト．"""

from pathlib import Path

import pytest

from generate_prompts import (
    STAGE_KEYS,
    build_prompt,
    build_source_note_title,
    generate_all_prompts,
    load_template,
)


@pytest.fixture
def fake_templates_dir(tmp_path: Path) -> Path:
    """最小限のテンプレートファイルを作るフィクスチャ．"""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    for key in STAGE_KEYS:
        (templates_dir / f"{key}.md").write_text(
            f"stage={key} session={{session_id}} source={{source_note}}",
            encoding="utf-8",
        )
    return templates_dir


class TestBuildSourceNoteTitle:
    """build_source_note_title のテスト．"""

    def test_default_suffix(self):
        assert build_source_note_title("foo") == "[foo] 元ノート"

    def test_custom_suffix(self):
        assert build_source_note_title("foo", "文字起こし") == "[foo] 文字起こし"

    def test_japanese_session_id(self):
        result = build_source_note_title("2026-05-01-他人のルールに乗る")
        assert result == "[2026-05-01-他人のルールに乗る] 元ノート"


class TestBuildPrompt:
    """build_prompt のテスト．"""

    def test_replaces_session_id(self):
        assert build_prompt("id={session_id}", "abc") == "id=abc"

    def test_replaces_source_note(self):
        assert build_prompt("src={source_note}", "abc") == "src=[abc] 元ノート"

    def test_replaces_both_placeholders(self):
        result = build_prompt("{session_id}/{source_note}", "x")
        assert result == "x/[x] 元ノート"

    def test_template_without_placeholders_unchanged(self):
        assert build_prompt("プレーンテキスト", "abc") == "プレーンテキスト"

    def test_preserves_unrelated_braces(self):
        """プレースホルダ以外の波括弧は保持される．"""
        template = "code: { print(); } id={session_id}"
        result = build_prompt(template, "x")
        assert "{ print(); }" in result
        assert "id=x" in result

    def test_custom_suffix_applied(self):
        result = build_prompt("{source_note}", "foo", "文字起こし")
        assert result == "[foo] 文字起こし"


class TestLoadTemplate:
    """load_template のテスト．"""

    def test_loads_existing_template(self, fake_templates_dir: Path):
        content = load_template("01_structure", fake_templates_dir)
        assert "stage=01_structure" in content

    def test_raises_when_template_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent", tmp_path)

    def test_raises_when_directory_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_template("01_structure", tmp_path / "no_such_dir")

    def test_handles_japanese_content(self, tmp_path: Path):
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "ja.md").write_text(
            "日本語テスト {session_id}", encoding="utf-8"
        )
        content = load_template("ja", templates_dir)
        assert "日本語テスト" in content


class TestGenerateAllPrompts:
    """generate_all_prompts のテスト．"""

    def test_creates_three_files(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        output_dir = tmp_path / "out"
        paths = generate_all_prompts(
            session_id="test",
            output_dir=output_dir,
            templates_dir=fake_templates_dir,
        )
        assert len(paths) == 3

    def test_all_files_exist(self, fake_templates_dir: Path, tmp_path: Path):
        output_dir = tmp_path / "out"
        paths = generate_all_prompts(
            session_id="test",
            output_dir=output_dir,
            templates_dir=fake_templates_dir,
        )
        for path in paths:
            assert path.exists()

    def test_all_files_are_markdown(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        paths = generate_all_prompts(
            session_id="test",
            output_dir=tmp_path / "out",
            templates_dir=fake_templates_dir,
        )
        for path in paths:
            assert path.suffix == ".md"

    def test_session_id_substituted_in_every_file(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        session_id = "unique-id-12345"
        paths = generate_all_prompts(
            session_id=session_id,
            output_dir=tmp_path / "out",
            templates_dir=fake_templates_dir,
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            assert f"session={session_id}" in content

    def test_source_note_substituted_in_every_file(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        paths = generate_all_prompts(
            session_id="foo",
            output_dir=tmp_path / "out",
            templates_dir=fake_templates_dir,
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            assert "source=[foo] 元ノート" in content

    def test_japanese_session_id_works(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        session_id = "2026-05-01-他人のルールに乗る"
        paths = generate_all_prompts(
            session_id=session_id,
            output_dir=tmp_path / "out",
            templates_dir=fake_templates_dir,
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            assert session_id in content

    def test_creates_output_directory_if_not_exists(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        output_dir = tmp_path / "nested" / "deeply" / "out"
        assert not output_dir.exists()
        generate_all_prompts(
            session_id="foo",
            output_dir=output_dir,
            templates_dir=fake_templates_dir,
        )
        assert output_dir.exists()

    def test_custom_suffix_applied(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        paths = generate_all_prompts(
            session_id="foo",
            output_dir=tmp_path / "out",
            templates_dir=fake_templates_dir,
            source_suffix="文字起こし",
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            assert "source=[foo] 文字起こし" in content

    def test_raises_when_template_missing(self, tmp_path: Path):
        empty_templates = tmp_path / "empty"
        empty_templates.mkdir()
        with pytest.raises(FileNotFoundError):
            generate_all_prompts(
                session_id="foo",
                output_dir=tmp_path / "out",
                templates_dir=empty_templates,
            )

    def test_returns_paths_in_stage_key_order(
        self, fake_templates_dir: Path, tmp_path: Path
    ):
        paths = generate_all_prompts(
            session_id="foo",
            output_dir=tmp_path / "out",
            templates_dir=fake_templates_dir,
        )
        stems = [p.stem for p in paths]
        assert stems == list(STAGE_KEYS)


class TestRealTemplates:
    """同梱の本物テンプレートを使った統合テスト．"""

    @pytest.fixture
    def project_templates_dir(self) -> Path:
        """プロジェクト同梱の templates ディレクトリ．"""
        return Path(__file__).parent / "templates"

    def test_real_templates_exist(self, project_templates_dir: Path):
        for key in STAGE_KEYS:
            assert (project_templates_dir / f"{key}.md").is_file()

    def test_real_templates_generate_successfully(
        self, project_templates_dir: Path, tmp_path: Path
    ):
        paths = generate_all_prompts(
            session_id="2026-05-01-他人のルールに乗る",
            output_dir=tmp_path / "out",
            templates_dir=project_templates_dir,
        )
        assert len(paths) == 3
        for path in paths:
            content = path.read_text(encoding="utf-8")
            assert "2026-05-01-他人のルールに乗る" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
