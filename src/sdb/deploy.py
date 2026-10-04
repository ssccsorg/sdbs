"""
The deploy engine: a provider-neutral host for deploy channels.

A deploy channel moves a built tree to an external store. The engine knows the
protocol a channel satisfies and nothing about any store: a channel is anything
with a ``name``, a ``validate``, and a ``deploy``, checked by duck typing, so an
external package provides one without importing or subclassing sdbs. The
``sdb.deploy`` entry point group is how those external channels are discovered;
the channels sdbs ships under :mod:`sdb.plugins` are registered by the command
line, which is the composition root.

``deploy`` runs as its own invocation, apart from the render. The render
container executes project-controlled Quarto and Jupyter code, so it stays free
of upload credentials; this step receives the credentials and walks the built
artifact without running project code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple

from .config import ConfigManager

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sdb.deploy"
DEFAULT_SOURCE = "_site"


class DeployError(RuntimeError):
    """A channel cannot run: its configuration, credentials, or source."""


@dataclass
class DeployTarget:
    """One configured channel: what to deploy, with which plugin."""

    name: str
    plugin: str
    source: str = DEFAULT_SOURCE
    enabled: bool = True
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeployContext:
    """The run a channel sees: where the docs root is and how to behave."""

    docs_root: Path
    dry_run: bool = False


@dataclass
class DeployResult:
    name: str
    plugin: str
    uploaded: int = 0
    deleted: int = 0
    urls: List[str] = field(default_factory=list)
    ok: bool = True
    message: str = ""


class DeployPlugin(Protocol):
    """The channel contract.

    A channel satisfies this by shape: a ``name``, and a ``validate`` and a
    ``deploy`` that take a :class:`DeployTarget` and a :class:`DeployContext`.
    The registry checks those members rather than an imported base class, so a
    channel stays free of any sdbs import and of any provider.
    """

    name: str

    def validate(self, target: DeployTarget, context: DeployContext) -> None:
        """Raise :class:`DeployError` when the channel cannot run. No side effects."""

    def deploy(self, target: DeployTarget, context: DeployContext) -> DeployResult:
        ...


class DeployRegistry:
    """The set of channels a run resolves a target's ``plugin`` against."""

    def __init__(self, plugins: Optional[Iterable[DeployPlugin]] = None) -> None:
        self._plugins: Dict[str, DeployPlugin] = {}
        for plugin in plugins or []:
            self.register(plugin)

    def register(self, plugin: DeployPlugin) -> None:
        problem = _plugin_problem(plugin)
        if problem:
            raise DeployError(
                f"deploy plugin {getattr(plugin, 'name', '')!r}: {problem}"
            )
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> Optional[DeployPlugin]:
        return self._plugins.get(name)

    def names(self) -> List[str]:
        return sorted(self._plugins)

    @classmethod
    def discover(cls, builtins: Iterable[DeployPlugin] = ()) -> "DeployRegistry":
        """Compose the given built-ins with the externally registered channels."""
        registry = cls(builtins)
        for plugin in _entry_point_plugins():
            registry.register(plugin)
        return registry


def _plugin_problem(plugin: Any) -> Optional[str]:
    name = getattr(plugin, "name", "")
    if not isinstance(name, str) or not name:
        return "no name"
    for method in ("validate", "deploy"):
        if not callable(getattr(plugin, method, None)):
            return f"no callable {method}()"
    return None


def _entry_point_plugins() -> Iterable[DeployPlugin]:
    try:
        discovered = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python < 3.10 selects differently
        discovered = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    for entry in discovered:
        try:
            loaded = entry.load()
            plugin = loaded() if isinstance(loaded, type) else loaded
        except Exception as error:
            logger.warning("Could not load deploy plugin %s: %s", entry.name, error)
            continue
        problem = _plugin_problem(plugin)
        if problem:
            logger.warning("Deploy entry point %s: %s", entry.name, problem)
            continue
        yield plugin


