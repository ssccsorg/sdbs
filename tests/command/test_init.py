"""Command-level tests for ``sdb init``.

After scaffolding, each test verifies the init result and optionally
runs ``sdb build`` to confirm the initialized project actually builds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from unittest.mock import patch

from sdb.cli import main


def _run_init(argv: list[str]) -> int:
    try:
        main(["init", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


SDBS_SRC = Path(__file__).resolve().parents[2] / "src"


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SDBS_SRC) + (f":{existing}" if existing else "")
    return env


class TestInitDefault:
    """``sdb init`` with default template creates a buildable project."""

    def test_default_template_creates_files(self, tmp_path: Path) -> None:
        target = tmp_path / "docs"
        code = _run_init([str(target), "--template", "default"])
        assert code == 0
        assert (target / "build.yml").exists()
        assert (target / "_quarto.yml").exists()
        assert (target / "index.qmd").exists()
        code = _run_init([str(target), "--template", "default"])
        assert code == 0

    def test_default_no_overwrite_without_force(self, tmp_path: Path) -> None:
        target = tmp_path / "existing"
        target.mkdir()
        (target / "build.yml").write_text("user content")
        code = _run_init([str(target), "--template", "default"])
        assert code == 0
        assert (target / "build.yml").read_text() == "user content"

    def test_default_overwrite_with_force(self, tmp_path: Path) -> None:
        target = tmp_path / "overwrite"
        target.mkdir()
        (target / "build.yml").write_text("user content")
        code = _run_init([str(target), "--force", "--template", "default"])
        assert code == 0
        content = (target / "build.yml").read_text()
        assert content != "user content"


class TestInitAdvancedTemplate:
    """``sdb init --template advanced`` creates extra files."""

    def test_advanced_creates_extra_files(self, tmp_path: Path) -> None:
        target = tmp_path / "site"
        code = _run_init([str(target), "--template", "advanced"])
        assert code == 0
        assert (target / "_include" / "_graphviz.py").exists()
        assert (target / "_include" / "_title_meta_items.qmd").exists()

    def test_advanced_with_force_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "forced"
        target.mkdir()
        (target / "build.yml").write_text("old")
        code = _run_init([str(target), "--force", "--template", "advanced"])
        assert code == 0
        assert (target / "build.yml").read_text() != "old"


class TestInitUnknownTemplate:
    """Unknown template name falls back to default."""

    def test_unknown_falls_back_to_default(self, tmp_path: Path) -> None:
        target = tmp_path / "fallback"
        code = _run_init([str(target), "--template", "nonexistent"])
        assert code == 0
        assert (target / "build.yml").exists()
        assert (target / "index.qmd").exists()


class TestInitThenBuild:
    """After scaffolding, the project should be buildable."""

    @pytest.mark.slow
    def test_default_template_builds(self, tmp_path: Path) -> None:
        target = tmp_path / "buildable"
        code = _run_init([str(target), "--template", "default"])
        assert code == 0

        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "build", str(target), "index", "--sequence"],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=60,
        )
        assert result.returncode == 0, f"Build failed:\n{result.stderr}"
        assert (target / "index.html").exists()

    @pytest.mark.slow
    def test_advanced_custom_path_builds(self, tmp_path: Path) -> None:
        """``sdb init mydocs --template advanced --force`` then build."""
        target = tmp_path / "mydocs"
        code = _run_init([str(target), "--template", "advanced", "--force"])
        assert code == 0
        assert (target / "_include" / "_graphviz.py").exists()

        result = subprocess.run(
            [sys.executable, "-m", "sdb.cli", "build", str(target), "index", "--sequence"],
            capture_output=True, text=True,
            cwd=str(SDBS_SRC.parent), env=_build_env(), timeout=60,
        )
        assert result.returncode == 0, f"Build failed:\n{result.stderr}"
        assert (target / "index.html").exists()


