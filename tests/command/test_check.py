"""Command-level tests for ``sdb check``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sdb.cli import main


def _run_check(argv: list[str]) -> int:
    try:
        main(["check", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


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
