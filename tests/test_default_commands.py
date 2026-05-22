"""Tests for built-in default pre/post commands in sdb.build."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sdb.build import (
    _DEFAULT_PRE_BUILD_COMMANDS,
    _DEFAULT_POST_RENDER_COMMANDS,
    _run_config_commands,
    build_targets,
    run_pre_build_commands,
    run_post_render_commands,
)


class TestDefaultCommandConstants:
    """Built-in default command lists contain expected entries."""

    def test_pre_build_has_generate_latest(self) -> None:
        cmds_str = [" ".join(c) for c in _DEFAULT_PRE_BUILD_COMMANDS]
        assert any("generate_latest_docs" in s for s in cmds_str)

    def test_pre_build_has_resolve(self) -> None:
        cmds_str = [" ".join(c) for c in _DEFAULT_PRE_BUILD_COMMANDS]
        assert any("resolve" in s for s in cmds_str)

    def test_pre_build_has_rumdl(self) -> None:
        names = [c[0] for c in _DEFAULT_PRE_BUILD_COMMANDS]
        assert "rumdl" in names

    def test_post_render_has_generate_llms(self) -> None:
        cmds_str = [" ".join(c) for c in _DEFAULT_POST_RENDER_COMMANDS]
        assert any("generate_llms_txt" in s for s in cmds_str)


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
        Verify that _run_config_commands is called with defaults first,
        then with user config. This prevents N+1 execution in parallel mode.
        """
        calls = []

        original_run = _run_config_commands

        def tracking_run(section, dr, phase, target_name=None):
            calls.append({
                "section": section,
                "phase": phase,
                "target_name": target_name,
            })
            return original_run(section, dr, phase, target_name=target_name)

        with patch(
            "sdb.build._run_config_commands", side_effect=tracking_run
        ):
            with patch("sdb.build.Path.cwd", return_value=docs_root):
                with patch("sdb.build.Path.mkdir"):
                    with patch("sdb.build.shutil.rmtree"):
                        with patch("sdb.build.shutil.copytree"):
                            with patch("sdb.build.os.cpu_count", return_value=4):
                                build_targets(
                                    targets=["index"],
                                    output_dir=None,
                                    sequence_mode=True,
                                    max_jobs=1,
                                    single_command=True,
                                    website=False,
                                    docs_root=docs_root,
                                )

        # Find all pre-build calls (phase == "Pre-build")
        pre_calls = [c for c in calls if c["phase"] == "Pre-build"]

        # The FIRST pre-build call should be the defaults
        assert len(pre_calls) >= 1
        default_call = pre_calls[0]
        assert default_call["target_name"] is None
        assert default_call["section"] == {"_global": _DEFAULT_PRE_BUILD_COMMANDS}

        # The SECOND pre-build call (if any) should be user config (empty in test)
        if len(pre_calls) > 1:
            user_call = pre_calls[1]
            assert user_call["section"] == []

        # Find all post-render calls
        post_calls = [c for c in calls if c["phase"] == "Post-render"]
        if post_calls:
            # The FIRST post-render call should be the defaults
            default_post = post_calls[0]
            assert default_post["target_name"] is None
            assert default_post["section"] == {
                "_global": _DEFAULT_POST_RENDER_COMMANDS
            }

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

        calls = []

        original_run = _run_config_commands

        def tracking_run(section, dr, phase, target_name=None):
            calls.append({
                "section": section,
                "phase": phase,
                "target_name": target_name,
            })
            return original_run(section, dr, phase, target_name=target_name)

        with patch(
            "sdb.build._run_config_commands", side_effect=tracking_run
        ):
            with patch("sdb.build.Path.cwd", return_value=docs_root):
                with patch("sdb.build.Path.mkdir"):
                    with patch("sdb.build.shutil.rmtree"):
                        with patch("sdb.build.shutil.copytree"):
                            with patch("sdb.build.os.cpu_count", return_value=4):
                                build_targets(
                                    targets=["index", "guide"],
                                    output_dir=None,
                                    sequence_mode=True,
                                    max_jobs=2,
                                    single_command=True,
                                    website=False,
                                    docs_root=docs_root,
                                )

        pre_default_calls = [
            c for c in calls
            if c["phase"] == "Pre-build"
            and c["section"] == {"_global": _DEFAULT_PRE_BUILD_COMMANDS}
        ]
        # Defaults should run exactly ONCE, not 2x or 3x
        assert len(pre_default_calls) == 1, (
            f"Expected 1 default pre-build call, got {len(pre_default_calls)}"
        )
