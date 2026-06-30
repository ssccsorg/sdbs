"""Tests for LaTeX metadata generation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from sdb.utils import latex_escape


# =========================================================================
# Unit tests --- latex_escape
# =========================================================================


class TestLatexEscape:
    """sdb.utils.latex_escape() correctly escapes LaTeX special characters."""

    def test_ampersand(self) -> None:
        """& is escaped to \\&."""
        assert latex_escape("Founder & Architect") == "Founder \\& Architect"

    def test_backslash(self) -> None:
        """\\ is escaped to \\textbackslash{}."""
        assert latex_escape("foo\\bar") == "foo\\textbackslash{}bar"

    def test_percent(self) -> None:
        """% is escaped to \\%."""
        assert latex_escape("100%") == "100\\%"

    def test_dollar(self) -> None:
        """$ is escaped to \\$."""
        assert latex_escape("$10") == "\\$10"

    def test_hash(self) -> None:
        """# is escaped to \\#."""
        assert latex_escape("#1") == "\\#1"

    def test_underscore(self) -> None:
        """_ is escaped to \\_."""
        assert latex_escape("a_b") == "a\\_b"

    def test_curly_braces(self) -> None:
        """{ and } are escaped."""
        assert latex_escape("{hello}") == "\\{hello\\}"

    def test_tilde(self) -> None:
        """~ is escaped to \\textasciitilde{}."""
        assert latex_escape("~") == "\\textasciitilde{}"

    def test_caret(self) -> None:
        """^ is escaped to \\textasciicircum{}."""
        result = latex_escape("^")
        assert "textasciicircum" in result

    def test_multiple_special_chars(self) -> None:
        """Multiple special characters in one string are all escaped."""
        result = latex_escape("A&B&C")
        assert result == "A\\&B\\&C"

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert latex_escape("") == ""

    def test_no_special_chars(self) -> None:
        """Plain text without special chars is unchanged."""
        assert latex_escape("Hello World") == "Hello World"

    def test_role_with_ampersand(self) -> None:
        """Typical author role string with & is properly escaped."""
        result = latex_escape("Founder & Architect")
        assert result == "Founder \\& Architect"
        assert "&" not in result.replace("\\&", "")


# =========================================================================
# Integration tests --- generator script produces valid LaTeX
# =========================================================================


class TestGeneratorProducesValidLatex:
    """The _generate_metadata_tex.py script writes correctly escaped LaTeX."""

    @pytest.fixture
    def temp_dir(self) -> Generator[Path, None, None]:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "_include").mkdir(parents=True, exist_ok=True)
            yield Path(tmpdir)

    @pytest.fixture
    def generator_path(self) -> Path:
        return (
            Path(__file__).resolve().parent.parent
            / "src"
            / "sdb"
            / "templates"
            / "advanced"
            / "_include"
            / "_generate_metadata_tex.py"
        )

    def _create_test_qmd(
        self, tmpdir: Path, filename: str = "test.qmd"
    ) -> Path:
        content = """---
title: "Test Document"
author:
  - name: Test Author
    email: test@example.com
    role: "Founder & Architect"
    affiliations:
      - name: SSCCS Foundation
        url: https://ssccs.org
        domain: ssccs.org
---

# Hello

This is a test.
"""
        qmd_path = tmpdir / filename
        qmd_path.write_text(content)
        return qmd_path

    def test_generator_escapes_ampersand(
        self, temp_dir: Path, generator_path: Path
    ) -> None:
        """Generator produces \\& instead of raw & in role field."""
        qmd_path = self._create_test_qmd(temp_dir)
        out_file = temp_dir / "_files" / "pd_metadata.tex"

        result = subprocess.run(
            [
                sys.executable,
                str(generator_path),
                "--input", str(qmd_path),
                "--output", str(out_file),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Generator failed: {result.stderr}"
        assert out_file.exists()

        tex_content = out_file.read_text()
        assert "\\&" in tex_content, (
            f"Expected escaped \\&, got:\n{tex_content}"
        )
        raw_ampersand_lines = [
            line for line in tex_content.splitlines()
            if "&" in line and "\\&" not in line
        ]
        assert len(raw_ampersand_lines) == 0, (
            f"Unescaped & found in: {raw_ampersand_lines}"
        )

    def test_generator_handles_plain_text(
        self, temp_dir: Path, generator_path: Path
    ) -> None:
        """Roles without special chars are left untouched."""
        qmd_path = temp_dir / "plain.qmd"
        qmd_path.write_text("""---
title: "Plain"
author:
  - name: Test
    role: "Software Engineer"
---

# Plain
""")
        out_file = temp_dir / "_files" / "plain_metadata.tex"

        result = subprocess.run(
            [sys.executable, str(generator_path), "--input", str(qmd_path), "--output", str(out_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out_file.exists()
        assert "Software Engineer" in out_file.read_text()

    def test_generator_fails_on_missing_qmd(
        self, temp_dir: Path, generator_path: Path
    ) -> None:
        """Generator exits non-zero when input file is missing."""
        result = subprocess.run(
            [sys.executable, str(generator_path), "--input", str(temp_dir / "nonexistent.qmd"), "--output", str(temp_dir / "_files" / "out.tex")],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
