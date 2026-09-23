"""Unit tests for the built-in LaTeX metadata generation step."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from sdb.utils.metadata import (
    GENERATED_MACROS,
    escape_value,
    find_metadata_inputs,
    front_matter_text,
    generate_metadata_tex,
    generate_metadata_for,
    named_contract_macros,
    read_front_matter,
    render_metadata_tex,
    resolve_metadata_files,
)

AUTHOR_YML = """author:
  - name: Taeho Lee
    email: lee@ssccs.org
    role: "Founder & Architect"
    affiliations:
      - name: Project Test (pre-incorporation)
        url: https://test.ssccs.org
        domain: test.ssccs.org
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _document(reference: str = "./_files/doc_metadata.tex") -> str:
    return (
        "---\n"
        'title: "Test"\n'
        "version-prefix: test_doc\n"
        "version-mark: true\n"
        "metadata-files:\n"
        "  - ./_include/author.yml\n"
        "format:\n"
        "  pdf:\n"
        "    include-in-header:\n"
        "      text: |\n"
        f"        \\input{{{reference}}}\n"
        "---\n"
        "\n"
        "Body.\n"
    )


class TestEscapeValue:
    """escape_value() escapes raw specials and respects existing escapes."""

    def test_raw_ampersand_is_escaped(self) -> None:
        assert escape_value("Founder & Architect") == "Founder \\& Architect"

    def test_existing_escape_is_left_alone(self) -> None:
        assert escape_value("Founder \\& Architect") == "Founder \\& Architect"

    def test_underscore_and_percent(self) -> None:
        assert escape_value("100% a_b") == "100\\% a\\_b"
        assert escape_value("a\\_b") == "a\\_b"

    def test_braces_dollar_hash(self) -> None:
        assert escape_value("{x}$1#2") == "\\{x\\}\\$1\\#2"

    def test_tilde_and_caret(self) -> None:
        assert escape_value("a~b^c") == (
            "a\\textasciitilde{}b\\textasciicircum{}c"
        )

    def test_plain_text_unchanged(self) -> None:
        assert escape_value("Taeho Lee") == "Taeho Lee"

    def test_url_keeps_its_shape(self) -> None:
        assert escape_value("https://test.ssccs.org") == "https://test.ssccs.org"


class TestFrontMatterText:
    """front_matter_text() returns the raw YAML block."""

    def test_reads_block(self) -> None:
        text = "---\ntitle: A\n---\n\nBody.\n"
        assert front_matter_text(text) == "title: A\n"

    def test_strips_byte_order_mark(self) -> None:
        text = "\ufeff---\ntitle: A\n---\n"
        assert front_matter_text(text) == "title: A\n"

    def test_no_front_matter(self) -> None:
        assert front_matter_text("# Heading\n") == ""

    def test_unterminated_block(self) -> None:
        assert front_matter_text("---\ntitle: A\n") == ""


class TestFindMetadataInputs:
    """find_metadata_inputs() locates the generated file reference."""

    def test_finds_reference(self) -> None:
        block = "      text: |\n        \\input{./_files/doc_metadata.tex}\n"
        assert find_metadata_inputs(block) == ["./_files/doc_metadata.tex"]

    def test_finds_several_references(self) -> None:
        block = "\\input{./_files/a_metadata.tex}\n\\input{./_files/b_metadata.tex}\n"
        assert find_metadata_inputs(block) == [
            "./_files/a_metadata.tex",
            "./_files/b_metadata.tex",
        ]

    def test_ignores_other_inputs(self) -> None:
        assert find_metadata_inputs("\\input{./_include/style.tex}\n") == []

    def test_ignores_body_reference(self) -> None:
        text = "---\ntitle: A\n---\n\n\\input{./_files/doc_metadata.tex}\n"
        assert find_metadata_inputs(front_matter_text(text)) == []


