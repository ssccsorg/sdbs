"""Unit tests for the footnote deduplication preprocessor."""

from __future__ import annotations

from pathlib import Path

from sdb.utils.footnotes import (
    clean_duplicate_footnotes,
    strip_duplicate_footnote_refs,
)


class TestStripDuplicateFootnoteRefs:
    """Core text-level behavior of strip_duplicate_footnote_refs."""

    def test_keeps_first_use_removes_rest(self) -> None:
        text = "Text[^tagma] and more[^tagma] again[^tagma].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "Text[^tagma] and more again.\n"
        assert removed == 2

    def test_no_duplicates_is_noop(self) -> None:
        text = "Text[^a] and more[^b].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == text
        assert removed == 0

    def test_distinct_labels_independent(self) -> None:
        text = "A[^a] B[^b] A[^a] B[^b].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "A[^a] B[^b] A B.\n"
        assert removed == 2

    def test_definition_never_removed(self) -> None:
        text = "Text[^a] and[^a].\n\n[^a]: The note.\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "Text[^a] and.\n\n[^a]: The note.\n"
        assert removed == 1

    def test_definition_does_not_mark_seen(self) -> None:
        text = "[^a]: The note.\n\nText[^a] and[^a].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "[^a]: The note.\n\nText[^a] and.\n"
        assert removed == 1

    def test_reference_inside_definition_body_counts(self) -> None:
        text = "Body[^b] text.\n\n[^a]: See [^b].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "Body[^b] text.\n\n[^a]: See.\n"
        assert removed == 1

    def test_front_matter_untouched(self) -> None:
        text = "---\ntitle: [^tagma]\n---\n\nText[^tagma] and[^tagma].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == (
            "---\ntitle: [^tagma]\n---\n\nText[^tagma] and.\n"
        )
        assert removed == 1

    def test_fenced_code_block_untouched(self) -> None:
        text = "Text[^a] and[^a].\n\n```\n[^a] [^a] [^a]\n```\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "Text[^a] and.\n\n```\n[^a] [^a] [^a]\n```\n"
        assert removed == 1

    def test_inline_code_span_untouched(self) -> None:
        text = "Use `[^a]` and text[^a] again[^a].\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "Use `[^a]` and text[^a] again.\n"
        assert removed == 1

    def test_escaped_reference_untouched(self) -> None:
        text = r"Literal \[^a] and text[^a] again[^a]." + "\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == r"Literal \[^a] and text[^a] again." + "\n"
        assert removed == 1

    def test_removal_consumes_adjacent_spaces(self) -> None:
        text = "word [^a] and [^a] more\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "word [^a] and more\n"
        assert removed == 1

    def test_removal_at_end_of_line_leaves_no_trailing_space(self) -> None:
        text = "sentence [^a]\nand [^a]\nnext line\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "sentence [^a]\nand\nnext line\n"
        assert removed == 1

    def test_removal_before_punctuation_collapses_space(self) -> None:
        text = "sentence [^a] ends. and [^a] ends.\n"
        cleaned, removed = strip_duplicate_footnote_refs(text)
        assert cleaned == "sentence [^a] ends. and ends.\n"
        assert removed == 1

    def test_empty_text_is_noop(self) -> None:
        cleaned, removed = strip_duplicate_footnote_refs("")
        assert cleaned == ""
        assert removed == 0


class TestCleanDuplicateFootnotes:
    """File-level behavior over a docs tree."""

    def _write(self, tmp_path: Path, rel: str, content: str) -> Path:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_only_qmd_files_processed(self, tmp_path: Path) -> None:
        self._write(tmp_path, "doc.qmd", "Text[^a] and[^a].\n")
        self._write(tmp_path, "doc.md", "Text[^a] and[^a].\n")
        clean_duplicate_footnotes(tmp_path)
        assert (
            (tmp_path / "doc.qmd").read_text(encoding="utf-8")
            == "Text[^a] and.\n"
        )
        assert (
            (tmp_path / "doc.md").read_text(encoding="utf-8")
            == "Text[^a] and[^a].\n"
        )

    def test_system_ignored_dirs_skipped(self, tmp_path: Path) -> None:
        self._write(tmp_path, "_site/doc.qmd", "Text[^a] and[^a].\n")
        self._write(tmp_path, "doc.qmd", "Text[^a] and[^a].\n")
        clean_duplicate_footnotes(tmp_path)
        assert (
            (tmp_path / "_site/doc.qmd").read_text(encoding="utf-8")
            == "Text[^a] and[^a].\n"
        )
        assert (
            (tmp_path / "doc.qmd").read_text(encoding="utf-8")
            == "Text[^a] and.\n"
        )

    def test_build_yml_excludes_honored(self, tmp_path: Path) -> None:
        self._write(tmp_path, "build.yml", "exclude:\n  - 'skip/'\n")
        self._write(tmp_path, "skip/doc.qmd", "Text[^a] and[^a].\n")
        self._write(tmp_path, "keep/doc.qmd", "Text[^a] and[^a].\n")
        clean_duplicate_footnotes(tmp_path)
        assert (
            (tmp_path / "skip/doc.qmd").read_text(encoding="utf-8")
            == "Text[^a] and[^a].\n"
        )
        assert (
            (tmp_path / "keep/doc.qmd").read_text(encoding="utf-8")
            == "Text[^a] and.\n"
        )
