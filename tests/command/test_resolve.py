"""Command-level tests for ``sdb resolve``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sdb.cli import main

SDBS_SRC = Path(__file__).resolve().parents[2] / "src"


def _run_resolve(argv: list[str]) -> int:
    try:
        main(["resolve", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SDBS_SRC) + (f":{existing}" if existing else "")
    return env


class TestResolveDefaults:
    """``sdb resolve`` default behavior."""

    def test_resolve_current_dir(self) -> None:
        with patch("sdb.resolve.resolve_all") as mock_resolve:
            mock_resolve.return_value = True
            code = _run_resolve([])
            assert code == 0
            mock_resolve.assert_called_once_with(
                docs_root=Path(".").resolve(),
                check_only=False,
            )

    def test_resolve_check_only(self) -> None:
        with patch("sdb.resolve.resolve_all") as mock_resolve:
            mock_resolve.return_value = True
            code = _run_resolve(["/tmp/docs", "--check-only"])
            assert code == 0
            kwargs = mock_resolve.call_args.kwargs
            assert kwargs["check_only"] is True

    def test_resolve_failure_exit_code(self) -> None:
        with patch("sdb.resolve.resolve_all") as mock_resolve:
            mock_resolve.return_value = False
            code = _run_resolve([])
            assert code == 1


class TestResolveReal:
    """Real ``sdb resolve`` against a scaffolded project."""

    @pytest.mark.slow
    def test_resolve_scaffolded_project(self, tmp_path: Path) -> None:
        from sdb.cli import main as cli_main
        try:
            cli_main(["init", str(tmp_path / "docs"), "--template", "default"])
        except SystemExit as e:
            assert e.code in (None, 0)
        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "resolve", str(tmp_path / "docs"), "--check-only"],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=30,
        )
        assert result.returncode == 0, f"Resolve failed:\n{result.stderr}"
