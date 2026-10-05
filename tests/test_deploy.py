"""
Tests for the external deploy plugins: the manifest contract, discovery, a
project's activation, and the driver that runs a plugin as a subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import sdb.deploy
from sdb.deploy import (
    DeployError,
    discover,
    list_plugins,
    load_activations,
    load_manifest,
    run_deploy,
)

_OK_PLUGIN = (
    "import json, pathlib, sys\n"
    "request = json.loads(sys.stdin.read())\n"
    "pathlib.Path('request.json').write_text(json.dumps(request))\n"
    "print(json.dumps({'deploy': 1, 'ok': True, 'uploaded': 1, 'deleted': 0}))\n"
)

_FAIL_PLUGIN = (
    "import json, sys\n"
    "print(json.dumps({'deploy': 1, 'ok': False, 'message': 'the store said no'}))\n"
    "sys.exit(2)\n"
)


def _write_manifest(directory: Path, name: str, command: list[str], extra: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"  - {json.dumps(part)}" for part in command)
    (directory / "manifest.yml").write_text(
        f"manifest: 1\nname: {name}\ncommand:\n{body}\n{extra}", encoding="utf-8"
    )
    return directory


def _make_plugin(plugins_root: Path, name: str, script: str) -> Path:
    directory = plugins_root / name
    _write_manifest(directory, name, ["python3", "run.py"])
    (directory / "run.py").write_text(script, encoding="utf-8")
    return directory


def _make_declaring_plugin(
    plugins_root: Path, name: str, script: str, options: list[str] | None
) -> Path:
    """A plugin whose manifest declares, or does not declare, the options it takes."""
    directory = plugins_root / name
    extra = ""
    if options is not None:
        declared = "".join(f"    - {option}\n" for option in options)
        extra = f"interface:\n  options:\n{declared}"
    _write_manifest(directory, name, ["python3", "run.py"], extra=extra)
    (directory / "run.py").write_text(script, encoding="utf-8")
    return directory


def _make_project(tmp_path: Path, config: str, artifact: bool = True) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "_deploy.yml").write_text(config, encoding="utf-8")
    if artifact:
        site = root / "docs" / "_site"
        site.mkdir(parents=True)
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
    return root


class TestManifest:
    def test_a_valid_manifest_loads(self, tmp_path: Path) -> None:
        directory = _write_manifest(tmp_path / "s3", "s3", ["python3", "__main__.py"])
        manifest = load_manifest(directory / "manifest.yml")
        assert manifest.name == "s3"
        assert manifest.command == ["python3", "__main__.py"]
        assert manifest.root == directory

    def test_a_missing_name_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text("manifest: 1\ncommand: [python3]\n", encoding="utf-8")
        with pytest.raises(DeployError):
            load_manifest(path)

    def test_a_command_that_is_not_a_list_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text("manifest: 1\nname: s3\ncommand: python3\n", encoding="utf-8")
        with pytest.raises(DeployError):
            load_manifest(path)

    def test_an_unsupported_api_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text("manifest: 2\nname: s3\ncommand: [python3]\n", encoding="utf-8")
        with pytest.raises(DeployError):
            load_manifest(path)

    def test_a_well_formed_interface_is_accepted(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text(
            "manifest: 1\nname: s3\ncommand: [python3]\n"
            "interface:\n  artifact: directory\n  options:\n    - bucket\n",
            encoding="utf-8",
        )
        assert load_manifest(path).name == "s3"

    def test_declared_options_are_captured(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text(
            "manifest: 1\nname: s3\ncommand: [python3]\n"
            "interface:\n  options:\n    - bucket\n    - prefix\n",
            encoding="utf-8",
        )
        assert load_manifest(path).options == ("bucket", "prefix")

    def test_a_manifest_without_an_interface_declares_no_options(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text(
            "manifest: 1\nname: s3\ncommand: [python3]\n", encoding="utf-8"
        )
        assert load_manifest(path).options is None

    def test_an_interface_that_is_not_a_mapping_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text(
            "manifest: 1\nname: s3\ncommand: [python3]\ninterface: bucket\n",
            encoding="utf-8",
        )
        with pytest.raises(DeployError):
            load_manifest(path)

    def test_an_interface_options_entry_that_is_not_a_string_is_rejected(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text(
            "manifest: 1\nname: s3\ncommand: [python3]\n"
            "interface:\n  options:\n    - 3\n",
            encoding="utf-8",
        )
        with pytest.raises(DeployError):
            load_manifest(path)


class TestDiscovery:
    def test_a_plugin_under_the_project_is_found(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path / "plugins", "s3", _OK_PLUGIN)
        index = discover(tmp_path)
        assert set(index) == {"s3"}
        assert index["s3"].path == tmp_path / "plugins" / "s3" / "manifest.yml"

    def test_the_plugin_path_env_is_searched(self, tmp_path: Path, monkeypatch) -> None:
        external = tmp_path / "shared"
        _make_plugin(external, "s3", _OK_PLUGIN)
        monkeypatch.setenv("SDB_PLUGIN_PATH", str(external))
        index = discover(tmp_path)
        assert "s3" in index

    def test_the_first_directory_wins(self, tmp_path: Path, monkeypatch) -> None:
        first = tmp_path / "first"
        _make_plugin(first, "s3", _OK_PLUGIN)
        monkeypatch.setenv("SDB_PLUGIN_PATH", str(first))
        _make_plugin(tmp_path / "plugins", "s3", _FAIL_PLUGIN)
        index = discover(tmp_path)
        assert index["s3"].root == first / "s3"

    def test_the_plugin_path_env_beats_the_project_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # An explicit location beats the convention, so a deployment that
        # names a plugin path can replace a plugin the project ships under the
        # same name.
        shared = tmp_path / "shared"
        _make_plugin(shared, "s3", _OK_PLUGIN)
        monkeypatch.setenv("SDB_PLUGIN_PATH", str(shared))
        _make_plugin(tmp_path / "plugins", "s3", _FAIL_PLUGIN)
        assert discover(tmp_path)["s3"].root == shared / "s3"

    def test_list_plugins_is_sorted(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path / "plugins", "zeta", _OK_PLUGIN)
        _make_plugin(tmp_path / "plugins", "alpha", _OK_PLUGIN)
        assert [manifest.name for manifest in list_plugins(tmp_path)] == ["alpha", "zeta"]


class TestActivations:
    def test_activations_are_read(self, tmp_path: Path) -> None:
        config = tmp_path / "_deploy.yml"
        config.write_text(
            "deploy:\n"
            "  - plugin: s3\n"
            "    artifact: docs/_site\n"
            "    options:\n"
            "      bucket: b\n",
            encoding="utf-8",
        )
        activations = load_activations(config)
        assert len(activations) == 1
        assert activations[0].plugin == "s3"
        assert activations[0].artifact == "docs/_site"
        assert activations[0].options == {"bucket": "b"}
        assert activations[0].require is False

    def test_a_missing_plugin_is_rejected(self, tmp_path: Path) -> None:
        config = tmp_path / "_deploy.yml"
        config.write_text("deploy:\n  - artifact: docs/_site\n", encoding="utf-8")
        with pytest.raises(DeployError):
            load_activations(config)

    def test_a_missing_artifact_is_rejected(self, tmp_path: Path) -> None:
        config = tmp_path / "_deploy.yml"
        config.write_text("deploy:\n  - plugin: s3\n", encoding="utf-8")
        with pytest.raises(DeployError):
            load_activations(config)


class TestRunDeploy:
    CONFIG = (
        "deploy:\n"
        "  - plugin: s3\n"
        "    artifact: docs/_site\n"
        "    options:\n"
        "      bucket: b\n"
        "      prefix: p\n"
    )

    def test_a_found_plugin_is_invoked(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        plugin = _make_plugin(root / "plugins", "s3", _OK_PLUGIN)
        assert run_deploy(root, dry_run=True) is True
        request = json.loads((plugin / "request.json").read_text(encoding="utf-8"))
        assert request["artifact"] == str(root / "docs" / "_site")
        assert request["options"] == {"bucket": "b", "prefix": "p"}
        assert request["dry_run"] is True

    def test_a_missing_optional_plugin_is_skipped(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        assert run_deploy(root) is True

    def test_a_missing_required_plugin_fails(self, tmp_path: Path) -> None:
        config = self.CONFIG.replace("plugin: s3", "plugin: s3\n    require: true")
        root = _make_project(tmp_path, config)
        assert run_deploy(root) is False

    def test_require_all_fails_on_a_missing_plugin(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        assert run_deploy(root, require_all=True) is False

    def test_a_missing_artifact_fails(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG, artifact=False)
        _make_plugin(root / "plugins", "s3", _OK_PLUGIN)
        assert run_deploy(root) is False

    def test_a_plugin_that_exits_nonzero_fails(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        _make_plugin(root / "plugins", "s3", _FAIL_PLUGIN)
        assert run_deploy(root) is False

    def test_no_config_is_nothing_to_do(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        root.mkdir()
        assert run_deploy(root) is True

    def test_dry_run_is_forwarded(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        plugin = _make_plugin(root / "plugins", "s3", _OK_PLUGIN)
        run_deploy(root, dry_run=False)
        request = json.loads((plugin / "request.json").read_text(encoding="utf-8"))
        assert request["dry_run"] is False


class TestDeclaredOptions:
    """An activation is checked against the options its manifest declares."""

    CONFIG = (
        "deploy:\n"
        "  - plugin: s3\n"
        "    artifact: docs/_site\n"
        "    options:\n"
        "      bucket: b\n"
    )

    def test_an_undeclared_option_fails_without_invoking_the_plugin(
        self, tmp_path: Path
    ) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        plugin = _make_declaring_plugin(root / "plugins", "s3", _OK_PLUGIN, ["prefix"])
        assert run_deploy(root) is False
        assert not (plugin / "request.json").exists()

    def test_a_declared_option_runs(self, tmp_path: Path) -> None:
        config = self.CONFIG.replace("bucket: b", "prefix: p")
        root = _make_project(tmp_path, config)
        _make_declaring_plugin(root / "plugins", "s3", _OK_PLUGIN, ["prefix"])
        assert run_deploy(root) is True

    def test_a_manifest_that_declares_no_options_accepts_any(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        _make_declaring_plugin(root / "plugins", "s3", _OK_PLUGIN, None)
        assert run_deploy(root) is True


class TestTimeout:
    CONFIG = (
        "deploy:\n"
        "  - plugin: s3\n"
        "    artifact: docs/_site\n"
        "    options:\n"
        "      bucket: b\n"
    )

    def test_a_plugin_that_does_not_return_fails(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        _make_plugin(root / "plugins", "s3", "import time\ntime.sleep(30)\n")
        assert run_deploy(root, timeout=0.5) is False

    def test_a_plugin_that_returns_within_the_limit_runs(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        _make_plugin(root / "plugins", "s3", _OK_PLUGIN)
        assert run_deploy(root, timeout=30) is True


class TestEngineIsolation:
    """The engine names no vendor and loads no plugin.

    sdbs invokes a plugin as a subprocess and reads no plugin code, so a
    provider constant or a plugin import that reaches the engine is a
    regression of the boundary this module exists to hold.
    """

    _FORBIDDEN = (
        "cloudflare",
        "cloudflarestorage",
        "amazonaws",
        "boto3",
        "minio",
        "wasabi",
        "backblaze",
    )

    def test_the_engine_sources_name_no_vendor(self) -> None:
        package = Path(sdb.deploy.__file__).parent
        findings: list[str] = []
        for path in sorted(package.rglob("*.py")):
            text = path.read_text(encoding="utf-8").lower()
            for token in self._FORBIDDEN:
                if token in text:
                    findings.append(f"{path.name}: {token}")
        assert findings == []

    def test_importing_the_engine_loads_no_plugin(self) -> None:
        # A fresh interpreter, because this process already holds the plugin
        # from the tests that exercise it. The check reads the loaded module
        # files, so it holds whatever the plugin's modules are named.
        code = (
            "import pathlib, sys; import sdb.deploy; "
            "print(sum(1 for m in sys.modules.values() "
            "if getattr(m, '__file__', None) "
            "and 'plugins' in pathlib.Path(m.__file__).parts))"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            [entry for entry in sys.path if entry]
            + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=environment,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0"
