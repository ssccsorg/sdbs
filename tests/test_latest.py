"""Tests for ``sdb.utils.latest._load_latest_count``."""

from __future__ import annotations

import yaml

from pathlib import Path
from sdb.utils.latest import _load_latest_count, ITEM_LENGTH


class TestLoadLatestCount:
    """``_load_latest_count`` reads ``latest_docs_list_count`` from build.yml."""

    def test_default_when_no_build_yml(self, tmp_path: Path) -> None:
        """No build.yml exists → returns ITEM_LENGTH."""
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_default_when_build_yml_has_no_key(self, tmp_path: Path) -> None:
        """build.yml exists but missing latest_docs_list_count → returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text("exclude:\n  - '**/README.md'\n", encoding="utf-8")
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_custom_value(self, tmp_path: Path) -> None:
        """build.yml with latest_docs_list_count: 5 → returns 5."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 5}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == 5

    def test_custom_large_value(self, tmp_path: Path) -> None:
        """build.yml with latest_docs_list_count: 25 → returns 25."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 25}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == 25

    def test_zero_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: 0 → not positive, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 0}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_negative_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: -5 → not positive, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": -5}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_non_integer_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: \"abc\" → not int, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": "abc"}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_float_value_falls_back(self, tmp_path: Path) -> None:
        """latest_docs_list_count: 5.5 → not int, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text(
            yaml.dump({"latest_docs_list_count": 5.5}), encoding="utf-8"
        )
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_invalid_yaml_falls_back(self, tmp_path: Path) -> None:
        """build.yml with invalid YAML → exception caught, returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text("{invalid: yaml: [unclosed", encoding="utf-8")
        assert _load_latest_count(tmp_path) == ITEM_LENGTH

    def test_empty_build_yml(self, tmp_path: Path) -> None:
        """build.yml empty → returns ITEM_LENGTH."""
        (tmp_path / "build.yml").write_text("", encoding="utf-8")
        assert _load_latest_count(tmp_path) == ITEM_LENGTH
