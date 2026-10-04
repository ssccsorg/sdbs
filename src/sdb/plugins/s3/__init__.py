"""
The s3 channel: upload a built tree to an S3-compatible object store.

S3 is a protocol rather than a provider, so this channel names no vendor.
Cloudflare R2 is the reference deployment: it speaks the S3 API, serves
path-style addressing, and accepts the region ``auto``. Any S3-compatible
store works, and nothing here special-cases one.

The channel is private by default. It sends no object ACL, so the only way an
object becomes reachable is a bucket exposure configured on the provider side,
and a ``visibility: public`` request is refused unless the operator confirms it
with ``--allow-public``. Endpoint and credentials come from the environment.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...deploy import (
    DeployContext,
    DeployError,
    DeployResult,
    DeployTarget,
    iter_source_files,
    resolve_source,
)
from .client import S3Client, S3Error

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT_ENV = "S3_ENDPOINT"
DEFAULT_ACCESS_KEY_ENV = "AWS_ACCESS_KEY_ID"
DEFAULT_SECRET_KEY_ENV = "AWS_SECRET_ACCESS_KEY"
DEFAULT_SESSION_TOKEN_ENV = "AWS_SESSION_TOKEN"
DEFAULT_REGION = "auto"
DEFAULT_PRESIGN_SECONDS = 3600


class S3DeployPlugin:
    """Upload a source directory to one prefix of a bucket."""

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
        files = iter_source_files(source)
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
