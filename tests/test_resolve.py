"""Tests for TitleMetaResolver in sdb.resolve."""

from __future__ import annotations

from pathlib import Path

from sdb.resolve import TitleMetaResolver


class TestTitleMetaResolver:
    """TitleMetaResolver inserts _title_meta_items.qmd include correctly."""

    resolver = TitleMetaResolver()

    def test_skips_when_include_already_present(self, tmp_path: Path) -> None:
        """File with existing include directive is not modified."""
        qmd = tmp_path / "test.qmd"
        qmd.write_text(
            "---\ntitle: Test\n---\n\n{{< include _include/_title_meta_items.qmd >}}\n\nContent\n"
        )
        result = self.resolver.fix_one_file(qmd, tmp_path, dry_run=True, verbose=False)
        assert result == 0

    def test_skips_root_index(self, tmp_path: Path) -> None:
        """Root-level index.qmd is not modified."""
        qmd = tmp_path / "index.qmd"
        qmd.write_text("---\ntitle: Home\n---\n\nContent\n")
        result = self.resolver.fix_one_file(qmd, tmp_path, dry_run=True, verbose=False)
        assert result == 0

    def test_adds_include_to_subpage(self, tmp_path: Path) -> None:
        """Subpage without include gets one added."""
        inc_dir = tmp_path / "_include"
        inc_dir.mkdir()
        (inc_dir / "_title_meta_items.qmd").write_text("")
        qmd = tmp_path / "guide" / "index.qmd"
        qmd.parent.mkdir()
        qmd.write_text("---\ntitle: Guide\n---\n\nContent\n")
        result = self.resolver.fix_one_file(qmd, tmp_path, dry_run=True, verbose=False)
        assert result == 1

    def test_does_not_match_string_in_yaml(self, tmp_path: Path) -> None:
        """_title_meta_items.qmd appearing in YAML metadata-files alone
        (without an actual include directive) triggers insertion."""
        inc_dir = tmp_path / "_include"
        inc_dir.mkdir()
        (inc_dir / "_title_meta_items.qmd").write_text("")
        qmd = tmp_path / "sub" / "page.qmd"
        qmd.parent.mkdir()
        qmd.write_text(
            "---\ntitle: Page\nmetadata-files:\n  - _include/_title_meta_items.qmd\n---\n\nContent\n"
        )
        result = self.resolver.fix_one_file(qmd, tmp_path, dry_run=True, verbose=False)
        assert result == 1

    def test_include_after_title_meta_items_def(self, tmp_path: Path) -> None:
        """With title_meta_items defined in a Python code block, the include
        directive is inserted AFTER that block."""
        inc_dir = tmp_path / "_include"
        inc_dir.mkdir()
        (inc_dir / "_title_meta_items.qmd").write_text("")
        qmd = tmp_path / "sub" / "page.qmd"
        qmd.parent.mkdir()
        qmd.write_text(
            "---\ntitle: Test\n---\n\n"
            "```{python}\n"
            "title_meta_items = {\"html\": []}\n"
            "```\n\nContent\n"
        )
        r = TitleMetaResolver()
        result = r.fix_one_file(qmd, tmp_path, dry_run=False, verbose=False)
        assert result == 1
        content = qmd.read_text()
        tmi_pos = content.index("title_meta_items")
        include_pos = content.index("_title_meta_items")
        assert include_pos > tmi_pos, (
            f"Include at {include_pos} should be after title_meta_items at {tmi_pos}"
        )

    def test_relocates_include_when_before_tmi(self, tmp_path: Path) -> None:
        """Existing include before title_meta_items is relocated after it."""
        inc_dir = tmp_path / "_include"
        inc_dir.mkdir()
        (inc_dir / "_title_meta_items.qmd").write_text("")
        qmd = tmp_path / "sub" / "page.qmd"
        qmd.parent.mkdir()
        qmd.write_text(
            "---\ntitle: Test\n---\n\n"
            "{{< include ../_include/_title_meta_items.qmd >}}\n\n"
            "```{python}\n"
            "title_meta_items = {\"html\": []}\n"
            "```\n\nContent\n"
        )
        r = TitleMetaResolver()
        result = r.fix_one_file(qmd, tmp_path, dry_run=False, verbose=False)
        assert result == 1, f"Expected relocation, got {result}"
        content = qmd.read_text()
        tmi_pos = content.index("title_meta_items")
        include_pos = content.index("_title_meta_items")
        assert include_pos > tmi_pos, (
            f"Include at {include_pos} should be after title_meta_items at {tmi_pos}"
        )

    def test_skips_when_include_already_after_tmi(self, tmp_path: Path) -> None:
        """Include already after title_meta_items is left in place."""
        inc_dir = tmp_path / "_include"
        inc_dir.mkdir()
        (inc_dir / "_title_meta_items.qmd").write_text("")
        qmd = tmp_path / "sub" / "page.qmd"
        qmd.parent.mkdir()
        qmd.write_text(
            "---\ntitle: Test\n---\n\n"
            "```{python}\n"
            "title_meta_items = {\"html\": []}\n"
            "```\n\n"
            "{{< include ../_include/_title_meta_items.qmd >}}\n\nContent\n"
        )
        r = TitleMetaResolver()
        result = r.fix_one_file(qmd, tmp_path, dry_run=False, verbose=False)
        assert result == 0, f"Expected no change, got {result}"
