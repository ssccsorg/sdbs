"""Tests for ``sdb.utils.latest``."""

from __future__ import annotations

import yaml

from pathlib import Path
from sdb.utils.latest import (
    EXCLUDE_PATTERNS,
    ITEM_LENGTH,
    _load_exclude_patterns,
    _load_latest_count,
    _is_system_ignored,
    doc_to_html,
    matches_exclude,
)


class TestLoadExcludePatterns:
    """``_load_exclude_patterns`` returns the union of EXCLUDE_PATTERNS + build.yml exclude."""

    def test_returns_exclude_patterns_when_no_build_yml(self, tmp_path: Path) -> None:
        """No build.yml exists -> returns EXCLUDE_PATTERNS as-is."""
        result = _load_exclude_patterns(tmp_path)
        assert result == EXCLUDE_PATTERNS

    def test_returns_exclude_patterns_when_build_yml_has_no_exclude(self, tmp_path: Path) -> None:
        """build.yml exists but missing exclude key -> returns EXCLUDE_PATTERNS."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 5}), encoding="utf-8"
        )
        result = _load_exclude_patterns(tmp_path)
        assert result == EXCLUDE_PATTERNS

    def test_appends_build_yml_patterns(self, tmp_path: Path) -> None:
        """build.yml with extra exclude patterns -> union of both."""
        extra = ["**/_*.qmd", "**/*_site/", "**/_llms/"]
        (tmp_path / "build.yml").write_text(
            yaml.dump({"exclude": extra}), encoding="utf-8"
        )
        result = _load_exclude_patterns(tmp_path)
        for p in EXCLUDE_PATTERNS:
            assert p in result, f"Missing hardcoded pattern: {p}"
        for p in extra:
            assert p in result, f"Missing build.yml pattern: {p}"

    def test_deduplicates_overlapping_patterns(self, tmp_path: Path) -> None:
        """build.yml pattern already in EXCLUDE_PATTERNS is not duplicated."""
        duplicate = ["**/README.md"]
        (tmp_path / "build.yml").write_text(
            yaml.dump({"exclude": duplicate}), encoding="utf-8"
        )
        result = _load_exclude_patterns(tmp_path)
        assert result.count("**/README.md") == 1, "Dedup failed: pattern appears more than once"
        assert len(result) == len(EXCLUDE_PATTERNS), "Extra patterns should not grow from overlap"

    def test_ignores_invalid_yaml(self, tmp_path: Path) -> None:
        """build.yml with invalid YAML -> returns EXCLUDE_PATTERNS."""
        (tmp_path / "build.yml").write_text("{invalid: yaml: [unclosed", encoding="utf-8")
        result = _load_exclude_patterns(tmp_path)
        assert result == EXCLUDE_PATTERNS

    def test_empty_exclude_list(self, tmp_path: Path) -> None:
        """build.yml with empty exclude list -> returns EXCLUDE_PATTERNS."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"exclude": []}), encoding="utf-8"
        )
        result = _load_exclude_patterns(tmp_path)
        assert result == EXCLUDE_PATTERNS


class TestMatchesExclude:
    """``matches_exclude`` checks a relative path against exclude patterns."""

    def test_readme_matches(self) -> None:
        assert matches_exclude("README.md", EXCLUDE_PATTERNS) is True

    def test_nested_readme_matches(self) -> None:
        assert matches_exclude("projects/syntagma/README.md", EXCLUDE_PATTERNS) is True

    def test_llms_md_matches(self) -> None:
        assert matches_exclude("projects/nexus/foo.llms.md", EXCLUDE_PATTERNS) is True

    def test_plain_llms_md_does_not_match(self) -> None:
        assert matches_exclude("projects/nexus/llms.md", EXCLUDE_PATTERNS) is False

    def test_include_dir_matches(self) -> None:
        assert matches_exclude("_include/header.qmd", EXCLUDE_PATTERNS) is True

    def test_nested_include_dir_matches(self) -> None:
        assert matches_exclude("projects/syntagma/_include/author.yml", EXCLUDE_PATTERNS) is True

    def test_utils_dir_matches(self) -> None:
        assert matches_exclude("_utils/build.py", EXCLUDE_PATTERNS) is True

    def test_output_files_dir_matches(self) -> None:
        assert matches_exclude("tagma/wp_files/figure.pdf", EXCLUDE_PATTERNS) is True

    def test_cached_dir_matches(self) -> None:
        assert matches_exclude("tagma/wp_cached/cache.db", EXCLUDE_PATTERNS) is True

    def test_libs_dir_matches(self) -> None:
        assert matches_exclude("paper/_libs/vendor.js", EXCLUDE_PATTERNS) is True

    def test_normal_qmd_does_not_match(self) -> None:
        assert matches_exclude("projects/syntagma/tagma/index.qmd", EXCLUDE_PATTERNS) is False

    def test_normal_index_qmd_does_not_match(self) -> None:
        assert matches_exclude("projects/syntagma/index.qmd", EXCLUDE_PATTERNS) is False

    def test_custom_pattern_appended(self) -> None:
        patterns = EXCLUDE_PATTERNS + ["**/_*.qmd"]
        assert matches_exclude("_updated_docs_list.qmd", patterns) is True
        assert matches_exclude("projects/syntagma/wp.qmd", patterns) is False


