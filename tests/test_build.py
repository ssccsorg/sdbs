"""Tests for the isolated docs copy a website parallel build renders from.

``sdb build --website -j N`` copies the docs root per target and renders from
the copy.  The copy excludes ``_files/``, because that is generated output, so
the metadata file a title page inputs has to be written again inside it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sdb.build import prepare_isolated_docs

AUTHOR_YML = """author:
  - name: Example Author
    email: lee@example.org
    affiliations:
      - name: Example Foundation
        domain: example.org
        url: https://example.org
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _document(reference: str | None = "./_files/doc_metadata.tex") -> str:
    lines = [
        "---",
        'title: "Test"',
        "version-prefix: test_doc",
        "metadata-files:",
        "  - ./_include/author.yml",
        "format:",
        "  pdf:",
        "    include-in-header:",
        "      text: |",
    ]
    if reference is not None:
        lines.append(f"        \\input{{{reference}}}")
    lines += [
        "        {\\large \\affiliationname \\par}",
        "---",
        "",
        "Body.",
        "",
    ]
    return "\n".join(lines)


def _copied_tree(tmp_path: Path, document: str) -> Path:
    """The tree a website build renders from, with no generated directory."""
    _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
    _write(tmp_path / "build.yml", 'exclude:\n  - "**/*_files/"\n')
    _write(tmp_path / "doc.qmd", document)
    return tmp_path


class TestPrepareIsolatedDocs:
    """prepare_isolated_docs() serves a target inside its own copy."""

    def test_writes_the_metadata_file_the_header_inputs(self, tmp_path: Path) -> None:
        _copied_tree(tmp_path, _document())
        prepare_isolated_docs(tmp_path, "doc.qmd")
        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(
            encoding="utf-8"
        )
        assert "\\newcommand{\\affiliationname}{Example Foundation}" in written

    def test_repairs_a_header_that_names_a_macro_without_a_reference(
        self, tmp_path: Path
    ) -> None:
        """The incident state reaches the copy too, so the reference the
        header needs is inserted there rather than only in the original."""
        _copied_tree(tmp_path, _document(reference=None))
        prepare_isolated_docs(tmp_path, "doc.qmd")
        assert "\\input{./_files/doc_metadata.tex}" in (
            tmp_path / "doc.qmd"
        ).read_text(encoding="utf-8")
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_a_document_that_asks_for_nothing_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        _copied_tree(tmp_path, "---\ntitle: T\n---\n\nBody.\n")
        prepare_isolated_docs(tmp_path, "doc.qmd")
        assert not (tmp_path / "_files").exists()

    def test_a_target_without_a_document_is_a_no_op(self, tmp_path: Path) -> None:
        _copied_tree(tmp_path, _document())
        prepare_isolated_docs(tmp_path, None)
        prepare_isolated_docs(tmp_path, "")
        assert not (tmp_path / "_files").exists()

    def test_a_document_absent_from_the_copy_is_a_no_op(self, tmp_path: Path) -> None:
        _copied_tree(tmp_path, _document())
        prepare_isolated_docs(tmp_path, "elsewhere/doc.qmd")
        assert not (tmp_path / "_files").exists()

    def test_a_failure_is_reported_rather_than_raised(
        self, tmp_path: Path, caplog, monkeypatch
    ) -> None:
        """A metadata failure must not take the copy down, which would abort
        the whole build; the render reports the missing file instead."""
        _copied_tree(tmp_path, _document())

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("sdb.build.generate_metadata_for", _boom)
        with caplog.at_level(logging.WARNING):
            prepare_isolated_docs(tmp_path, "doc.qmd")
        assert any(
            "Metadata generation failed" in str(record.message)
            for record in caplog.records
        )
