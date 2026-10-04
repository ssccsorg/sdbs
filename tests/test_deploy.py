"""
Tests for the deploy engine, its protocol seam, and the reference s3 channel.

The engine and its channels are separate modules, so these tests also pin that
importing the engine does not pull a channel in.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sdb.deploy import (
    DeployContext,
    DeployError,
    DeployPlugin,
    DeployRegistry,
    DeployResult,
    DeployTarget,
    iter_source_files,
    load_deploy_targets,
    run_deploy,
)
from sdb_plugins import builtin_plugins
from sdb_plugins.s3 import S3DeployPlugin, _object_key

ENDPOINT = "https://account.example.com"
REGION = "region-1"


@pytest.fixture
def s3_env(monkeypatch):
    """The endpoint, region, and credentials a channel reads from the environment."""
    monkeypatch.setenv("S3_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("AWS_REGION", REGION)
    return monkeypatch


def _write_build_yml(docs_root: Path, body: str) -> Path:
    config = docs_root / "build.yml"
    config.write_text(textwrap.dedent(body), encoding="utf-8")
    return config


class _RecordingPlugin(DeployPlugin):
    name = "recording"

    def __init__(self) -> None:
        self.validated: list[str] = []
        self.deployed: list[str] = []

    def validate(self, target: DeployTarget, context: DeployContext) -> None:
        self.validated.append(target.name)

    def deploy(self, target: DeployTarget, context: DeployContext) -> DeployResult:
        self.deployed.append(target.name)
        return DeployResult(
            name=target.name, plugin=self.name, uploaded=2, urls=["https://example.test/"]
        )


class TestEngineSeparation:
    def test_the_engine_does_not_import_a_channel(self) -> None:
        """Importing sdb.deploy must not pull any sdb_plugins module in."""
        code = (
            "import sys, sdb.deploy\n"
            "loaded = [m for m in sys.modules if m.startswith('sdb_plugins')]\n"
            "assert not loaded, loaded\n"
        )
        subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            env=dict(os.environ),
            capture_output=True,
        )


class TestConfig:
    def test_a_missing_file_yields_no_targets(self) -> None:
        assert load_deploy_targets(None) == []

    def test_defaults_are_applied(self, tmp_path: Path) -> None:
        config = _write_build_yml(
            tmp_path,
            """
            deploy:
              - name: docs
                plugin: s3
            """,
        )
        targets = load_deploy_targets(config)
        assert len(targets) == 1
        assert targets[0].source == "_site"
        assert targets[0].enabled is True
        assert targets[0].options == {}

    def test_options_are_read(self, tmp_path: Path) -> None:
        config = _write_build_yml(
            tmp_path,
            """
            deploy:
              - name: docs
                plugin: s3
                source: _site
                options:
                  bucket: b
                  prefix: p
            """,
        )
        targets = load_deploy_targets(config)
        assert targets[0].options == {"bucket": "b", "prefix": "p"}

    def test_a_non_list_deploy_key_is_rejected(self, tmp_path: Path) -> None:
        config = _write_build_yml(tmp_path, "deploy: {name: x}\n")
        with pytest.raises(DeployError):
            load_deploy_targets(config)

    def test_a_channel_without_a_name_is_rejected(self, tmp_path: Path) -> None:
        config = _write_build_yml(tmp_path, "deploy:\n  - plugin: s3\n")
        with pytest.raises(DeployError):
            load_deploy_targets(config)

    def test_a_channel_without_a_plugin_is_rejected(self, tmp_path: Path) -> None:
        config = _write_build_yml(tmp_path, "deploy:\n  - name: docs\n")
        with pytest.raises(DeployError):
            load_deploy_targets(config)

    def test_a_duplicate_name_is_rejected(self, tmp_path: Path) -> None:
        config = _write_build_yml(
            tmp_path,
            """
            deploy:
              - name: docs
                plugin: s3
              - name: docs
                plugin: s3
            """,
        )
        with pytest.raises(DeployError):
            load_deploy_targets(config)

    def test_non_mapping_options_are_rejected(self, tmp_path: Path) -> None:
        config = _write_build_yml(
            tmp_path, "deploy:\n  - name: docs\n    plugin: s3\n    options: [1, 2]\n"
        )
        with pytest.raises(DeployError):
            load_deploy_targets(config)


class TestRegistry:
    def test_discover_composes_builtins_and_entry_points(self) -> None:
        registry = DeployRegistry.discover(builtin_plugins())
        assert "s3" in registry.names()
        assert isinstance(registry.get("s3"), S3DeployPlugin)

    def test_a_plugin_missing_a_member_is_rejected(self) -> None:
        class Nameless:
            def validate(self, target, context): ...

            def deploy(self, target, context): ...

        with pytest.raises(DeployError):
            DeployRegistry([Nameless()])

        class NoDeploy:
            name = "broken"

            def validate(self, target, context): ...

        with pytest.raises(DeployError):
            DeployRegistry([NoDeploy()])

    def test_a_non_string_name_is_rejected(self) -> None:
        class Numeric:
            name = 7

            def validate(self, target, context): ...

            def deploy(self, target, context): ...

        with pytest.raises(DeployError):
            DeployRegistry([Numeric()])

    def test_entry_point_plugins_are_discovered(self, monkeypatch) -> None:
        class External(DeployPlugin):
            name = "external"

            def deploy(self, target: DeployTarget, context: DeployContext) -> DeployResult:
                return DeployResult(name=target.name, plugin=self.name)

        class FakeEntryPoint:
            name = "external"

            def load(self):
                return External

        import sdb.deploy as deploy_module

        monkeypatch.setattr(
            deploy_module, "entry_points", lambda group: [FakeEntryPoint()]
        )
        registry = DeployRegistry.discover()
        assert "external" in registry.names()
        assert isinstance(registry.get("external"), External)

    def test_an_entry_point_that_cannot_be_built_is_skipped(self, monkeypatch) -> None:
        class NeedsArguments(DeployPlugin):
            name = "needs-arguments"

            def __init__(self, required): ...

            def deploy(self, target, context): ...

        class FakeEntryPoint:
            name = "needs-arguments"

            def load(self):
                return NeedsArguments

        import sdb.deploy as deploy_module

        monkeypatch.setattr(
            deploy_module, "entry_points", lambda group: [FakeEntryPoint()]
        )
        # The failing entry point does not stop discovery of the others.
        registry = DeployRegistry.discover()
        assert "needs-arguments" not in registry.names()


class TestRunDeploy:
    def test_it_runs_every_channel(self, tmp_path: Path) -> None:
        (tmp_path / "_site").mkdir()
        config = _write_build_yml(
            tmp_path,
            """
            deploy:
              - name: first
                plugin: recording
              - name: second
                plugin: recording
            """,
        )
        plugin = _RecordingPlugin()
        ok = run_deploy(
            tmp_path,
            config_path=config,
            registry=DeployRegistry([plugin]),
        )
        assert ok is True
        assert plugin.validated == ["first", "second"]
        assert plugin.deployed == ["first", "second"]

    def test_a_disabled_channel_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "_site").mkdir()
        config = _write_build_yml(
            tmp_path,
            """
            deploy:
              - name: off
                plugin: recording
                enabled: false
            """,
        )
        plugin = _RecordingPlugin()
        ok = run_deploy(tmp_path, config_path=config, registry=DeployRegistry([plugin]))
        assert ok is False
        assert plugin.deployed == []

    def test_an_unknown_plugin_fails_the_run(self, tmp_path: Path) -> None:
        (tmp_path / "_site").mkdir()
        config = _write_build_yml(
            tmp_path, "deploy:\n  - name: docs\n    plugin: nope\n"
        )
        ok = run_deploy(tmp_path, config_path=config, registry=DeployRegistry([]))
        assert ok is False

    def test_an_unknown_channel_filter_fails_the_run(self, tmp_path: Path) -> None:
        (tmp_path / "_site").mkdir()
        config = _write_build_yml(
            tmp_path, "deploy:\n  - name: docs\n    plugin: recording\n"
        )
        plugin = _RecordingPlugin()
        ok = run_deploy(
            tmp_path,
            config_path=config,
            channels=["absent"],
            registry=DeployRegistry([plugin]),
        )
        assert ok is False
        assert plugin.deployed == []

    def test_no_channels_fails_the_run(self, tmp_path: Path) -> None:
        _write_build_yml(tmp_path, "deploy: []\n")
        assert run_deploy(tmp_path, registry=DeployRegistry([])) is False


def _s3_target(options: dict) -> DeployTarget:
    return DeployTarget(name="docs", plugin="s3", source="_site", options=options)


class TestS3Validation:
    def test_a_missing_bucket_is_rejected(self, tmp_path: Path, s3_env) -> None:
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        with pytest.raises(DeployError):
            plugin.validate(_s3_target({}), DeployContext(docs_root=tmp_path))

    def test_a_missing_endpoint_is_rejected(self, tmp_path: Path, s3_env) -> None:
        s3_env.delenv("S3_ENDPOINT", raising=False)
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        with pytest.raises(DeployError):
            plugin.validate(_s3_target({"bucket": "b"}), DeployContext(docs_root=tmp_path))

    def test_a_missing_region_is_rejected(self, tmp_path: Path, s3_env) -> None:
        s3_env.delenv("AWS_REGION", raising=False)
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        context = DeployContext(docs_root=tmp_path)
        # No region anywhere: refused, since the protocol scope needs one.
        with pytest.raises(DeployError):
            plugin.validate(_s3_target({"bucket": "b"}), context)
        # A region on the channel is enough, and a region in the environment too.
        plugin.validate(_s3_target({"bucket": "b", "region": REGION}), context)
        s3_env.setenv("AWS_REGION", REGION)
        plugin.validate(_s3_target({"bucket": "b"}), context)

    def test_missing_credentials_are_rejected(self, tmp_path: Path, s3_env) -> None:
        s3_env.delenv("AWS_ACCESS_KEY_ID", raising=False)
        s3_env.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        with pytest.raises(DeployError):
            plugin.validate(_s3_target({"bucket": "b"}), DeployContext(docs_root=tmp_path))

    def test_a_missing_source_directory_is_rejected(self, tmp_path: Path, s3_env) -> None:
        plugin = S3DeployPlugin()
        with pytest.raises(DeployError):
            plugin.validate(_s3_target({"bucket": "b"}), DeployContext(docs_root=tmp_path))

    def test_an_unknown_auth_mode_is_rejected(self, tmp_path: Path, s3_env) -> None:
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        target = _s3_target({"bucket": "b", "auth": {"mode": "sso"}})
        with pytest.raises(DeployError):
            plugin.validate(target, DeployContext(docs_root=tmp_path))

    def test_access_without_a_domain_is_rejected(self, tmp_path: Path, s3_env) -> None:
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        target = _s3_target({"bucket": "b", "auth": {"mode": "access"}})
        with pytest.raises(DeployError):
            plugin.validate(target, DeployContext(docs_root=tmp_path))

    def test_presigned_without_objects_is_rejected(self, tmp_path: Path, s3_env) -> None:
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        target = _s3_target({"bucket": "b", "auth": {"mode": "presigned"}})
        with pytest.raises(DeployError):
            plugin.validate(target, DeployContext(docs_root=tmp_path))

    def test_presigned_needs_no_domain(self, tmp_path: Path, s3_env) -> None:
        """A presigned URL is minted on the store endpoint, so no domain is used."""
        site = tmp_path / "_site"
        site.mkdir()
        (site / "a.pdf").write_text("pdf", encoding="utf-8")
        plugin = S3DeployPlugin()
        target = _s3_target(
            {"bucket": "b", "auth": {"mode": "presigned", "objects": ["a.pdf"]}}
        )
        plugin.validate(target, DeployContext(docs_root=tmp_path))

    def test_a_presigned_object_must_be_in_the_source(self, tmp_path: Path, s3_env) -> None:
        site = tmp_path / "_site"
        site.mkdir()
        (site / "present.pdf").write_text("pdf", encoding="utf-8")
        plugin = S3DeployPlugin()
        context = DeployContext(docs_root=tmp_path)
        plugin.validate(
            _s3_target(
                {"bucket": "b", "auth": {"mode": "presigned", "objects": ["present.pdf"]}}
            ),
            context,
        )
        # Absent: refused, since the reported URL would resolve to nothing.
        with pytest.raises(DeployError):
            plugin.validate(
                _s3_target(
                    {"bucket": "b", "auth": {"mode": "presigned", "objects": ["missing.pdf"]}}
                ),
                context,
            )
        # Outside the source: refused.
        with pytest.raises(DeployError):
            plugin.validate(
                _s3_target(
                    {"bucket": "b", "auth": {"mode": "presigned", "objects": ["../escape.pdf"]}}
                ),
                context,
            )

    def test_presign_seconds_must_be_in_range(self, tmp_path: Path, s3_env) -> None:
        site = tmp_path / "_site"
        site.mkdir()
        (site / "a.pdf").write_text("pdf", encoding="utf-8")
        plugin = S3DeployPlugin()
        context = DeployContext(docs_root=tmp_path)
        base = {"mode": "presigned", "objects": ["a.pdf"]}
        with pytest.raises(DeployError):
            plugin.validate(
                _s3_target({"bucket": "b", "auth": {**base, "expires_seconds": 0}}),
                context,
            )
        with pytest.raises(DeployError):
            plugin.validate(
                _s3_target({"bucket": "b", "auth": {**base, "expires_seconds": "soon"}}),
                context,
            )
        plugin.validate(
            _s3_target({"bucket": "b", "auth": {**base, "expires_seconds": 3600}}),
            context,
        )

    def test_delete_at_the_root_needs_a_prefix_or_confirmation(
        self, tmp_path: Path, s3_env
    ) -> None:
        (tmp_path / "_site").mkdir()
        plugin = S3DeployPlugin()
        context = DeployContext(docs_root=tmp_path)
        with pytest.raises(DeployError):
            plugin.validate(_s3_target({"bucket": "b", "delete": True}), context)
        plugin.validate(
            _s3_target({"bucket": "b", "delete": True, "prefix": "p"}), context
        )
        plugin.validate(
            _s3_target(
                {"bucket": "b", "delete": True, "allow_unscoped_delete": True}
            ),
            context,
        )


class TestS3DryRun:
    def test_dry_run_counts_without_contacting_the_store(
        self, tmp_path: Path, s3_env
    ) -> None:
        site = tmp_path / "_site"
        (site / "assets").mkdir(parents=True)
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
        (site / "assets" / "style.css").write_text("body{}", encoding="utf-8")

        plugin = S3DeployPlugin()
        target = _s3_target({"bucket": "b", "prefix": "project/docs"})
        result = plugin.deploy(target, DeployContext(docs_root=tmp_path, dry_run=True))
        assert result.uploaded == 2
        assert result.ok is True


class TestHelpers:
    def test_object_key_joins_the_prefix(self) -> None:
        assert _object_key("p/docs", "a/b.html") == "p/docs/a/b.html"
        assert _object_key("", "a/b.html") == "a/b.html"

    def test_iter_source_files_are_relative_and_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.txt").write_text("c", encoding="utf-8")
        files = iter_source_files(tmp_path)
        assert [relative for relative, _ in files] == ["a.txt", "b.txt", "sub/c.txt"]

    def test_iter_source_files_skips_a_link_outside_the_source(self, tmp_path: Path) -> None:
        source = tmp_path / "site"
        source.mkdir()
        (source / "inside.txt").write_text("x", encoding="utf-8")
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            (source / "link.txt").symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available here")
        files = iter_source_files(source)
        assert [relative for relative, _ in files] == ["inside.txt"]


class TestS3Client:
    def test_a_transport_error_becomes_a_deploy_error(self, monkeypatch) -> None:
        import requests

        from sdb_plugins.s3.client import S3Client, S3Error

        client = S3Client(
            endpoint="https://example.test",
            bucket="b",
            access_key="k",
            secret_key="s",
            region=REGION,
        )

        def boom(*args, **kwargs):
            raise requests.ConnectionError("no route to host")

        monkeypatch.setattr("sdb_plugins.s3.client.requests.request", boom)
        with pytest.raises(S3Error):
            client.put_object("a.txt", b"data")
        # The engine recognizes the failure from its own error type.
        assert issubclass(S3Error, DeployError)

    def test_list_keys_parses_a_list_response(self) -> None:
        from sdb_plugins.s3.client import _parse_list_keys, _parse_next_token

        payload = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            b"<Contents><Key>a/b.txt</Key></Contents>"
            b"<Contents><Key>c.txt</Key></Contents>"
            b"<NextContinuationToken>tok</NextContinuationToken>"
            b"</ListBucketResult>"
        )
        assert _parse_list_keys(payload) == ["a/b.txt", "c.txt"]
        assert _parse_next_token(payload) == "tok"
