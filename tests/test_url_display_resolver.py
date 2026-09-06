"""Tests for UrlDisplayResolver and rewrite_url_displays in sdb.resolve.

Scenarios cover the three target forms (full-URL label links, autolinks,
bare URLs in prose), every protected context (front matter, fenced code,
inline code, HTML, link destinations, reference definitions), trailing
punctuation, and idempotency.
"""

from __future__ import annotations

from pathlib import Path

from sdb.resolve import UrlDisplayResolver, rewrite_url_displays


class TestUrlDisplayResolver:
    """UrlDisplayResolver normalizes explicit full URL displays."""

    resolver = UrlDisplayResolver()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_file(self, base: Path, rel: str, content: str) -> Path:
        """Create a file at ``base / rel`` and return its path."""
        path = (base / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def _fix(self, base: Path, rel: str, content: str) -> int:
        """Write ``content``, run the resolver, and return the fix count."""
        path = self._make_file(base, rel, content)
        return self.resolver.fix_one_file(
            path, base, dry_run=False, verbose=False
        )

    # ------------------------------------------------------------------
    # Target forms
    # ------------------------------------------------------------------
    def test_inline_full_label_link(self, tmp_path: Path) -> None:
        """[https://x](https://x) label drops the scheme prefix."""
        n = self._fix(
            tmp_path, "doc.qmd",
            "See [https://docs.ssccs.org](https://docs.ssccs.org) now.\n",
        )
        assert n == 1, f"Expected 1 fix, got {n}"
        text = (tmp_path / "doc.qmd").read_text()
        assert "[docs.ssccs.org](https://docs.ssccs.org)" in text

    def test_inline_full_label_with_title(self, tmp_path: Path) -> None:
        """Label rewrite preserves a link title."""
        n = self._fix(
            tmp_path, "doc.md",
            '[https://a.b](https://a.b "title")\n',
        )
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert '[a.b](https://a.b "title")' in text

    def test_autolink(self, tmp_path: Path) -> None:
        """<https://x> becomes a scheme-less label link."""
        n = self._fix(
            tmp_path, "doc.md", "See <https://a.b/c> for details.\n"
        )
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert "[a.b/c](https://a.b/c)" in text

    def test_bare_url_in_prose(self, tmp_path: Path) -> None:
        """A bare URL in prose becomes a scheme-less label link."""
        n = self._fix(
            tmp_path, "doc.qmd",
            "Docs live at https://docs.ssccs.org/projects/sdbs/ today.\n",
        )
        assert n == 1
        text = (tmp_path / "doc.qmd").read_text()
        assert (
            "Docs live at [docs.ssccs.org/projects/sdbs/]"
            "(https://docs.ssccs.org/projects/sdbs/) today."
        ) in text

    def test_bare_url_trailing_punctuation(self, tmp_path: Path) -> None:
        """Trailing punctuation stays outside the generated link."""
        n = self._fix(tmp_path, "doc.md", "See https://a.b. Done.\n")
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert "[a.b](https://a.b)." in text

    def test_http_scheme(self, tmp_path: Path) -> None:
        """http:// is normalized like https://."""
        n = self._fix(tmp_path, "doc.md", "See http://a.b now.\n")
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert "[a.b](http://a.b)" in text

    def test_bare_url_with_balanced_parens(self, tmp_path: Path) -> None:
        """A closing paren that balances an open paren stays in the URL."""
        n = self._fix(
            tmp_path, "doc.md",
            "See https://en.wikipedia.org/wiki/Foo_(bar) for it.\n",
        )
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert (
            "[en.wikipedia.org/wiki/Foo_(bar)]"
            "(https://en.wikipedia.org/wiki/Foo_(bar)) for it."
        ) in text

    def test_bare_url_surrounded_by_parens(self, tmp_path: Path) -> None:
        """Prose parens around a URL stay outside the generated link."""
        n = self._fix(
            tmp_path, "doc.md",
            "(See https://en.wikipedia.org/wiki/Foo_(bar)).\n",
        )
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert (
            "(See [en.wikipedia.org/wiki/Foo_(bar)]"
            "(https://en.wikipedia.org/wiki/Foo_(bar)))."
        ) in text

    def test_multiple_forms_in_one_file(self, tmp_path: Path) -> None:
        """All three forms in one file are normalized together."""
        n = self._fix(
            tmp_path, "doc.qmd",
            "[https://a.b](https://a.b) <https://c.d/e> https://f.g.\n",
        )
        assert n == 3, f"Expected 3 fixes, got {n}"
        text = (tmp_path / "doc.qmd").read_text()
        assert "[a.b](https://a.b) [c.d/e](https://c.d/e) " in text
        assert "[f.g](https://f.g)." in text

    # ------------------------------------------------------------------
    # Protected contexts
    # ------------------------------------------------------------------
    def test_distinct_label_untouched(self, tmp_path: Path) -> None:
        """A link with its own label text is left alone."""
        n = self._fix(tmp_path, "doc.md", "[click here](https://a.b)\n")
        assert n == 0

    def test_reference_definition_untouched(self, tmp_path: Path) -> None:
        """Reference link definitions are never rewritten."""
        content = "[ref]: https://a.b\n\n[see][ref]\n"
        n = self._fix(tmp_path, "doc.md", content)
        assert n == 0
        assert (tmp_path / "doc.md").read_text() == content

    def test_angle_reference_definition_untouched(self, tmp_path: Path) -> None:
        """Autolink-style reference definitions are never rewritten."""
        content = "[ref]: <https://a.b>\n\n[see][ref]\n"
        n = self._fix(tmp_path, "doc.md", content)
        assert n == 0
        assert (tmp_path / "doc.md").read_text() == content

    def test_fenced_code_untouched(self, tmp_path: Path) -> None:
        """Fenced code blocks including Quarto chunks are protected."""
        content = (
            "```{python}\n"
            'url = "https://a.b/c"\n'
            "```\n\n"
            "```text\nhttps://c.d\n```\n"
        )
        n = self._fix(tmp_path, "doc.qmd", content)
        assert n == 0
        assert (tmp_path / "doc.qmd").read_text() == content

    def test_inline_code_untouched(self, tmp_path: Path) -> None:
        """Inline code spans are protected."""
        content = "Use `https://a.b` and `x = https://c.d` now.\n"
        n = self._fix(tmp_path, "doc.md", content)
        assert n == 0
        assert (tmp_path / "doc.md").read_text() == content

    def test_front_matter_untouched(self, tmp_path: Path) -> None:
        """URLs in YAML front matter are protected."""
        content = (
            "---\n"
            "title: Test\n"
            "url: https://a.b\n"
            "---\n\n"
            "Body https://c.d text.\n"
        )
        n = self._fix(tmp_path, "doc.qmd", content)
        assert n == 1
        text = (tmp_path / "doc.qmd").read_text()
        assert "url: https://a.b" in text
        assert "[c.d](https://c.d)" in text

    def test_html_tag_untouched(self, tmp_path: Path) -> None:
        """URLs inside HTML tags are protected."""
        content = '<a href="https://a.b">site</a> and text https://c.d.\n'
        n = self._fix(tmp_path, "doc.md", content)
        assert n == 1
        text = (tmp_path / "doc.md").read_text()
        assert 'href="https://a.b"' in text
        assert "[c.d](https://c.d)" in text

    def test_link_destination_untouched(self, tmp_path: Path) -> None:
        """Destinations of existing links are never rewritten."""
        content = "[label](https://a.b) and [label](<https://c.d>).\n"
        n = self._fix(tmp_path, "doc.md", content)
        assert n == 0
        assert (tmp_path / "doc.md").read_text() == content

    def test_bare_url_in_brackets_untouched(self, tmp_path: Path) -> None:
        """A bare URL sitting in a label-like bracket pair stays put."""
        content = "Keep [https://a.b] intact.\n"
        n = self._fix(tmp_path, "doc.md", content)
        assert n == 0
        assert (tmp_path / "doc.md").read_text() == content

    # ------------------------------------------------------------------
    # Realistic combined document
    # ------------------------------------------------------------------
    def test_realistic_document(self, tmp_path: Path) -> None:
        """A realistic qmd document: only intended displays change."""
        content = (
            "---\n"
            "title: Sample\n"
            "url: https://keep.frontmatter\n"
            "---\n\n"
            "{{< include _include/_title_meta_items.qmd >}}\n\n"
            "```{python}\n"
            'client = "https://keep.code"\n'
            "```\n\n"
            "Intro with https://docs.example.com/a and "
            "<https://docs.example.com/b> and "
            "[https://docs.example.com/c](https://docs.example.com/c), "
            "then [see](https://docs.example.com/d).\n\n"
            "| col |\n"
            "|-----|\n"
            "| https://docs.example.com/e |\n\n"
            "`https://keep.span` ![alt](https://keep.image.png)\n\n"
            "[ref]: https://keep.def\n\n"
            "Footnote text https://docs.example.com/f.\n"
        )
        n = self._fix(tmp_path, "doc.qmd", content)
        assert n == 5, f"Expected 5 fixes, got {n}"
        text = (tmp_path / "doc.qmd").read_text()
        assert "url: https://keep.frontmatter" in text
        assert 'client = "https://keep.code"' in text
        assert "https://keep.span" in text
        assert "![alt](https://keep.image.png)" in text
        assert "[ref]: https://keep.def" in text
        assert "[see](https://docs.example.com/d)" in text
        assert "[docs.example.com/a](https://docs.example.com/a)" in text
        assert "[docs.example.com/b](https://docs.example.com/b)" in text
        assert "[docs.example.com/c](https://docs.example.com/c)" in text
        assert "[docs.example.com/e](https://docs.example.com/e)" in text
        assert "[docs.example.com/f](https://docs.example.com/f)" in text

    def test_realistic_document_idempotent(self, tmp_path: Path) -> None:
        """The combined document is stable after a second pass."""
        content = (
            "---\n"
            "title: Sample\n"
            "---\n\n"
            "Text https://docs.example.com/a and "
            "<https://docs.example.com/b> and "
            "[https://docs.example.com/c](https://docs.example.com/c).\n"
        )
        path = self._make_file(tmp_path, "doc.qmd", content)
        n1 = self.resolver.fix_one_file(
            path, tmp_path, dry_run=False, verbose=False
        )
        n2 = self.resolver.fix_one_file(
            path, tmp_path, dry_run=False, verbose=False
        )
        assert n1 == 3
        assert n2 == 0

    # ------------------------------------------------------------------
    # Idempotency and API
    # ------------------------------------------------------------------
    def test_idempotent(self, tmp_path: Path) -> None:
        """A second run makes no further changes."""
        content = (
            "[https://a.b](https://a.b) <https://c.d/e> and https://f.g.\n"
        )
        path = self._make_file(tmp_path, "doc.md", content)
        n1 = self.resolver.fix_one_file(
            path, tmp_path, dry_run=False, verbose=False
        )
        n2 = self.resolver.fix_one_file(
            path, tmp_path, dry_run=False, verbose=False
        )
        assert n1 == 3
        assert n2 == 0

    def test_rewrite_url_displays_function(self) -> None:
        """The module-level helper returns text and a fix count."""
        new_text, count = rewrite_url_displays(
            "See https://a.b and [https://c.d](https://c.d).\n"
        )
        assert count == 2
        assert "See [a.b](https://a.b) and " in new_text
        assert "[c.d](https://c.d)." in new_text
