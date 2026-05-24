"""Unit tests for IncludeResolver."""

from __future__ import annotations

from pathlib import Path

from sdb.resolve import IncludeResolver


def _make_resolver(dry_run: bool = True) -> IncludeResolver:
    return IncludeResolver()


class TestIncludeResolver:
    """IncludeResolver core behavior."""

    def _write_and_fix(self, tmp_path: Path, content: str) -> str:
        """Write content to a qmd file in a scaffolded tree, run fix, return text."""
        docs = tmp_path / "docs"
        inc = docs / "_include"
        inc.mkdir(parents=True)
        (inc / "_title_meta_items.qmd").write_text("<!-- title meta -->\n")
        (inc / "_license.md").write_text("<!-- license -->\n")

        proj = docs / "projects" / "ev"
        proj.mkdir(parents=True)
        qmd = proj / "index.qmd"
        qmd.write_text(content)

        resolver = _make_resolver()
        resolver.fix_one_file(qmd, docs, dry_run=False, verbose=False)
        return qmd.read_text()

    def test_corrects_license_include_path(self, tmp_path: Path) -> None:
        """_license.md with wrong relative path is corrected."""
        content = (
            "---\ntitle: Test\n---\n"
            "{{< include ../../_include/_title_meta_items.qmd >}}\n"
            "# Body\n"
            "{{< include ../_include/_license.md >}}\n"
        )
        fixed = self._write_and_fix(tmp_path, content)
        assert "{{< include ../../_include/_license.md >}}" in fixed
        assert "{{< include ../_include/_license.md >}}" not in fixed

    def test_correct_license_path_is_noop(self, tmp_path: Path) -> None:
        """Already-correct _license.md path is left untouched."""
        content = (
            "---\ntitle: Test\n---\n"
            "{{< include ../../_include/_title_meta_items.qmd >}}\n"
            "# Body\n"
            "{{< include ../../_include/_license.md >}}\n"
        )
        fixed = self._write_and_fix(tmp_path, content)
        assert fixed == content

    def test_correct_title_meta_is_noop(self, tmp_path: Path) -> None:
        """Correct title-meta path is left unchanged."""
        content = (
            "---\ntitle: Test\n---\n"
            "{{< include ../../_include/_title_meta_items.qmd >}}\n"
            "# Body\n"
            "{{< include ../../_include/_license.md >}}\n"
        )
        fixed = self._write_and_fix(tmp_path, content)
        assert "{{< include ../../_include/_title_meta_items.qmd >}}" in fixed

    def test_wrong_title_meta_corrected(self, tmp_path: Path) -> None:
        """Wrong title-meta path is corrected."""
        content = (
            "---\ntitle: Test\n---\n"
            "{{< include ../_include/_title_meta_items.qmd >}}\n"
            "# Body\n"
            "{{< include ../_include/_license.md >}}\n"
        )
        fixed = self._write_and_fix(tmp_path, content)
        assert "{{< include ../../_include/_title_meta_items.qmd >}}" in fixed
        assert "{{< include ../_include/_title_meta_items.qmd >}}" not in fixed
        assert "{{< include ../../_include/_license.md >}}" in fixed
        assert "{{< include ../_include/_license.md >}}" not in fixed

    def test_unknown_include_is_not_corrected(self, tmp_path: Path) -> None:
        """Include referencing a non-existent file is left as-is."""
        content = (
            "---\ntitle: Test\n---\n"
            "{{< include ../../_include/_title_meta_items.qmd >}}\n"
            "# Body\n"
            "{{< include ../_include/nonexistent.md >}}\n"
        )
        fixed = self._write_and_fix(tmp_path, content)
        assert "{{< include ../_include/nonexistent.md >}}" in fixed

    def test_no_include_inserted_when_title_meta_exists(self, tmp_path: Path) -> None:
        """No duplicate title-meta inserted when one already exists."""
        content = (
            "---\ntitle: Test\n---\n"
            "{{< include ../../_include/_title_meta_items.qmd >}}\n"
            "# Body\n"
        )
        fixed = self._write_and_fix(tmp_path, content)
        assert fixed.count("_title_meta_items.qmd") == 1
