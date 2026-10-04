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
            ("deploy", "sdb.deploy.run_deploy"),
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


class TestDeployCommand:
    """Tests for the ``sdb deploy`` subcommand."""

    def test_deploy_defaults(self, tmp_path: Path) -> None:
        """sdb deploy <dir> runs every channel without a filter."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.deploy.run_deploy") as mock_deploy:
            mock_deploy.return_value = True
            code = _run_main(["deploy", str(docs_root)])
            assert code == 0
            kwargs = mock_deploy.call_args.kwargs
            assert kwargs["channels"] is None
            assert kwargs["dry_run"] is False

    def test_deploy_channel_and_flags(self, tmp_path: Path) -> None:
        """--channel and --dry-run reach run_deploy."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.deploy.run_deploy") as mock_deploy:
            mock_deploy.return_value = True
            code = _run_main(
                [
                    "deploy",
                    str(docs_root),
                    "--channel",
                    "private-docs",
                    "--dry-run",
                ]
            )
            assert code == 0
            kwargs = mock_deploy.call_args.kwargs
            assert kwargs["channels"] == ["private-docs"]
            assert kwargs["dry_run"] is True

    def test_deploy_failure_exit_code(self, tmp_path: Path) -> None:
        """A channel that fails makes the command exit non-zero."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.deploy.run_deploy") as mock_deploy:
            mock_deploy.return_value = False
            code = _run_main(["deploy", str(docs_root)])
            assert code == 1


class TestDistCommand:
    """Tests for the ``sdb dist`` subcommand (the renamed pub)."""

    def test_dist_collects_artifacts(self, tmp_path: Path) -> None:
        """sdb dist renders the matches and assembles their artifacts."""
        rendered = [tmp_path / "map.qmd"]
        with (
            patch("sdb.utils.quick_render.find_build_yml", return_value=None),
            patch(
                "sdb.utils.quick_render.resolve_and_render",
                return_value=(True, rendered),
            ) as mock_resolve,
            patch("sdb.utils.quick_render.dist_artifacts") as mock_dist,
        ):
            mock_dist.return_value = 1
            code = _run_main(["dist", "map"])
            assert code == 0
            assert mock_resolve.call_args.kwargs["format"] == "pdf"
            mock_dist.assert_called_once_with(rendered)

    def test_pub_is_no_longer_a_command(self) -> None:
        """The rename removed the old name rather than aliasing it."""
        code = _run_main(["pub", "map"])
        assert code != 0


class TestDeployEndToEnd:
    """The deploy command, wired through the real engine and the s3 channel.

    These run the command end to end, so they cover the composition the mocked
    dispatch tests leave out: the registry, the config load, and the channel's
    own validation.
    """

    CONFIG = (
        "deploy:\n"
        "  - name: docs-private\n"
        "    plugin: s3\n"
        "    source: _site\n"
        "    options:\n"
        "      bucket: check-bucket\n"
    )

    def _docs_with_site(self, tmp_path: Path) -> Path:
        docs = tmp_path / "docs"
        (docs / "_site").mkdir(parents=True)
        (docs / "_site" / "index.html").write_text("<html></html>", encoding="utf-8")
        (docs / "build.yml").write_text(self.CONFIG, encoding="utf-8")
        return docs

    def test_a_dry_run_reaches_the_channel(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("S3_ENDPOINT", "https://example.invalid")
        monkeypatch.setenv("AWS_REGION", "region-1")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "check")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "check")
        code = _run_main(["deploy", str(self._docs_with_site(tmp_path)), "--dry-run"])
        assert code == 0

    def test_a_channel_that_cannot_run_fails(self, tmp_path: Path, monkeypatch) -> None:
        # No endpoint and no region: the channel refuses before any upload.
        monkeypatch.delenv("S3_ENDPOINT", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "check")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "check")
        code = _run_main(["deploy", str(self._docs_with_site(tmp_path)), "--dry-run"])
        assert code == 1

    def test_no_channels_is_a_failure(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        code = _run_main(["deploy", str(docs)])
        assert code == 1
