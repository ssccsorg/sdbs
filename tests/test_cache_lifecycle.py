"""Tests for cache lifecycle: capture, cleanup, and sidebar re-render decision."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sdb.build as build_module
from sdb.build import TARGET_CONFIG


def _make_cached(project_root: Path, names: list[str]) -> Path:
    cached = project_root / "_cached"
    cached.mkdir(parents=True, exist_ok=True)
    for name in names:
        (cached / name).mkdir()
    return cached


# ---------------------------------------------------------------------------
# capture_initial_cached_targets
# ---------------------------------------------------------------------------


class TestCaptureInitialCachedTargets:
    """_cached에서 현재 소스 기준 타겟만 수집"""

    def test_no_cache_dir(self, tmp_path: Path) -> None:
        TARGET_CONFIG.clear()
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        build_module.capture_initial_cached_targets(docs_root)
        assert build_module._INITIAL_CACHED_TARGETS == set()

    def test_stale_entries_filtered(self, tmp_path: Path) -> None:
        TARGET_CONFIG.clear()
        TARGET_CONFIG.update({"a": {}, "b": {}, "c": {}})
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        _make_cached(tmp_path, ["a", "b", "c", "poc-arch_sv_diagram"])
        build_module.capture_initial_cached_targets(docs_root)
        assert build_module._INITIAL_CACHED_TARGETS == {"a", "b", "c"}

    def test_all_stale_no_targets(self, tmp_path: Path) -> None:
        TARGET_CONFIG.clear()
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        _make_cached(tmp_path, ["poc-arch_sv_diagram", "old-target"])
        build_module.capture_initial_cached_targets(docs_root)
        assert build_module._INITIAL_CACHED_TARGETS == set()

    def test_empty_cache_dir(self, tmp_path: Path) -> None:
        TARGET_CONFIG.clear()
        TARGET_CONFIG.update({"a": {}})
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        _make_cached(tmp_path, [])
        build_module.capture_initial_cached_targets(docs_root)
        assert build_module._INITIAL_CACHED_TARGETS == set()

    def test_some_stale_some_valid(self, tmp_path: Path) -> None:
        TARGET_CONFIG.clear()
        TARGET_CONFIG.update({"a": {}, "c": {}})
        docs_root = tmp_path / "docs"
        docs_root.mkdir()
        _make_cached(tmp_path, ["a", "poc-arch_sv_diagram", "c"])
        build_module.capture_initial_cached_targets(docs_root)
        assert build_module._INITIAL_CACHED_TARGETS == {"a", "c"}


# ---------------------------------------------------------------------------
# should_rerender_for_sidebar
# ---------------------------------------------------------------------------


class TestShouldRerenderForSidebar:
    """소스 기준 타겟 추가/삭제만 감지."""

    def test_no_change(self, tmp_path: Path) -> None:
        build_module._INITIAL_CACHED_TARGETS = {"a", "b", "c"}
        assert build_module.should_rerender_for_sidebar({"a", "b", "c"}, tmp_path) is False

    def test_new_target_added(self, tmp_path: Path) -> None:
        build_module._INITIAL_CACHED_TARGETS = {"a", "b"}
        assert build_module.should_rerender_for_sidebar({"a", "b", "c"}, tmp_path) is True

    def test_target_removed(self, tmp_path: Path) -> None:
        build_module._INITIAL_CACHED_TARGETS = {"a", "b", "c"}
        assert build_module.should_rerender_for_sidebar({"a", "b"}, tmp_path) is True

    def test_stale_cache_ignored(self, tmp_path: Path) -> None:
        build_module._INITIAL_CACHED_TARGETS = {"a", "b"}
        assert build_module.should_rerender_for_sidebar({"a", "b"}, tmp_path) is False

    def test_add_and_remove_same_time(self, tmp_path: Path) -> None:
        build_module._INITIAL_CACHED_TARGETS = {"a", "b"}
        assert build_module.should_rerender_for_sidebar({"b", "c"}, tmp_path) is True


# ---------------------------------------------------------------------------
# _cleanup_orphaned_caches
# ---------------------------------------------------------------------------


class TestCleanupOrphanedCaches:
    """stale 캐시 디렉토리를 실제로 삭제하는지 검증."""

    @patch.object(build_module, "get_cache_base")
    def test_orphaned_removed(self, mock_get_base: MagicMock, tmp_path: Path) -> None:
        cached_dir = _make_cached(tmp_path, ["a", "b", "poc-arch_sv_diagram"])
        mock_get_base.return_value = cached_dir
        returned = build_module._cleanup_orphaned_caches({"a", "b"}, tmp_path)
        assert returned == 1
        assert (cached_dir / "poc-arch_sv_diagram").exists() is False
        assert (cached_dir / "a").exists() is True
        assert (cached_dir / "b").exists() is True

    @patch.object(build_module, "get_cache_base")
    def test_no_orphans(self, mock_get_base: MagicMock, tmp_path: Path) -> None:
        cached_dir = _make_cached(tmp_path, ["a", "b"])
        mock_get_base.return_value = cached_dir
        returned = build_module._cleanup_orphaned_caches({"a", "b"}, tmp_path)
        assert returned == 0

    @patch.object(build_module, "get_cache_base")
    def test_no_cache_dir(self, mock_get_base: MagicMock, tmp_path: Path) -> None:
        mock_get_base.return_value = tmp_path / "_cached"
        returned = build_module._cleanup_orphaned_caches({"a", "b"}, tmp_path)
        assert returned == 0

    @patch.object(build_module, "get_cache_base")
    def test_all_orphaned(self, mock_get_base: MagicMock, tmp_path: Path) -> None:
        cached_dir = _make_cached(tmp_path, ["old-a", "old-b"])
        mock_get_base.return_value = cached_dir
        returned = build_module._cleanup_orphaned_caches(set(), tmp_path)
        assert returned == 2
        assert (cached_dir / "old-a").exists() is False
        assert (cached_dir / "old-b").exists() is False
