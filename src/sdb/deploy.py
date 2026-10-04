"""
External deploy plugins.

A deploy plugin is an external tool, unrelated to sdbs. It lives in its own
directory, declares its contract in a ``manifest.yml`` at that root, and is
invoked as a subprocess. sdbs carries no plugin code and imports no plugin: it
reads a manifest, runs the command, and reads the result.

Activation belongs to the project that uses sdbs, in a ``_deploy.yml`` at that
project's root. A plugin named there and found on the plugin path is invoked;
a plugin named there and not found is skipped, unless the activation sets
``require: true`` or the run passes ``--require-all``.

The contract across the process boundary is one JSON request on the plugin's
stdin and one JSON result on its stdout, with the exit code carrying success or
failure. Credentials travel in the environment, never on the command line or in
the request.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import ConfigManager

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.yml"
CONFIG_NAME = "_deploy.yml"
PLUGIN_PATH_ENV = "SDB_PLUGIN_PATH"
DEFAULT_PLUGINS_DIR = "plugins"
MANIFEST_API = 1
WIRE_API = 1


class DeployError(RuntimeError):
    """A manifest, a configuration, or a plugin run that cannot proceed."""


@dataclass
class PluginManifest:
    """The contract a plugin declares at its root."""

    name: str
    command: List[str]
    root: Path
    env: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    path: Optional[Path] = None


@dataclass
class Activation:
    """One channel a project asks for, from its ``_deploy.yml``."""

    plugin: str
    artifact: str
    options: Dict[str, Any] = field(default_factory=dict)
    require: bool = False


def load_manifest(manifest_path: Path) -> PluginManifest:
    raw = ConfigManager.load_yaml_file(manifest_path)
    if not raw:
        raise DeployError(f"{manifest_path}: the manifest is empty or not readable")
    api = raw.get("manifest")
    if api != MANIFEST_API:
        raise DeployError(
            f"{manifest_path}: manifest api {api!r} is not the supported {MANIFEST_API}"
        )
    name = str(raw.get("name") or "").strip()
    if not name:
        raise DeployError(f"{manifest_path}: 'name' is required")
    command = raw.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) for part in command
    ):
        raise DeployError(f"{manifest_path}: 'command' must be a non-empty list of strings")
    env = raw.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(k, str) for k in env):
        raise DeployError(f"{manifest_path}: 'env' must be a mapping")
    _validate_interface(raw.get("interface"), manifest_path)
    return PluginManifest(
        name=name,
        command=list(command),
        root=manifest_path.parent,
        env={str(k): str(v) for k, v in env.items()},
        description=str(raw.get("description") or ""),
        path=manifest_path,
    )


def _validate_interface(interface: Any, manifest_path: Path) -> None:
    """Check the optional ``interface`` block a manifest declares.

    The block is metadata for a human, and the engine reads nothing from it to
    run a plugin. Rejecting a malformed one keeps the declaration honest, so a
    plugin author learns of a typo here rather than from a reader who trusted a
    field that said nothing.
    """
    if interface is None:
        return
    if not isinstance(interface, dict):
        raise DeployError(f"{manifest_path}: 'interface' must be a mapping")
    artifact = interface.get("artifact")
    if artifact is not None and not isinstance(artifact, str):
        raise DeployError(f"{manifest_path}: interface.artifact must be a string")
    options = interface.get("options")
    if options is not None and (
        not isinstance(options, list)
        or not all(isinstance(option, str) for option in options)
    ):
        raise DeployError(
            f"{manifest_path}: interface.options must be a list of strings"
        )


def plugin_dirs(project_root: Path, extra: Optional[List[str]] = None) -> List[Path]:
    """The directories searched for plugins, in order, first match wins."""
    dirs: List[Path] = []
    for value in (extra or []):
        dirs.append(Path(value))
    env = os.environ.get(PLUGIN_PATH_ENV, "")
    for value in env.split(os.pathsep):
        if value:
            dirs.append(Path(value))
    dirs.append(project_root / DEFAULT_PLUGINS_DIR)
    return dirs


def discover(
    project_root: Path, extra: Optional[List[str]] = None
) -> Dict[str, PluginManifest]:
    """Index every plugin that declares a manifest, by name."""
    index: Dict[str, PluginManifest] = {}
    for directory in plugin_dirs(project_root, extra):
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir()):
            manifest_path = child / MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            manifest = load_manifest(manifest_path)
            if manifest.name in index:
                logger.debug(
                    "Deploy: plugin %r at %s is shadowed by %s",
                    manifest.name,
                    manifest_path,
                    index[manifest.name].path,
                )
                continue
            index[manifest.name] = manifest
    return index


def load_activations(config_path: Path) -> List[Activation]:
    """Read the ``deploy`` list from a project's ``_deploy.yml``."""
    raw = ConfigManager.load_yaml_file(config_path)
    entries = raw.get("deploy") or []
    if not isinstance(entries, list):
        raise DeployError(f"{config_path}: 'deploy' must be a list")
    activations: List[Activation] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise DeployError(f"{config_path}: deploy entry {index} is not a mapping")
        plugin = str(entry.get("plugin") or "").strip()
        if not plugin:
            raise DeployError(f"{config_path}: deploy entry {index} has no plugin")
        artifact = str(entry.get("artifact") or "").strip()
        if not artifact:
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}) has no artifact"
            )
        options = entry.get("options") or {}
        if not isinstance(options, dict):
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}): options must be a mapping"
            )
        activations.append(
            Activation(
                plugin=plugin,
                artifact=artifact,
                options=options,
                require=bool(entry.get("require", False)),
            )
        )
    return activations


