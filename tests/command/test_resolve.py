"""Command-level tests for ``sdb resolve``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sdb.cli import main


def _run_resolve(argv: list[str]) -> int:
    try:
        main(["resolve", *argv])
        return 0
    except SystemExit as e:
        code = e.code if e.code is not None else 0
        return code if isinstance(code, int) else 1


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