class TestNamedContractMacros:
    """named_contract_macros() reports the macros a document names."""

    def test_detects_two_names(self) -> None:
        block = "{\\large \\@author , \\affiliationname \\par}\n{\\href{\\affiliationurl}{x}}\n"
        assert named_contract_macros(block) == [
            "affiliationname",
            "affiliationurl",
        ]

    def test_empty_when_absent(self) -> None:
        assert named_contract_macros("title: Test\n") == []

    def test_ignores_similar_plain_key(self) -> None:
        assert named_contract_macros("version-prefix: test_doc\n") == []


class TestResolveMetadataFiles:
    """resolve_metadata_files() merges the chain and reports the sources."""

    def test_merges_chain_and_front_matter_wins(self, tmp_path: Path) -> None:
        _write(tmp_path / "_include" / "a.yml", "author: from_a\nlink-citations: true\n")
        _write(tmp_path / "_include" / "b.yml", "author: from_b\n")
        qmd = _write(
            tmp_path / "doc.qmd",
            "---\nmetadata-files:\n  - ./_include/a.yml\n  - ./_include/b.yml\n"
            "author: from_qmd\n---\n",
        )
        merged, sources = resolve_metadata_files(read_front_matter(qmd), qmd)
        assert merged["author"] == "from_qmd"
        assert merged["link-citations"] is True
        assert [p.name for p in sources] == ["a.yml", "b.yml"]

    def test_missing_file_is_skipped(self, tmp_path: Path) -> None:
        qmd = _write(
            tmp_path / "doc.qmd",
            "---\nmetadata-files:\n  - ./_include/absent.yml\n---\n",
        )
        merged, sources = resolve_metadata_files(read_front_matter(qmd), qmd)
        assert sources == []
        assert merged == {"metadata-files": ["./_include/absent.yml"]}


class TestRenderMetadataTex:
    """render_metadata_tex() writes the macro contract."""

    def _render(
        self,
        tmp_path: Path,
        front: str = AUTHOR_YML,
        extra: str = "version-mark: true\n",
    ) -> str:
        _write(tmp_path / "_include" / "author.yml", front)
        qmd = _write(
            tmp_path / "doc.qmd",
            "---\nmetadata-files:\n  - ./_include/author.yml\n" + extra + "---\n",
        )
        merged, _ = resolve_metadata_files(read_front_matter(qmd), qmd)
        return render_metadata_tex(merged, qmd)

    def test_declares_every_macro(self, tmp_path: Path) -> None:
        rendered = self._render(tmp_path)
        for name in GENERATED_MACROS:
            assert f"\\newcommand{{\\{name}}}{{" in rendered

    def test_escapes_specials_in_text_values(self, tmp_path: Path) -> None:
        rendered = self._render(tmp_path)
        assert "\\authorrole}{Founder \\& Architect}" in rendered
        assert "\\affiliationurl}{https://test.ssccs.org}" in rendered

    def test_respects_pre_escaped_data(self, tmp_path: Path) -> None:
        """ssccs and es store the role escaped, and it must survive intact."""
        rendered = self._render(
            tmp_path,
            front=AUTHOR_YML.replace('"Founder & Architect"', '"Founder \\\\& Architect"'),
        )
        assert "\\authorrole}{Founder \\& Architect}" in rendered
        assert "textbackslash" not in rendered

    def test_version_carries_prefix_hash_and_date(self, tmp_path: Path) -> None:
        qmd = _write(
            tmp_path / "doc.qmd",
            "---\nversion-prefix: test_doc\n---\n",
        )
        rendered = render_metadata_tex({"version-prefix": "test_doc"}, qmd)
        version_line = rendered.splitlines()[0]
        assert version_line.startswith("\\newcommand{\\version}{test\\_doc-")
        assert len(version_line.split("-")[1]) == 6

    def test_version_mark_block_only_when_requested(self, tmp_path: Path) -> None:
        assert "\\backgroundsetup" in self._render(tmp_path)
        assert "\\backgroundsetup" not in self._render(tmp_path, extra="")