class TestIsSystemIgnored:
    """``_is_system_ignored`` checks system directory components."""

    def test_git_dir(self) -> None:
        assert _is_system_ignored(".git/config") is True

    def test_quarto_dir(self) -> None:
        assert _is_system_ignored(".quarto/cache/file.qmd") is True

    def test_venv_dir(self) -> None:
        assert _is_system_ignored(".venv/bin/python") is True

    def test_node_modules(self) -> None:
        assert _is_system_ignored("node_modules/pkg/index.js") is True

    def test_pycache(self) -> None:
        assert _is_system_ignored("__pycache__/module.pyc") is True

    def test_normal_path_not_ignored(self) -> None:
        assert _is_system_ignored("projects/syntagma/tagma/index.qmd") is False


class TestDocToHtml:
    """``doc_to_html`` resolves the correct output extension."""

    def test_html_only(self, tmp_path: Path) -> None:
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: Test\nformat:\n  html: {}\n---\n", encoding="utf-8")
        assert doc_to_html("doc.qmd", tmp_path) == "/doc.html"

    def test_pdf_only(self, tmp_path: Path) -> None:
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: Test\nformat:\n  pdf:\n    pdf-engine: xelatex\n---\n", encoding="utf-8")
        assert doc_to_html("doc.qmd", tmp_path) == "/doc.pdf"

    def test_beamer_only(self, tmp_path: Path) -> None:
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: Test\nformat:\n  beamer: {}\n---\n", encoding="utf-8")
        assert doc_to_html("doc.qmd", tmp_path) == "/doc.pdf"

    def test_html_preferred_over_pdf(self, tmp_path: Path) -> None:
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: Test\nformat:\n  html: {}\n  pdf:\n    pdf-engine: xelatex\n---\n", encoding="utf-8")
        assert doc_to_html("doc.qmd", tmp_path) == "/doc.html"

    def test_html_preferred_over_beamer(self, tmp_path: Path) -> None:
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: Test\nformat:\n  html: {}\n  beamer: {}\n---\n", encoding="utf-8")
        assert doc_to_html("doc.qmd", tmp_path) == "/doc.html"

    def test_no_format_specified(self, tmp_path: Path) -> None:
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: Test\n---\n", encoding="utf-8")
        assert doc_to_html("doc.qmd", tmp_path) == "/doc.html"

    def test_md_file_defaults_to_html(self, tmp_path: Path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("# Test\n", encoding="utf-8")
        assert doc_to_html("doc.md", tmp_path) == "/doc.html"

    def test_index_qmd_in_subdir(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        qmd = sub / "index.qmd"
        qmd.write_text("---\ntitle: Test\n---\n", encoding="utf-8")
        assert doc_to_html("sub/index.qmd", tmp_path) == "/sub/index.html"


class TestLoadLatestCount:
    """``_load_latest_count`` reads ``latest_docs_list_count`` from build.yml."""

    def test_default_when_no_build_yml(self, tmp_path: Path) -> None:
        """No build.yml exists → returns ITEM_LENGTH."""
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_default_when_build_yml_has_no_key(self, tmp_path: Path) -> None:
        """build.yml exists but missing latest_docs_list_count → returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text("exclude:\n  - '**/README.md'\n", encoding="utf-8")
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_custom_value(self, tmp_path: Path) -> None:
        """build.yml with latest_docs_list_count: 5 → returns 5."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 5}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == 5

    def test_custom_large_value(self, tmp_path: Path) -> None:
        """build.yml with latest_docs_list_count: 25 → returns 25."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 25}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == 25

    def test_zero_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: 0 → not positive, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 0}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_negative_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: -5 → not positive, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": -5}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_non_integer_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: \"abc\" → not int, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": "abc"}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_float_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: 5.5 → not int, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 5.5}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_invalid_yaml_falls_back(self, tmp_path: Path) -> None:
        """build.yml with invalid YAML → exception caught, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text("{invalid: yaml: [unclosed", encoding="utf-8")
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_empty_build_yml(self, tmp_path: Path) -> None:
        """build.yml empty → returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text("", encoding="utf-8")
        assert _load_latest_count(tmp_path) == ITEM_LENGTH
