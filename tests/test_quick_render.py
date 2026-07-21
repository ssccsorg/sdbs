"""Tests for sdb.utils.quick_render (``sdb render`` subcommand)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdb.utils.quick_render import find_qmd_files, quick_render, render_qmd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qmd_tree(tmp_path: Path) -> Path:
    """Create a temporary .qmd file tree simulating a small docs project.

    Layout::

        root/
          docs/
            projects/
              syntagma/
                tagma/
                  kv.qmd
                  index.qmd
                _include/
                  bench/
                    fig-bench-kv-batch.qmd
                    fig-bench-kv-bridge.qmd
                    fig-bench-kv-get.qmd
                    fig-bench-kv-insert.qmd
            whitepaper/
              whitepaper.qmd
    """
    files = {
        "docs/projects/syntagma/tagma/kv.qmd": "---\ntitle: KV\n---\n\nContent\n",
        "docs/projects/syntagma/tagma/index.qmd": "---\ntitle: Tagma\n---\n\nContent\n",
        "docs/projects/syntagma/_include/bench/fig-bench-kv-batch.qmd": "---\ntitle: KV Batch\n---\n",
        "docs/projects/syntagma/_include/bench/fig-bench-kv-bridge.qmd": "---\ntitle: KV Bridge\n---\n",
        "docs/projects/syntagma/_include/bench/fig-bench-kv-get.qmd": "---\ntitle: KV Get\n---\n",
        "docs/projects/syntagma/_include/bench/fig-bench-kv-insert.qmd": "---\ntitle: KV Insert\n---\n",
        "docs/whitepaper/whitepaper.qmd": "---\ntitle: Whitepaper\n---\n",
        "docs/reference/smartkv.qmd": "---\ntitle: SmartKV\n---\n",
    }
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


# ============================================================================
# find_qmd_files
# ============================================================================


class TestFindQmdFiles:
    """Tests for the file-search logic."""

    def test_no_qmd_files(self, tmp_path: Path) -> None:
        """Empty directory yields no matches."""
        assert find_qmd_files("any", root=tmp_path) == []

    def test_exact_match(self, qmd_tree: Path) -> None:
        """Stem exactly equals pattern."""
        matches = find_qmd_files("kv", root=qmd_tree)
        assert len(matches) >= 1
        assert matches[0].name == "kv.qmd"

    def test_exact_match_first_in_order(self, qmd_tree: Path) -> None:
        """Exact match is always first in the result list."""
        matches = find_qmd_files("kv", root=qmd_tree)
        assert matches[0].stem == "kv"

    def test_suffix_match(self, qmd_tree: Path) -> None:
        """Stem ends with pattern (but is not exact)."""
        matches = find_qmd_files("kv", root=qmd_tree)
        suffix_matches = [m for m in matches if m.stem != "kv" and m.stem.endswith("kv")]
        assert len(suffix_matches) == 1
        assert suffix_matches[0].stem == "smartkv"

    def test_substring_match(self, qmd_tree: Path) -> None:
        """Pattern appears anywhere in stem."""
        matches = find_qmd_files("paper", root=qmd_tree)
        assert len(matches) == 1
        assert matches[0].stem == "whitepaper"

    def test_path_fragment(self, qmd_tree: Path) -> None:
        """Pattern with slash is treated as relative path fragment."""
        matches = find_qmd_files("tagma/kv", root=qmd_tree)
        assert len(matches) == 1
        assert matches[0].name == "kv.qmd"

    def test_path_fragment_nested(self, qmd_tree: Path) -> None:
        """Pattern with deeper slash finds nested match."""
        matches = find_qmd_files("syntagma/tagma", root=qmd_tree)
        assert len(matches) == 2
        assert all("tagma" in str(m.relative_to(qmd_tree)) for m in matches)

    def test_no_match(self, qmd_tree: Path) -> None:
        """Pattern that matches nothing returns empty list."""
        assert find_qmd_files("nonexistent", root=qmd_tree) == []

    def test_match_prioritization(self, qmd_tree: Path) -> None:
        """Result order: exact > suffix > substring."""
        matches = find_qmd_files("kv", root=qmd_tree)
        assert matches[0].stem == "kv"  # exact first
        assert matches[1].stem == "smartkv"  # suffix second
        # Remainder are substring matches (none ends with 'kv')
        for i in range(2, len(matches)):
            assert not matches[i].stem.endswith("kv")

    def test_case_sensitivity(self, qmd_tree: Path) -> None:
        """Pattern matching is case-sensitive (stem comparison)."""
        matches_lower = find_qmd_files("kv", root=qmd_tree)
        matches_upper = find_qmd_files("KV", root=qmd_tree)
        assert len(matches_lower) > 0
        assert len(matches_upper) == 0

    def test_only_qmd_files_considered(self, tmp_path: Path) -> None:
        """Non-.qmd files are ignored."""
        (tmp_path / "notes.md").write_text("# Notes")
        (tmp_path / "data.txt").write_text("data")
        (tmp_path / "chapter.qmd").write_text("---\ntitle: C\n---\n")
        matches = find_qmd_files("chapter", root=tmp_path)
        assert len(matches) == 1
        assert matches[0].name == "chapter.qmd"

    def test_root_defaults_to_cwd(self) -> None:
        """When root is None, uses current working directory."""
        result = find_qmd_files("__no_such_file__")
        assert result == []

    def test_dot_in_stem(self, tmp_path: Path) -> None:
        """File stem containing a dot is handled correctly."""
        d = tmp_path / "sub"
        d.mkdir()
        (d / "my.file.qmd").write_text("---\n")
        (d / "my.file.test.qmd").write_text("---\n")
        matches = find_qmd_files("file", root=tmp_path)
        assert len(matches) == 2


# ============================================================================
# render_qmd
# ============================================================================


class TestRenderQmd:
    """Tests for single-file Quarto rendering."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Non-existent file returns False."""
        assert render_qmd(tmp_path / "nonexistent.qmd") is False

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_render_success(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Successful quarto render returns True."""
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\ntitle: T\n---\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Output created."
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        assert render_qmd(qmd) is True
        mock_run.assert_called_once()
        args, _ = mock_run.call_args
        assert args[0] == ["quarto", "render", str(qmd)]

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_render_failure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Failed quarto render returns False."""
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\n")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error!"
        mock_run.return_value = mock_result

        assert render_qmd(qmd) is False

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_render_with_format(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Format argument is passed as --to."""
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        assert render_qmd(qmd, format="pdf") is True
        args, _ = mock_run.call_args
        assert "--to" in args[0]
        to_idx = args[0].index("--to")
        assert args[0][to_idx + 1] == "pdf"

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_cwd_default_is_parent(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Default cwd is the file's parent directory."""
        nested = tmp_path / "sub"
        nested.mkdir()
        qmd = nested / "doc.qmd"
        qmd.write_text("---\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        assert render_qmd(qmd) is True
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == nested

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_cwd_explicit(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Explicit cwd is passed to subprocess."""
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\n")
        custom_cwd = tmp_path / "other"
        custom_cwd.mkdir()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        assert render_qmd(qmd, cwd=custom_cwd) is True
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == custom_cwd

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_quarto_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """FileNotFoundError from subprocess returns False."""
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\n")
        mock_run.side_effect = FileNotFoundError("quarto not found")

        assert render_qmd(qmd) is False

    @patch("sdb.utils.quick_render.subprocess.run")
    def test_unexpected_exception(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Generic exception returns False."""
        qmd = tmp_path / "doc.qmd"
        qmd.write_text("---\n")
        mock_run.side_effect = PermissionError("Access denied")

        assert render_qmd(qmd) is False


# ============================================================================
# quick_render (integration of find + render)
# ============================================================================


class TestQuickRender:
    """Tests for the orchestration layer."""

    @patch("sdb.utils.quick_render.render_qmd")
    def test_single_match_renders(self, mock_render: MagicMock, qmd_tree: Path) -> None:
        """Single match calls render_qmd once."""
        mock_render.return_value = True
        result = quick_render("whitepaper", root=qmd_tree, prompt=False)
        assert result is True
        mock_render.assert_called_once()
        args, _ = mock_render.call_args
        assert args[0].name == "whitepaper.qmd"

    @patch("sdb.utils.quick_render.render_qmd")
    def test_no_match(self, mock_render: MagicMock, qmd_tree: Path) -> None:
        """No matches returns False and does not render."""
        result = quick_render("nonexistent", root=qmd_tree)
        assert result is False
        mock_render.assert_not_called()

    @patch("sdb.utils.quick_render.render_qmd")
    def test_no_qmd_files_in_dir(self, mock_render: MagicMock, tmp_path: Path) -> None:
        """Directory with no .qmd files returns False."""
        result = quick_render("anything", root=tmp_path)
        assert result is False
        mock_render.assert_not_called()

    @patch("sdb.utils.quick_render.render_qmd")
    def test_multiple_matches_all_flag(
        self, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """With --all (prompt=False), all matches are rendered."""
        mock_render.return_value = True
        result = quick_render("kv", root=qmd_tree, prompt=False)
        assert result is True
        assert mock_render.call_count == 6

    @patch("sdb.utils.quick_render.render_qmd")
    def test_format_passed_to_render(
        self, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Format argument is forwarded to render_qmd."""
        mock_render.return_value = True
        quick_render("whitepaper", root=qmd_tree, format="pdf")
        _, kwargs = mock_render.call_args
        assert kwargs["format"] == "pdf"

    @patch("sdb.utils.quick_render.render_qmd")
    def test_root_passed_to_render(
        self, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Root directory is passed as cwd to render_qmd."""
        mock_render.return_value = True
        quick_render("whitepaper", root=qmd_tree)
        _, kwargs = mock_render.call_args
        assert kwargs["cwd"] == qmd_tree

    @patch("sdb.utils.quick_render.render_qmd")
    def test_partial_failure(self, mock_render: MagicMock, qmd_tree: Path) -> None:
        """If one render fails, quick_render returns False but continues."""
        mock_render.side_effect = [True, False, True, True, True, True]
        result = quick_render("kv", root=qmd_tree, prompt=False)
        assert result is False
        assert mock_render.call_count == 6

    @patch("sdb.utils.quick_render.render_qmd")
    def test_defaults_to_cwd(self, mock_render: MagicMock) -> None:
        """When root is None, uses Path.cwd()."""
        mock_render.return_value = True
        result = quick_render("__no_match__")
        assert result is False
        mock_render.assert_not_called()

    # --- prompt behaviour ---------------------------------------------------

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_prompt_select_first_on_enter(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Pressing Enter (empty string) selects the first match."""
        mock_render.return_value = True
        mock_input.return_value = ""
        result = quick_render("kv", root=qmd_tree, prompt=True)
        assert result is True
        mock_render.assert_called_once()
        assert mock_render.call_args[0][0].name == "kv.qmd"

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_prompt_select_by_number(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Typing a valid number selects that match."""
        mock_render.return_value = True
        mock_input.return_value = "3"
        result = quick_render("kv", root=qmd_tree, prompt=True)
        assert result is True
        mock_render.assert_called_once()
        called_path = mock_render.call_args[0][0]
        assert called_path.stem != "kv"

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_prompt_select_all(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Typing 'a' selects all matches."""
        mock_render.return_value = True
        mock_input.return_value = "a"
        result = quick_render("kv", root=qmd_tree, prompt=True)
        assert result is True
        assert mock_render.call_count == 6

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_prompt_cancel(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Typing 'q' cancels without rendering."""
        mock_input.return_value = "q"
        result = quick_render("kv", root=qmd_tree, prompt=True)
        assert result is False
        mock_render.assert_not_called()

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_prompt_retry_on_invalid(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path
    ) -> None:
        """Invalid input causes retry, then valid input succeeds."""
        mock_render.return_value = True
        mock_input.side_effect = ["99", "invalid", "1"]
        result = quick_render("kv", root=qmd_tree, prompt=True)
        assert result is True
        mock_render.assert_called_once()
        assert mock_render.call_args[0][0].name == "kv.qmd"

    # --- label (progress indicator) -----------------------------------------

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_label_in_prompt_header(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path, capsys
    ) -> None:
        """When label is given, it appears in the prompt header."""
        mock_render.return_value = True
        mock_input.return_value = ""  # enter = first match
        result = quick_render("kv", root=qmd_tree, prompt=True, label="1/3")
        assert result is True
        captured = capsys.readouterr()
        assert "[1/3]" in captured.out

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_label_in_hint(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path, capsys
    ) -> None:
        """When label is given, it appears in the selection hint."""
        mock_render.return_value = True
        mock_input.return_value = ""
        result = quick_render("kv", root=qmd_tree, prompt=True, label="2/2")
        assert result is True
        captured = capsys.readouterr()
        assert "[2/2]" in captured.out

    @patch("sdb.utils.quick_render.render_qmd")
    @patch("builtins.input")
    def test_label_omitted_when_none(
        self, mock_input: MagicMock, mock_render: MagicMock, qmd_tree: Path, capsys
    ) -> None:
        """When label is None, no bracket prefix is printed."""
        mock_render.return_value = True
        mock_input.return_value = ""
        result = quick_render("kv", root=qmd_tree, prompt=True, label=None)
        assert result is True
        captured = capsys.readouterr()
        assert "[None]" not in captured.out
        assert "Multiple files match" in captured.out

    @patch("sdb.utils.quick_render.render_qmd")
    def test_label_ignored_when_prompt_false(
        self, mock_render: MagicMock, qmd_tree: Path, capsys
    ) -> None:
        """Label has no effect when prompt is False (--all mode)."""
        mock_render.return_value = True
        result = quick_render("kv", root=qmd_tree, prompt=False, label="1/3")
        assert result is True
        captured = capsys.readouterr()
        assert "[1/3]" not in captured.out
        assert mock_render.call_count == 6
