"""
External deploy channels.

sdbs builds artifacts and stops there. A deploy channel moves a built tree to
an external store, and channels are plugins so a new destination is added
without changing the driver: built-ins register themselves and an external
package registers through the ``sdb.deploy`` entry point group.

``deploy`` runs as its own invocation, apart from the render. The render
container executes project-controlled Quarto and Jupyter code, so it stays
free of upload credentials; this step receives the credentials and walks the
built artifact without running project code.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import ConfigManager
from .utils.s3 import S3Client, S3Error

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sdb.deploy"
DEFAULT_ENDPOINT_ENV = "S3_ENDPOINT"
DEFAULT_ACCESS_KEY_ENV = "AWS_ACCESS_KEY_ID"
DEFAULT_SECRET_KEY_ENV = "AWS_SECRET_ACCESS_KEY"
DEFAULT_SESSION_TOKEN_ENV = "AWS_SESSION_TOKEN"
DEFAULT_SOURCE = "_site"
DEFAULT_REGION = "auto"
DEFAULT_PRESIGN_SECONDS = 3600


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
    allow_public: bool = False


@dataclass
class DeployResult:
    name: str
    plugin: str
    uploaded: int = 0
    deleted: int = 0
    urls: List[str] = field(default_factory=list)
    ok: bool = True
    message: str = ""


class DeployPlugin:
    """A deploy destination.

    A built-in subclasses this and registers itself. An external package
    subclasses it and exposes an instance, or a zero-argument callable that
    returns one, under the ``sdb.deploy`` entry point group.
    """

    name = ""

    def validate(self, target: DeployTarget, context: DeployContext) -> None:
        """Raise :class:`DeployError` when the channel cannot run. No side effects."""

    def deploy(self, target: DeployTarget, context: DeployContext) -> DeployResult:
        raise NotImplementedError


class DeployRegistry:
    """The set of plugins a run can resolve a channel's ``plugin`` against."""

    def __init__(self, plugins: Optional[Iterable[DeployPlugin]] = None) -> None:
        self._plugins: Dict[str, DeployPlugin] = {}
        for plugin in plugins or []:
            self.register(plugin)

    def register(self, plugin: DeployPlugin) -> None:
        name = getattr(plugin, "name", "")
        if not name:
            raise DeployError("a deploy plugin needs a non-empty name")
        self._plugins[name] = plugin

    def get(self, name: str) -> Optional[DeployPlugin]:
        return self._plugins.get(name)

    def names(self) -> List[str]:
        return sorted(self._plugins)

    @classmethod
    def discover(cls) -> "DeployRegistry":
        registry = cls(_BUILTIN_PLUGINS)
        for plugin in _entry_point_plugins():
            registry.register(plugin)
        return registry


def _entry_point_plugins() -> Iterable[DeployPlugin]:
    try:
        discovered = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python < 3.10 selects differently
        discovered = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    for entry in discovered:
        try:
            loaded = entry.load()
        except Exception as error:
            logger.warning("Could not load deploy plugin %s: %s", entry.name, error)
            continue
        plugin = loaded() if isinstance(loaded, type) else loaded
        if not isinstance(plugin, DeployPlugin):
            logger.warning(
                "Deploy entry point %s did not yield a DeployPlugin", entry.name
            )
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
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = docs_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise DeployError(f"deploy source is not a directory: {candidate}")
    return candidate


