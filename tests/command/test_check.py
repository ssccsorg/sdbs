"""Command-level tests for ``sdb check``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sdb.cli import main

SDBS_SRC = Path(__file__).resolve().parents[2] / "src"


def _run_check(argv: list[str]) -> int:
    try:
        main(["check", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SDBS_SRC) + (f":{existing}" if existing else "")
    return env


class TestCheckDefaults:
    """``sdb check`` default behavior."""

    def test_check_current_dir(self) -> None:
        with patch("sdb.check.run_check") as mock_check:
            mock_check.return_value = True
            code = _run_check([])
            assert code == 0
            mock_check.assert_called_once_with(
                docs_root=Path(".").resolve(),
                validate_only=False,
                cleanup_uncited=False,
            )

    def test_check_validate_only(self) -> None:
        with patch("sdb.check.run_check") as mock_check:
            mock_check.return_value = True
            code = _run_check([".", "--validate-only"])
            assert code == 0
            mock_check.assert_called_once()

    def test_check_cleanup_uncited(self) -> None:
        with patch("sdb.check.run_check") as mock_check:
            mock_check.return_value = True
            code = _run_check(["/tmp/mydocs", "--cleanup-uncited"])
            assert code == 0
            kwargs = mock_check.call_args.kwargs
            assert kwargs["validate_only"] is False
            assert kwargs["cleanup_uncited"] is True

    def test_check_failure_exit_code(self) -> None:
        with patch("sdb.check.run_check") as mock_check:
            mock_check.return_value = False
            code = _run_check([])
            assert code == 1


class TestCheckReal:
    """Real ``sdb check`` against a scaffolded project."""

    @pytest.mark.slow
    def test_check_scaffolded_project(self, tmp_path: Path) -> None:
        from sdb.cli import main as cli_main
        try:
            cli_main(["init", str(tmp_path / "docs")])
        except SystemExit as e:
            assert e.code in (None, 0)
        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "check", str(tmp_path / "docs"), "--validate-only"],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=30,
        )
        assert result.returncode == 0, f"Check failed:\n{result.stderr}"
