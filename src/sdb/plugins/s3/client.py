"""
A minimal S3-compatible client for the deploy channels.

Covers the operations a private upload needs: put an object, list the keys
under a prefix, delete a key, and mint a presigned GET URL. Requests are
signed with :mod:`sdb.utils.s3sig` and sent with ``requests``, which the
package already depends on.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

from ...deploy import DeployError
from . import signer as s3sig


class S3Error(DeployError):
    """A request the store rejected, or a response that cannot be read.

    It derives from the engine's error so the driver reports a failed channel
    from one catch, without the engine importing anything S3-specific.
    """


class S3Client:
    """A path-style S3 client, signing each request with SigV4."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str,
        service: str = "s3",
        session_token: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        parts = urllib.parse.urlsplit(endpoint)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise S3Error(f"endpoint must be an absolute URL, got {endpoint!r}")
        if not bucket:
            raise S3Error("bucket is required")
        self.scheme = parts.scheme
        self.host = parts.netloc
        self.base_path = parts.path.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.service = service
        self.session_token = session_token
        self.timeout = timeout

    def put_object(
        self, key: str, body: bytes, content_type: Optional[str] = None
    ) -> None:
        self._send("PUT", key, body=body, content_type=content_type)

    def delete_object(self, key: str) -> None:
        self._send("DELETE", key)

    def list_objects(self, prefix: str = "") -> List[str]:
        keys: List[str] = []
        token: Optional[str] = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            response = self._send("GET", None, params=params)
            keys.extend(_parse_list_keys(response.content))
            token = _parse_next_token(response.content)
            if not token:
                return keys

    def presign_get(self, key: str, expires: int) -> str:
        return s3sig.presigned_url(
            scheme=self.scheme,
            host=self.host,
            path=self._path_for_key(key),
            params={},
            access_key=self.access_key,
            secret_key=self.secret_key,
            amz_date=s3sig.amz_timestamp(),
            region=self.region,
            service=self.service,
            expires=expires,
            session_token=self.session_token,
        )

    def _path_for_key(self, key: Optional[str]) -> str:
        if key is None:
            return f"{self.base_path}/{self.bucket}"
        return f"{self.base_path}/{self.bucket}/{key.lstrip('/')}"

    def _send(
        self,
        method: str,
        key: Optional[str],
        *,
        params: Optional[dict] = None,
        body: bytes = b"",
        content_type: Optional[str] = None,
    ) -> requests.Response:
        params = params or {}
        path = self._path_for_key(key)
        payload_hash = s3sig.sha256_hex(body) if body else s3sig.empty_payload_hash()
        amz_date = s3sig.amz_timestamp()

        signed_headers = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if content_type:
            signed_headers["content-type"] = content_type
        if self.session_token:
            signed_headers["x-amz-security-token"] = self.session_token

        scope = s3sig.credential_scope(amz_date, self.region, self.service)
        request, signed = s3sig.canonical_request(
            method, path, params, signed_headers, payload_hash
        )
        signature = s3sig.sign_string(
            s3sig.signing_key(self.secret_key, amz_date, self.region, self.service),
            s3sig.string_to_sign(amz_date, scope, request),
        )

        # ``host`` is left to the HTTP client, which derives it from the URL and
        # therefore sends the value that was signed.
        sent_headers = {
            name: value
            for name, value in signed_headers.items()
            if name not in ("host", "content-type")
        }
        if content_type:
            sent_headers["Content-Type"] = content_type
        sent_headers["Authorization"] = s3sig.authorization_header(
            self.access_key, scope, signed, signature
        )

        url = f"{self.scheme}://{self.host}{s3sig.canonical_uri(path)}"
        if params:
            url = f"{url}?{s3sig.canonical_query(params)}"

        try:
            response = requests.request(
                method,
                url,
                headers=sent_headers,
                data=body if body else None,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise S3Error(f"{method} {path} could not reach {self.host}: {error}") from error
        if response.status_code >= 300:
            raise S3Error(
                f"{method} {path} failed with {response.status_code}: "
                f"{response.text[:500]}"
            )
        return response


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_list_keys(payload: bytes) -> List[str]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise S3Error(f"could not parse the list response: {error}") from error
    keys = []
    for element in root:
        if _strip_namespace(element.tag) != "Contents":
            continue
        for child in element:
            if _strip_namespace(child.tag) == "Key" and child.text:
                keys.append(child.text)
    return keys


def _parse_next_token(payload: bytes) -> Optional[str]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise S3Error(f"could not parse the list response: {error}") from error
    for element in root:
        if _strip_namespace(element.tag) == "NextContinuationToken" and element.text:
            return element.text
    return None
