"""Tests for built-in default pre/post commands in sdb.build."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdb.build import (
    _DEFAULT_PRE_BUILD,
    _DEFAULT_POST_RENDER,
    _run_default_sequence,
    _run_config_commands,
    build_targets,
    run_pre_build_commands,
    run_post_render_commands,
)


class TestDefaultCommandConstants:
    """Built-in default sequences contain expected entries."""

    def test_pre_build_has_callable_generate_latest(self) -> None:
        from sdb.utils.latest import generate_latest_docs
        assert generate_latest_docs in _DEFAULT_PRE_BUILD

    def test_pre_build_has_callable_resolve_all(self) -> None:
        from sdb.resolve import resolve_all
        assert resolve_all in _DEFAULT_PRE_BUILD

    def test_pre_build_has_callable_clean_duplicate_footnotes(self) -> None:
        from sdb.utils.footnotes import clean_duplicate_footnotes
        assert clean_duplicate_footnotes in _DEFAULT_PRE_BUILD

    def test_pre_build_has_rumdl(self) -> None:
        assert ["rumdl", "fmt", ".", "--silent", "--disable", "MD036"] in _DEFAULT_PRE_BUILD

    def test_metadata_generation_runs_last(self) -> None:
        """The version stamp must cover the text after formatting."""
        from sdb.utils.metadata import generate_metadata_tex
        assert _DEFAULT_PRE_BUILD[-1] is generate_metadata_tex

    def test_post_render_has_generate_llms(self) -> None:
        from sdb.utils.llms import generate_llms_txt
        assert generate_llms_txt in _DEFAULT_POST_RENDER


class TestRunPreBuildCommandsNoDefaults:
    """run_pre_build_commands no longer injects defaults internally."""

    def test_empty_config_runs_nothing(
        self, docs_root: Path
    ) -> None:
        with patch("sdb.build._run_config_commands") as mock_run:
            run_pre_build_commands({}, docs_root)
            mock_run.assert_called_once_with(
                [],
                docs_root,
                "Pre-build",
                target_name=None,
            )

    def test_user_commands_still_executed(
        self, docs_root: Path
    ) -> None:
        config = {"pre_build": [["echo", "user"]]}
        with patch("sdb.build._run_config_commands") as mock_run:
            run_pre_build_commands(config, docs_root)
            mock_run.assert_called_once_with(
                config["pre_build"],
                docs_root,
                "Pre-build",
                target_name=None,
            )

    def test_user_commands_with_target(
        self, docs_root: Path
    ) -> None:
        config = {"pre_build": {"whitepaper": [["echo", "wp"]]}}
        with patch("sdb.build._run_config_commands") as mock_run:
            run_pre_build_commands(config, docs_root, target_name="whitepaper")
            mock_run.assert_called_once_with(
                config["pre_build"],
                docs_root,
                "Pre-build",
                target_name="whitepaper",
            )


class TestRunPostRenderCommandsNoDefaults:
    """run_post_render_commands no longer injects defaults internally."""

    def test_empty_config_runs_nothing(
        self, docs_root: Path
    ) -> None:
        with patch("sdb.build._run_config_commands") as mock_run:
            run_post_render_commands({}, docs_root)
            mock_run.assert_called_once_with(
                [],
                docs_root,
                "Post-render",
                target_name=None,
            )


@pytest.fixture
def docs_root() -> Path:
    return Path("/tmp/test_docs")


@pytest.fixture
def mock_initialize() -> MagicMock:
    """Pre-populate module-level globals that build_targets expects."""
    import sdb.build as build_mod
    build_mod.EXTERNAL_CONFIG = {}
    build_mod.TARGET_CONFIG = {
        "index": {"qmd": "index.qmd"},
    }
    build_mod.BUILD_FUNCTIONS = {
        "index": lambda **kw: True,
    }
    build_mod.OUTPUT_DIR_TARGETS = set()
    build_mod.PROJECT_ROOT = Path("/tmp")
    yield


class TestBuildTargetsDefaultPrePost:
    """build_targets orchestrates defaults separately from user commands."""

    def test_defaults_run_once_before_user_global(
        self,
        docs_root: Path,
        mock_initialize: MagicMock,
    ) -> None:
        """
        Verify that _run_default_sequence is called with the default
        sequences before user config commands, preventing N+1 execution
        in parallel mode.
        """
        seq_calls = []
        config_calls = []

        original_seq = _run_default_sequence
        original_config = _run_config_commands

        def tracking_seq(steps, dr, phase):
            seq_calls.append({"steps": steps, "phase": phase})
            return original_seq(steps, dr, phase)

        def tracking_config(section, dr, phase, target_name=None):
            config_calls.append({
                "section": section,
                "phase": phase,
                "target_name": target_name,
            })
            return original_config(section, dr, phase, target_name=target_name)

        with (
            patch("sdb.build._run_default_sequence", side_effect=tracking_seq),
            patch("sdb.build._run_config_commands", side_effect=tracking_config),
            patch("sdb.build.Path.cwd", return_value=docs_root),
            patch("sdb.build.Path.mkdir"),
            patch("sdb.build.shutil.rmtree"),
            patch("sdb.build.shutil.copytree"),
            patch("sdb.build.os.cpu_count", return_value=4),
        ):
            build_targets(
                targets=["index"],
                output_dir=None,
                sequence_mode=True,
                max_jobs=1,
                single_command=True,
                website=False,
                docs_root=docs_root,
            )

        # _run_default_sequence should be called with pre-build then post-render
        assert len(seq_calls) == 2
        assert seq_calls[0]["steps"] is _DEFAULT_PRE_BUILD
        assert seq_calls[0]["phase"] == "Pre-build"
        assert seq_calls[1]["steps"] is _DEFAULT_POST_RENDER
        assert seq_calls[1]["phase"] == "Post-render"

        # _run_config_commands calls should be for user config only
        pre_config = [c for c in config_calls if c["phase"] == "Pre-build"]
        assert len(pre_config) >= 1
        # First user pre-build call (empty in test)
        assert pre_config[0]["section"] == []

    def test_defaults_do_not_run_per_target(
        self,
        docs_root: Path,
        mock_initialize: MagicMock,
    ) -> None:
        """
        When multiple targets are specified, defaults should run once
        globally, not once per target.
        """
        import sdb.build as build_mod
        build_mod.TARGET_CONFIG = {
            "index": {"qmd": "index.qmd"},
            "guide": {"qmd": "guide.qmd"},
        }
        build_mod.BUILD_FUNCTIONS = {
            "index": lambda **kw: True,
            "guide": lambda **kw: True,
        }

        seq_calls = []

        original_seq = _run_default_sequence

        def tracking_seq(steps, dr, phase):
            seq_calls.append({"steps": steps, "phase": phase})
            return original_seq(steps, dr, phase)

        with (
            patch("sdb.build._run_default_sequence", side_effect=tracking_seq),
            patch("sdb.build._run_config_commands"),
            patch("sdb.build.Path.cwd", return_value=docs_root),
            patch("sdb.build.Path.mkdir"),
            patch("sdb.build.shutil.rmtree"),
            patch("sdb.build.shutil.copytree"),
            patch("sdb.build.os.cpu_count", return_value=4),
        ):
            build_targets(
                targets=["index", "guide"],
                output_dir=None,
                sequence_mode=True,
                max_jobs=2,
                single_command=True,
                website=False,
                docs_root=docs_root,
            )

        # Each default sequence should run exactly ONCE, not 2x or 3x
        pre_calls = [c for c in seq_calls if c["phase"] == "Pre-build"]
        assert len(pre_calls) == 1, (
            f"Expected 1 default pre-build call, got {len(pre_calls)}"
        )
        assert pre_calls[0]["steps"] is _DEFAULT_PRE_BUILD

        post_calls = [c for c in seq_calls if c["phase"] == "Post-render"]
        assert len(post_calls) == 1, (
            f"Expected 1 default post-render call, got {len(post_calls)}"
        )
        assert post_calls[0]["steps"] is _DEFAULT_POST_RENDER


class TestDefaultSequenceSummary:
    """A step that did not work is counted, so the run does not read as clean.

    The sequence tolerates a failing step on purpose, because an absent
    optional tool must not fail a build.  The summary is what keeps that
    tolerance from looking like success.
    """

    @staticmethod
    def _summary(caplog) -> str:
        matches = [
            str(r.message)
            for r in caplog.records
            if "step(s) completed" in str(r.message)
        ]
        assert len(matches) == 1, matches
        return matches[0]

    def test_a_step_that_raises_is_reported(
        self, tmp_path: Path, caplog
    ) -> None:
        def boom(_root: Path) -> None:
            raise RuntimeError("no")

        def fine(_root: Path) -> None:
            return None

        with caplog.at_level(logging.INFO):
            _run_default_sequence([fine, boom], tmp_path, "Pre-build")
        summary = self._summary(caplog)
        assert "1 of 2 step(s) completed" in summary
        assert "1 failed (boom)" in summary
        assert caplog.records[-1].levelno == logging.WARNING

    def test_a_clean_run_is_summarized_at_info(
        self, tmp_path: Path, caplog
    ) -> None:
        def fine(_root: Path) -> None:
            return None

        def also_fine(_root: Path) -> None:
            return None

        with caplog.at_level(logging.INFO):
            _run_default_sequence([fine, also_fine], tmp_path, "Post-render")
        summary = self._summary(caplog)
        assert "2 of 2 step(s) completed" in summary
        assert "failed" not in summary
        assert caplog.records[-1].levelno == logging.INFO

    def test_a_missing_executable_is_skipped_not_failed(
        self, tmp_path: Path, caplog
    ) -> None:
        tool = "sdb-no-such-tool-at-all"
        with caplog.at_level(logging.INFO):
            _run_default_sequence([[tool]], tmp_path, "Pre-build")
        summary = self._summary(caplog)
        assert f"0 of 1 step(s) completed, 1 skipped ({tool})" in summary
        assert "failed" not in summary
        assert caplog.records[-1].levelno == logging.INFO

    def test_a_command_that_exits_nonzero_is_failed(
        self, tmp_path: Path, caplog
    ) -> None:
        with caplog.at_level(logging.INFO):
            _run_default_sequence([["false"]], tmp_path, "Pre-build")
        summary = self._summary(caplog)
        assert "0 of 1 step(s) completed" in summary
        assert "1 failed (false)" in summary
        assert caplog.records[-1].levelno == logging.WARNING
