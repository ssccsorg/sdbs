"""Command-level tests for ``sdb build``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sdb.cli import main

SDBS_SRC = Path(__file__).resolve().parents[2] / "src"


def _run_build(argv: list[str]) -> int:
    try:
        main(["build", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SDBS_SRC) + (f":{existing}" if existing else "")
    return env


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
            assert _kwargs["max_jobs"] == 4
            assert _kwargs["website"] is True

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
            assert _kwargs["sequence_mode"] is True

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
            assert _kwargs["single_command"] is False


class TestBuildReal:
    """Real ``sdb build`` against a scaffolded project."""

    @pytest.mark.slow
    def test_scaffold_then_build(self, tmp_path: Path) -> None:
        target = tmp_path / "reality"
        from sdb.cli import main as cli_main
        try:
            cli_main(["init", str(target), "--template", "default"])
        except SystemExit as e:
            assert e.code in (None, 0)
        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "build", str(target), "index", "--sequence"],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=60,
        )
        assert result.returncode == 0, f"Build failed:\n{result.stderr}"
        assert (target / "index.html").exists()
