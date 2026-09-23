"""Unit tests for the built-in LaTeX metadata generation step.

The scenarios mirror the documents that motivated the step, so a failure
here names the incident it would have caused.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pytest

from sdb.utils.metadata import (
    GENERATED_MACROS,
    escape_value,
    find_inputs,
    find_metadata_inputs,
    front_matter_text,
    generate_metadata_tex,
    generate_metadata_for,
    named_contract_macros,
    parse_front_matter,
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

# ssccs/docs/_include/author.yml carries no role and a foundation name.
SSCCS_AUTHOR = """author:
  - name: SSCCS Foundation
    email: contact@ssccs.org
    affiliations:
      - name: SSCCS Foundation
        domain: ssccs.org
        url: https://ssccs.org
"""

# es/docs/_include/author.founder.yml stores the ampersand already escaped.
ES_FOUNDER = """author:
  - name: Taeho Lee
    orcid: 0009-0006-8767-8069
    email: lee@ssccs.org
    role: "Founder \\\\& Architect"
    affiliations:
      - name: SSCCS Foundation
        domain: ssccs.org
        url: https://ssccs.org
"""

# ct/docs/_include/author.founder.yml stores it raw.
CT_FOUNDER = """author:
  - name: Taeho Lee
    email: chton@ssccs.org
    role: "Founder & Architect"
    affiliations:
      - name: Project Chton (pre-incorporation)
        domain: ssccs.org
        url: https://ssccs.org
"""

# ktema/docs/_include/author.ktema.yml, which whitepaper.qmd resolves.
KTEMA_AUTHOR = """author:
  - name: Taeho Lee
    role: "Founder and Architect"
    affiliations:
      - name: Ktema Systems (Pre-incorporation)
        domain: ktema.systems
        url: https://ktema.systems
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _front_matter(path: Path) -> dict:
    parsed = parse_front_matter(path.read_text(encoding="utf-8"))
    assert parsed is not None, f"front matter of {path} is invalid"
    return parsed


