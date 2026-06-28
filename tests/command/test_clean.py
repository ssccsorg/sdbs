"""Command-level tests for ``sdb clean``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sdb.cli import main

SDBS_SRC = Path(__file__).resolve().parents[2] / "src"


def _run_clean(argv: list[str]) -> int:
    try:
        main(["clean", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SDBS_SRC) + (f":{existing}" if existing else "")
    return env


class TestCleanDefaults:
    """``sdb clean`` default behavior."""

    def test_clean_current_dir(self) -> None:
        with patch("sdb.build.clean_quarto_artifacts") as mock_clean:
            code = _run_clean([])
            assert code == 0
            mock_clean.assert_called_once()

    def test_clean_with_docs_root(self) -> None:
        with patch("sdb.build.clean_quarto_artifacts") as mock_clean:
            code = _run_clean(["/tmp/docs"])
            assert code == 0
            mock_clean.assert_called_once()
            args, _kwargs = mock_clean.call_args
            assert str(args[0]).endswith("/tmp/docs")

    def test_clean_propagates_failure(self) -> None:
        with patch("sdb.build.clean_quarto_artifacts", return_value=False):
            code = _run_clean(["/tmp/docs"])
            assert code == 1


class TestCleanReal:
    """Real ``sdb clean`` against a scaffolded project."""

    @pytest.mark.slow
    def test_clean_removes_artifacts(self, tmp_path: Path) -> None:
        from sdb.cli import main as cli_main
        try:
            cli_main(["init", str(tmp_path / "docs"), "--template", "default"])
        except SystemExit as e:
            assert e.code in (None, 0)

        docs = tmp_path / "docs"
        cached = docs / "index_cached"
        cached.mkdir(parents=True, exist_ok=True)
        (cached / "test.txt").write_text("cache")
        html = docs / "index_files"
        html.mkdir(parents=True, exist_ok=True)
        (html / "style.css").write_text("css")

        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "clean", str(docs)],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=30,
        )
        assert result.returncode == 0, f"Clean failed:\n{result.stderr}"
        assert not cached.exists(), f"_cached dir still exists: {cached}"
        assert not html.exists(), f"_files dir still exists: {html}"
