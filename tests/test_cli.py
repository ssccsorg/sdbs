"""Tests for sdb.cli argument parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sdb.cli import main


def _run_main(argv: list[str]) -> int:
    """Run main() with the given argv and return the exit code.

    Catches SystemExit and returns the code.
    """
    try:
        main(argv)
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


class TestInitCommand:
    """Tests for the ``sdb init`` subcommand."""

    def test_init_defaults(self) -> None:
        """sdb init -> command='init', path=Path('docs'), force=False, template='default'."""
        with (
            patch("sdb.cli.init_module.scaffold") as mock_scaffold,
            patch("builtins.input", return_value="2"),
        ):
            mock_scaffold.return_value = True
            code = _run_main(["init"])
            assert code == 0
            mock_scaffold.assert_called_once_with(
                Path("docs"), force=False, template="default"
            )

    def test_init_custom_path_force(self) -> None:
        """sdb init /tmp/test --force -> path=Path('/tmp/test'), force=True."""
        with (
            patch("sdb.cli.init_module.scaffold") as mock_scaffold,
            patch("builtins.input", return_value="2"),
        ):
            mock_scaffold.return_value = True
            code = _run_main(["init", "/tmp/test", "--force"])
            assert code == 0
            mock_scaffold.assert_called_once_with(
                Path("/tmp/test"), force=True, template="default"
            )

    def test_init_template_advanced(self) -> None:
        """sdb init --template advanced -> template='advanced'."""
        with patch("sdb.cli.init_module.scaffold") as mock_scaffold:
            mock_scaffold.return_value = True
            code = _run_main(["init", "--template", "advanced"])
            assert code == 0
            mock_scaffold.assert_called_once_with(
                Path("docs"), force=False, template="advanced"
            )

    def test_init_failure_exit_code(self) -> None:
        """When scaffold returns False, sdb init should exit with code 1."""
        with (
            patch("sdb.cli.init_module.scaffold") as mock_scaffold,
            patch("builtins.input", return_value="2"),
        ):
            mock_scaffold.return_value = False
            code = _run_main(["init"])
            assert code == 1

    def test_init_force_and_template(self) -> None:
        """sdb init /my/path --force --template ssccs."""
        with patch("sdb.cli.init_module.scaffold") as mock_scaffold:
            mock_scaffold.return_value = True
            code = _run_main(
                ["init", "/my/path", "--force", "--template", "advanced"]
            )
            assert code == 0
            mock_scaffold.assert_called_once_with(
                Path("/my/path"), force=True, template="advanced"
            )


class TestBuildCommand:
    """Tests for the ``sdb build`` subcommand."""

    def test_build_defaults(self) -> None:
        """sdb build . --website -> command='build', docs_root=Path('.'), website=True, targets=['all']."""
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            mock_build.return_value = True
            code = _run_main(["build", ".", "--website"])
            assert code == 0

    def test_build_with_targets(self, tmp_path: Path) -> None:
        """sdb build <dir> whitepaper --website -j 4 -> targets=['whitepaper'], website=True, jobs=4."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.parse_targets") as mock_parse,
            patch("sdb.cli.build_module.validate_targets") as mock_validate,
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            mock_parse.return_value = ["whitepaper"]
            mock_validate.return_value = ["whitepaper"]
            mock_build.return_value = True
            code = _run_main(
                ["build", str(docs_root), "whitepaper", "--website", "-j", "4"]
            )
            assert code == 0
            mock_parse.assert_called_once_with(["whitepaper"])
            mock_build.assert_called_once()
            _kwargs = mock_build.call_args.kwargs
            assert _kwargs["max_jobs"] == 4  # type: ignore[index]
            assert _kwargs["website"] is True  # type: ignore[index]

    def test_build_all_implicit(self) -> None:
        """When no targets specified, defaults to ['all']."""
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            mock_build.return_value = True
            code = _run_main(["build"])
            assert code == 0
            # The 'all' target expands to BUILD_FUNCTIONS keys
            mock_build.assert_called_once()

    def test_clean_exit_zero(self, tmp_path: Path) -> None:
        """sdb clean <dir> triggers clean_quarto_artifacts."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.cli.build_module.clean_quarto_artifacts") as mock_clean:
            mock_clean.return_value = True
            code = _run_main(["clean", str(docs_root)])
            assert code == 0
            mock_clean.assert_called_once_with(docs_root.resolve())

    def test_clean_exit_one(self, tmp_path: Path) -> None:
        """When clean fails, exit code is 1."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.cli.build_module.clean_quarto_artifacts") as mock_clean:
            mock_clean.return_value = False
            code = _run_main(["clean", str(docs_root)])
            assert code == 1