def _document(
    reference: str | None = "./_files/doc_metadata.tex",
    *,
    prefix: str | None = "test_doc",
    version_mark: bool = True,
    fmt: str = "pdf",
    header_extra: str = "",
    metadata_files: tuple[str, ...] = ("./_include/author.yml",),
) -> str:
    lines = ["---", 'title: "Test"']
    if prefix is not None:
        lines.append(f"version-prefix: {prefix}")
    if version_mark:
        lines.append("version-mark: true")
    if metadata_files:
        lines.append("metadata-files:")
        lines += [f"  - {path}" for path in metadata_files]
    lines += ["format:", f"  {fmt}:", "    include-in-header:", "      text: |"]
    if reference is not None:
        lines.append(f"        \\input{{{reference}}}")
    if header_extra:
        lines += [f"        {line}" for line in header_extra.splitlines()]
    lines += ["---", "", "Body.", ""]
    return "\n".join(lines)


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

    def test_command_with_an_argument_survives(self) -> None:
        """A value that already carries LaTeX is not half-escaped."""
        assert escape_value(r"\textbackslash{}") == r"\textbackslash{}"

    def test_command_argument_survives_beside_a_raw_special(self) -> None:
        assert (
            escape_value(r"\textbf{Founder} & Architect")
            == r"\textbf{Founder} \& Architect"
        )

    def test_escaped_special_survives(self) -> None:
        assert escape_value(r"100\% of them") == r"100\% of them"

    def test_url_keeps_its_shape(self) -> None:
        assert escape_value("https://test.ssccs.org") == "https://test.ssccs.org"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Taeho Lee", "Taeho Lee"),
            ("SSCCS Foundation", "SSCCS Foundation"),
            ("contact@ssccs.org", "contact@ssccs.org"),
            ("0009-0006-8767-8069", "0009-0006-8767-8069"),
            ("Founder & Architect", r"Founder \& Architect"),
            (r"Founder \& Architect", r"Founder \& Architect"),
            (
                "Kletos (A product of Ktema Systems, Pre-incorporation)",
                "Kletos (A product of Ktema Systems, Pre-incorporation)",
            ),
            ("kletos_pitch", r"kletos\_pitch"),
            ("kletos.ktema.systems", "kletos.ktema.systems"),
            ("https://kletos.ktema.systems", "https://kletos.ktema.systems"),
            ("100%_done", r"100\%\_done"),
            (
                "a#b$c{d}e~f^g",
                r"a\#b\$c\{d\}e\textasciitilde{}f\textasciicircum{}g",
            ),
        ],
    )
    def test_values_taken_from_the_corpus(self, raw: str, expected: str) -> None:
        """Real author, affiliation, and prefix values survive intact."""
        assert escape_value(raw) == expected


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

    def test_crlf_line_endings(self) -> None:
        """A document written on another platform still yields its block."""
        assert front_matter_text("---\r\ntitle: A\r\n---\r\n") == "title: A\r\n"


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

    def test_reference_without_a_dot_slash(self) -> None:
        """A hand-written document may omit the leading ./ that the corpus uses."""
        assert find_metadata_inputs("\\input{_files/x_metadata.tex}") == [
            "_files/x_metadata.tex"
        ]

    def test_finds_every_input(self) -> None:
        block = "\\input{./_files/doc_metadata.tex}\n\\input{./_include/style.tex}\n"
        assert find_inputs(block) == [
            "./_files/doc_metadata.tex",
            "./_include/style.tex",
        ]
        assert find_metadata_inputs(block) == ["./_files/doc_metadata.tex"]

    def test_the_name_is_the_filter(self) -> None:
        """A reference that breaks the convention is invisible to generation."""
        assert find_inputs("\\input{./_files/meta.tex}") == ["./_files/meta.tex"]
        assert find_metadata_inputs("\\input{./_files/meta.tex}") == []

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
        merged, sources = resolve_metadata_files(_front_matter(qmd), qmd)
        assert merged["author"] == "from_qmd"
        assert merged["link-citations"] is True
        assert [p.name for p in sources] == ["a.yml", "b.yml"]

    def test_missing_file_is_skipped(self, tmp_path: Path) -> None:
        qmd = _write(
            tmp_path / "doc.qmd",
            "---\nmetadata-files:\n  - ./_include/absent.yml\n---\n",
        )
        merged, sources = resolve_metadata_files(_front_matter(qmd), qmd)
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
        merged, _ = resolve_metadata_files(_front_matter(qmd), qmd)
        return render_metadata_tex(merged, qmd)

    def test_declares_every_macro(self, tmp_path: Path) -> None:
        rendered = self._render(tmp_path)
        for name in GENERATED_MACROS:
            assert f"\\newcommand{{\\{name}}}{{" in rendered

    def test_escapes_specials_in_text_values(self, tmp_path: Path) -> None:
        rendered = self._render(tmp_path)
        assert "\\authorrole}{Founder \\& Architect}" in rendered
        assert "\\affiliationurl}{https://test.ssccs.org}" in rendered

    def test_ssccs_style_author_without_role(self, tmp_path: Path) -> None:
        """ssccs/docs/_include/author.yml declares no role and a foundation."""
        rendered = self._render(tmp_path, front=SSCCS_AUTHOR)
        assert "\\authorname}{SSCCS Foundation}" in rendered
        assert "\\authorrole}{}" in rendered
        assert "\\affiliationname}{SSCCS Foundation}" in rendered
        assert "\\affiliationdomain}{ssccs.org}" in rendered

    def test_es_style_role_already_escaped(self, tmp_path: Path) -> None:
        """es stores the role escaped, and the escape must survive intact."""
        rendered = self._render(tmp_path, front=ES_FOUNDER)
        assert "\\authorrole}{Founder \\& Architect}" in rendered
        assert "\\orcid}{0009-0006-8767-8069}" in rendered
        assert "textbackslash" not in rendered

    def test_ct_style_role_raw(self, tmp_path: Path) -> None:
        """ct stores the raw ampersand, which the writer has to escape."""
        rendered = self._render(tmp_path, front=CT_FOUNDER)
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

    @pytest.mark.parametrize(
        "prefix", ["kletos_pitch", "ktema_pitch", "es_pitchdeck", "doc_prefix"]
    )
    def test_version_prefixes_from_the_corpus(self, tmp_path: Path, prefix: str) -> None:
        """Every prefix in the corpus carries an underscore, so the stamp
        has to be escaped for the text-mode consumer in a title page."""
        qmd = _write(tmp_path / "doc.qmd", "---\ntitle: T\n---\n")
        rendered = render_metadata_tex({"version-prefix": prefix}, qmd)
        assert rendered.startswith(
            "\\newcommand{\\version}{" + prefix.replace("_", "\\_") + "-"
        )

    def test_version_without_a_prefix(self, tmp_path: Path) -> None:
        """A document that declares no version-prefix gets hash and date."""
        import re

        qmd = _write(tmp_path / "doc.qmd", "---\ntitle: T\n---\n")
        rendered = render_metadata_tex({}, qmd)
        assert re.match(
            r"\\newcommand\{\\version\}\{[0-9a-f]{6}-\d{6}\}", rendered
        )

    def test_declaration_order_matches_the_template_generator(self, tmp_path: Path) -> None:
        """The template generator writes the same order, so a project can
        switch between the two without churning the file."""
        import re

        names = re.findall(
            r"\\newcommand\{\\([a-z]+)\}", self._render(tmp_path)
        )
        assert names == list(GENERATED_MACROS)


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
        """Several documents in a directory may share one generated file, as
        the ssccs philosophy series and the es documents do.  The choice of
        which document supplies the stamp has to be stated once."""
        for name in ("a.qmd", "b.qmd", "c.qmd"):
            _write(tmp_path / name, _document())
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        messages = [str(r.message) for r in caplog.records]
        contests = [m for m in messages if "documents reference" in m]
        assert len(contests) == 1, contests
        assert "3 documents reference" in contests[0]
        assert "a.qmd" in contests[0] and "c.qmd" in contests[0]

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