def load_deploy_targets(config_path: Optional[Path]) -> List[DeployTarget]:
    """Read the ``deploy`` list from a build configuration file.

    A missing file or a file without a ``deploy`` key yields no targets. A
    malformed entry stops the load, naming the entry, because a channel a
    reader cannot see is worse than a run that refuses to start.
    """
    raw = ConfigManager.load_yaml_file(config_path) if config_path else {}
    entries = raw.get("deploy") or []
    if not isinstance(entries, list):
        raise DeployError("build.yml: 'deploy' must be a list of channels")
    targets: List[DeployTarget] = []
    seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise DeployError(f"build.yml: deploy entry {index} is not a mapping")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise DeployError(f"build.yml: deploy entry {index} has no name")
        if name in seen:
            raise DeployError(f"build.yml: deploy channel {name!r} is declared twice")
        seen.add(name)
        plugin = str(entry.get("plugin") or "").strip()
        if not plugin:
            raise DeployError(f"build.yml: deploy channel {name!r} has no plugin")
        options = entry.get("options") or {}
        if not isinstance(options, dict):
            raise DeployError(
                f"build.yml: deploy channel {name!r}: options must be a mapping"
            )
        targets.append(
            DeployTarget(
                name=name,
                plugin=plugin,
                source=str(entry.get("source") or DEFAULT_SOURCE),
                enabled=bool(entry.get("enabled", True)),
                options=options,
            )
        )
    return targets


def resolve_source(docs_root: Path, source: str) -> Path:
    """Resolve a channel's source, relative to the docs root, and require it."""
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = docs_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise DeployError(f"deploy source is not a directory: {candidate}")
    return candidate


def iter_source_files(source: Path) -> List[Tuple[str, Path]]:
    """Return ``(relative posix path, path)`` for every file under a source.

    A path that resolves outside the source is skipped, so a symlink in a built
    tree cannot turn a deploy into a copy of a file that is not in it.
    """
    files: List[Tuple[str, Path]] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(source):
            logger.debug("Skipping %s: it resolves outside the source", path)
            continue
        files.append((path.relative_to(source).as_posix(), path))
    return files


def run_deploy(
    docs_root: Path,
    config_path: Optional[Path] = None,
    channels: Optional[List[str]] = None,
    dry_run: bool = False,
    registry: Optional[DeployRegistry] = None,
) -> bool:
    """Run every selected channel and report whether all of them succeeded."""
    registry = registry or DeployRegistry.discover()
    if config_path is None:
        candidate = docs_root / "build.yml"
        config_path = candidate if candidate.exists() else None
    try:
        targets = load_deploy_targets(config_path)
    except DeployError as error:
        logger.error("Deploy: %s", error)
        return False

    if channels:
        known = {target.name for target in targets}
        unknown = [name for name in channels if name not in known]
        if unknown:
            logger.error("Deploy: unknown channel(s): %s", ", ".join(unknown))
            return False
        wanted = set(channels)
        targets = [target for target in targets if target.name in wanted]

    targets = [target for target in targets if target.enabled]
    if not targets:
        logger.error("Deploy: no deploy channels are configured and enabled")
        return False

    context = DeployContext(docs_root=docs_root, dry_run=dry_run)
    ok = True
    for target in targets:
        plugin = registry.get(target.plugin)
        if plugin is None:
            logger.error(
                "Deploy: channel %r names unknown plugin %r (known: %s)",
                target.name,
                target.plugin,
                ", ".join(registry.names()) or "none",
            )
            ok = False
            continue
        try:
            plugin.validate(target, context)
            result = plugin.deploy(target, context)
        except DeployError as error:
            logger.error("Deploy: channel %r failed: %s", target.name, error)
            ok = False
            continue
        logger.info(
            "Deploy %s [%s]: %d uploaded, %d deleted",
            result.name,
            result.plugin,
            result.uploaded,
            result.deleted,
        )
        for url in result.urls:
            logger.info("Deploy %s: %s", result.name, url)
    return ok