def run_deploy(
    docs_root: Path,
    config_path: Optional[Path] = None,
    channels: Optional[List[str]] = None,
    dry_run: bool = False,
    allow_public: bool = False,
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

    context = DeployContext(
        docs_root=docs_root, dry_run=dry_run, allow_public=allow_public
    )
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
        except (DeployError, S3Error) as error:
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


class S3DeployPlugin(DeployPlugin):
    """Upload a built tree to an S3-compatible store, private by default.

    The channel never sets an object ACL, so the only way an object becomes
    reachable is a bucket exposure configured on the provider side. A
    ``visibility: public`` request is refused unless the operator confirms it
    with ``--allow-public``, which keeps a public destination from being a
    quiet default.
    """

    name = "s3"

    def validate(self, target: DeployTarget, context: DeployContext) -> None:
        options = target.options
        if not options.get("bucket"):
            raise DeployError(
                f"deploy channel {target.name!r}: options.bucket is required"
            )
        visibility = options.get("visibility", "private")
        if visibility not in ("private", "public"):
            raise DeployError(
                f"deploy channel {target.name!r}: visibility must be "
                f"'private' or 'public', got {visibility!r}"
            )
        if visibility == "public" and not context.allow_public:
            raise DeployError(
                f"deploy channel {target.name!r} asks for visibility: public; "
                f"pass --allow-public to confirm the destination is meant to be reachable"
            )
        if options.get("delete", False) and not str(options.get("prefix") or "").strip("/"):
            if not options.get("allow_unscoped_delete", False):
                raise DeployError(
                    f"deploy channel {target.name!r}: delete at the bucket root would "
                    f"remove every object outside the source; set options.prefix or "
                    f"confirm with options.allow_unscoped_delete"
                )
        if not _endpoint(options):
            raise DeployError(
                f"deploy channel {target.name!r}: no endpoint. Set options.endpoint "
                f"or the {DEFAULT_ENDPOINT_ENV} environment variable"
            )
        _credentials(options)
        resolve_source(context.docs_root, target.source)
        auth = options.get("auth") or {}
        if not isinstance(auth, dict):
            raise DeployError(
                f"deploy channel {target.name!r}: options.auth must be a mapping"
            )
        mode = auth.get("mode", "none")
        if mode not in ("none", "access", "presigned"):
            raise DeployError(
                f"deploy channel {target.name!r}: auth.mode must be one of "
                f"none, access, presigned"
            )
        if mode in ("access", "presigned") and not auth.get("domain"):
            raise DeployError(
                f"deploy channel {target.name!r}: auth.mode {mode} needs auth.domain"
            )
        if mode == "presigned" and not auth.get("objects"):
            raise DeployError(
                f"deploy channel {target.name!r}: auth.mode presigned needs an "
                f"explicit objects list, since a website is not presigned per object"
            )

    def deploy(self, target: DeployTarget, context: DeployContext) -> DeployResult:
        options = target.options
        source = resolve_source(context.docs_root, target.source)
        prefix = str(options.get("prefix") or "").strip("/")
        files = _source_files(source)
        local_keys = {_object_key(prefix, relative) for relative, _ in files}

        result = DeployResult(name=target.name, plugin=self.name)
        if context.dry_run:
            result.uploaded = len(files)
            result.message = (
                f"dry run: {len(files)} object(s) would be uploaded under "
                f"{prefix or '/'}"
            )
            logger.info("Deploy %s [s3] %s", target.name, result.message)
            return result

        credentials = _credentials(options)
        client = S3Client(
            endpoint=_endpoint(options),
            bucket=str(options["bucket"]),
            access_key=credentials["access_key"],
            secret_key=credentials["secret_key"],
            region=str(options.get("region") or DEFAULT_REGION),
            session_token=credentials["session_token"],
        )

        for relative, path in files:
            key = _object_key(prefix, relative)
            client.put_object(key, path.read_bytes(), _content_type(path))
            result.uploaded += 1

        if options.get("delete", False):
            remote = set(client.list_objects(f"{prefix}/" if prefix else ""))
            for key in sorted(remote - local_keys):
                client.delete_object(key)
                result.deleted += 1

        result.urls = _client_urls(client, options, prefix)
        return result


def _client_urls(
    client: S3Client, options: Dict[str, Any], prefix: str
) -> List[str]:
    auth = options.get("auth") or {}
    mode = auth.get("mode", "none")
    if mode == "none":
        return []
    domain = str(auth.get("domain") or "").rstrip("/")
    if mode == "access":
        return [f"{domain}/"] if domain else []
    expires = int(auth.get("expires_seconds") or DEFAULT_PRESIGN_SECONDS)
    urls = []
    for relative in auth.get("objects") or []:
        key = _object_key(prefix, str(relative).lstrip("/"))
        urls.append(client.presign_get(key, expires))
    return urls


def _source_files(source: Path) -> List[Tuple[str, Path]]:
    return [
        (path.relative_to(source).as_posix(), path)
        for path in sorted(source.rglob("*"))
        if path.is_file()
    ]


def _object_key(prefix: str, relative: str) -> str:
    return f"{prefix}/{relative}" if prefix else relative


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _endpoint(options: Dict[str, Any]) -> str:
    value = options.get("endpoint") or os.environ.get(DEFAULT_ENDPOINT_ENV, "")
    return str(value).strip()


def _env_name(options: Dict[str, Any], key: str, default: str) -> str:
    return str(options.get(key) or default)


def _credentials(options: Dict[str, Any]) -> Dict[str, Optional[str]]:
    access_env = _env_name(options, "access_key_id_env", DEFAULT_ACCESS_KEY_ENV)
    secret_env = _env_name(options, "secret_access_key_env", DEFAULT_SECRET_KEY_ENV)
    token_env = _env_name(options, "session_token_env", DEFAULT_SESSION_TOKEN_ENV)
    access_key = os.environ.get(access_env, "")
    secret_key = os.environ.get(secret_env, "")
    if not access_key or not secret_key:
        raise DeployError(
            f"missing credentials for this channel: set {access_env} and {secret_env}"
        )
    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "session_token": os.environ.get(token_env) or None,
    }


_BUILTIN_PLUGINS: List[DeployPlugin] = [S3DeployPlugin()]