# =========================================================================
# Scenarios drawn from the documents that motivated the step
# =========================================================================


class TestDocumentScenarios:
    """The incidents, and the variants the corpus actually contains."""

    def _project(
        self,
        tmp_path: Path,
        document: str,
        author: str = AUTHOR_YML,
        name: str = "doc.qmd",
    ) -> Path:
        _write(tmp_path / "_include" / "author.yml", author)
        _write(tmp_path / name, document)
        return tmp_path

    def test_kletos_pitch_reports_every_named_macro(self, tmp_path, caplog) -> None:
        r"""kletos/docs/pitch.qmd named three macros with no reference line,
        and LuaLaTeX reported only the first, one line below \maketitle."""
        document = _document(
            reference=None,
            header_extra=(
                "{\\large \\@author \\affiliationname \\par}\n"
                "{\\normalsize \\texttt{\\href{\\affiliationurl}"
                "{\\affiliationdomain}} \\par}"
            ),
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(r.message) for r in caplog.records)
        for name in ("affiliationname", "affiliationurl", "affiliationdomain"):
            assert name in message
        assert not (tmp_path / "_files").exists()

    def test_ktema_whitepaper_needs_no_named_macro(self, tmp_path) -> None:
        r"""ktema/docs/whitepaper.qmd names no macro: the watermark block the
        generated file carries is what consumes \version, so the reference
        alone has to be enough."""
        self._project(tmp_path, _document(reference="./_files/wp_metadata.tex"))
        generate_metadata_tex(tmp_path)
        written = (tmp_path / "_files" / "wp_metadata.tex").read_text(encoding="utf-8")
        assert "\\newcommand{\\version}" in written
        assert "\\backgroundsetup" in written

    def test_ssccs_pt_names_version_in_a_beamer_header(self, tmp_path, caplog) -> None:
        r"""ssccs/docs/works/pt.qmd is beamer and consumes \version in its
        title template without asking for the watermark."""
        document = _document(
            reference="./_files/pt_metadata.tex",
            fmt="beamer",
            prefix="ssccs",
            version_mark=False,
            header_extra="{\\scriptsize \\texttt{\\color{lightgray}\\version} \\par}",
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        written = (tmp_path / "_files" / "pt_metadata.tex").read_text(encoding="utf-8")
        assert written.startswith("\\newcommand{\\version}{ssccs-")
        assert "\\backgroundsetup" not in written
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_ssccs_nested_document_writes_beside_itself(self, tmp_path) -> None:
        """A nested document keeps its generated file next to itself, as
        projects/syntagma/tagma/map/index.qmd does."""
        document = _document(
            reference="./_files/kv_metadata.tex",
            metadata_files=("../../../../_include/author.yml",),
        )
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(
            tmp_path / "projects" / "syntagma" / "tagma" / "map" / "index.qmd",
            document,
        )
        generate_metadata_tex(tmp_path)
        nested = tmp_path / "projects" / "syntagma" / "tagma" / "map"
        assert (nested / "_files" / "kv_metadata.tex").is_file()
        assert not (tmp_path / "_files").exists()

    def test_absent_target_is_created(self, tmp_path) -> None:
        """Fifteen documents in the corpus referenced a file the tree lacks."""
        self._project(tmp_path, _document())
        assert not (tmp_path / "_files").exists()
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_stale_after_an_author_change(self, tmp_path) -> None:
        """ktema/docs/_files/wp_metadata.tex still declares SSCCS Foundation
        while whitepaper.qmd resolves author.ktema.yml."""
        _write(tmp_path / "_include" / "author.yml", SSCCS_AUTHOR)
        _write(
            tmp_path / "whitepaper.qmd",
            _document(reference="./_files/wp_metadata.tex"),
        )
        generate_metadata_tex(tmp_path)
        target = tmp_path / "_files" / "wp_metadata.tex"
        assert "SSCCS Foundation" in target.read_text(encoding="utf-8")

        _write(tmp_path / "_include" / "author.yml", KTEMA_AUTHOR)
        future = time.time() + 10
        os.utime(tmp_path / "_include" / "author.yml", (future, future))
        generate_metadata_tex(tmp_path)
        rewritten = target.read_text(encoding="utf-8")
        assert "Ktema Systems (Pre-incorporation)" in rewritten
        assert "SSCCS Foundation" not in rewritten

    def test_output_of_a_project_hook_survives(self, tmp_path) -> None:
        """A project hook writes the same path at render time.  Its output is
        newer than the document, so the pre-build pass leaves it alone."""
        self._project(tmp_path, _document())
        generate_metadata_tex(tmp_path)
        target = tmp_path / "_files" / "doc_metadata.tex"
        hook_output = (
            "% written by _quarto_pre-render.py\n"
            + target.read_text(encoding="utf-8")
        )
        target.write_text(hook_output, encoding="utf-8")
        generate_metadata_tex(tmp_path)
        assert target.read_text(encoding="utf-8") == hook_output

    def test_second_pass_changes_nothing(self, tmp_path) -> None:
        self._project(tmp_path, _document())
        generate_metadata_tex(tmp_path)
        target = tmp_path / "_files" / "doc_metadata.tex"
        before = (target.stat().st_mtime_ns, target.read_bytes())
        generate_metadata_tex(tmp_path)
        assert (target.stat().st_mtime_ns, target.read_bytes()) == before

    def test_two_references_in_one_document(self, tmp_path) -> None:
        document = _document(
            reference="./_files/a_metadata.tex",
            header_extra="\\input{./_files/b_metadata.tex}",
        )
        self._project(tmp_path, document)
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_files" / "a_metadata.tex").is_file()
        assert (tmp_path / "_files" / "b_metadata.tex").is_file()

    def test_relative_reference_without_a_dot_slash(self, tmp_path) -> None:
        self._project(tmp_path, _document(reference="_files/doc_metadata.tex"))
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_a_markdown_document_is_served(self, tmp_path) -> None:
        """Quarto renders .md alongside .qmd and sdbs treats both as source
        documents, so both can carry the reference."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "notes.md", _document(reference="./_files/notes_metadata.tex"))
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_files" / "notes_metadata.tex").is_file()

    def test_a_name_that_breaks_the_convention_is_reported(
        self, tmp_path, caplog
    ) -> None:
        """The name is the discovery key, so ./_files/meta.tex is served by
        nothing while the header's macros still need a definition."""
        document = _document(
            reference="./_files/meta.tex",
            header_extra="{\\large \\@author \\affiliationname \\par}",
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(r.message) for r in caplog.records)
        assert "_files/meta.tex" in message
        assert "does not end in _metadata.tex" in message
        assert not (tmp_path / "_files").exists()

    def test_an_existing_side_input_is_not_reported(self, tmp_path, caplog) -> None:
        """A hand-written file that the header also inputs is not this step's."""
        _write(tmp_path / "_include" / "style.tex", "% hand written\n")
        document = _document(
            header_extra=(
                "\\input{./_include/style.tex}\n"
                "{\\large \\@author \\affiliationname \\par}"
            ),
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_an_input_a_chunk_writes_is_not_reported(self, tmp_path, caplog) -> None:
        """A file a code chunk produces during the render has no contract
        macro beside it, so the report stays confined to the naming case."""
        document = _document(header_extra="\\input{./_files/from_chunk.tex}")
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_same_reference_twice_is_not_a_collision(self, tmp_path, caplog) -> None:
        """A document may repeat its own reference without tripping the guard
        that exists for two documents sharing one target."""
        document = _document(
            reference="./_files/doc_metadata.tex",
            header_extra="\\input{./_files/doc_metadata.tex}",
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_generated_trees_are_excluded(self, tmp_path) -> None:
        """Output and dependency trees carry copies that must not be served."""
        _write(
            tmp_path / "build.yml",
            'exclude:\n  - "**/*_files/"\n  - "**/*_cached/"\n  - "_archive/**"\n',
        )
        for tree in ("_site", "node_modules", "_cached", "_archive"):
            _write(tmp_path / tree / "doc.qmd", _document())
        generate_metadata_tex(tmp_path)
        for tree in ("_site", "node_modules", "_cached", "_archive"):
            assert not (tmp_path / tree / "_files" / "doc_metadata.tex").exists()


class TestDegradedInputs:
    """Inputs the step has to survive in a corpus of hand-written documents."""

    def test_parse_front_matter_signals_the_difference(self) -> None:
        assert parse_front_matter("---\ntitle: A\n---\n") == {"title": "A"}
        assert parse_front_matter("no front matter\n") == {}
        assert parse_front_matter('---\ntitle: "A\n---\n') is None

    def test_invalid_yaml_stops_generation(self, tmp_path, caplog) -> None:
        """A file of empty macros would degrade the title page in silence,
        which is worse than the missing file it replaces."""
        _write(
            tmp_path / "doc.qmd",
            '---\ntitle: "Test\nmetadata-files:\n  - ./_include/author.yml\n'
            "format:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \\input{./_files/doc_metadata.tex}\n---\n\nBody.\n",
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert any("invalid front matter" in r.message for r in caplog.records)
        assert not (tmp_path / "_files").exists()

    def test_missing_metadata_file_warns_and_the_chain_continues(
        self, tmp_path, caplog
    ) -> None:
        """A document can list a metadata file the tree does not carry."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(
            tmp_path / "doc.qmd",
            _document(
                metadata_files=("./_include/absent.yml", "./_include/author.yml")
            ),
        )
        with caplog.at_level(logging.WARNING):
            generate_metadata_tex(tmp_path)
        assert any("missing metadata file" in r.message for r in caplog.records)
        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(encoding="utf-8")
        assert "\\authorname}{Taeho Lee}" in written

    def test_document_without_front_matter_is_ignored(self, tmp_path) -> None:
        _write(tmp_path / "doc.qmd", "# Heading\n\nBody.\n")
        assert generate_metadata_tex(tmp_path) is True
        assert not (tmp_path / "_files").exists()

    def test_document_without_author_data(self, tmp_path) -> None:
        """A document that resolves no author still gets a well-formed file."""
        _write(tmp_path / "doc.qmd", _document(metadata_files=()))
        generate_metadata_tex(tmp_path)
        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(encoding="utf-8")
        assert "\\newcommand{\\authorname}{}" in written

    def test_byte_order_mark_front_matter_is_read(self, tmp_path) -> None:
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", "\ufeff" + _document())
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()