def invoke(manifest: PluginManifest, request: Dict[str, Any]) -> Dict[str, Any]:
    """Run one plugin and return its JSON result."""
    environment = dict(os.environ)
    environment.update(manifest.env)
    try:
        process = subprocess.run(
            manifest.command,
            cwd=manifest.root,
            env=environment,
            input=json.dumps(request).encode("utf-8"),
            capture_output=True,
        )
    except FileNotFoundError as error:
        raise DeployError(
            f"plugin {manifest.name!r}: command not found: {manifest.command[0]}"
        ) from error
    stderr = process.stderr.decode("utf-8", errors="replace").strip()
    result: Optional[Dict[str, Any]] = None
    try:
        result = _read_result(process.stdout, manifest.name)
    except DeployError:
        result = None
    if process.returncode != 0:
        message = str(result.get("message") or "") if isinstance(result, dict) else ""
        raise DeployError(
            f"plugin {manifest.name!r} exited with {process.returncode}: "
            + (message or stderr or "no message")
        )
    if result is None:
        raise DeployError(f"plugin {manifest.name!r} produced no result")
    return result


def _read_result(stdout: bytes, name: str) -> Dict[str, Any]:
    line = next(
        (line for line in reversed(stdout.decode("utf-8", errors="replace").splitlines()) if line.strip()),
        None,
    )
    if line is None:
        raise DeployError(f"plugin {name!r} produced no result")
    try:
        result = json.loads(line)
    except json.JSONDecodeError as error:
        raise DeployError(f"plugin {name!r} did not produce JSON: {error}") from error
    if not isinstance(result, dict) or result.get("deploy") != WIRE_API:
        raise DeployError(
            f"plugin {name!r}: result api {result.get('deploy')!r} is not the supported {WIRE_API}"
        )
    return result


def run_deploy(
    project_root: Path,
    config_path: Optional[Path] = None,
    dry_run: bool = False,
    require_all: bool = False,
    extra_plugin_dirs: Optional[List[str]] = None,
    plugins: Optional[Dict[str, PluginManifest]] = None,
) -> bool:
    """Run every activation in a project's ``_deploy.yml``.

    A plugin that is named but not found is skipped unless it is required. A
    plugin that is found and fails fails the run.
    """
    config_path = config_path or (project_root / CONFIG_NAME)
    if not config_path.is_file():
        logger.info("Deploy: no %s under %s; nothing to do", CONFIG_NAME, project_root)
        return True
    try:
        activations = load_activations(config_path)
    except DeployError as error:
        logger.error("Deploy: %s", error)
        return False

    base = config_path.parent
    index = plugins if plugins is not None else discover(project_root, extra_plugin_dirs)

    ok = True
    for activation in activations:
        artifact = Path(activation.artifact)
        if not artifact.is_absolute():
            artifact = base / artifact
        artifact = artifact.resolve()
        if not artifact.exists():
            logger.error(
                "Deploy: %s: artifact does not exist: %s", activation.plugin, artifact
            )
            ok = False
            continue

        manifest = index.get(activation.plugin)
        if manifest is None:
            if activation.require or require_all:
                logger.error(
                    "Deploy: plugin %r is required but no manifest was found on the plugin path",
                    activation.plugin,
                )
                ok = False
            else:
                logger.info(
                    "Deploy: plugin %r not found; skipped", activation.plugin
                )
            continue

        request = {
            "deploy": WIRE_API,
            "plugin": activation.plugin,
            "artifact": str(artifact),
            "options": activation.options,
            "dry_run": dry_run,
        }
        logger.info(
            "Deploy %s [%s] %s", activation.plugin, manifest.path, artifact
        )
        try:
            result = invoke(manifest, request)
        except DeployError as error:
            logger.error("Deploy: %s", error)
            ok = False
            continue
        if not result.get("ok", False):
            logger.error(
                "Deploy: plugin %r reported failure: %s",
                activation.plugin,
                result.get("message") or "no message",
            )
            ok = False
            continue
        logger.info(
            "Deploy %s: %s uploaded, %s deleted",
            activation.plugin,
            result.get("uploaded", 0),
            result.get("deleted", 0),
        )
        for url in result.get("urls", []) or []:
            logger.info("Deploy %s: %s", activation.plugin, url)
    return ok


def list_plugins(
    project_root: Path, extra_plugin_dirs: Optional[List[str]] = None
) -> List[PluginManifest]:
    index = discover(project_root, extra_plugin_dirs)
    return [index[name] for name in sorted(index)]
