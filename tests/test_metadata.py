"""Unit tests for the built-in LaTeX metadata generation step.

The scenarios mirror the documents that motivated the step, so a failure
here names the incident it would have caused.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import pytest

from sdb.utils.metadata import (
    CASE_ORDER,
    GENERATED_MACROS,
    MetadataPolicy,
    derive_affiliation_domain,
    derive_affiliation_url,
    escape_value,
    find_inputs,
    find_metadata_inputs,
    find_plain_references,
    front_matter_text,
    generate_metadata_tex,
    generate_metadata_for,
    guard_reference,
    has_guarded_reference,
    insert_reference,
    load_metadata_policy,
    named_contract_macros,
    parse_front_matter,
    render_metadata_tex,
    resolve_metadata_files,
    supply_affiliation_declaration,
)

AUTHOR_YML = """author:
  - name: Example Author
    email: lee@example.org
    role: "Founder & Architect"
    affiliations:
      - name: Project Alpha (pre-incorporation)
        url: https://test.example.org
        domain: test.example.org
"""

# An author file that carries no role and a foundation name.
FOUNDATION_AUTHOR = """author:
  - name: Example Foundation
    email: contact@example.org
    affiliations:
      - name: Example Foundation
        domain: example.org
        url: https://example.org
"""

# An author file that stores the ampersand already escaped.
ESCAPED_FOUNDER = """author:
  - name: Example Author
    orcid: 0000-0000-0000-0000
    email: lee@example.org
    role: "Founder \\\\& Architect"
    affiliations:
      - name: Example Foundation
        domain: example.org
        url: https://example.org
"""

# An author file that stores it raw.
RAW_FOUNDER = """author:
  - name: Example Author
    email: author@example.org
    role: "Founder & Architect"
    affiliations:
      - name: Project Beta (pre-incorporation)
        domain: example.org
        url: https://example.org
"""

# An author file whitepaper.qmd resolves: the affiliation name sits beside a
# domain and url.
WHITEPAPER_AUTHOR = """author:
  - name: Example Author
    role: "Founder and Architect"
    affiliations:
      - name: Example Systems (Pre-incorporation)
        domain: example.systems
        url: https://example.systems
"""

# An author file that states the url at author level, beside an affiliations
# entry that declares only a name.
AUTHOR_URL_KEY = """author:
  - name: Example Author
    corresponding: true
    email: lee@example.org
    role: "Founder & Architect"
    affiliation-name: Project Gamma (Pre-Incorporation)
    affiliation-url: https://gamma.example.org
    affiliations:
      - name: Project Gamma (Pre-Incorporation)
"""

# An author file that declares a name and nothing else.
AUTHOR_BLANK = """author:
  - name: Example Author
    corresponding: true
    email: author@example.org
    role: "Founder & Architect"
    affiliations:
      - name: Project Beta (pre-incorporation)
"""

# An affiliation that declares a domain but no url.
AUTHOR_DOMAIN_ONLY = """author:
  - name: Example Author
    email: lee@example.org
    affiliations:
      - name: Example Systems (Pre-incorporation)
        domain: example.systems
"""

# An affiliation that declares a url but no domain.
AUTHOR_URL_ONLY = """author:
  - name: Example Author
    email: lee@example.org
    affiliations:
      - name: Example Systems (Pre-incorporation)
        url: https://example.systems
