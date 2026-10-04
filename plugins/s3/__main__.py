"""
The s3 deploy plugin: one JSON request on stdin, one JSON result on stdout.

An external tool, unrelated to sdbs: it reads one JSON request, uploads the
named artifact directory to an S3-compatible object store, and writes one JSON
result. The store endpoint, region, and credentials come from the environment,
so nothing secret crosses the request. The exit code carries success or
failure, and a failure also writes a result with ``ok: false`` and a message.
"""

from __future__ import annotations

import json
import sys

from channel import WIRE_API, PluginError, handle
from client import S3Error


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as error:
        return _fail(f"the request is not JSON: {error}")
    if not isinstance(request, dict):
        return _fail("the request is not a JSON object")
    try:
        result = handle(request)
    except (PluginError, S3Error) as error:
        return _fail(str(error))
    print(json.dumps(result))
    return 0


def _fail(message: str) -> int:
    print(json.dumps({"deploy": WIRE_API, "ok": False, "message": message}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
