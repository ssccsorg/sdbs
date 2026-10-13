"""Tests for ``LinkResolver``, which heals a markdown link whose target moved.

The resolver covers the document a link names and the asset a markdown image
displays, since a move breaks either relative path the same way.
"""

from __future__ import annotations

from pathlib import Path

from sdb.resolve import LinkResolver


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestImageDestination:
    """A markdown image is a link, and its asset is healed like a document."""

    def test_leaves_an_image_that_still_resolves(self, tmp_path: Path) -> None:
        _write(tmp_path / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![shot](../_include/shot.png){width=100%}\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 0
        assert doc.read_text() == "![shot](../_include/shot.png){width=100%}\n"

    def test_heals_an_image_the_move_brought_beside_the_document(
        self, tmp_path: Path
    ) -> None:
        """The asset now sits under the document, so ``../`` is one level too high."""
        _write(tmp_path / "mtep" / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![shot](../_include/shot.png){width=100%}\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 1
        assert doc.read_text() == "![shot](./_include/shot.png){width=100%}\n"

    def test_leaves_the_attribute_list_untouched(self, tmp_path: Path) -> None:
        """The list after the parenthesis is not part of the destination."""
        _write(tmp_path / "mtep" / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![shot](../_include/shot.png){width=100% #fig-delta}\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 1
        text = doc.read_text()
        assert text == "![shot](./_include/shot.png){width=100% #fig-delta}\n"

    def test_leaves_a_remote_and_an_absolute_image(self, tmp_path: Path) -> None:
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![a](https://example.org/a.png)\n\n![b](/assets/b.png)\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 0
        assert doc.read_text() == (
            "![a](https://example.org/a.png)\n\n![b](/assets/b.png)\n"
        )

    def test_leaves_an_image_whose_asset_moved_off_the_path(
        self, tmp_path: Path
    ) -> None:
        """The search reaches upward only, so an asset elsewhere is left alone."""
        _write(tmp_path / "assets" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![shot](../_include/shot.png)\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 0


    def test_keeps_the_title_inside_the_parenthesis(self, tmp_path: Path) -> None:
        """Only the path is replaced, so a title beside it survives."""
        _write(tmp_path / "mtep" / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            '![shot](../_include/shot.png "Caption")\n',
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 1
        assert doc.read_text() == '![shot](./_include/shot.png "Caption")\n'

    def test_keeps_the_angle_brackets(self, tmp_path: Path) -> None:
        _write(tmp_path / "mtep" / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![shot](<../_include/shot.png>)\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 1
        assert doc.read_text() == "![shot](<./_include/shot.png>)\n"

    def test_leaves_a_destination_in_a_fenced_block(self, tmp_path: Path) -> None:
        """A markdown example is not a link."""
        _write(tmp_path / "mtep" / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "Example:\n\n```markdown\n![shot](../_include/shot.png)\n```\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 0
        assert "../_include/shot.png" in doc.read_text()

    def test_leaves_a_destination_in_an_inline_span(self, tmp_path: Path) -> None:
        _write(tmp_path / "mtep" / "_include" / "shot.png", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "Write `![shot](../_include/shot.png)` to embed it.\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 0

    def test_leaves_a_suffix_the_set_does_not_name(self, tmp_path: Path) -> None:
        """The suffix comparison is exact, as it is for the documents."""
        _write(tmp_path / "mtep" / "_include" / "SHOT.PNG", "png")
        doc = _write(
            tmp_path / "mtep" / "page.qmd",
            "![shot](../_include/SHOT.PNG)\n",
        )

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 0


class TestDocumentLink:
    """The document case is unchanged by the widened suffix set."""

    def test_heals_a_document_link_as_before(self, tmp_path: Path) -> None:
        _write(tmp_path / "mtep" / "guide" / "index.md", "# Guide\n")
        doc = _write(tmp_path / "mtep" / "page.qmd", "[guide](guide.md)\n")

        assert LinkResolver().fix_one_file(
            doc, tmp_path, dry_run=False, verbose=False
        ) == 1
        assert doc.read_text() == "[guide](./guide/index.md)\n"
