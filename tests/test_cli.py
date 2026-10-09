"""Tests for sdb.cli argument parsing."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from sdb.cli import main
from sdb.deploy import DEFAULT_TIMEOUT


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
        root = tmp_path / "project"
        root.mkdir()
        with patch("sdb.deploy.run_deploy") as mock_deploy:
            mock_deploy.return_value = True
            code = _run_main(["deploy", str(root)])
            assert code == 0
            kwargs = mock_deploy.call_args.kwargs
            assert kwargs["dry_run"] is False
            assert kwargs["require_all"] is False
            assert kwargs["timeout"] == DEFAULT_TIMEOUT

    def test_deploy_flags(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        root.mkdir()
        with patch("sdb.deploy.run_deploy") as mock_deploy:
            mock_deploy.return_value = True
            code = _run_main(
                [
                    "deploy",
                    str(root),
                    "--dry-run",
                    "--require-all",
                    "--plugin-path",
                    "/x",
                    "--timeout",
                    "120",
                ]
            )
            assert code == 0
            kwargs = mock_deploy.call_args.kwargs
            assert kwargs["dry_run"] is True
            assert kwargs["require_all"] is True
            assert kwargs["extra_plugin_dirs"] == ["/x"]
            assert kwargs["timeout"] == 120

    def test_deploy_failure_exit_code(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        root.mkdir()
        with patch("sdb.deploy.run_deploy") as mock_deploy:
            mock_deploy.return_value = False
            code = _run_main(["deploy", str(root)])
            assert code == 1


class TestRenderCommand:
    """Tests for the ``sdb render`` subcommand.

    The search runs in the current directory unless a leading argument names one,
    and each document that rendered is assembled into the distribution it is
    published as, which is the role the removed ``sdb pub`` command carried.
    """

    def test_a_short_name_searches_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plain short name is looked up in the current directory."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("sdb.utils.quick_render.find_build_yml", return_value=None),
            patch(
                "sdb.utils.quick_render.resolve_and_render",
                return_value=(True, []),
            ) as mock_resolve,
        ):
            code = _run_main(["render", "map"])
        assert code == 0
        assert mock_resolve.call_args.args == (["map"], Path.cwd())

    def test_several_short_names_share_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a directory, every argument is a short name."""
        monkeypatch.chdir(tmp_path)
        with (
            patch("sdb.utils.quick_render.find_build_yml", return_value=None),
            patch(
                "sdb.utils.quick_render.resolve_and_render",
                return_value=(True, []),
            ) as mock_resolve,
        ):
            code = _run_main(["render", "map", "id"])
        assert code == 0
        assert mock_resolve.call_args.args == (["map", "id"], Path.cwd())

    def test_a_leading_directory_is_the_docs_root(self, tmp_path: Path) -> None:
        """A first argument that names a directory is the root, not a short name."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with (
            patch("sdb.utils.quick_render.find_build_yml", return_value=None),
            patch(
                "sdb.utils.quick_render.resolve_and_render",
                return_value=(True, []),
            ) as mock_resolve,
        ):
            code = _run_main(["render", str(docs_root), "map"])
        assert code == 0
        assert mock_resolve.call_args.args == (["map"], docs_root.resolve())

    def test_a_root_alone_is_not_enough(self, tmp_path: Path, capsys) -> None:
        """A directory with no short name following it has nothing to select."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        with patch("sdb.utils.quick_render.resolve_and_render") as mock_resolve:
            code = _run_main(["render", str(docs_root)])
        assert code != 0
        mock_resolve.assert_not_called()
        assert "no short name follows it" in capsys.readouterr().err

    def test_the_render_assembles_what_it_produced(self, tmp_path: Path) -> None:
        """A document that rendered is assembled into its distribution."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        document = docs_root / "map.qmd"
        with (
            patch("sdb.utils.quick_render.find_build_yml", return_value=None),
            patch(
                "sdb.utils.quick_render.resolve_and_render",
                return_value=(True, [document]),
            ),
            patch(
                "sdb.utils.quick_render.article_artifacts", return_value=3
            ) as mock_assemble,
        ):
            code = _run_main(["render", str(docs_root), "map"])
        assert code == 0
        assert mock_assemble.call_args.args == ([document],)

    def test_a_failed_render_assembles_nothing(self, tmp_path: Path) -> None:
        """A render that failed is not assembled into a distribution."""
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        document = docs_root / "map.qmd"
        with (
            patch("sdb.utils.quick_render.find_build_yml", return_value=None),
            patch(
                "sdb.utils.quick_render.resolve_and_render",
                return_value=(False, [document]),
            ),
            patch("sdb.utils.quick_render.article_artifacts") as mock_assemble,
        ):
            code = _run_main(["render", str(docs_root), "map"])
        assert code == 1
        mock_assemble.assert_not_called()


class TestBuildArticle:
    """Tests for the article output of ``sdb build``.

    The article is a build output rather than a separate command, and the
    former ``sdb dist`` command is gone rather than aliased.
    """

    TARGET_CONFIG = {"map": {"qmd": "map.qmd"}}

    def _docs(self, tmp_path: Path) -> Path:
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        (docs_root / "map.qmd").write_text("---\ntitle: m\n---\n", encoding="utf-8")
        return docs_root

    def test_article_renders_pdf_and_assembles(
        self, tmp_path: Path, capsys
    ) -> None:
        """sdb build <docs> --article renders pdf and assembles the distribution."""
        docs_root = self._docs(tmp_path)
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.TARGET_CONFIG", self.TARGET_CONFIG),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"map": lambda: True}),
            patch("sdb.cli.build_module.EXTERNAL_CONFIG", {}),
            patch("sdb.cli.build_module.run_pre_build_sequence") as mock_pre,
            patch(
                "sdb.utils.quick_render.render_qmd", return_value=True
            ) as mock_render,
            patch(
                "sdb.utils.quick_render.article_artifacts", return_value=3
            ) as mock_assemble,
        ):
            code = _run_main(["build", str(docs_root), "--article"])
        assert code == 0
        mock_pre.assert_called_once()
        assert mock_render.call_args.args[0] == docs_root / "map.qmd"
        assert mock_render.call_args.kwargs["format"] == "pdf"
        assert mock_assemble.call_args.args == ([docs_root / "map.qmd"], None)

    def test_article_places_the_distribution_where_asked(
        self, tmp_path: Path
    ) -> None:
        """--output-dir decides where an assembled distribution lands."""
        docs_root = self._docs(tmp_path)
        output_dir = tmp_path / "out"
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.TARGET_CONFIG", self.TARGET_CONFIG),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"map": lambda: True}),
            patch("sdb.cli.build_module.EXTERNAL_CONFIG", {}),
            patch("sdb.cli.build_module.run_pre_build_sequence"),
            patch("sdb.utils.quick_render.render_qmd", return_value=True),
            patch(
                "sdb.utils.quick_render.article_artifacts", return_value=1
            ) as mock_assemble,
        ):
            code = _run_main(
                ["build", str(docs_root), "--article", "-o", str(output_dir)]
            )
        assert code == 0
        assert mock_assemble.call_args.args == ([docs_root / "map.qmd"], output_dir)

    def test_a_failed_render_assembles_nothing(self, tmp_path: Path) -> None:
        """A render that failed is not assembled into a distribution."""
        docs_root = self._docs(tmp_path)
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.TARGET_CONFIG", self.TARGET_CONFIG),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"map": lambda: True}),
            patch("sdb.cli.build_module.EXTERNAL_CONFIG", {}),
            patch("sdb.cli.build_module.run_pre_build_sequence"),
            patch("sdb.utils.quick_render.render_qmd", return_value=False),
            patch("sdb.utils.quick_render.article_artifacts") as mock_assemble,
        ):
            code = _run_main(["build", str(docs_root), "--article"])
        assert code == 1
        mock_assemble.assert_not_called()

    def test_website_and_article_are_mutually_exclusive(
        self, tmp_path: Path, capsys
    ) -> None:
        """Two outputs for one invocation is a contradiction, so argparse refuses."""
        docs_root = self._docs(tmp_path)
        with patch("sdb.cli.build_module.initialize_config"):
            code = _run_main(
                ["build", str(docs_root), "--website", "--article"]
            )
        assert code != 0
        assert "not allowed with" in capsys.readouterr().err

    @pytest.mark.parametrize("flag", ["--sequence", "--jobs", "--parallel-formats"])
    def test_flags_that_do_not_apply_are_refused(
        self, tmp_path: Path, flag: str, caplog
    ) -> None:
        """A flag the article path does not use stops the run instead of being ignored."""
        docs_root = self._docs(tmp_path)
        argv = ["build", str(docs_root), "--article"]
        argv += [flag, "2"] if flag == "--jobs" else [flag]
        with (
            caplog.at_level(logging.ERROR),
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.utils.quick_render.render_qmd") as mock_render,
        ):
            code = _run_main(argv)
        assert code == 1
        mock_render.assert_not_called()
        assert flag in caplog.text

    def test_the_snapshot_target_does_not_apply(
        self, tmp_path: Path, caplog
    ) -> None:
        """'snapshot' refreshes the site cache, which an article build does not use."""
        docs_root = self._docs(tmp_path)
        with (
            caplog.at_level(logging.ERROR),
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.utils.quick_render.render_qmd") as mock_render,
        ):
            code = _run_main(["build", str(docs_root), "snapshot", "--article"])
        assert code == 1
        mock_render.assert_not_called()
        assert "snapshot" in caplog.text

    def test_dist_is_no_longer_a_command(self) -> None:
        """The article output replaced the command rather than aliasing it."""
        assert _run_main(["dist", "map"]) != 0

    def test_pub_is_no_longer_a_command(self) -> None:
        """The rename removed the old name rather than aliasing it."""
        code = _run_main(["pub", "map"])
        assert code != 0


class TestDeployEndToEnd:
    """The deploy command, wired through the engine and an external plugin.

    These run the command end to end, so they cover what the mocked dispatch
    tests leave out: the config load, plugin discovery, and the subprocess run.
    """

    def _project(self, tmp_path: Path) -> Path:
        root = tmp_path / "project"
        site = root / "docs" / "_site"
        site.mkdir(parents=True)
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "_deploy.yml").write_text(
            "deploy:\n"
            "  - plugin: echo\n"
            "    artifact: docs/_site\n"
            "    options:\n"
            "      bucket: b\n",
            encoding="utf-8",
        )
        plugin = root / "plugins" / "echo"
        plugin.mkdir(parents=True)
        (plugin / "manifest.yml").write_text(
            "manifest: 1\nname: echo\ncommand:\n  - python3\n  - run.py\n",
            encoding="utf-8",
        )
        (plugin / "run.py").write_text(
            "import json, sys\n"
            "json.loads(sys.stdin.read())\n"
            "print(json.dumps({'deploy': 1, 'ok': True, 'uploaded': 1}))\n",
            encoding="utf-8",
        )
        return root

    def test_a_deploy_runs_through_the_cli(self, tmp_path: Path) -> None:
        assert _run_main(["deploy", str(self._project(tmp_path))]) == 0

    def test_a_missing_artifact_fails(self, tmp_path: Path) -> None:
        root = self._project(tmp_path)
        (root / "docs" / "_site" / "index.html").unlink()
        (root / "docs" / "_site").rmdir()
        assert _run_main(["deploy", str(root)]) == 1

    def test_a_missing_optional_plugin_is_skipped(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        (root / "docs" / "_site").mkdir(parents=True)
        (root / "_deploy.yml").write_text(
            "deploy:\n  - plugin: absent\n    artifact: docs/_site\n", encoding="utf-8"
        )
        assert _run_main(["deploy", str(root)]) == 0

    def _documents_project(self, tmp_path: Path) -> Path:
        root = tmp_path / "project"
        site = root / "docs" / "_site"
        site.mkdir(parents=True)
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
        (site / "intro.pdf").write_text("%PDF", encoding="utf-8")
        (root / "_deploy.yml").write_text(
            "deploy:\n"
            "  - plugin: echo\n"
            "    documents: [pdf]\n"
            "    source: docs/_site\n",
            encoding="utf-8",
        )
        plugin = root / "plugins" / "echo"
        plugin.mkdir(parents=True)
        (plugin / "manifest.yml").write_text(
            "manifest: 1\nname: echo\ncommand:\n  - python3\n  - run.py\n",
            encoding="utf-8",
        )
        (plugin / "run.py").write_text(
            "import json, pathlib, sys\n"
            "request = json.loads(sys.stdin.read())\n"
            "artifact = pathlib.Path(request['artifact'])\n"
            "files = sorted(str(p.relative_to(artifact))\n"
            "               for p in artifact.rglob('*') if p.is_file())\n"
            "pathlib.Path('seen.json').write_text(json.dumps({\n"
            "    'artifact': str(artifact), 'files': files}))\n"
            "print(json.dumps({'deploy': 1, 'ok': True, 'uploaded': len(files)}))\n",
            encoding="utf-8",
        )
        return root

    def test_a_document_selection_runs_through_the_cli(self, tmp_path: Path) -> None:
        """What the plugin receives is the selection the engine composed."""
        root = self._documents_project(tmp_path)
        assert _run_main(["deploy", str(root)]) == 0
        seen = json.loads(
            (root / "plugins" / "echo" / "seen.json").read_text(encoding="utf-8")
        )
        assert seen["files"] == ["intro.pdf"]
        assert not Path(seen["artifact"]).exists()

    def test_a_selection_with_nothing_to_publish_fails(self, tmp_path: Path) -> None:
        """A build output holding no document stops the run rather than uploading none."""
        root = self._documents_project(tmp_path)
        (root / "docs" / "_site" / "intro.pdf").unlink()
        assert _run_main(["deploy", str(root)]) == 1


class TestPluginsCommand:
    """Tests for the ``sdb plugins`` subcommand."""

    def test_it_lists_a_found_plugin(self, tmp_path: Path, capsys) -> None:
        plugin = tmp_path / "plugins" / "echo"
        plugin.mkdir(parents=True)
        (plugin / "manifest.yml").write_text(
            "manifest: 1\nname: echo\ndescription: echo it\ncommand: [python3]\n",
            encoding="utf-8",
        )
        code = _run_main(["plugins", str(tmp_path)])
        assert code == 0
        assert "echo" in capsys.readouterr().out

    def test_no_plugins_reports(self, tmp_path: Path, capsys) -> None:
        code = _run_main(["plugins", str(tmp_path)])
        assert code == 0
        assert "No plugins" in capsys.readouterr().out
