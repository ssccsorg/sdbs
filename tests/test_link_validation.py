"""Tests for link validation in sdb.check."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Set, Tuple

import pytest

from sdb.check import validate_all_links, is_inside_inline_code


# The same pattern used in validate_all_links
def _extract_bare_urls(content: str) -> Set[Tuple[str, int]]:
    bare_url_pattern = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]*://[^>]+)>")
    links: Set[Tuple[str, int]] = set()
    for match in bare_url_pattern.finditer(content):
        if is_inside_inline_code(content, match.start()):
            continue
        links.add((match.group(1), content.count("\n", 0, match.start()) + 1))
    return links


def _extract_md_links(content: str) -> Set[Tuple[str, int]]:
    md_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    links: Set[Tuple[str, int]] = set()
    for match in md_pattern.finditer(content):
        if is_inside_inline_code(content, match.start()):
            continue
        links.add((match.group(2), content.count("\n", 0, match.start()) + 1))
    return links


class TestBareUrlExtraction:
    """<url> bare Quarto links are correctly extracted."""

    @staticmethod
    def _links(urls_only: Set[Tuple[str, int]]) -> Set[str]:
        return {u for u, _ in urls_only}

    def test_standard_https_url(self) -> None:
        """<https://example.com> is extracted."""
        result = _extract_bare_urls("<https://example.com/path>")
        assert "https://example.com/path" in self._links(result)

    def test_http_url(self) -> None:
        """<http://example.com> is extracted."""
        result = _extract_bare_urls("<http://example.com>")
        assert "http://example.com" in self._links(result)

    def test_ftp_url(self) -> None:
        """<ftp://files.example.com> is extracted."""
        result = _extract_bare_urls("<ftp://files.example.com>")
        assert "ftp://files.example.com" in self._links(result)

    def test_url_with_query(self) -> None:
        """<https://example.com?a=1&b=2> is extracted."""
        result = _extract_bare_urls("<https://example.com?a=1&b=2>")
        assert "https://example.com?a=1&b=2" in self._links(result)

    def test_url_with_fragment(self) -> None:
        """<https://example.com#section> is extracted; fragment stripped later."""
        result = _extract_bare_urls("<https://example.com#section>")
        assert "https://example.com#section" in self._links(result)

    def test_arxiv_url(self) -> None:
        """<https://arxiv.org/abs/2601.12345> is extracted."""
        result = _extract_bare_urls("<https://arxiv.org/abs/2601.12345>")
        assert "https://arxiv.org/abs/2601.12345" in self._links(result)

    def test_multiple_urls(self) -> None:
        """Multiple <url>s on separate lines are all extracted."""
        content = (
            "<https://first.example.com>\n"
            "some text\n"
            "<https://second.example.com/path>\n"
        )
        result = self._links(_extract_bare_urls(content))
        assert "https://first.example.com" in result
        assert "https://second.example.com/path" in result
        assert len(result) == 2

    def test_inside_inline_code_is_ignored(self) -> None:
        """<url> inside backtick inline code is not extracted."""
        content = "text `<https://ignored.example.com>` more text"
        result = _extract_bare_urls(content)
        assert "https://ignored.example.com" not in self._links(result)

    def test_mixed_with_md_links(self) -> None:
        """<url> and [text](url) are independently extracted."""
        content = (
            "See <https://bare.example.com> or [click](https://md.example.com)."
        )
        bare = self._links(_extract_bare_urls(content))
        md = self._links(_extract_md_links(content))
        assert "https://bare.example.com" in bare
        assert "https://md.example.com" in md
        assert len(bare) == 1
        assert len(md) == 1

    def test_github_url(self) -> None:
        """<https://github.com/org/repo> is extracted."""
        result = _extract_bare_urls("<https://github.com/ssccsorg/sdbs>")
        assert "https://github.com/ssccsorg/sdbs" in self._links(result)
