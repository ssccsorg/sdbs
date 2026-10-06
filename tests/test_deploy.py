"""
Tests for the external deploy plugins: the manifest contract, discovery, a
project's activation, and the driver that runs a plugin as a subprocess.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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

# A plugin that records the directory it was handed, so a test can see the
# selection after the engine has removed it.
_RECORDING_PLUGIN = (
    "import json, pathlib, sys\n"
    "request = json.loads(sys.stdin.read())\n"
    "artifact = pathlib.Path(request['artifact'])\n"
    "files = sorted(str(p.relative_to(artifact))\n"
    "               for p in artifact.rglob('*') if p.is_file())\n"
    "pathlib.Path('seen.json').write_text(json.dumps({\n"
    "    'artifact': str(artifact), 'files': files}))\n"
    "print(json.dumps({'deploy': 1, 'ok': True, 'uploaded': len(files)}))\n"
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


def _make_site(root: Path, source: str = "_site") -> Path:
    """A build output holding documents, a page, and the page's own assets."""
    site = root / source
    (site / "nested").mkdir(parents=True)
    (site / "index.html").write_text("<html></html>", encoding="utf-8")
    (site / "intro.pdf").write_text("%PDF", encoding="utf-8")
    (site / "nested" / "deep.pdf").write_text("%PDF", encoding="utf-8")
    (site / "tag.c2pa").write_text("{}", encoding="utf-8")
    (site / "site_libs" / "quarto-html").mkdir(parents=True)
    (site / "site_libs" / "quarto-html" / "asset.pdf").write_text(
        "%PDF", encoding="utf-8"
    )
    (site / "intro_files" / "figure-pdf").mkdir(parents=True)
    (site / "intro_files" / "figure-pdf" / "fig.pdf").write_text(
        "%PDF", encoding="utf-8"
    )
    return site


