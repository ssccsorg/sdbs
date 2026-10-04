"""
AWS Signature Version 4 for S3-compatible object stores.

Implements the header-signed request path and the query-string presign path
with the standard library only, so a deploy channel adds no cloud SDK to the
image. The published AWS vectors in ``tests/test_s3sig.py`` pin this module
against the specification rather than against its own output: a signer that
only agrees with itself cannot tell a correct canonical request from a wrong
one.
"""

from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from datetime import datetime, timezone

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
MAX_PRESIGN_EXPIRES = 604800
_UNRESERVED = "-_.~"


def empty_payload_hash() -> str:
    """SHA-256 of the empty body, the payload hash for a bodyless request."""
    return hashlib.sha256(b"").hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def amz_timestamp(moment: datetime | None = None) -> str:
    """Format an instant as the ``YYYYMMDDTHHMMSSZ`` the signature needs."""
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def credential_scope(amz_date: str, region: str, service: str) -> str:
    return f"{amz_date[:8]}/{region}/{service}/aws4_request"


def signing_key(secret_key: str, amz_date: str, region: str, service: str) -> bytes:
    date_key = _hmac(("AWS4" + secret_key).encode("utf-8"), amz_date[:8])
    region_key = _hmac(date_key, region)
    service_key = _hmac(region_key, service)
    return _hmac(service_key, "aws4_request")


def canonical_uri(path: str) -> str:
    """Encode a path for the canonical request, keeping separators intact."""
    if not path.startswith("/"):
        path = "/" + path
    return urllib.parse.quote(path, safe="/" + _UNRESERVED)


def canonical_query(params: dict[str, str]) -> str:
    encoded = sorted((_quote(k), _quote(v)) for k, v in params.items())
    return "&".join(f"{name}={value}" for name, value in encoded)


def canonical_headers(headers: dict[str, str]) -> tuple[str, str]:
    """Return the canonical header block and the signed-header list."""
    normalised = {
        name.lower().strip(): " ".join(str(value).split())
        for name, value in headers.items()
    }
    names = sorted(normalised)
    block = "".join(f"{name}:{normalised[name]}\n" for name in names)
    return block, ";".join(names)


def canonical_request(
    method: str,
    path: str,
    params: dict[str, str],
    headers: dict[str, str],
    payload_hash: str,
) -> tuple[str, str]:
    """Return the canonical request and its signed-header list."""
    block, signed = canonical_headers(headers)
    request = "\n".join(
        [
            method.upper(),
            canonical_uri(path),
            canonical_query(params),
            block,
            signed,
            payload_hash,
        ]
    )
    return request, signed


def string_to_sign(amz_date: str, scope: str, request: str) -> str:
    return "\n".join(
        [ALGORITHM, amz_date, scope, sha256_hex(request.encode("utf-8"))]
    )


def sign_string(signing_key_bytes: bytes, string: str) -> str:
    return hmac.new(
        signing_key_bytes, string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def authorization_header(
    access_key: str, scope: str, signed_headers: str, signature: str
) -> str:
    return (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def presigned_url(
    *,
    scheme: str,
    host: str,
    path: str,
    params: dict[str, str],
    access_key: str,
    secret_key: str,
    amz_date: str,
    region: str,
    service: str,
    expires: int,
    session_token: str | None = None,
) -> str:
    """Return a presigned GET URL for one object.

    The canonical request signs only the host header and the unsigned payload,
    which is what the query-string form of SigV4 specifies.
    """
    if not 1 <= expires <= MAX_PRESIGN_EXPIRES:
        raise ValueError(
            f"expires must be between 1 and {MAX_PRESIGN_EXPIRES} seconds, got {expires}"
        )
    scope = credential_scope(amz_date, region, service)
    query: dict[str, str] = {
        "X-Amz-Algorithm": ALGORITHM,
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    query.update(params)
    if session_token:
        query["X-Amz-Security-Token"] = session_token
        query["X-Amz-SignedHeaders"] = "host;x-amz-security-token"
        headers = {"host": host, "x-amz-security-token": session_token}
    else:
        headers = {"host": host}
    request, signed = canonical_request(
        "GET", path, query, headers, UNSIGNED_PAYLOAD
    )
    signature = sign_string(
        signing_key(secret_key, amz_date, region, service),
        string_to_sign(amz_date, scope, request),
    )
    # The signed-header list in the query has to be the one that was signed,
    # which the session-token branch above widens.
    query["X-Amz-SignedHeaders"] = signed
    return f"{scheme}://{host}{canonical_uri(path)}?{canonical_query(query)}&X-Amz-Signature={signature}"


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe=_UNRESERVED)


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()
