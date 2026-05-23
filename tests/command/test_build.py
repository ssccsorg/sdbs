"""Command-level tests for ``sdb build``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from sdb.cli import main


def _run_build(argv: list[str]) -> int:
    try:
        main(["build", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


class TestBuildDefaults:
    """``sdb build`` defaults."""

    def test_build_current_dir_all_targets(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            mock_build.return_value = True
            code = _run_build([])
            assert code == 0
            mock_build.assert_called_once()

    def test_build_specific_target(self) -> None:
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
            code = _run_build(["docs", "whitepaper", "--website", "-j", "4"])
            assert code == 0
            mock_parse.assert_called_once_with(["whitepaper"])
            _kwargs: Any = mock_build.call_args.kwargs
            assert _kwargs["max_jobs"] == 4  # type: ignore[index]
            assert _kwargs["website"] is True  # type: ignore[index]

    def test_build_clean_succeeds(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.clean_quarto_artifacts") as mock_clean,
        ):
            mock_clean.return_value = True
            code = _run_build(["docs", "clean"])
            assert code == 0

    def test_build_clean_fails(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.clean_quarto_artifacts") as mock_clean,
        ):
            mock_clean.return_value = False
            code = _run_build(["docs", "clean"])
            assert code == 1


class TestBuildSequence:
    """``--sequence`` flag forces sequential execution."""

    def test_sequence_flag(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            mock_build.return_value = True
            code = _run_build([".", "--sequence"])
            assert code == 0
            _kwargs: Any = mock_build.call_args.kwargs
            assert _kwargs["sequence_mode"] is True  # type: ignore[index]

    def test_parallel_formats_flag(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            mock_build.return_value = True
            code = _run_build([".", "--parallel-formats"])
            assert code == 0
            _kwargs: Any = mock_build.call_args.kwargs
            assert _kwargs["single_command"] is False  # type: ignore[index]
