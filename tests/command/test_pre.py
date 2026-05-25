"""Command-level tests for ``sdb pre``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sdb.cli import main

SDBS_SRC = Path(__file__).resolve().parents[2] / "src"


def _run_pre(argv: list[str]) -> int:
    try:
        main(["pre", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SDBS_SRC) + (f":{existing}" if existing else "")
    return env


class TestPreDefaults:
    """``sdb pre`` default behavior."""

    def test_pre_current_dir(self) -> None:
        with patch("sdb.build._run_default_sequence") as mock_seq:
            code = _run_pre([])
            assert code == 0
            mock_seq.assert_called_once()
            args, kwargs = mock_seq.call_args
            assert args[2] == "Pre-build"

    def test_pre_with_docs_root(self) -> None:
        with patch("sdb.build._run_default_sequence") as mock_seq:
            code = _run_pre(["/tmp/docs"])
            assert code == 0
            mock_seq.assert_called_once()
            args, kwargs = mock_seq.call_args
            assert str(args[1]).endswith("/tmp/docs")


class TestPreReal:
    """Real ``sdb pre`` against a scaffolded project."""

    @pytest.mark.slow
    def test_pre_scaffolded_project(self, tmp_path: Path) -> None:
        from sdb.cli import main as cli_main
        try:
            cli_main(["init", str(tmp_path / "docs"), "--template", "default"])
        except SystemExit as e:
            assert e.code in (None, 0)
        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "pre", str(tmp_path / "docs")],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=30,
        )
        assert result.returncode == 0, f"Pre failed:\n{result.stderr}"
