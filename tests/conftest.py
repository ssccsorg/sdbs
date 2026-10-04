"""
Shared test setup.

The sdbs image sets ``SDB_PLUGIN_PATH`` to the reference plugins it ships, and
the container that runs this suite inherits it. A test that builds its own
plugins would then see the image's as well, so the suite clears the variable
for every test; a test that exercises the variable sets it itself.
"""

from __future__ import annotations

import pytest

PLUGIN_PATH_ENV = "SDB_PLUGIN_PATH"


@pytest.fixture(autouse=True)
def _clear_plugin_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PLUGIN_PATH_ENV, raising=False)
