"""
The s3 plugin's work, separated from its stdio entry point.

The request is ``{"artifact": "<dir>", "options": {...}, "dry_run": false}``.
The endpoint, the region, and the credentials come from the environment, so the
request holds no secret. ``handle`` returns the result mapping the entry point
writes to stdout.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from client import S3Client, S3Error
from signer import MAX_PRESIGN_EXPIRES

WIRE_API = 1
ENDPOINT_ENV = "S3_ENDPOINT"
REGION_ENV = "AWS_REGION"
ACCESS_KEY_ENV = "AWS_ACCESS_KEY_ID"
SECRET_KEY_ENV = "AWS_SECRET_ACCESS_KEY"
SESSION_TOKEN_ENV = "AWS_SESSION_TOKEN"
PRESIGN_SECONDS = 3600


class PluginError(RuntimeError):
    """The request cannot be satisfied."""


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    artifact = Path(str(request.get("artifact") or "")).resolve()
    if not artifact.is_dir():
        raise PluginError(f"artifact is not a directory: {artifact}")
    options = request.get("options") or {}
    if not isinstance(options, dict):
        raise PluginError("options must be a mapping")
    dry_run = bool(request.get("dry_run"))

    bucket = str(options.get("bucket") or "").strip()
    if not bucket:
        raise PluginError("options.bucket is required")
    prefix = str(options.get("prefix") or "").strip("/")
    files = _source_files(artifact)
    local_keys = {_object_key(prefix, relative) for relative, _ in files}

    auth = options.get("auth") or {}
    if not isinstance(auth, dict):
        raise PluginError("options.auth must be a mapping")
    _validate_options(options, prefix)
    _validate_auth(auth, artifact)

    if dry_run:
        return _result(
            uploaded=len(files),
            message=f"dry run: {len(files)} object(s) under {prefix or '/'}",
        )

    credentials = _credentials()
    client = S3Client(
        endpoint=_endpoint(options),
        bucket=bucket,
        access_key=credentials["access_key"],
        secret_key=credentials["secret_key"],
        region=_region(options),
        session_token=credentials["session_token"],
    )

    uploaded = 0
    for relative, path in files:
        client.put_object(
            _object_key(prefix, relative), path.read_bytes(), _content_type(path)
        )
        uploaded += 1

    deleted = 0
    if options.get("delete", False):
        remote = set(client.list_objects(f"{prefix}/" if prefix else ""))
        for key in sorted(remote - local_keys):
            client.delete_object(key)
            deleted += 1

    return _result(
        uploaded=uploaded, deleted=deleted, urls=_client_urls(client, auth, prefix)
    )


def _validate_options(options: Dict[str, Any], prefix: str) -> None:
    if (
        options.get("delete", False)
        and not prefix
        and not options.get("allow_unscoped_delete", False)
    ):
        raise PluginError(
            "delete at the bucket root would remove every object outside the "
            "source; set options.prefix or options.allow_unscoped_delete"
        )


def _validate_auth(auth: Dict[str, Any], artifact: Path) -> None:
    mode = auth.get("mode", "none")
    if mode not in ("none", "access", "presigned"):
        raise PluginError("auth.mode must be one of none, access, presigned")
    if mode == "access" and not auth.get("domain"):
        raise PluginError("auth.mode access needs auth.domain")
    if mode == "presigned":
        objects = auth.get("objects") or []
        if not objects:
            raise PluginError(
                "auth.mode presigned needs an explicit objects list, since a "
                "website is not presigned per object"
            )
        for relative in objects:
            candidate = artifact / str(relative).lstrip("/")
            inside = candidate.resolve().is_relative_to(artifact)
            if not inside or not candidate.is_file():
                raise PluginError(
                    f"presigned object is not a file in the artifact: {relative!r}"
                )
        _presign_seconds(auth)


def _client_urls(client: S3Client, auth: Dict[str, Any], prefix: str) -> List[str]:
    mode = auth.get("mode", "none")
    if mode == "none":
        return []
    domain = str(auth.get("domain") or "").rstrip("/")
    if mode == "access":
        return [f"{domain}/"] if domain else []
    expires = _presign_seconds(auth)
    return [
        client.presign_get(_object_key(prefix, str(relative).lstrip("/")), expires)
        for relative in auth.get("objects") or []
    ]


def _source_files(artifact: Path) -> List[Tuple[str, Path]]:
    files: List[Tuple[str, Path]] = []
    for path in sorted(artifact.rglob("*")):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(artifact):
            continue
        files.append((path.relative_to(artifact).as_posix(), path))
    return files


def _object_key(prefix: str, relative: str) -> str:
    return f"{prefix}/{relative}" if prefix else relative


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _endpoint(options: Dict[str, Any]) -> str:
    value = str(options.get("endpoint") or os.environ.get(ENDPOINT_ENV, "")).strip()
    if not value:
        raise PluginError(f"no endpoint: set options.endpoint or {ENDPOINT_ENV}")
    return value


def _region(options: Dict[str, Any]) -> str:
    value = str(options.get("region") or os.environ.get(REGION_ENV, "")).strip()
    if not value:
        raise PluginError(f"no region: set options.region or {REGION_ENV}")
    return value


def _credentials() -> Dict[str, Optional[str]]:
    access_key = os.environ.get(ACCESS_KEY_ENV, "")
    secret_key = os.environ.get(SECRET_KEY_ENV, "")
    if not access_key or not secret_key:
        raise PluginError(
            f"missing credentials: set {ACCESS_KEY_ENV} and {SECRET_KEY_ENV}"
        )
    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "session_token": os.environ.get(SESSION_TOKEN_ENV) or None,
    }


def _presign_seconds(auth: Dict[str, Any]) -> int:
    value = auth.get("expires_seconds", PRESIGN_SECONDS)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        raise PluginError(f"expires_seconds must be an integer, got {value!r}") from None
    if not 1 <= seconds <= MAX_PRESIGN_EXPIRES:
        raise PluginError(
            f"expires_seconds must be between 1 and {MAX_PRESIGN_EXPIRES}, got {seconds}"
        )
    return seconds


def _result(
    *,
    uploaded: int = 0,
    deleted: int = 0,
    urls: Optional[List[str]] = None,
    message: str = "",
) -> Dict[str, Any]:
    return {
        "deploy": WIRE_API,
        "ok": True,
        "uploaded": uploaded,
        "deleted": deleted,
        "urls": urls or [],
        "message": message,
    }
