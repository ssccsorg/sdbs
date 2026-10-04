"""Tests for the s3 plugin's request handler, which runs outside sdbs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdb_s3.channel import PluginError, handle
from sdb_s3.client import S3Client, S3Error


def _artifact(tmp_path: Path, names: tuple[str, ...] = ("index.html",)) -> Path:
    root = tmp_path / "site"
    root.mkdir()
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return root


def _request(artifact: Path, dry_run: bool = True, **options) -> dict:
    return {"deploy": 1, "artifact": str(artifact), "options": options, "dry_run": dry_run}


def _client(endpoint: str, bucket: str = "pdocs") -> S3Client:
    return S3Client(
        endpoint=endpoint,
        bucket=bucket,
        access_key="key",
        secret_key="secret",
        region="auto",
    )


class TestEndpoint:
    """The account endpoint is given without the bucket.

    A store's console shows a bucket URL with the bucket in the path, and the
    client appends the bucket itself, so accepting such an endpoint would nest
    the bucket twice and upload to the wrong keys.
    """

    def test_a_bucket_in_the_endpoint_is_rejected(self) -> None:
        with pytest.raises(S3Error):
            _client("https://account.r2.cloudflarestorage.com/pdocs")

    def test_the_account_endpoint_builds_the_expected_path(self) -> None:
        client = _client("https://account.r2.cloudflarestorage.com")
        assert client._path_for_key("ktema/index.html") == "/pdocs/ktema/index.html"


class TestDryRun:
    def test_counts_without_a_store(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path, ("index.html", "assets/style.css"))
        result = handle(_request(artifact, bucket="b", prefix="p"))
        assert result["ok"] is True
        assert result["uploaded"] == 2

    def test_a_prefix_is_optional(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path)
        result = handle(_request(artifact, bucket="b"))
        assert result["ok"] is True


class TestValidation:
    def test_a_bucket_is_required(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError):
            handle(_request(_artifact(tmp_path)))

    def test_the_artifact_must_be_a_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "absent"
        with pytest.raises(PluginError):
            handle(_request(missing, bucket="b"))

    def test_delete_at_the_root_is_refused(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path)
        with pytest.raises(PluginError):
            handle(_request(artifact, bucket="b", delete=True))

    def test_delete_with_a_prefix_is_allowed(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path)
        result = handle(_request(artifact, bucket="b", prefix="p", delete=True))
        assert result["ok"] is True

    def test_access_needs_a_domain(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path)
        with pytest.raises(PluginError):
            handle(_request(artifact, bucket="b", auth={"mode": "access"}))

    def test_presigned_needs_objects(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path)
        with pytest.raises(PluginError):
            handle(_request(artifact, bucket="b", auth={"mode": "presigned"}))

    def test_a_presigned_object_must_be_in_the_artifact(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path)
        with pytest.raises(PluginError):
            handle(
                _request(
                    artifact,
                    bucket="b",
                    auth={"mode": "presigned", "objects": ["absent.pdf"]},
                )
            )

    def test_a_present_presigned_object_passes(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path, ("whitepaper.pdf",))
        result = handle(
            _request(
                artifact,
                bucket="b",
                auth={"mode": "presigned", "objects": ["whitepaper.pdf"]},
            )
        )
        assert result["ok"] is True

    def test_expires_out_of_range_is_refused(self, tmp_path: Path) -> None:
        artifact = _artifact(tmp_path, ("a.pdf",))
        with pytest.raises(PluginError):
            handle(
                _request(
                    artifact,
                    bucket="b",
                    auth={"mode": "presigned", "objects": ["a.pdf"], "expires_seconds": 0},
                )
            )


class TestRealRun:
    def test_credentials_are_required(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        artifact = _artifact(tmp_path)
        with pytest.raises(PluginError):
            handle(
                _request(
                    artifact,
                    dry_run=False,
                    bucket="b",
                    endpoint="https://example.invalid",
                    region="region-1",
                )
            )

    def test_an_endpoint_is_required(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
        artifact = _artifact(tmp_path)
        with pytest.raises(PluginError):
            handle(_request(artifact, dry_run=False, bucket="b", region="region-1"))
