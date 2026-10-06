"""
External deploy plugins.

A deploy plugin is an external tool, unrelated to sdbs. It lives in its own
directory, declares its contract in a ``manifest.yml`` at that root, and is
invoked as a subprocess. sdbs carries no plugin code and imports no plugin: it
reads a manifest, runs the command, and reads the result.

Activation belongs to the project that uses sdbs, in a ``_deploy.yml`` at that
project's root. A plugin named there and found on the plugin path is invoked;
a plugin named there and not found is skipped, unless the activation sets
``require: true`` or the run passes ``--require-all``. A manifest that declares
an interface states the options it takes, and an activation option the manifest
does not declare fails the run, so a typo is reported rather than passed to a
plugin that ignores it.

An activation declares what it publishes in exactly one of two ways: the
``artifact`` directory to upload, or the ``documents`` extensions to select out
of the build output. A selection is the engine's work rather than a project
script's: the engine knows where the build wrote its output and which of those
paths are documents rather than page assets, copies the selection into a
directory it owns, and hands that directory to the plugin.

The contract across the process boundary is one JSON request on the plugin's
stdin and one JSON result on its stdout, with the exit code carrying success or
failure. Credentials travel in the environment, never on the command line or in
the request.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .config import ConfigManager

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.yml"
CONFIG_NAME = "_deploy.yml"
PLUGIN_PATH_ENV = "SDB_PLUGIN_PATH"
DEFAULT_PLUGINS_DIR = "plugins"
MANIFEST_API = 1
WIRE_API = 1
DEFAULT_TIMEOUT = 900.0
# Where a Quarto site build writes its output, relative to the directory holding
# the activation unless the activation names another place.
SITE_DIR = "_site"
# A site build writes page assets into these directories beside a page. A
# document that lands inside one of them belongs to the page, not to a channel
# that publishes documents.
PAGE_ASSET_DIR_NAMES = frozenset({"site_libs"})
PAGE_ASSET_DIR_SUFFIXES = ("_files",)


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
    # The option names the manifest declares: None when it declares none and
    # therefore accepts any option, an empty tuple when it declares an empty
    # list and therefore accepts no option.
    declared_options: Optional[Tuple[str, ...]] = None


@dataclass
class Activation:
    """One channel a project asks for, from its ``_deploy.yml``."""

    plugin: str
    # The directory the channel uploads, when the project names one.
    artifact: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)
    require: bool = False
    # The document extensions the channel publishes, selected out of the build
    # output. Exactly one of artifact and documents is given.
    documents: Optional[Tuple[str, ...]] = None
    # The build output a selection reads, when it is not the site directory.
    source: Optional[str] = None


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
    declared_options = _interface_options(raw.get("interface"), manifest_path)
    return PluginManifest(
        name=name,
        command=list(command),
        root=manifest_path.parent,
        env={str(k): str(v) for k, v in env.items()},
        description=str(raw.get("description") or ""),
        path=manifest_path,
        declared_options=declared_options,
    )


def _interface_options(
    interface: Any, manifest_path: Path
) -> Optional[Tuple[str, ...]]:
    """Check the optional ``interface`` block and return its option names.

    The block states what the plugin takes, and the names it lists are the
    contract an activation is checked against. A manifest without the block, or
    without ``options`` in it, declares nothing and accepts any option, which
    keeps a plugin that takes free-form options working. Rejecting a malformed
    block keeps the declaration honest, so a plugin author learns of a typo here
    rather than from a reader who trusted a field that said nothing.
    """
    if interface is None:
        return None
    if not isinstance(interface, dict):
        raise DeployError(f"{manifest_path}: 'interface' must be a mapping")
    artifact = interface.get("artifact")
    if artifact is not None and not isinstance(artifact, str):
        raise DeployError(f"{manifest_path}: interface.artifact must be a string")
    options = interface.get("options")
    if options is None:
        return None
    if not isinstance(options, list) or not all(
        isinstance(option, str) for option in options
    ):
        raise DeployError(
            f"{manifest_path}: interface.options must be a list of strings"
        )
    return tuple(options)


def _document_extensions(
    value: Any, config_path: Path, index: int, plugin: str
) -> Optional[Tuple[str, ...]]:
    """The document extensions an activation publishes, or None when it publishes a
    directory instead."""
    if value is None:
        return None
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) for item in value
    ):
        raise DeployError(
            f"{config_path}: deploy entry {index} ({plugin}): 'documents' must be a "
            "non-empty list of extensions"
        )
    extensions: List[str] = []
    for item in value:
        name = item.strip().lower().lstrip(".")
        if not name or not all(part.isalnum() for part in name.split(".")):
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}): {item!r} is not a "
                "document extension"
            )
        extensions.append(name)
    return tuple(extensions)


def _is_page_asset(relative: Path) -> bool:
    """Whether a path belongs to a page's asset directory rather than to a document.

    A site build writes ``site_libs`` and ``*_files`` beside the page that owns
    them, and a document that lands inside one is that page's asset.
    """
    return any(
        part in PAGE_ASSET_DIR_NAMES or part.endswith(PAGE_ASSET_DIR_SUFFIXES)
        for part in relative.parts[:-1]
    )


def select_documents(source: Path, extensions: Tuple[str, ...]) -> List[Path]:
    """The files under *source* a channel publishing *extensions* uploads."""
    selected = {
        path
        for extension in extensions
        for path in source.rglob(f"*.{extension}")
        if path.is_file() and not _is_page_asset(path.relative_to(source))
    }
    return sorted(selected)


@contextmanager
def assemble_documents(
    source: Path, extensions: Tuple[str, ...]
) -> Iterator[Path]:
    """Gather the documents a channel publishes into a directory of the engine's own.

    The build output belongs to the render, and a deploy container mounts the
    tree read-only, so the selection is copied into a temporary directory that
    the activation removes when it finishes.
    """
    if not source.is_dir():
        raise DeployError(
            f"the build output {source} is not a directory; run the build that "
            "writes it before the deploy"
        )
    documents = select_documents(source, extensions)
    if not documents:
        wanted = " or ".join(f".{extension}" for extension in extensions)
        raise DeployError(
            f"the build output {source} holds no {wanted} document to publish"
        )
    staging = Path(tempfile.mkdtemp(prefix="sdb-deploy-"))
    try:
        for document in documents:
            destination = staging / document.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(document, destination)
        logger.info(
            "Deploy: selected %d document(s) from %s", len(documents), source
        )
        yield staging
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
    """Index every plugin that declares a manifest, by name.

    A plugin whose manifest cannot be read is reported and skipped, so one
    broken plugin does not stop the others from running. An activation that
    names the skipped plugin then meets the missing-plugin path, and
    ``require: true`` turns that into a failure, so the cause is reported
    beside the consequence.
    """
    index: Dict[str, PluginManifest] = {}
    for directory in plugin_dirs(project_root, extra):
        if not directory.is_dir():
            continue
        try:
            children = sorted(directory.iterdir())
        except OSError as error:
            logger.warning("Deploy: cannot read %s: %s; skipped", directory, error)
            continue
        for child in children:
            manifest_path = child / MANIFEST_NAME
            try:
                if not manifest_path.is_file():
                    continue
                manifest = load_manifest(manifest_path)
            except (DeployError, OSError) as error:
                logger.warning("Deploy: %s; skipped", error)
                continue
            if manifest.name in index:
                logger.warning(
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
        documents = _document_extensions(
            entry.get("documents"), config_path, index, plugin
        )
        if bool(artifact) == (documents is not None):
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}) needs exactly one of "
                "'artifact', a directory to upload, and 'documents', the extensions to "
                "select from the build output"
            )
        source = entry.get("source")
        if source is not None and not isinstance(source, str):
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}): 'source' must be a "
                "string"
            )
        source = (source or "").strip() or None
        if source is not None and documents is None:
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}): 'source' names the "
                "build output 'documents' selects from, so it needs 'documents'"
            )
        options = entry.get("options") or {}
        if not isinstance(options, dict):
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}): options must be a mapping"
            )
        if not all(isinstance(name, str) for name in options):
            raise DeployError(
                f"{config_path}: deploy entry {index} ({plugin}): "
                "option names must be strings"
            )
        activations.append(
            Activation(
                plugin=plugin,
                artifact=artifact,
                options=options,
                require=bool(entry.get("require", False)),
                documents=documents,
                source=source,
            )
        )
    return activations


def invoke(
    manifest: PluginManifest,
    request: Dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise DeployError(
            f"plugin {manifest.name!r} did not return within {timeout:g}s"
        ) from error
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


def _undeclared_options(
    options: Dict[str, Any], manifest: PluginManifest
) -> List[str]:
    """The activation options the manifest does not declare, if it declares any."""
    if manifest.declared_options is None:
        return []
    return sorted(name for name in options if name not in manifest.declared_options)


def _resolve(base: Path, value: str) -> Path:
    """Resolve a path an activation declares against the directory holding its config."""
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _run_activation(
    activation: Activation,
    manifest: PluginManifest,
    artifact: Path,
    dry_run: bool,
    timeout: float,
) -> bool:
    """Run one activation against a resolved artifact directory."""
    request = {
        "deploy": WIRE_API,
        "plugin": activation.plugin,
        "artifact": str(artifact),
        "options": activation.options,
        "dry_run": dry_run,
    }
    logger.info("Deploy %s [%s] %s", activation.plugin, manifest.path, artifact)
    try:
        result = invoke(manifest, request, timeout)
    except DeployError as error:
        logger.error("Deploy: %s", error)
        return False
    if not result.get("ok", False):
        logger.error(
            "Deploy: plugin %r reported failure: %s",
            activation.plugin,
            result.get("message") or "no message",
        )
        return False
    logger.info(
        "Deploy %s: %s uploaded, %s deleted",
        activation.plugin,
        result.get("uploaded", 0),
        result.get("deleted", 0),
    )
    for url in result.get("urls", []) or []:
        logger.info("Deploy %s: %s", activation.plugin, url)
    return True


def _activation_artifact(activation: Activation, base: Path) -> Path:
    """The directory an activation uploads, resolved and checked to exist."""
    artifact = _resolve(base, activation.artifact or "")
    if not artifact.exists():
        raise DeployError(f"{activation.plugin}: artifact does not exist: {artifact}")
    return artifact


def run_deploy(
    project_root: Path,
    config_path: Optional[Path] = None,
    dry_run: bool = False,
    require_all: bool = False,
    extra_plugin_dirs: Optional[List[str]] = None,
    plugins: Optional[Dict[str, PluginManifest]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Run every activation in a project's ``_deploy.yml``.

    A plugin that is named but not found is skipped unless it is required. A
    plugin that is found and fails fails the run.
    """
    if timeout <= 0:
        logger.error("Deploy: the timeout must be greater than zero, got %g", timeout)
        return False
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

        undeclared = _undeclared_options(activation.options, manifest)
        if undeclared:
            logger.error(
                "Deploy: plugin %r does not declare option(s): %s (it declares: %s)",
                activation.plugin,
                ", ".join(undeclared),
                ", ".join(manifest.declared_options or ()) or "none",
            )
            ok = False
            continue

        if activation.documents is not None:
            source = _resolve(base, activation.source or SITE_DIR)
            try:
                with assemble_documents(source, activation.documents) as artifact:
                    if not _run_activation(
                        activation, manifest, artifact, dry_run, timeout
                    ):
                        ok = False
            except DeployError as error:
                logger.error("Deploy: %s", error)
                ok = False
        else:
            try:
                artifact = _activation_artifact(activation, base)
            except DeployError as error:
                logger.error("Deploy: %s", error)
                ok = False
                continue
            if not _run_activation(activation, manifest, artifact, dry_run, timeout):
                ok = False
    return ok


def list_plugins(
    project_root: Path, extra_plugin_dirs: Optional[List[str]] = None
) -> List[PluginManifest]:
    index = discover(project_root, extra_plugin_dirs)
    return [index[name] for name in sorted(index)]