"""

# The header the pitch document carries: the affiliation link is what
# consumes the two values the declaration has to supply.
AFFILIATION_HEADER = (
    "{\\normalsize \\texttt{\\href{\\affiliationurl}"
    "{\\affiliationdomain}} \\par}"
)


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


def _affiliation_document() -> str:
    """A document whose title page links with the affiliation macros."""
    return _document(header_extra=AFFILIATION_HEADER)


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
        assert escape_value("Example Author") == "Example Author"

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
        assert escape_value("https://test.example.org") == "https://test.example.org"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Example Author", "Example Author"),
            ("Example Foundation", "Example Foundation"),
            ("contact@example.org", "contact@example.org"),
            ("0000-0000-0000-0000", "0000-0000-0000-0000"),
            ("Founder & Architect", r"Founder \& Architect"),
            (r"Founder \& Architect", r"Founder \& Architect"),
            (
                "Widget (A product of Example Systems, Pre-incorporation)",
                "Widget (A product of Example Systems, Pre-incorporation)",
            ),
            ("widget_pitch", r"widget\_pitch"),
            ("widget.example.systems", "widget.example.systems"),
            ("https://widget.example.systems", "https://widget.example.systems"),
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

    def test_an_undeclared_name_is_not_returned(self) -> None:
        """The contract is the declared list, so a name outside it is not a
        contract macro even when it reads like one."""
        assert named_contract_macros("{\\large \\affiliationcity \\par}") == []


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
        assert "\\affiliationurl}{https://test.example.org}" in rendered

    def test_author_without_a_role(self, tmp_path: Path) -> None:
        """The author file declares no role and a foundation."""
        rendered = self._render(tmp_path, front=FOUNDATION_AUTHOR)
        assert "\\authorname}{Example Foundation}" in rendered
        assert "\\authorrole}{}" in rendered
        assert "\\affiliationname}{Example Foundation}" in rendered
        assert "\\affiliationdomain}{example.org}" in rendered

    def test_role_already_escaped(self, tmp_path: Path) -> None:
        """The role is stored escaped, and the escape must survive intact."""
        rendered = self._render(tmp_path, front=ESCAPED_FOUNDER)
        assert "\\authorrole}{Founder \\& Architect}" in rendered
        assert "\\orcid}{0000-0000-0000-0000}" in rendered
        assert "textbackslash" not in rendered

    def test_role_raw(self, tmp_path: Path) -> None:
        """The raw ampersand is stored, which the writer has to escape."""
        rendered = self._render(tmp_path, front=RAW_FOUNDER)
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
        "prefix", ["widget_pitch", "example_pitch", "sample_pitchdeck", "doc_prefix"]
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
        assert "Project Alpha (pre-incorporation)" in rendered

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
        _write(author, AUTHOR_YML.replace("Example Author", "Example Author (edited)"))
        future = time.time() + 10
        os.utime(author, (future, future))
        generate_metadata_tex(tmp_path)
        assert "Example Author (edited)" in target.read_text(encoding="utf-8")

    def test_names_macro_without_reference_is_repaired(self, tmp_path: Path) -> None:
        """A header that asks for the contract with no reference is the
        inconsistency that reaches LuaLaTeX as an undefined control sequence,
        so the reference is added and the file it names is generated."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(
            tmp_path / "doc.qmd",
            "---\nmetadata-files:\n  - ./_include/author.yml\n"
            "format:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        {\\large \\affiliationname \\par}\n---\n",
        )
        assert generate_metadata_tex(tmp_path) is True

        document = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert "\\input{./_files/doc_metadata.tex}" in document
        assert document.startswith("---\nmetadata-files:")

        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(encoding="utf-8")
        assert "\\affiliationname}{Project Alpha (pre-incorporation)}" in written
        # The stamp has to describe the repaired text, not the text before it.
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()[:6]
        assert digest in written.splitlines()[0]

    def test_a_header_that_opens_with_a_blank_line_is_repaired(
        self, tmp_path: Path
    ) -> None:
        """The shape a hand-edited header reaches: the literal block opens with
        a blank line and the reference has been taken out."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(
            tmp_path / "doc.qmd",
            "---\ntitle: T\nmetadata-files:\n  - ./_include/author.yml\n"
            "format:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \n"
            "        \\usepackage{xcolor}\n"
            "        {\\large \\affiliationname \\par}\n---\n\nBody.\n",
        )
        assert generate_metadata_tex(tmp_path) is True
        document = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert "\\IfFileExists{./_files/doc_metadata.tex}" in document
        assert "\\providecommand{\\affiliationname}{}" in document
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_a_plain_reference_is_guarded(self, tmp_path: Path, caplog) -> None:
        """An input that a render without sdbs would fail on is put behind a
        guard, and the stamp covers the guarded text."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(
            tmp_path / "doc.qmd",
            _document(header_extra="{\\large \\affiliationname \\par}"),
        )
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        document = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert "\\IfFileExists{./_files/doc_metadata.tex}" in document
        assert "\\providecommand{\\affiliationname}{}" in document
        digest = hashlib.sha256(document.encode("utf-8")).hexdigest()[:6]
        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(encoding="utf-8")
        assert digest in written.splitlines()[0]
        assert "Metadata[reference-unguarded]:" in " ".join(
            str(record.message) for record in caplog.records
        )

    def test_a_document_with_nothing_to_consume_is_guarded_too(
        self, tmp_path: Path
    ) -> None:
        """The input itself is what fails when the file is absent, so a
        document that declares no macro still gets the guard."""
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        assert generate_metadata_tex(tmp_path) is True
        document = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert "\\IfFileExists{./_files/doc_metadata.tex}" in document
        assert "\\providecommand" not in document

    def test_a_guarded_document_is_left_alone(self, tmp_path: Path, caplog) -> None:
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        guarded = _document(header_extra="{\\large \\affiliationname \\par}").replace(
            "        \\input{./_files/doc_metadata.tex}",
            "        \\IfFileExists{./_files/doc_metadata.tex}"
            "{\\input{./_files/doc_metadata.tex}}"
            "{\\providecommand{\\affiliationname}{}}",
        )
        _write(tmp_path / "doc.qmd", guarded)
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        assert (tmp_path / "doc.qmd").read_text(encoding="utf-8") == guarded
        assert not any(
            "reference-unguarded" in str(record.message)
            for record in caplog.records
        )

    def test_the_guard_case_can_be_switched_off(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "build.yml",
            "metadata:\n  disabled:\n    - reference-unguarded\n",
        )
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        assert generate_metadata_tex(tmp_path) is True
        document = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert "\\IfFileExists" not in document
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_the_guard_case_under_report_only_is_reported(
        self, tmp_path: Path, caplog
    ) -> None:
        _write(tmp_path / "build.yml", "metadata:\n  report_only: true\n")
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(record.message) for record in caplog.records)
        assert "Metadata[reference-unguarded]:" in message
        assert "report_only leaves it alone" in message
        assert "\\IfFileExists" not in (tmp_path / "doc.qmd").read_text(
            encoding="utf-8"
        )

    def test_a_reference_in_another_form_is_reported(
        self, tmp_path: Path, caplog
    ) -> None:
        """A flow scalar header offers no line to rewrite, so the document is
        reported rather than left to fail on a render without sdbs."""
        _write(
            tmp_path / "doc.qmd",
            "---\ntitle: T\nformat:\n  pdf:\n    include-in-header:\n"
            '      text: "\\input{./_files/doc_metadata.tex} '
            '{\\large \\affiliationname \\par}"\n---\n',
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(record.message) for record in caplog.records)
        assert "Metadata[reference-unguarded]:" in message
        assert "cannot rewrite" in message
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
        a series of documents does.  Which document supplies the stamp is
        stated once."""
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


class TestGuardReference:
    """guard_reference() puts an existing input behind \\IfFileExists."""

    def _document(self, header: str, indent: str = "        ") -> str:
        lines = (
            "---",
            'title: "Test"',
            "format:",
            "  pdf:",
            "    include-in-header:",
            "      text: |",
            indent + header,
            "---",
            "",
            "Body.",
            "",
        )
        return "\n".join(lines)

    def test_rewrites_a_plain_input(self) -> None:
        before = self._document("\\input{./_files/doc_metadata.tex}")
        after = guard_reference(before, ["affiliationname"])
        assert after is not None
        assert (
            "        \\IfFileExists{./_files/doc_metadata.tex}"
            "{\\input{./_files/doc_metadata.tex}}{\\GenericWarning" in after
        )
        assert "\\providecommand{\\affiliationname}{}" in after
        assert "\n        \\input{./_files/doc_metadata.tex}\n" not in after
        assert after.endswith("Body.\n")

    def test_guards_even_without_macro_names(self) -> None:
        """A document that consumes nothing still has to survive the absent
        file, because the input itself is what fails."""
        before = self._document("\\input{./_files/doc_metadata.tex}")
        after = guard_reference(before, [])
        assert after is not None
        assert "\\IfFileExists{./_files/doc_metadata.tex}" in after
        assert "\\providecommand" not in after

    def test_an_already_guarded_header_is_left_alone(self) -> None:
        before = self._document(
            "\\IfFileExists{./_files/doc_metadata.tex}"
            "{\\input{./_files/doc_metadata.tex}}{}"
        )
        assert guard_reference(before, ["affiliationname"]) is None

    def test_a_header_without_an_input_is_left_alone(self) -> None:
        before = self._document("{\\large \\affiliationname \\par}")
        assert guard_reference(before, ["affiliationname"]) is None

    def test_line_endings_are_preserved(self) -> None:
        before = self._document("\\input{./_files/doc_metadata.tex}").replace(
            "\n", "\r\n"
        )
        after = guard_reference(before, ["version"])
        assert after is not None
        assert after.count("\r\n") == before.count("\r\n")

    def test_the_readers_see_both_forms(self) -> None:
        plain = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \\input{./_files/a_metadata.tex}\n---\n"
        )
        guarded = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \\IfFileExists{./_files/a_metadata.tex}"
            "{\\input{./_files/a_metadata.tex}}{}\n---\n"
        )
        assert find_plain_references(plain) == ["./_files/a_metadata.tex"]
        assert find_plain_references(guarded) == []
        assert has_guarded_reference(guarded) is True
        assert has_guarded_reference(plain) is False


class TestInsertReference:
    """insert_reference() adds the line and touches nothing else."""

    def _document(self, header: str, indent: str = "        ") -> str:
        lines = (
            "---",
            'title: "Test"',
            "format:",
            "  pdf:",
            "    include-in-header:",
            "      text: |",
        ) + tuple(indent + line for line in header.splitlines()) + ("---", "", "Body.", "")
        return "\n".join(lines)

    def test_inserts_at_the_front_of_the_block(self) -> None:
        before = self._document("\\usepackage{microtype}\n{\\large \\affiliationname \\par}")
        after = insert_reference(before, "./_files/doc_metadata.tex")
        assert after is not None
        added = [line for line in after.splitlines() if line not in before.splitlines()]
        assert added == ["        \\input{./_files/doc_metadata.tex}"]
        assert after.index("\\input{") < after.index("\\usepackage")
        assert after.replace("        \\input{./_files/doc_metadata.tex}\n", "") == before

    def test_a_guarded_reference_declares_the_macros_empty(self) -> None:
        """A header that uses the contract can be rendered without sdbs, so the
        line declares those macros for the branch where the generated file does
        not exist yet."""
        before = self._document("{\\large \\affiliationname \\par}")
        after = insert_reference(
            before, "./_files/doc_metadata.tex", ["affiliationname", "version"]
        )
        assert after is not None
        assert (
            "        \\IfFileExists{./_files/doc_metadata.tex}"
            "{\\input{./_files/doc_metadata.tex}}" in after
        )
        assert "\\providecommand{\\affiliationname}{}" in after
        assert "\\providecommand{\\version}{}" in after
        # The degradation is stated rather than silent.
        assert "\\GenericWarning" in after

    def test_the_guard_keeps_the_reference_discoverable(self) -> None:
        """The discovery key is the ``\\input`` inside the guard, so the step
        still finds the document that asks for the file."""
        before = self._document("{\\large \\affiliationname \\par}")
        after = insert_reference(
            before, "./_files/doc_metadata.tex", ["affiliationname"]
        )
        assert after is not None
        block = front_matter_text(after)
        assert find_metadata_inputs(block) == ["./_files/doc_metadata.tex"]
        assert named_contract_macros(block) == ["affiliationname"]

    def test_ignores_a_block_that_names_no_macro(self) -> None:
        before = self._document("\\usepackage{microtype}")
        assert insert_reference(before, "./_files/doc_metadata.tex") is None

    def test_edits_every_block_that_needs_it(self) -> None:
        before = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        {\\large \\affiliationname \\par}\n"
            "  beamer:\n    include-in-header:\n      text: |\n"
            "        {\\scriptsize \\version \\par}\n---\n"
        )
        after = insert_reference(before, "./_files/doc_metadata.tex")
        assert after is not None
        assert after.count("\\input{./_files/doc_metadata.tex}") == 2

    def test_accepts_a_strip_chomping_block(self) -> None:
        before = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |-\n"
            "        {\\large \\affiliationname \\par}\n---\n"
        )
        assert insert_reference(before, "./_files/a_metadata.tex") is not None

    def test_copies_a_deeper_indentation(self) -> None:
        before = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "            {\\large \\authorrole \\par}\n---\n"
        )
        after = insert_reference(before, "./_files/a_metadata.tex")
        assert after is not None
        assert "            \\input{./_files/a_metadata.tex}" in after

    def test_no_front_matter_is_left_alone(self) -> None:
        assert insert_reference("# Heading\n", "./_files/a_metadata.tex") is None

    def test_a_flow_scalar_header_is_left_alone(self) -> None:
        before = (
            "---\nformat:\n  pdf:\n    include-in-header:\n"
            '      text: "{\\large \\affiliationname \\par}"\n---\n'
        )
        assert insert_reference(before, "./_files/a_metadata.tex") is None

    def test_a_block_that_opens_with_a_blank_line_is_editable(self) -> None:
        """A literal block may open with blank lines, which YAML keeps as
        content and which say nothing about the macros below them."""
        before = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \n"
            "        {\\large \\affiliationname \\par}\n---\n"
        )
        after = insert_reference(before, "./_files/doc_metadata.tex")
        assert after is not None
        lines = after.splitlines()
        assert lines[5].strip() == ""
        assert lines[6] == "        \\input{./_files/doc_metadata.tex}"
        assert lines[7] == "        {\\large \\affiliationname \\par}"

    def test_a_block_of_only_blank_lines_offers_nothing(self) -> None:
        before = (
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \n"
            "        \n---\n"
        )
        assert insert_reference(before, "./_files/doc_metadata.tex") is None

    def test_the_result_is_served_on_the_next_pass(self) -> None:
        """Once the line is in place, the reference is what discovery finds."""
        before = self._document("{\\large \\affiliationname \\par}")
        after = insert_reference(before, "./_files/doc_metadata.tex")
        assert after is not None
        assert find_metadata_inputs(front_matter_text(after)) == [
            "./_files/doc_metadata.tex"
        ]


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

    def test_pitch_is_repaired(self, tmp_path, caplog) -> None:
        r"""The pitch document named three macros with no reference line, so
        LuaLaTeX reported an undefined \affiliationname one line below
        \maketitle.  The header is repaired and the file it needs is written."""
        document = _document(
            reference=None,
            header_extra=(
                "{\\large \\@author \\affiliationname \\par}\n"
                "{\\normalsize \\texttt{\\href{\\affiliationurl}"
                "{\\affiliationdomain}} \\par}"
            ),
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True

        repaired = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert repaired.count("\\input{") == 1
        assert "\\input{./_files/doc_metadata.tex}" in repaired
        # The header uses the contract, so the guard declares those macros for a
        # render that never reaches sdbs.
        assert "\\IfFileExists{./_files/doc_metadata.tex}" in repaired
        assert "\\providecommand{\\affiliationname}{}" in repaired
        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(encoding="utf-8")
        for name in ("affiliationname", "affiliationurl", "affiliationdomain"):
            assert f"\\newcommand{{\\{name}}}" in written

    def test_a_header_that_cannot_be_edited_is_reported(
        self, tmp_path, caplog
    ) -> None:
        """A header written as a flow scalar offers no line to add, so the
        document is reported and left alone."""
        _write(
            tmp_path / "doc.qmd",
            "---\nformat:\n  pdf:\n    include-in-header:\n"
            '      text: "{\\large \\affiliationname \\par}"\n---\n',
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(r.message) for r in caplog.records)
        assert "affiliationname" in message
        assert not (tmp_path / "_files").exists()
        assert "\\input{" not in (tmp_path / "doc.qmd").read_text(encoding="utf-8")

    def test_repair_stays_out_when_another_input_is_missing(
        self, tmp_path, caplog
    ) -> None:
        """A header that already inputs something nothing creates has an
        ambiguous intent, so a second reference is not added."""
        _write(
            tmp_path / "doc.qmd",
            "---\nformat:\n  pdf:\n    include-in-header:\n      text: |\n"
            "        \\input{./_files/meta.tex}\n"
            "        {\\large \\affiliationname \\par}\n---\n",
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(r.message) for r in caplog.records)
        assert "_files/meta.tex" in message
        document = (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert document.count("\\input{") == 1
        assert not (tmp_path / "_files").exists()

    def test_whitepaper_needs_no_named_macro(self, tmp_path) -> None:
        r"""whitepaper.qmd names no macro: the watermark block the
        generated file carries is what consumes \version, so the reference
        alone has to be enough."""
        self._project(tmp_path, _document(reference="./_files/wp_metadata.tex"))
        generate_metadata_tex(tmp_path)
        written = (tmp_path / "_files" / "wp_metadata.tex").read_text(encoding="utf-8")
        assert "\\newcommand{\\version}" in written
        assert "\\backgroundsetup" in written

    def test_beamer_header_names_version(self, tmp_path, caplog) -> None:
        r"""A beamer document consumes \version in its
        title template without asking for the watermark."""
        document = _document(
            reference="./_files/pt_metadata.tex",
            fmt="beamer",
            prefix="foundation",
            version_mark=False,
            header_extra="{\\scriptsize \\texttt{\\color{lightgray}\\version} \\par}",
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        written = (tmp_path / "_files" / "pt_metadata.tex").read_text(encoding="utf-8")
        assert written.startswith("\\newcommand{\\version}{foundation-")
        assert "\\backgroundsetup" not in written
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_nested_document_writes_beside_itself(self, tmp_path) -> None:
        """A nested document keeps its generated file next to itself, as
        projects/section/chapter/map/index.qmd does."""
        document = _document(
            reference="./_files/kv_metadata.tex",
            metadata_files=("../../../../_include/author.yml",),
        )
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(
            tmp_path / "projects" / "section" / "chapter" / "map" / "index.qmd",
            document,
        )
        generate_metadata_tex(tmp_path)
        nested = tmp_path / "projects" / "section" / "chapter" / "map"
        assert (nested / "_files" / "kv_metadata.tex").is_file()
        assert not (tmp_path / "_files").exists()

    def test_absent_target_is_created(self, tmp_path) -> None:
        """Fifteen documents in the corpus referenced a file the tree lacks."""
        self._project(tmp_path, _document())
        assert not (tmp_path / "_files").exists()
        generate_metadata_tex(tmp_path)
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_stale_after_an_author_change(self, tmp_path) -> None:
        """wp_metadata.tex still declares Example Foundation while
        whitepaper.qmd resolves the author file."""
        _write(tmp_path / "_include" / "author.yml", FOUNDATION_AUTHOR)
        _write(
            tmp_path / "whitepaper.qmd",
            _document(reference="./_files/wp_metadata.tex"),
        )
        generate_metadata_tex(tmp_path)
        target = tmp_path / "_files" / "wp_metadata.tex"
        assert "Example Foundation" in target.read_text(encoding="utf-8")

        _write(tmp_path / "_include" / "author.yml", WHITEPAPER_AUTHOR)
        future = time.time() + 10
        os.utime(tmp_path / "_include" / "author.yml", (future, future))
        generate_metadata_tex(tmp_path)
        rewritten = target.read_text(encoding="utf-8")
        assert "Example Systems (Pre-incorporation)" in rewritten
        assert "Example Foundation" not in rewritten

    def test_output_of_a_project_hook_survives(self, tmp_path) -> None:
        """A project hook writes the same path at render time.  Its output is
        newer than the document, so the pre-build pass leaves it alone."""
        self._project(tmp_path, _document())
        generate_metadata_tex(tmp_path)
        target = tmp_path / "_files" / "doc_metadata.tex"
        hook_output = (
            "% written by a project hook\n"
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

    def test_a_name_outside_the_declared_list_passes_in_silence(
        self, tmp_path, caplog
    ) -> None:
        r"""The contract is the declared macro list, so a header that names a
        command the generator does not declare is not this step's to judge."""
        document = _document(
            reference=None,
            header_extra="{\\large \\affiliationcity \\par}",
        )
        self._project(tmp_path, document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not (tmp_path / "_files").exists()
        assert "\\input{" not in (tmp_path / "doc.qmd").read_text(encoding="utf-8")

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

    def test_two_documents_on_one_outside_target_report_once(
        self, tmp_path, caplog
    ) -> None:
        """The skip is per target, so the report is consolidated like the
        shared-target report rather than repeated per document."""
        reference = "../../shared/notes_metadata.tex"
        for name in ("a.qmd", "b.qmd"):
            _write(tmp_path / name, _document(reference))
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        reported = [
            str(record.message) for record in caplog.records
            if "outside the docs root" in str(record.message)
        ]
        assert len(reported) == 1, reported
        assert "2 document(s)" in reported[0]
        assert not (tmp_path / "_files").exists()

    def test_a_symlinked_document_is_skipped_as_a_document(
        self, tmp_path, caplog
    ) -> None:
        """A document resolving out of the tree is a document-level skip, not
        a bad reference reported against the document that points at it."""
        outside = _write(tmp_path.parent / "linked_source.qmd", _document())
        try:
            os.symlink(outside, tmp_path / "linked.qmd")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available in this environment")
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        message = " ".join(str(r.message) for r in caplog.records)
        assert "resolves outside the docs root" in message
        assert not (tmp_path / "_files").exists()

    def test_a_fresh_shared_target_is_not_rewritten_for_another_sharer(
        self, tmp_path
    ) -> None:
        """The first document in path order owns a shared target, so a second
        document that happens to be newer does not change it."""
        self._project(tmp_path, _document(), name="a.qmd")
        generate_metadata_tex(tmp_path)
        target = tmp_path / "_files" / "doc_metadata.tex"
        before = target.read_text(encoding="utf-8")
        _write(tmp_path / "b.qmd", _document())
        generate_metadata_tex(tmp_path)
        assert target.read_text(encoding="utf-8") == before

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
        assert "\\authorname}{Example Author}" in written

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


class TestMetadataPolicy:
    """A case can be switched off on its own, and every repair at once."""

    def test_absent_policy_repairs(self, tmp_path: Path) -> None:
        policy = load_metadata_policy(tmp_path)
        assert policy == MetadataPolicy()
        assert policy.is_enabled(CASE_ORDER[0])
        assert policy.may_repair(CASE_ORDER[0])

    def test_disabled_case_and_report_only_are_read(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "build.yml",
            "metadata:\n  disabled:\n    - affiliation-blank\n"
            "  report_only: true\n",
        )
        policy = load_metadata_policy(tmp_path)
        assert policy.is_enabled("reference-missing")
        assert not policy.is_enabled("affiliation-blank")
        assert not policy.may_repair("reference-missing")
        assert not policy.may_repair("affiliation-blank")

    def test_unknown_case_name_is_reported(self, tmp_path: Path, caplog) -> None:
        _write(tmp_path / "build.yml", "metadata:\n  disabled:\n    - typo-case\n")
        with caplog.at_level(logging.WARNING):
            policy = load_metadata_policy(tmp_path)
        message = " ".join(str(r.message) for r in caplog.records)
        assert "typo-case" in message
        assert "reference-missing" in message
        assert policy.is_enabled("reference-missing")

    def test_a_yml_without_the_block_uses_the_default(self, tmp_path: Path) -> None:
        _write(tmp_path / "build.yml", 'exclude:\n  - "**/skip/**"\n')
        assert load_metadata_policy(tmp_path) == MetadataPolicy()

    def test_invalid_build_yml_uses_the_default(self, tmp_path: Path, caplog) -> None:
        _write(tmp_path / "build.yml", "metadata: [not a mapping\n")
        with caplog.at_level(logging.WARNING):
            policy = load_metadata_policy(tmp_path)
        assert policy == MetadataPolicy()

    def test_disabled_case_repairs_nothing(self, tmp_path: Path) -> None:
        """A disabled case is off entirely rather than reported."""
        _write(
            tmp_path / "build.yml",
            "metadata:\n  disabled:\n    - metadata-file-missing-or-stale\n",
        )
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        assert generate_metadata_tex(tmp_path) is True
        assert not (tmp_path / "_files" / "doc_metadata.tex").exists()

    def test_report_only_writes_nothing(self, tmp_path: Path, caplog) -> None:
        _write(tmp_path / "build.yml", "metadata:\n  report_only: true\n")
        author = _write(tmp_path / "_include" / "author.yml", AUTHOR_URL_KEY)
        before = author.read_text(encoding="utf-8")
        _write(tmp_path / "doc.qmd", _affiliation_document())
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert not (tmp_path / "_files").exists()
        assert author.read_text(encoding="utf-8") == before
        message = " ".join(str(r.message) for r in caplog.records)
        assert "Metadata[metadata-file-missing-or-stale]:" in message
        assert "report_only leaves it alone" in message

    def test_report_only_still_reports_a_missing_reference(
        self, tmp_path, caplog
    ) -> None:
        _write(tmp_path / "build.yml", "metadata:\n  report_only: true\n")
        _write(
            tmp_path / "doc.qmd",
            _document(
                reference=None,
                header_extra="{\\large \\affiliationname \\par}",
            ),
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert "\\input{" not in (tmp_path / "doc.qmd").read_text(encoding="utf-8")
        assert any(
            str(r.message).startswith("Metadata[reference-missing]:")
            for r in caplog.records
        )


class TestAffiliationDerivation:
    """The derivation is a pure function of the declaration."""

    def test_url_is_left_alone_when_declared(self) -> None:
        assert derive_affiliation_url(
            {"affiliation-url": "https://author.example"},
            {"url": "https://affiliation.example"},
        ) == (None, None)

    def test_url_comes_from_the_author_key_before_the_domain(self) -> None:
        assert derive_affiliation_url(
            {"affiliation-url": "https://author.example"},
            {"domain": "affiliation.example"},
        ) == ("https://author.example", "affiliation-url-from-author-key")

    def test_url_comes_from_the_domain_with_https(self) -> None:
        assert derive_affiliation_url({}, {"domain": "example.systems"}) == (
            "https://example.systems",
            "affiliation-url-from-domain",
        )

    def test_nothing_to_derive(self) -> None:
        assert derive_affiliation_url({}, {"name": "Only a name"}) == (None, None)

    def test_domain_is_left_alone_when_declared(self) -> None:
        assert derive_affiliation_domain({"domain": "a.example"}, None) == (
            None,
            None,
        )

    def test_domain_comes_from_the_url(self) -> None:
        assert derive_affiliation_domain({}, "https://example.systems/x") == (
            "example.systems",
            "affiliation-domain-from-url",
        )

    def test_domain_from_a_url_without_a_host_is_not_derived(self) -> None:
        assert derive_affiliation_domain({}, "example.systems") == (None, None)

    def test_blank_values_are_treated_as_absent(self) -> None:
        assert derive_affiliation_url(
            {}, {"url": "   ", "domain": "a.example"}
        ) == ("https://a.example", "affiliation-url-from-domain")
        assert derive_affiliation_domain({"domain": "  "}, None) == (None, None)

    def test_a_document_that_links_no_macro_edits_nothing(self, tmp_path: Path) -> None:
        author = _write(tmp_path / "author.yml", AUTHOR_URL_KEY)
        before = author.read_text(encoding="utf-8")
        assert supply_affiliation_declaration(
            author, [], MetadataPolicy(), tmp_path
        ) is False
        assert author.read_text(encoding="utf-8") == before
        assert supply_affiliation_declaration(
            author, ["affiliationurl"], MetadataPolicy(), tmp_path
        ) is True
        assert "url: https://gamma.example.org" in author.read_text(encoding="utf-8")

    def test_the_macro_names_may_be_a_one_shot_iterable(self, tmp_path: Path) -> None:
        """The caller's macro names are consulted for both keys, so a
        generator has to be materialised rather than consumed once."""
        author = _write(tmp_path / "author.yml", AUTHOR_URL_KEY)
        assert supply_affiliation_declaration(
            author,
            iter(["affiliationurl", "affiliationdomain"]),
            MetadataPolicy(),
            tmp_path,
        ) is True
        declared = author.read_text(encoding="utf-8")
        assert "url: https://gamma.example.org" in declared
        assert "domain: gamma.example.org" in declared


class TestAffiliationDeclaration:
    """The url and domain a title page links with are supplied where declared."""

    def _project(self, tmp_path: Path, author: str) -> Path:
        _write(tmp_path / "_include" / "author.yml", author)
        _write(tmp_path / "doc.qmd", _affiliation_document())
        return tmp_path / "_include" / "author.yml"

    def test_url_and_domain_from_the_author_key(self, tmp_path, caplog) -> None:
        """The author file states the url at author level, beside an
        affiliations entry that declares only a name."""
        author = self._project(tmp_path, AUTHOR_URL_KEY)
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        declared = author.read_text(encoding="utf-8")
        assert "\n        url: https://gamma.example.org\n" in declared
        assert "\n        domain: gamma.example.org\n" in declared
        rendered = (tmp_path / "_files" / "doc_metadata.tex").read_text(
            encoding="utf-8"
        )
        assert "\\newcommand{\\affiliationurl}{https://gamma.example.org}" in rendered
        assert "\\newcommand{\\affiliationdomain}{gamma.example.org}" in rendered
        message = " ".join(str(r.message) for r in caplog.records)
        assert "Metadata[affiliation-url-from-author-key]:" in message
        assert "Metadata[affiliation-domain-from-url]:" in message

    def test_url_from_the_domain(self, tmp_path, caplog) -> None:
        author = self._project(tmp_path, AUTHOR_DOMAIN_ONLY)
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        declared = author.read_text(encoding="utf-8")
        assert "\n        url: https://example.systems\n" in declared
        # The domain is declared, so it is not derived beside the url.
        assert declared.count("domain:") == 1
        assert "Metadata[affiliation-url-from-domain]:" in " ".join(
            str(r.message) for r in caplog.records
        )

    def test_domain_from_the_url(self, tmp_path, caplog) -> None:
        author = self._project(tmp_path, AUTHOR_URL_ONLY)
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        declared = author.read_text(encoding="utf-8")
        assert "\n        domain: example.systems\n" in declared
        assert "Metadata[affiliation-domain-from-url]:" in " ".join(
            str(r.message) for r in caplog.records
        )

    def test_indentation_matches_the_siblings(self, tmp_path) -> None:
        """A deeper affiliations list keeps the indentation it uses."""
        author = self._project(
            tmp_path,
            "author:\n  - name: T\n    affiliations:\n"
            "          - name: Example Systems\n"
            "            domain: example.systems\n",
        )
        assert generate_metadata_tex(tmp_path) is True
        assert "\n            url: https://example.systems\n" in author.read_text(
            encoding="utf-8"
        )

    def test_blank_affiliation_is_reported_and_left_alone(
        self, tmp_path, caplog
    ) -> None:
        """The author file declares a name and nothing else, so there is
        nothing here to derive from."""
        author = self._project(tmp_path, AUTHOR_BLANK)
        before = author.read_text(encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert author.read_text(encoding="utf-8") == before
        message = " ".join(str(r.message) for r in caplog.records)
        assert "Metadata[affiliation-blank]:" in message
        assert "no url or domain" in message

    def test_declared_values_are_not_touched(self, tmp_path) -> None:
        author = self._project(tmp_path, AUTHOR_YML)
        before = author.read_text(encoding="utf-8")
        assert generate_metadata_tex(tmp_path) is True
        assert author.read_text(encoding="utf-8") == before

    def test_a_gap_the_header_does_not_link_is_not_reported(
        self, tmp_path, caplog
    ) -> None:
        """An affiliation link no header consumes is not a mismatch."""
        author = self._project(tmp_path, AUTHOR_BLANK)
        before = author.read_text(encoding="utf-8")
        _write(
            tmp_path / "doc.qmd",
            _document(header_extra="{\\large \\affiliationname \\par}"),
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert author.read_text(encoding="utf-8") == before
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_an_inline_affiliation_is_reported_and_left_alone(
        self, tmp_path, caplog
    ) -> None:
        """A supplied key goes into a metadata-files entry, because that is
        what the generator reads, so a document that declares the affiliation
        itself is reported rather than edited."""
        # The guard case rewrites the header, so it is switched off to isolate
        # what this case does to the document.
        _write(
            tmp_path / "build.yml",
            "metadata:\n  disabled:\n    - reference-unguarded\n",
        )
        document = (
            "---\n"
            'title: "Test"\n'
            "author:\n"
            "  - name: Example Author\n"
            "    affiliations:\n"
            "      - name: Example Foundation\n"
            "metadata-files:\n"
            "  - ./_include/other.yml\n"
            "format:\n"
            "  pdf:\n"
            "    include-in-header:\n"
            "      text: |\n"
            "        \\input{./_files/doc_metadata.tex}\n"
            f"        {AFFILIATION_HEADER}\n"
            "---\n"
            "\n"
            "Body.\n"
        )
        _write(tmp_path / "_include" / "other.yml", "csl: x\n")
        _write(tmp_path / "doc.qmd", document)
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert (tmp_path / "doc.qmd").read_text(encoding="utf-8") == document
        rendered = (tmp_path / "_files" / "doc_metadata.tex").read_text(
            encoding="utf-8"
        )
        assert "\\newcommand{\\affiliationurl}{}" in rendered
        message = " ".join(str(r.message) for r in caplog.records)
        assert "Metadata[affiliation-blank]:" in message

    def test_second_pass_changes_nothing(self, tmp_path) -> None:
        author = self._project(tmp_path, AUTHOR_URL_KEY)
        generate_metadata_tex(tmp_path)
        declared = author.read_text(encoding="utf-8")
        (tmp_path / "_files" / "doc_metadata.tex").write_text(
            "% marker\n", encoding="utf-8"
        )
        generate_metadata_tex(tmp_path)
        assert author.read_text(encoding="utf-8") == declared

    def test_a_disabled_case_leaves_the_declaration_alone(self, tmp_path) -> None:
        _write(
            tmp_path / "build.yml",
            "metadata:\n  disabled:\n    - affiliation-url-from-author-key\n",
        )
        author = self._project(tmp_path, AUTHOR_URL_KEY)
        before = author.read_text(encoding="utf-8")
        generate_metadata_tex(tmp_path)
        assert author.read_text(encoding="utf-8") == before


class TestCaseTags:
    """Every finding and repair names the case that produced it."""

    def test_an_unrepairable_reference_is_tagged(self, tmp_path, caplog) -> None:
        _write(
            tmp_path / "doc.qmd",
            "---\nformat:\n  pdf:\n    include-in-header:\n"
            '      text: "{\\large \\affiliationname \\par}"\n---\n',
        )
        with caplog.at_level(logging.WARNING):
            assert generate_metadata_tex(tmp_path) is True
        assert any(
            str(r.message).startswith("Metadata[reference-missing]:")
            for r in caplog.records
        )

    def test_a_write_is_tagged_as_its_case(self, tmp_path, caplog) -> None:
        _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
        _write(tmp_path / "doc.qmd", _document())
        with caplog.at_level(logging.INFO):
            assert generate_metadata_tex(tmp_path) is True
        records = [str(r.message) for r in caplog.records]
        assert any(
            m.startswith("Metadata[metadata-file-missing-or-stale]:")
            for m in records
        )
        assert any(m.endswith("(FIXING)") for m in records)
