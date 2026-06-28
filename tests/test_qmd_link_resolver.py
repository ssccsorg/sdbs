"""Tests for QmdLinkResolver in sdb.resolve.

Scenarios cover URL resolution (relative, absolute, upward traversal,
missing targets), label replacement (YAML title, # heading, fallback),
link formatting preservation, code-block exclusion, and discovered
edge cases.
"""

from __future__ import annotations

from pathlib import Path

from sdb.resolve import QmdLinkResolver


class TestQmdLinkResolver:
    """QmdLinkResolver fixes .qmd links: URL -> .html, label -> YAML title."""

    resolver = QmdLinkResolver()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_file(
        self, base: Path, rel: str, content: str = ""
    ) -> Path:
        """Create a file at ``base / rel`` with optional content,
        creating parent directories."""
        path = (base / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def _make_qmd_with_frontmatter(
        self, base: Path, rel: str, title: str
    ) -> Path:
        """Create a .qmd file with YAML frontmatter containing title."""
        return self._make_file(
            base, rel,
            f"---\ntitle: {title}\n---\n\nContent.\n",
        )

    def _make_qmd_with_heading(
        self, base: Path, rel: str, heading: str
    ) -> Path:
        """Create a .qmd file without frontmatter, using # heading."""
        return self._make_file(base, rel, f"# {heading}\n\nContent.\n")

    # ==============================================================
    # URL resolution scenarios
    # ==============================================================

    def test_relative_qmd_same_dir(self, tmp_path: Path) -> None:
        """Link to .qmd in same directory: URL becomes .html."""
        self._make_qmd_with_frontmatter(tmp_path, "target.qmd", "Target")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[target.qmd](target.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes (label+URL), got {n}"
        text = source.read_text()
        assert "./target.html" in text, f"URL not fixed: {text}"
        assert "Target" in text, f"Label not replaced: {text}"

    def test_relative_qmd_subdir(self, tmp_path: Path) -> None:
        """Link to .qmd in subdirectory: URL becomes .html."""
        self._make_qmd_with_frontmatter(tmp_path, "notes/target.qmd", "Target Note")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[notes/target.qmd](notes/target.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "notes/target.html" in text, f"URL not fixed: {text}"
        assert "Target Note" in text, f"Label not replaced: {text}"

    def test_upward_traversal_qmd(self, tmp_path: Path) -> None:
        """Link with ../ to parent directory: resolved via _search_upward."""
        self._make_qmd_with_frontmatter(tmp_path, "notes/target.qmd", "Target Up")
        source = self._make_file(
            tmp_path, "sub/deep/source.qmd",
            "[../notes/target.qmd](../notes/target.qmd)\n",
        )
        n = self.resolver.fix_one_file(
            source, tmp_path, dry_run=False, verbose=False
        )
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        # After resolution, the path should be recalculated relative to source's dir
        assert "../../notes/target.html" in text or "target.html" in text, (
            f"URL not fixed: {text}"
        )

    def test_html_link_label_fix(self, tmp_path: Path) -> None:
        """.html link gets its label replaced with the .qmd source title."""
        self._make_qmd_with_frontmatter(
            tmp_path, "guide.qmd", "Guide Document"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[sdsds](/guide.html)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 1, f"Expected 1 fix (label only), got {n}"
        text = source.read_text()
        assert "Guide Document" in text, (
            f"Label not replaced: {text}"
        )
        assert "/guide.html" in text, (
            f"URL should remain unchanged: {text}"
        )

    def test_html_relative_link_label_fix(self, tmp_path: Path) -> None:
        """Relative .html link gets label replaced."""
        self._make_qmd_with_frontmatter(
            tmp_path, "notes/guide.qmd", "Relative Guide"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[ss](notes/guide.html)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 1, f"Expected 1 fix (label only), got {n}"
        text = source.read_text()
        assert "Relative Guide" in text, (
            f"Label not replaced: {text}"
        )
        assert "notes/guide.html" in text, (
            f"URL should remain unchanged: {text}"
        )

    def test_html_link_no_qmd_source(self, tmp_path: Path) -> None:
        """.html link without corresponding .qmd source: no change."""
        source = self._make_file(
            tmp_path, "source.qmd",
            "[label](/external.html)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=True, verbose=False)
        assert n == 0, f"Expected 0 fixes, got {n}"

    def test_missing_qmd_no_change(self, tmp_path: Path) -> None:
        """Link to non-existent .qmd: no change."""
        source = self._make_file(
            tmp_path, "source.qmd",
            "[missing.qmd](missing.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=True, verbose=False)
        assert n == 0, f"Expected 0 fixes for missing target, got {n}"

    def test_absolute_path_qmd(self, tmp_path: Path) -> None:
        """Absolute path .qmd link: resolves from project root correctly."""
        self._make_qmd_with_frontmatter(
            tmp_path, "notes/target.qmd", "Target Abs"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[/notes/target.qmd](/notes/target.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "target.html" in text, f"URL not fixed: {text}"
        assert "Target Abs" in text, f"Label not replaced: {text}"

    # ==============================================================
    # Exclusion scenarios
    # ==============================================================

    def test_inside_fenced_code_block(self, tmp_path: Path) -> None:
        """.qmd link inside ``` code block is skipped."""
        self._make_qmd_with_frontmatter(tmp_path, "target.qmd", "Target")
        source = self._make_file(
            tmp_path, "source.qmd",
            "```\n[target.qmd](target.qmd)\n```\n",
        )
        n = self.resolver.fix_one_file(
            source, tmp_path, dry_run=True, verbose=False
        )
        assert n == 0, (
            f"Expected 0 fixes for code-block link, got {n}"
        )

    def test_external_url_skipped(self, tmp_path: Path) -> None:
        """External https/http links are skipped even if they contain .qmd."""
        source = self._make_file(
            tmp_path, "source.qmd",
            "[site](https://example.com/file.qmd)\n",
        )
        n = self.resolver.fix_one_file(
            source, tmp_path, dry_run=True, verbose=False
        )
        assert n == 0, f"Expected 0 for external URL, got {n}"

    def test_anchor_link_skipped(self, tmp_path: Path) -> None:
        """Anchor links starting with # are skipped."""
        source = self._make_file(
            tmp_path, "source.qmd",
            "[section](#section)\n",
        )
        n = self.resolver.fix_one_file(
            source, tmp_path, dry_run=True, verbose=False
        )
        assert n == 0, f"Expected 0 for anchor link, got {n}"

    def test_non_qmd_link_skipped(self, tmp_path: Path) -> None:
        """Links ending in .md or other extensions are skipped."""
        source = self._make_file(
            tmp_path, "source.qmd",
            "[other.md](other.md)\n[page.html](page.html)\n",
        )
        n = self.resolver.fix_one_file(
            source, tmp_path, dry_run=True, verbose=False
        )
        assert n == 0, f"Expected 0 for non-.qmd links, got {n}"

    # ==============================================================
    # Label replacement scenarios
    # ==============================================================

    def test_yaml_title_in_label(self, tmp_path: Path) -> None:
        """Label with .qmd path replaced by YAML title."""
        self._make_qmd_with_frontmatter(tmp_path, "notes/doc.qmd", "Document Title")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[notes/doc.qmd](notes/doc.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "Document Title" in text, f"Label not replaced: {text}"
        assert "notes/doc.html" in text, f"URL not fixed: {text}"

    def test_heading_fallback_in_label(self, tmp_path: Path) -> None:
        """Label replaced by # heading when YAML title absent."""
        self._make_qmd_with_heading(
            tmp_path, "notes/doc.qmd", "Heading Title"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[notes/doc.qmd](notes/doc.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "Heading Title" in text, f"Heading not used: {text}"

    def test_human_readable_label_is_replaced(self, tmp_path: Path) -> None:
        """Even human-readable labels are replaced by target title.
        This is deterministic: every .qmd link gets title injection."""
        self._make_qmd_with_frontmatter(tmp_path, "notes/doc.qmd", "Some Doc")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[My custom label](notes/doc.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        # Label replaced + URL fixed
        assert n == 2, f"Expected 2 fixes (label+URL), got {n}"
        text = source.read_text()
        assert "Some Doc" in text, (
            f"Label should be replaced with title: {text}"
        )
        assert "My custom label" not in text, (
            f"Original label should be gone: {text}"
        )

    def test_label_fallback_to_html(self, tmp_path: Path) -> None:
        """Label falls back to .html when target has no title or heading."""
        _ = self._make_file(tmp_path, "notes/doc.qmd", "Just content\n")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[notes/doc.qmd](notes/doc.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        # Fallback label should be notes/doc.html
        assert "notes/doc.html" in text, f"Fallback label not correct: {text}"

    # ==============================================================
    # Link formatting preservation
    # ==============================================================

    def test_angle_bracket_url_preserved(self, tmp_path: Path) -> None:
        """URL with < > angle brackets preserves formatting.
        Label is replaced with target title unconditionally."""
        self._make_qmd_with_frontmatter(
            tmp_path, "target.qmd", "Target"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            '[link](<target.qmd>)\n',
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        # Label replaced + URL fixed
        assert n == 2, f"Expected 2 fixes (label+URL), got {n}"
        text = source.read_text()
        assert "Target" in text, (
            f"Label should be replaced: {text}"
        )
        assert "<" in text and ">" in text, (
            f"Angle brackets not preserved: {text}"
        )

    def test_link_with_anchor(self, tmp_path: Path) -> None:
        """.qmd link with #anchor becomes .html with same anchor."""
        self._make_qmd_with_frontmatter(
            tmp_path, "notes/doc.qmd", "Document"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[notes/doc.qmd](notes/doc.qmd#section)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "notes/doc.html#section" in text or "doc.html#section" in text, (
            f"Anchor not preserved: {text}"
        )

    # ==============================================================
    # Multiple links in same file
    # ==============================================================

    def test_multiple_qmd_links(self, tmp_path: Path) -> None:
        """Multiple .qmd links in same file all get fixed."""
        self._make_qmd_with_frontmatter(tmp_path, "a.qmd", "File A")
        self._make_qmd_with_frontmatter(tmp_path, "b.qmd", "File B")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[a.qmd](a.qmd) and [b.qmd](b.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 4, f"Expected 4 fixes (2 labels + 2 URLs), got {n}"
        text = source.read_text()
        assert "File A" in text
        assert "File B" in text
        assert "./a.html" in text or "a.html" in text
        assert "./b.html" in text or "b.html" in text

    # ==============================================================
    # Edge cases discovered during testing
    # ==============================================================

    def test_url_start_at_zero(self, tmp_path: Path) -> None:
        """Link at the very start of file: url_start is 0, pre slice
        must not fail."""
        self._make_qmd_with_frontmatter(tmp_path, "target.qmd", "Target")
        source = self._make_file(tmp_path, "source.qmd", "[t](target.qmd)\n")
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes (label+URL), got {n}"

    def test_label_with_newline_before_bracket(self, tmp_path: Path) -> None:
        """Label [text] separated from (url) by whitespace or newline
        is still matched correctly."""
        self._make_qmd_with_frontmatter(tmp_path, "target.qmd", "Target Doc")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[target.qmd]\n(target.qmd)\n",
        )
        # In standard markdown, label and URL MUST be on same line with no
        # whitespace between ] and (. So this is not a valid markdown link.
        # QmdLinkResolver's RE_LINK won't match it, so no fixes expected.
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=True, verbose=False)
        assert n == 0, (
            f"Expected 0 for split [label]\\n(url), got {n}"
        )

    def test_label_matching_multiline_safe(self, tmp_path: Path) -> None:
        """pre[:url_start - 1] slice is safe when url_start > 0."""
        self._make_qmd_with_frontmatter(tmp_path, "notes/doc.qmd", "Multi Doc")
        source = self._make_file(
            tmp_path, "source.qmd",
            "Some text before\n\n[notes/doc.qmd](notes/doc.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "Multi Doc" in text, f"Label not replaced: {text}"

    def test_link_in_table_gets_fixed(self, tmp_path: Path) -> None:
        """.qmd link inside a markdown table: both label and URL fixed."""
        self._make_qmd_with_frontmatter(tmp_path, "notes/report.qmd", "Report Title")
        source = self._make_file(
            tmp_path, "source.qmd",
            "| Name | Link |\n|---|---|\n"
            "| Summary | [notes/report.qmd](notes/report.qmd) |\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes (label+URL), got {n}"
        text = source.read_text()
        assert "Report Title" in text, f"Label not replaced: {text}"
        assert "notes/report.html" in text, f"URL not fixed: {text}"

    def test_same_file_twice(self, tmp_path: Path) -> None:
        """Same .qmd referenced twice in same file: both fixed."""
        self._make_qmd_with_frontmatter(tmp_path, "target.qmd", "Target")
        source = self._make_file(
            tmp_path, "source.qmd",
            "[target.qmd](target.qmd) and [target.qmd](target.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        # Two links = 4 fixes (2 labels + 2 URLs)
        assert n == 4, f"Expected 4 fixes for 2 identical links, got {n}"
        text = source.read_text()
        assert text.count("Target") == 2, (
            f"Both labels should be replaced: {text}"
        )

    def test_yaml_title_special_chars(self, tmp_path: Path) -> None:
        """YAML title with colons is quoted in frontmatter to prevent
        parsing issues."""
        # In YAML, a value containing ": " must be quoted
        raw_title = 'Special: Title with colons'
        self._make_file(
            tmp_path, "notes/doc.qmd",
            '---\ntitle: "' + raw_title + '"\n---\n\nContent.\n',
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[notes/doc.qmd](notes/doc.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert raw_title.split(":")[0] in text, (
            f"Special chars label issue: {text}"
        )

    def test_relative_path_no_dotdot(self, tmp_path: Path) -> None:
        """Relative path without ../ prefix resolves correctly when
        the target exists via _search_upward starting from doc_dir."""
        self._make_qmd_with_frontmatter(
            tmp_path, "subdir/target.qmd", "Subdir Target"
        )
        source = self._make_file(
            tmp_path, "source.qmd",
            "[target.qmd](target.qmd)\n",
        )
        # target.qmd is not directly in tmp_path, but in subdir/
        # _search_upward starts from source's parent (tmp_path) and
        # looks for target.qmd directly. If not found there, it
        # goes up. Since tmp_path is root, won't go above.
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=True, verbose=False)
        assert n == 0, (
            "Expected 0 when target.qmd not in same dir and not "
            f"reachable via upward search, got {n}"
        )

    def test_link_url_with_trailing_quote(self, tmp_path: Path) -> None:
        """Link URL with trailing 'title' or \"title\" is handled by
        _clean_url inherited from LinkResolver."""
        self._make_qmd_with_frontmatter(
            tmp_path, "notes/doc.qmd", "Quoted Title"
        )
        # Standard markdown: [text](path "title")
        source = self._make_file(
            tmp_path, "source.qmd",
            '[notes/doc.qmd](notes/doc.qmd "Display")\n',
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert 'notes/doc.html "Display"' in text or "notes/doc.html" in text, (
            f"URL with title not fixed: {text}"
        )
        # Label with .qmd path should be replaced
        assert "Quoted Title" in text, f"Label not replaced: {text}"

    def test_nested_upward_directory(self, tmp_path: Path) -> None:
        """Deeply nested parent traversal resolves correctly."""
        self._make_qmd_with_frontmatter(
            tmp_path, "deep/dir/target.qmd", "Deep Target"
        )
        source = self._make_file(
            tmp_path, "a/b/c/source.qmd",
            "[../../../deep/dir/target.qmd](../../../deep/dir/target.qmd)\n",
        )
        n = self.resolver.fix_one_file(
            source, tmp_path, dry_run=False, verbose=False
        )
        assert n == 2, f"Expected 2 fixes (label+URL), got {n}"
        text = source.read_text()
        assert "Deep Target" in text, f"Label not replaced: {text}"
        # The computed relative path should use the correct number of ../
        assert "deep/dir/target.html" in text or "target.html" in text, (
            f"URL not fixed correctly: {text}"
        )

    def test_absolute_path_from_subdir(self, tmp_path: Path) -> None:
        """Absolute path link from a nested source resolves to
        correct relative path."""
        self._make_qmd_with_frontmatter(
            tmp_path, "notes/target.qmd", "Target Abs"
        )
        source = self._make_file(
            tmp_path, "sub/deep/source.qmd",
            "[/notes/target.qmd](/notes/target.qmd)\n",
        )
        n = self.resolver.fix_one_file(source, tmp_path, dry_run=False, verbose=False)
        assert n == 2, f"Expected 2 fixes, got {n}"
        text = source.read_text()
        assert "Target Abs" in text, f"Label not replaced: {text}"
        assert "../../notes/target.html" in text, (
            f"Relative path not computed correctly: {text}"
        )