class TestGenerateMetadataTex:
    """generate_metadata_tex() writes only what a document references."""

    def _project(self, tmp_path: Path) -> Path:
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        return tmp_path / "_files" / "doc_metadata.tex"

    def test_writes_referenced_file(self, tmp_path: Path) -> None:
        target = self._project(tmp_path)
        assert generate_metadata_tex(tmp_path) is True
        assert target.is_file()
        rendered = target.read_text(encoding="utf-8")
        assert "Project Test (pre-incorporation)" in rendered

    def test_fresh_file_is_left_alone(self, tmp_path: Path) -> None:
        target = self._project(tmp_path)
        generate_metadata_tex(tmp_path)
        target.write_text("% hand edited\n", encoding="utf-8")
        generate_metadata_tex(tmp_path)
        assert target.read_text(encoding="utf-8") == "% hand edited\n"

    def test_regenerates_when_a_metadata_file_is_newer(self, tmp_path: Path) -> None:
        target = self._project(tmp_path)
        generate_metadata_tex(tmp_path)
        target.write_text("% stale marker\n", encoding="utf-8")
        author = tmp_path / "_include" / "author.yml"
        _write(author, AUTHOR_YML.replace("Taeho Lee", "Taeho Lee (edited)"))
        future = time.time() + 10
        os.utime(author, (future, future))
        generate_metadata_tex(tmp_path)
        assert "Taeho Lee (edited)" in target.read_text(encoding="utf-8")

    def test_names_macro_without_reference(self, tmp_path: Path, caplog) -> None:
        _write(
            tmp_path / "doc.qmd",
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        {\\large \\affiliationname \\par}\n---\n",
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert any("affiliationname" in r.message for r in caplog.records), (
            "expected a warning naming the macro"
        )
        assert not (tmp_path / "_files").exists()

    def test_reference_outside_root_is_skipped(self, tmp_path: Path, caplog) -> None:
        _write(
            tmp_path / "a" / "doc.qmd",
            _document("../../outside_doc_metadata.tex"),
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert any("outside the docs root" in r.message for r in caplog.records)
        assert not (tmp_path.parent / "outside_doc_metadata.tex").exists()

    def test_shared_target_is_reported(self, tmp_path: Path, caplog) -> None:
        _write(tmp_path / "a.qmd", _document())
        _write(tmp_path / "b.qmd", _document())
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert any("both reference" in r.message for r in caplog.records)

    def test_excluded_document_is_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path / "build.yml", 'exclude:\n  - "skip/**"\n')
        _write(tmp_path / "skip" / "doc.qmd", _document())
        generate_metadata_tex(tmp_path)
        assert not (tmp_path / "skip" / "_files" / "doc_metadata.tex").exists()

    def test_document_without_reference_creates_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path / "doc.qmd", "---\ntitle: T\n---\n\nBody.\n")
        assert generate_metadata_tex(tmp_path) is True
        assert not (tmp_path / "_files").exists()

    def test_output_path_is_the_referenced_one(self, tmp_path: Path) -> None:
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "sub" / "doc.qmd", _document("../_cached/other_metadata.tex"))
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_cached" / "other_metadata.tex").is_file()


class TestGenerateMetadataFor:
    """generate_metadata_for() serves only the documents it is given."""

    def test_only_given_documents_are_served(self, tmp_path: Path) -> None:
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "a.qmd", _document("./_files/a_metadata.tex"))
        _write(tmp_path / "b.qmd", _document("./_files/b_metadata.tex"))
        assert generate_metadata_for([tmp_path / "a.qmd"], tmp_path) is True
        assert (tmp_path / "_files" / "a_metadata.tex").is_file()
        assert not (tmp_path / "_files" / "b_metadata.tex").exists()

    def test_unresolved_path_under_root(self, tmp_path: Path) -> None:
        """A selection path and a resolved root can differ through a symlink."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        indirect = tmp_path / "sub" / ".." / "doc.qmd"
        assert generate_metadata_for([indirect], tmp_path) is True
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_document_outside_root_does_not_raise(self, tmp_path: Path) -> None:
        outside = _write(tmp_path.parent / "outside_root_doc.qmd", _document())
        assert generate_metadata_for([outside], tmp_path) is True