class TestCheckCommand:
    """Tests for the ``sdb check`` subcommand."""

    def test_check_validate_only(self) -> None:
        """sdb check . --validate-only -> command='check', validate_only=True."""
        with patch("sdb.check.run_check") as mock_run_check:
            mock_run_check.return_value = True
            code = _run_main(["check", ".", "--validate-only"])
            assert code == 0
            mock_run_check.assert_called_once()

    def test_check_defaults(self) -> None:
        """sdb check -> docs_root=Path('.'), validate_only=False, cleanup_uncited=False."""
        with patch("sdb.check.run_check") as mock_run_check:
            mock_run_check.return_value = True
            code = _run_main(["check"])
            assert code == 0
            mock_run_check.assert_called_once_with(
                docs_root=Path(".").resolve(),
                validate_only=False,
                cleanup_uncited=False,
            )


class TestPreCommand:
    """Tests for the ``sdb pre`` subcommand."""

    def test_pre_defaults(self) -> None:
        """sdb pre -> calls _run_default_sequence with Pre-build phase."""
        with patch("sdb.build._run_default_sequence") as mock_seq:
            code = _run_main(["pre"])
            assert code == 0
            mock_seq.assert_called_once()
            args = mock_seq.call_args
            assert args[0][2] == "Pre-build"

    def test_pre_with_docs_root(self, tmp_path: Path) -> None:
        """sdb pre <dir> -> the resolved docs_root reaches _run_default_sequence."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.build._run_default_sequence") as mock_seq:
            code = _run_main(["pre", str(docs_root)])
            assert code == 0
            mock_seq.assert_called_once()
            args = mock_seq.call_args
            assert Path(args[0][1]) == docs_root.resolve()


class TestMissingDocsRoot:
    """A docs root that is not a directory stops the command.

    Every command takes the docs root from the command line, so a wrong path
    has to stop the command rather than walk nothing and report success.
    """

    @pytest.mark.parametrize(
        "command, delegated",
        [
            ("pre", "sdb.build._run_default_sequence"),
            ("check", "sdb.check.run_check"),
            ("build", "sdb.build.build_targets"),
            ("clean", "sdb.build.clean_quarto_artifacts"),
        ],
    )
    def test_a_missing_root_stops_before_the_work(
        self, tmp_path: Path, command: str, delegated: str, capsys
    ) -> None:
        absent = tmp_path / "absent"
        with patch(delegated) as mock_work:
            code = _run_main([command, str(absent)])
        assert code == 1
        mock_work.assert_not_called()
        captured = capsys.readouterr()
        assert f"sdb {command}: docs root is not a directory" in captured.err
        assert "absent" in captured.err

    def test_a_file_is_not_a_docs_root(self, tmp_path: Path) -> None:
        """A path that exists and is a document is still not a docs root."""
        document = tmp_path / "doc.qmd"
        document.write_text("---\ntitle: x\n---\n", encoding="utf-8")
        with patch("sdb.build._run_default_sequence") as mock_seq:
            code = _run_main(["pre", str(document)])
        assert code == 1
        mock_seq.assert_not_called()


class TestInvalidCommand:
    """When no valid command is provided, argparse should exit."""

    def test_no_command(self) -> None:
        """Running sdb with no subcommand should exit non-zero."""
        code = _run_main([])
        assert code != 0

    def test_unknown_command(self) -> None:
        """Running sdb with an unrecognised command should exit non-zero."""
        code = _run_main(["nonexistent"])
        assert code != 0