def _seen(plugin: Path) -> dict:
    """What a recording plugin observed."""
    return json.loads((plugin / "seen.json").read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, body: str) -> Path:
    config = tmp_path / "_deploy.yml"
    config.write_text(body, encoding="utf-8")
    return config


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
        assert load_manifest(path).declared_options == ("bucket", "prefix")

    def test_a_manifest_without_an_interface_declares_no_options(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "manifest.yml"
        path.write_text(
            "manifest: 1\nname: s3\ncommand: [python3]\n", encoding="utf-8"
        )
        assert load_manifest(path).declared_options is None

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

    def test_a_non_string_option_name_is_rejected(self, tmp_path: Path) -> None:
        # A name that is not a string reaches the report as a value the join
        # cannot take, so it is refused where the file is read.
        config = tmp_path / "_deploy.yml"
        config.write_text(
            "deploy:\n"
            "  - plugin: s3\n"
            "    artifact: docs/_site\n"
            "    options:\n"
            "      7: x\n",
            encoding="utf-8",
        )
        with pytest.raises(DeployError):
            load_activations(config)

    def _documents_config(self, tmp_path: Path, body: str) -> Path:
        return _write_config(tmp_path, body)

    def test_a_document_selection_is_read(self, tmp_path: Path) -> None:
        config = self._documents_config(
            tmp_path, "deploy:\n  - plugin: s3\n    documents: [pdf, c2pa]\n"
        )
        activations = load_activations(config)
        assert activations[0].documents == ("pdf", "c2pa")
        assert activations[0].artifact == ""
        assert activations[0].source is None

    def test_extensions_are_normalized(self, tmp_path: Path) -> None:
        """A leading dot and a different case name the same extension."""
        config = self._documents_config(
            tmp_path, "deploy:\n  - plugin: s3\n    documents: ['.PDF', ' c2pa ']\n"
        )
        assert load_activations(config)[0].documents == ("pdf", "c2pa")

    def test_an_artifact_and_a_selection_together_are_rejected(
        self, tmp_path: Path
    ) -> None:
        """One channel publishes one thing, so naming two is a contradiction."""
        config = self._documents_config(
            tmp_path,
            "deploy:\n"
            "  - plugin: s3\n"
            "    artifact: docs/_site\n"
            "    documents: [pdf]\n",
        )
        with pytest.raises(DeployError):
            load_activations(config)

    @pytest.mark.parametrize(
        "documents",
        [
            "[]",
            "pdf",
            "[pdf, 7]",
            "['']",
            "['a b']",
            "['.']",
        ],
    )
    def test_a_selection_that_is_not_a_list_of_extensions_is_rejected(
        self, tmp_path: Path, documents: str
    ) -> None:
        config = self._documents_config(
            tmp_path, f"deploy:\n  - plugin: s3\n    documents: {documents}\n"
        )
        with pytest.raises(DeployError):
            load_activations(config)

    def test_a_source_without_a_selection_is_rejected(self, tmp_path: Path) -> None:
        """A build output nothing selects from would be read by nobody."""
        config = self._documents_config(
            tmp_path,
            "deploy:\n"
            "  - plugin: s3\n"
            "    artifact: docs/_site\n"
            "    source: elsewhere\n",
        )
        with pytest.raises(DeployError):
            load_activations(config)

    def test_a_source_that_is_not_a_string_is_rejected(self, tmp_path: Path) -> None:
        config = self._documents_config(
            tmp_path,
            "deploy:\n  - plugin: s3\n    documents: [pdf]\n    source: [a]\n",
        )
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


class TestDocumentSelection:
    """A channel that publishes documents, selected out of the build output."""

    CONFIG = (
        "deploy:\n"
        "  - plugin: s3\n"
        "    documents: [pdf, c2pa]\n"
        "    options:\n"
        "      bucket: b\n"
    )

    def _project(self, tmp_path: Path) -> tuple[Path, Path]:
        root = _make_project(tmp_path, self.CONFIG, artifact=False)
        _make_site(root, "_site")
        plugin = _make_plugin(root / "plugins", "s3", _RECORDING_PLUGIN)
        return root, plugin

    def test_the_selection_reaches_the_plugin(self, tmp_path: Path) -> None:
        root, plugin = self._project(tmp_path)
        assert run_deploy(root) is True
        assert _seen(plugin)["files"] == [
            "intro.pdf",
            "nested/deep.pdf",
            "tag.c2pa",
        ]

    def test_page_assets_are_not_documents(self, tmp_path: Path) -> None:
        """A PDF inside a page's asset directory belongs to the page, not the channel."""
        root, plugin = self._project(tmp_path)
        run_deploy(root)
        for path in _seen(plugin)["files"]:
            assert not path.startswith("site_libs/"), path
            assert "_files/" not in path, path

    def test_the_composed_directory_is_removed_afterwards(self, tmp_path: Path) -> None:
        """The engine owns the directory, so nothing is left behind in the tree."""
        root, plugin = self._project(tmp_path)
        run_deploy(root)
        composed = Path(_seen(plugin)["artifact"])
        assert not composed.exists()
        assert composed != root / "_site"

    def test_the_selection_leaves_the_build_output_alone(self, tmp_path: Path) -> None:
        root, _ = self._project(tmp_path)
        before = sorted(p.name for p in (root / "_site").iterdir())
        run_deploy(root)
        assert sorted(p.name for p in (root / "_site").iterdir()) == before

    def test_the_source_can_name_the_build_output(self, tmp_path: Path) -> None:
        """A build that wrote somewhere other than _site is named rather than guessed."""
        config = self.CONFIG.replace(
            "    options:", "    source: build/out\n    options:"
        )
        root = _make_project(tmp_path, config, artifact=False)
        _make_site(root, "build/out")
        plugin = _make_plugin(root / "plugins", "s3", _RECORDING_PLUGIN)
        assert run_deploy(root) is True
        assert _seen(plugin)["files"] == [
            "intro.pdf",
            "nested/deep.pdf",
            "tag.c2pa",
        ]

    def test_a_missing_build_output_fails(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG, artifact=False)
        _make_plugin(root / "plugins", "s3", _RECORDING_PLUGIN)
        assert run_deploy(root) is False

    def test_a_selection_that_matches_nothing_fails(self, tmp_path: Path) -> None:
        """A run that would upload nothing reports rather than succeeding."""
        root = _make_project(tmp_path, self.CONFIG, artifact=False)
        site = root / "_site"
        site.mkdir()
        (site / "index.html").write_text("<html></html>", encoding="utf-8")
        _make_plugin(root / "plugins", "s3", _RECORDING_PLUGIN)
        assert run_deploy(root) is False

    def test_a_selection_is_not_checked_against_the_declared_options(
        self, tmp_path: Path
    ) -> None:
        """'documents' composes the artifact rather than reaching the plugin."""
        config = "deploy:\n  - plugin: s3\n    documents: [pdf]\n"
        root = _make_project(tmp_path, config, artifact=False)
        _make_site(root, "_site")
        _make_declaring_plugin(root / "plugins", "s3", _RECORDING_PLUGIN, options=[])
        assert run_deploy(root) is True

    def test_a_composition_that_cannot_be_written_fails(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A copy that fails is a deploy failure rather than a traceback."""
        root, _ = self._project(tmp_path)

        def refuse(source, destination):
            raise OSError("no space left on device")

        monkeypatch.setattr(sdb.deploy.shutil, "copy2", refuse)
        assert run_deploy(root) is False


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

    def test_a_non_positive_timeout_fails(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        plugin = _make_plugin(root / "plugins", "s3", _OK_PLUGIN)
        assert run_deploy(root, timeout=0) is False
        assert not (plugin / "request.json").exists()


class TestBrokenPlugin:
    """A plugin that cannot be read is reported, and the others still run."""

    CONFIG = (
        "deploy:\n"
        "  - plugin: good\n"
        "    artifact: docs/_site\n"
        "    options:\n"
        "      bucket: b\n"
    )

    _BROKEN = "manifest: 2\nname: broken\ncommand: [python3]\n"

    def _add_broken(self, root: Path) -> None:
        directory = root / "plugins" / "broken"
        directory.mkdir(parents=True)
        (directory / "manifest.yml").write_text(self._BROKEN, encoding="utf-8")

    def test_a_broken_manifest_does_not_stop_the_others(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root = _make_project(tmp_path, self.CONFIG)
        _make_plugin(root / "plugins", "good", _OK_PLUGIN)
        self._add_broken(root)
        with caplog.at_level(logging.WARNING, logger="sdb.deploy"):
            assert run_deploy(root, dry_run=True) is True
        assert any("broken" in record.getMessage() for record in caplog.records)

    def test_a_required_activation_that_names_a_broken_plugin_fails(
        self, tmp_path: Path
    ) -> None:
        config = self.CONFIG.replace("plugin: good", "plugin: broken\n    require: true")
        root = _make_project(tmp_path, config)
        self._add_broken(root)
        assert run_deploy(root) is False


class TestDocumentedManifest:
    """The manifest the README shows is the one the reference plugin carries."""

    def test_the_readme_example_is_the_reference_manifest(self) -> None:
        root = Path(__file__).resolve().parent.parent
        readme = (root / "README.md").read_text(encoding="utf-8")
        shown = next(
            block
            for block in (
                yaml.safe_load(text)
                for text in re.findall(r"```yaml\n(.*?)```", readme, re.DOTALL)
            )
            if isinstance(block, dict) and "manifest" in block
        )
        carried = yaml.safe_load(
            (root / "plugins" / "s3" / "manifest.yml").read_text(encoding="utf-8")
        )
        assert shown == carried


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
