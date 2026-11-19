"""Healing a build input that resolves above the docs root.

A website build copies the docs root per target and renders from that copy, so a
reference the source tree can reach above the root is gone at render time.  The
resolvers that rewrite build inputs decide by the reach of that copy.
"""

from __future__ import annotations

from pathlib import Path

from sdb.resolve import IncludeResolver, PathResolver


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _document(root: Path, body: str) -> Path:
    """Write a document two directories below the root, as a family note is."""
    return _write(root / "nexus" / "notes" / "qimeng.qmd", body)


class TestTheDocsRootIsTheBoundary:
    resolver = PathResolver()

    def test_a_metadata_file_above_the_root_is_rewritten_into_it(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "docs"
        _write(tmp_path / "_include" / "author.yml", "author: []\n")
        _write(root / "_include" / "author.yml", "author: []\n")
        qmd = _document(
            root,
            "---\ntitle: Test\nmetadata-files:\n"
            "  - ../../../_include/author.yml\n---\n\nBody.\n",
        )

        fixes = self.resolver.fix_one_file(qmd, root, dry_run=False, verbose=False)

        assert fixes == 1
        assert "- ../../_include/author.yml" in qmd.read_text(encoding="utf-8")

    def test_a_run_directive_above_the_root_is_rewritten_into_it(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "docs"
        _write(tmp_path / "_include" / "_graphviz.py", "print(1)\n")
        _write(root / "_include" / "_graphviz.py", "print(1)\n")
        qmd = _document(
            root,
            "---\ntitle: Test\n---\n\n```{python}\n"
            "%run ../../../_include/_graphviz.py\n```\n",
        )

        fixes = self.resolver.fix_one_file(qmd, root, dry_run=False, verbose=False)

        assert fixes == 1
        assert "%run ../../_include/_graphviz.py" in qmd.read_text(encoding="utf-8")

    def test_a_reference_inside_the_root_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "docs"
        _write(tmp_path / "_include" / "author.yml", "author: []\n")
        _write(root / "nexus" / "notes" / "_include" / "author.yml", "author: []\n")
        text = (
            "---\ntitle: Test\nmetadata-files:\n"
            "  - ./_include/author.yml\n---\n\nBody.\n"
        )
        qmd = _document(root, text)

        fixes = self.resolver.fix_one_file(qmd, root, dry_run=False, verbose=False)

        assert fixes == 0
        assert qmd.read_text(encoding="utf-8") == text

    def test_an_escape_with_no_copy_in_the_root_is_reported(
        self, tmp_path: Path, capsys
    ) -> None:
        root = tmp_path / "docs"
        _write(tmp_path / "_include" / "author.yml", "author: []\n")
        text = (
            "---\ntitle: Test\nmetadata-files:\n"
            "  - ../../../_include/author.yml\n---\n\nBody.\n"
        )
        qmd = _document(root, text)

        fixes = self.resolver.fix_one_file(qmd, root, dry_run=False, verbose=False)

        assert fixes == 0
        assert qmd.read_text(encoding="utf-8") == text
        assert "OUTSIDE the docs root" in capsys.readouterr().out


class TestTheBoundaryForIncludes:
    resolver = IncludeResolver()

    def test_an_include_above_the_root_is_rewritten_into_it(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "docs"
        _write(tmp_path / "_include" / "_title_meta_items.qmd", "Meta.\n")
        _write(root / "_include" / "_title_meta_items.qmd", "Meta.\n")
        qmd = _document(
            root,
            "---\ntitle: Test\n---\n\n"
            "{{< include ../../../_include/_title_meta_items.qmd >}}\n",
        )

        fixes = self.resolver.fix_one_file(qmd, root, dry_run=False, verbose=False)

        assert fixes == 1
        assert (
            "{{< include ../../_include/_title_meta_items.qmd >}}"
            in qmd.read_text(encoding="utf-8")
        )

    def test_an_escape_with_no_copy_in_the_root_is_reported(
        self, tmp_path: Path, capsys
    ) -> None:
        root = tmp_path / "docs"
        _write(tmp_path / "_include" / "_title_meta_items.qmd", "Meta.\n")
        text = (
            "---\ntitle: Test\n---\n\n"
            "{{< include ../../../_include/_title_meta_items.qmd >}}\n"
        )
        qmd = _document(root, text)

        fixes = self.resolver.fix_one_file(qmd, root, dry_run=False, verbose=False)

        assert fixes == 0
        assert qmd.read_text(encoding="utf-8") == text
        assert "OUTSIDE the docs root" in capsys.readouterr().out
